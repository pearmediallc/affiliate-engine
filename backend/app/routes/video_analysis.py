"""Routes for video hook analysis"""
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from ..database import get_db
from ..schemas import APIResponse
from ..services.video_hook_analyzer import VideoHookAnalyzerService
from ..middleware.auth import get_optional_user, log_usage
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

router = APIRouter()


class AnalyzeVideoHookRequest(BaseModel):
    """Request to analyze video hook"""
    video_url: str
    hook_duration_seconds: int = 5


class AnalyzeWithTranscriptRequest(BaseModel):
    """Request to analyze video with transcript"""
    video_url: str
    transcript_text: Optional[str] = None
    hook_duration_seconds: int = 5


@router.post("/analyze-hook")
async def analyze_video_hook(
    request: AnalyzeVideoHookRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Analyze the hook (first 5-10 seconds) of a video using Gemini model

    Returns insights on:
    - Hook type and attention grabbers
    - Conversion elements and psychology
    - Emotional triggers used
    - Effectiveness score and recommendations
    - How to replicate for affiliate ads
    """
    try:
        if not request.video_url:
            raise HTTPException(status_code=400, detail="video_url is required")

        if request.hook_duration_seconds < 3 or request.hook_duration_seconds > 15:
            raise HTTPException(
                status_code=400,
                detail="hook_duration_seconds must be between 3 and 15 seconds"
            )

        analyzer = VideoHookAnalyzerService()
        result = await analyzer.analyze_video_hook(
            video_url=request.video_url,
            hook_duration_seconds=request.hook_duration_seconds,
        )

        if user:
            log_usage("video_hook_analysis", user.id, db, cost_usd=0.02)

        return APIResponse(
            success=True,
            message="Video hook analyzed successfully",
            data=result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Video hook analysis failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-hook-upload")
async def analyze_video_hook_upload(
    file: UploadFile = File(...),
    hook_duration_seconds: int = Form(default=5),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Analyze uploaded video file's hook using Gemini model"""
    try:
        if hook_duration_seconds < 3 or hook_duration_seconds > 15:
            raise HTTPException(
                status_code=400,
                detail="hook_duration_seconds must be between 3 and 15 seconds"
            )

        # Save uploaded file temporarily
        suffix = f".{file.filename.split('.')[-1]}" if file.filename else ".mp4"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            analyzer = VideoHookAnalyzerService()
            result = await analyzer.analyze_video_file(
                video_path=temp_path,
                filename=file.filename or "uploaded_video",
                hook_duration_seconds=hook_duration_seconds,
            )

            if user:
                log_usage("video_hook_analysis", user.id, db, cost_usd=0.02)

            return APIResponse(
                success=True,
                message="Video hook analyzed successfully",
                data=result
            )
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Video hook upload analysis failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-with-transcript")
async def analyze_with_transcript(
    request: AnalyzeWithTranscriptRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Analyze video hook with transcript for detailed insights

    Provides comprehensive analysis including:
    - Script analysis and speech patterns
    - Copywriting framework identification (PAS, AIDA, BAB, etc.)
    - Visual + audio synergy breakdown
    - Replication guide for creating similar hooks
    - Vertical applicability recommendations
    """
    try:
        if not request.video_url:
            raise HTTPException(status_code=400, detail="video_url is required")

        analyzer = VideoHookAnalyzerService()
        result = await analyzer.analyze_with_transcript(
            video_url=request.video_url,
            transcript_text=request.transcript_text,
            hook_duration_seconds=request.hook_duration_seconds,
        )

        if user:
            log_usage("video_hook_analysis", user.id, db, cost_usd=0.02)

        return APIResponse(
            success=True,
            message="Video hook with transcript analyzed successfully",
            data=result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcript analysis failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
