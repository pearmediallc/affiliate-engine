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
from ..services.script_parser import parse_script, normalize_for_veo
from ..services.long_video_service import LongVideoService, LONG_VIDEOS_DIR, LONG_STITCHED_DIR
from ..middleware.auth import get_current_user
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


# ---- Long Video (chained Veo + optional stitch) ----

class LongVideoRequest(BaseModel):
    script: str
    aspect_ratio: str = "16:9"
    target_segments: int = 8       # max Veo 3.1 can do = 21 (1 base + 20 ext)
    auto_stitch: bool = False
    budget_usd: float = 3.5


@router.post("/long/create")
async def long_video_create(
    request: LongVideoRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a long-video job. Parses script, kicks off base clip, returns job_id."""
    try:
        # Parse user's raw script
        raw_segments = parse_script(request.script, target_segments=request.target_segments)
        if not raw_segments:
            raise HTTPException(status_code=400, detail="Could not parse script - please provide at least one line of description")

        # Cap by target_segments AND by budget
        budget_max = LongVideoService.max_segments_for_budget(request.budget_usd)
        effective_max = min(request.target_segments, budget_max, 21)  # 21 = Veo's hard ceiling
        if effective_max < 1:
            raise HTTPException(status_code=400, detail="Budget too low to generate even one clip")

        plan = normalize_for_veo(raw_segments, max_segments=effective_max)
        job = LongVideoService.start_job(
            db=db, user_id=user.id,
            segments_plan=plan,
            aspect_ratio=request.aspect_ratio,
            auto_stitch=request.auto_stitch,
            budget_usd=request.budget_usd,
            raw_script=request.script,
        )

        log_usage("long_video", user.id, db, cost_usd=0.40)

        return APIResponse(
            success=True,
            message=f"Long video job started: {len(plan)} segments planned",
            data={
                "job_id": job.id,
                "segment_count": len(plan),
                "estimated_cost_usd": round(LongVideoService.estimate_cost(len(plan)), 2),
                "estimated_length_seconds": 8 + (len(plan) - 1) * 7,
                "auto_stitch": request.auto_stitch,
                "raw_segment_count_detected": len(raw_segments),
                "truncated": len(raw_segments) > effective_max,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Long video create failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/long/status/{job_id}")
async def long_video_status(
    job_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Drives the long-video state machine forward by one tick and returns the snapshot.
    Each call will: poll the active segment, and if it's done, kick off the next.
    """
    job = JobService.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != user.id and not (user.role and user.role.name == "admin"):
        raise HTTPException(status_code=403, detail="Not your job")
    if job.job_type != "long_video":
        raise HTTPException(status_code=400, detail="Not a long video job")

    snap = LongVideoService.advance(db, job)
    return APIResponse(success=True, message="Long video status", data=snap)


@router.get("/long/download/{filename}")
async def long_video_download(filename: str):
    """Download a long-video segment or the stitched output."""
    safe = os.path.basename(filename)
    # Try stitched dir first, then segments dir
    for base in (LONG_STITCHED_DIR, LONG_VIDEOS_DIR):
        fp = os.path.join(base, safe)
        if os.path.isfile(fp):
            return FileResponse(fp, media_type="video/mp4",
                                headers={"Content-Disposition": f"attachment; filename={safe}"})
    raise HTTPException(status_code=404, detail="File not found")


@router.post("/long/stitch/{job_id}")
async def long_video_stitch_now(
    job_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manual stitch trigger (for users who didn't tick auto-stitch at start)."""
    job = JobService.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your job")
    if job.job_type != "long_video":
        raise HTTPException(status_code=400, detail="Not a long video job")

    result_data = job.result_data or {}
    segments = result_data.get("segments", [])
    if not segments or not all(s["status"] in ("completed", "failed", "skipped_budget") for s in segments):
        raise HTTPException(status_code=400, detail="Job not finished generating yet")

    try:
        stitched = LongVideoService._stitch(segments, job.id)
        result_data["stitched_filename"] = stitched
        result_data["stitched_url"] = f"/api/v1/video/long/download/{stitched}"
        JobService.update_job(db=db, job_id=job.id, result_data=result_data,
                              result_url=result_data["stitched_url"])
        return APIResponse(success=True, message="Stitched", data={
            "stitched_url": result_data["stitched_url"],
        })
    except Exception as e:
        logger.error(f"Manual stitch failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/capabilities")
async def get_capabilities():
    """Get Veo 3.1 capabilities for the frontend"""
    return APIResponse(
        success=True,
        message="Video creation capabilities",
        data=VideoCreatorService.get_capabilities(),
    )
