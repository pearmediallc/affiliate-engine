"""Routes for speech generation"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional
from ..database import get_db
from ..services.speech_generator import SpeechGeneratorService
from ..services.learning_service import LearningService
from ..middleware.auth import get_optional_user, log_usage
import logging
import base64
from fastapi.responses import StreamingResponse
import io

logger = logging.getLogger(__name__)

router = APIRouter()
speech_generator = SpeechGeneratorService()


class SpeechGenerateRequest(BaseModel):
    """Request to generate speech"""
    text: str = Field(..., description="Text to convert to speech", min_length=1, max_length=5000)
    voice: str = Field(default="Kore", description="Voice name")
    style: Optional[str] = Field(default=None, description="Style description (e.g., 'excited', 'whispers', 'confident')")
    language: str = Field(default="en", description="Language code")
    output_format: str = Field(default="mp3", description="Output format (mp3, wav, ogg, pcm)")


class SpeechResponse(BaseModel):
    """Response with audio data"""
    success: bool
    message: str
    data: dict


@router.post("/generate", response_model=SpeechResponse)
async def generate_speech(
    request: SpeechGenerateRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Generate speech from text"""
    try:
        logger.info(f"Generating speech: voice={request.voice}, language={request.language}")

        result = await speech_generator.generate_speech(
            text=request.text,
            voice=request.voice,
            style=request.style,
            language=request.language,
            output_format=request.output_format,
        )

        cost = float(result.get("cost_usd") or 0.0)
        if user:
            log_usage("speech_generation", user.id, db, cost_usd=cost,
                      metadata={"provider": result.get("provider"), "model": result.get("model"),
                                "char_count": result.get("char_count")})
            try:
                LearningService.record_generation(
                    db=db, user_id=user.id, vertical="general",
                    feature="speech_generation",
                    input_data={"text": request.text[:500]},
                    output_data={"provider": result.get("provider", "unknown"), "cost": cost},
                )
            except Exception:
                pass
            try:
                from ..services.job_service import JobService
                JobService.save_sync_result(
                    db=db, user_id=user.id, job_type="speech_generation",
                    input_data={"text": request.text[:500], "voice": request.voice, "language": request.language},
                    result_data={"provider": result.get("provider"), "model": result.get("model"),
                                 "char_count": result.get("char_count"), "duration_ms": result.get("duration_ms")},
                    cost_usd=cost, provider=result.get("provider", "unknown"),
                )
            except Exception:
                pass

        return SpeechResponse(
            success=True,
            message="Speech generated successfully",
            data={
                "audio_base64": result["audio_base64"],
                "mime_type": result["mime_type"],
                "voice": result["voice"],
                "style": result.get("style"),
                "language": result["language"],
                "duration_ms": result["duration_ms"],
                "model": result["model"],
                "provider": result.get("provider", "unknown"),
            }
        )

    except Exception as e:
        logger.error(f"Speech generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Speech generation failed: {str(e)}")


@router.get("/voices")
async def get_voices():
    """Get available voices"""
    return {
        "success": True,
        "voices": speech_generator.get_available_voices(),
        "total": len(speech_generator.get_available_voices()),
    }


@router.get("/languages")
async def get_languages():
    """Get supported languages"""
    return {
        "success": True,
        "languages": speech_generator.get_supported_languages(),
        "total": len(speech_generator.get_supported_languages()),
    }


@router.post("/download/{audio_id}")
async def download_audio(audio_id: str, audio_data: str):
    """Download audio file"""
    try:
        # Decode base64 audio
        audio_bytes = base64.b64decode(audio_data)

        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/wav",
            headers={"Content-Disposition": f"attachment; filename=affiliate-script-{audio_id[:12]}.wav"}
        )
    except Exception as e:
        logger.error(f"Audio download failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to download audio")
