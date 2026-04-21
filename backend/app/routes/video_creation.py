"""Video creation routes - Veo 3.1 text-to-video and image-to-video"""
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_optional_user, log_usage
from ..services.video_creator import VideoCreatorService, VIDEOS_DIR
from ..services.job_service import JobService
from ..models.job import Job
import tempfile
import os
import logging
import subprocess

logger = logging.getLogger(__name__)
router = APIRouter()

VEO_THUMBS_DIR = os.path.join(VIDEOS_DIR, "thumbs")
os.makedirs(VEO_THUMBS_DIR, exist_ok=True)


def _veo_thumb(video_path: str, thumb_path: str) -> bool:
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-ss", "00:00:01", "-vframes", "1",
             "-vf", "scale=480:-2", "-q:v", "3", thumb_path],
            capture_output=True, timeout=30,
        )
        return r.returncode == 0 and os.path.exists(thumb_path)
    except Exception as e:
        logger.warning(f"Veo thumbnail generation failed: {e}")
        return False


class TextToVideoRequest(BaseModel):
    prompt: str
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    duration: str = "8"


class ImageToVideoRequest(BaseModel):
    prompt: str = ""
    aspect_ratio: str = "16:9"


@router.post("/generate")
async def generate_video(
    request: TextToVideoRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Generate a video from text prompt using Veo 3.1"""
    try:
        # Veo 3.1 constraint: 1080p/4k require 8s duration. Auto-correct.
        resolution = request.resolution or "720p"
        try:
            dur_int = int(str(request.duration).rstrip("s").strip())
        except Exception:
            dur_int = 8
        if resolution in ("1080p", "4k") and dur_int != 8:
            logger.info(f"Veo: forcing duration=8s for resolution={resolution} (was {dur_int}s)")
            dur_int = 8

        result = VideoCreatorService.generate_video(
            prompt=request.prompt,
            aspect_ratio=request.aspect_ratio,
            resolution=resolution,
            duration=str(dur_int),
        )
        if user:
            log_usage("video_creation", user.id, db, cost_usd=0.10)
            # Persist Veo job so user can track + retrieve later
            try:
                JobService.create_job(
                    db=db, user_id=user.id, job_type="veo_video",
                    provider="google", provider_job_id=result.get("operation_name", ""),
                    input_data={
                        "prompt": request.prompt[:500],
                        "aspect_ratio": request.aspect_ratio,
                        "resolution": resolution,
                        "duration": dur_int,
                    },
                    cost_usd=0.10,
                )
            except Exception as je:
                logger.warning(f"Veo job record failed: {je}")

        return APIResponse(success=True, message="Video generation started", data=result)
    except Exception as e:
        logger.error(f"Video generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-from-image")
async def generate_from_image(
    image: UploadFile = File(...),
    prompt: str = Form(default=""),
    aspect_ratio: str = Form(default="16:9"),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Generate a video using an uploaded image as the starting frame"""
    try:
        suffix = f".{image.filename.split('.')[-1]}" if image.filename else ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await image.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = VideoCreatorService.generate_from_image(
                image_path=tmp_path,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )
            if user:
                log_usage("video_creation", user.id, db, cost_usd=0.10)

            return APIResponse(success=True, message="Image-to-video generation started", data=result)
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass

    except Exception as e:
        logger.error(f"Image-to-video failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{operation_name:path}")
async def video_status(
    operation_name: str,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Check the status of a video generation operation"""
    try:
        result = VideoCreatorService.check_status(operation_name)

        # If Veo finished and saved a file locally, generate a thumbnail + complete the job
        if result.get("done") and result.get("video_filename"):
            filename = result["video_filename"]
            filepath = os.path.join(VIDEOS_DIR, filename)
            thumb_name = filename.replace(".mp4", ".jpg")
            thumb_path = os.path.join(VEO_THUMBS_DIR, thumb_name)
            if os.path.isfile(filepath) and not os.path.exists(thumb_path):
                _veo_thumb(filepath, thumb_path)
            result["thumb_filename"] = thumb_name if os.path.exists(thumb_path) else None
            result["thumb_url"] = f"/api/v1/video/thumb/{thumb_name}" if os.path.exists(thumb_path) else None

            if user:
                try:
                    job = db.query(Job).filter(
                        Job.user_id == user.id,
                        Job.provider_job_id == operation_name,
                        Job.job_type == "veo_video",
                    ).first()
                    if job and job.status != "completed":
                        JobService.complete_job(
                            db=db, job_id=job.id,
                            result_data={
                                "video_filename": filename,
                                "thumb_filename": result.get("thumb_filename"),
                            },
                            result_url=f"/api/v1/video/download/{filename}",
                        )
                except Exception as je:
                    logger.warning(f"Veo complete job failed: {je}")

        return APIResponse(success=True, message=f"Status: {result['status']}", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{filename}")
async def download_video(filename: str):
    """Download a generated video"""
    filepath = os.path.join(VIDEOS_DIR, os.path.basename(filename))
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(
        filepath, media_type="video/mp4",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/thumb/{filename}")
async def veo_thumb(filename: str):
    filepath = os.path.join(VEO_THUMBS_DIR, os.path.basename(filename))
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(filepath, media_type="image/jpeg")


@router.get("/capabilities")
async def get_capabilities():
    """Get Veo 3.1 capabilities for the frontend"""
    return APIResponse(
        success=True,
        message="Video creation capabilities",
        data=VideoCreatorService.get_capabilities(),
    )
