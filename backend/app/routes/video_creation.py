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
import tempfile
import os
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


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
        result = VideoCreatorService.generate_video(
            prompt=request.prompt,
            aspect_ratio=request.aspect_ratio,
            resolution=request.resolution,
            duration=request.duration,
        )
        if user:
            log_usage("video_creation", user.id, db, cost_usd=0.10)

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
async def video_status(operation_name: str):
    """Check the status of a video generation operation"""
    try:
        result = VideoCreatorService.check_status(operation_name)
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


@router.get("/capabilities")
async def get_capabilities():
    """Get Veo 3.1 capabilities for the frontend"""
    return APIResponse(
        success=True,
        message="Video creation capabilities",
        data=VideoCreatorService.get_capabilities(),
    )
