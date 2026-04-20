"""Video enhancement routes"""
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_optional_user, log_usage
from ..services.video_enhancer import VideoEnhancerService, ENHANCED_DIR
import tempfile
import os
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/enhance")
async def enhance_video(
    video: UploadFile = File(...),
    color_grade: str = Form(default="cinematic"),
    text: Optional[str] = Form(default=None),
    text_position: str = Form(default="bottom"),
    platform: Optional[str] = Form(default=None),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Enhance a video with color grading, text overlay, and platform resize"""
    try:
        suffix = f".{video.filename.split('.')[-1]}" if video.filename else ".mp4"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await video.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = VideoEnhancerService.enhance_full(
                video_path=tmp_path,
                color_grade=color_grade,
                text=text,
                text_position=text_position,
                platform=platform,
            )
            if user:
                log_usage("video_enhance", user.id, db, cost_usd=0.0)
            return APIResponse(success=True, message="Video enhanced", data=result)
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass
    except Exception as e:
        logger.error(f"Video enhancement failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/options")
async def get_enhance_options():
    """Get available enhancement options"""
    return APIResponse(
        success=True,
        message="Enhancement options",
        data=VideoEnhancerService.get_options(),
    )
