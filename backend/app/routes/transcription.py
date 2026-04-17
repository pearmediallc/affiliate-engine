"""Routes for audio transcription using Whisper or Deepgram"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from ..database import get_db
from ..services import TranscriptionService
from ..schemas import APIResponse
from ..middleware.auth import get_optional_user, log_usage
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

router = APIRouter()
transcription_service = TranscriptionService()


class TranscribeAudioRequest(BaseModel):
    """Request to transcribe audio from URL"""
    audio_url: str
    provider: str = "openai"  # "openai" or "deepgram"
    language: Optional[str] = None


@router.post("/transcribe-file")
async def transcribe_audio_file(
    file: UploadFile = File(...),
    provider: str = Form(default="openai"),
    language: Optional[str] = Form(default=None),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """
    Transcribe uploaded audio file to text

    Supports:
    - MP3, MP4, WAV, M4A, FLAC, WEBM
    - Providers: openai (Whisper), deepgram
    - 25MB max file size

    Returns:
    - Transcribed text
    - Language detected
    - Confidence score (if available)
    """
    try:
        # Validate file size (25MB max)
        content = await file.read()
        file_size = len(content)
        if file_size > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large (max 25MB)")

        # Save file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file.filename.split('.')[-1]}") as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            # Transcribe
            result = await transcription_service.transcribe_audio(
                temp_path,
                provider=provider,
                language=language,
            )

            if user:
                log_usage("transcript_analysis", user.id, db, cost_usd=0.02)

            return APIResponse(
                success=True,
                message="Audio transcribed successfully",
                data=result
            )

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@router.post("/transcribe-url")
async def transcribe_audio_url(
    request: TranscribeAudioRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """
    Transcribe audio from URL to text

    Supports:
    - Remote audio files (MP3, MP4, WAV, M4A, FLAC, WEBM)
    - Providers: openai (Whisper), deepgram
    - 25MB max file size

    Returns:
    - Transcribed text
    - Language detected
    - Confidence score (if available)
    """
    try:
        if not request.audio_url:
            raise HTTPException(status_code=400, detail="audio_url is required")

        if request.provider not in ["openai", "deepgram"]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider. Supported: openai, deepgram"
            )

        result = await transcription_service.transcribe_audio_url(
            request.audio_url,
            provider=request.provider,
            language=request.language,
        )

        if user:
            log_usage("transcript_analysis", user.id, db, cost_usd=0.02)

        return APIResponse(
            success=True,
            message="Audio transcribed successfully",
            data=result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcription from URL failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@router.get("/providers")
async def get_transcription_providers():
    """Get list of available transcription providers"""
    providers = TranscriptionService.get_supported_providers()
    return APIResponse(
        success=True,
        message="Available providers retrieved",
        data={
            "providers": providers,
            "default": "openai",
        }
    )


@router.get("/languages")
async def get_supported_languages():
    """Get list of supported languages for transcription"""
    languages = TranscriptionService.get_supported_languages()
    return APIResponse(
        success=True,
        message="Supported languages retrieved",
        data={
            "languages": languages,
            "count": len(languages),
        }
    )
