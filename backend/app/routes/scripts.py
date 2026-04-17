from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from ..database import get_db
from ..schemas import APIResponse
from ..services import ScriptGeneratorService
from ..services.learning_service import LearningService
from ..middleware.auth import get_optional_user, log_usage
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# Request Schemas
class GenerateScriptRequest(BaseModel):
    product: str
    vertical: str
    target_audience: str
    framework: str = "PAS"
    angle: str = "benefit"
    psychological_triggers: Optional[list[str]] = None
    include_cta: bool = True
    desired_duration_seconds: Optional[int] = 30  # Target duration: 15, 30, 60, 90, 120 seconds


class IterateScriptRequest(BaseModel):
    original_script: str
    feedback: str
    preserve_elements: Optional[list[str]] = None


# Endpoints
@router.post("/generate")
async def generate_script(
    request: GenerateScriptRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Generate high-converting affiliate scripts using copywriting frameworks

    Supports custom script duration targeting:
    - 15 seconds: Quick hooks for social media
    - 30 seconds: Standard TikTok/Instagram Reels (DEFAULT)
    - 60 seconds: Extended YouTube Shorts/mid-roll ads
    - 90 seconds: Premium ad content
    - 120+ seconds: Long-form sales content
    """
    try:
        generator = ScriptGeneratorService()
        result = await generator.generate_script(
            product=request.product,
            vertical=request.vertical,
            target_audience=request.target_audience,
            framework=request.framework,
            angle=request.angle,
            psychological_triggers=request.psychological_triggers,
            include_cta=request.include_cta,
            desired_duration_seconds=request.desired_duration_seconds or 30,
        )
        if user:
            log_usage("script_generation", user.id, db, cost_usd=0.02)
            try:
                LearningService.record_generation(
                    db=db, user_id=user.id, vertical=request.vertical,
                    feature="script_generation",
                    input_data={"product": request.product, "framework": request.framework, "angle": request.angle},
                    output_data={"provider": "gemini", "cost": 0.02},
                )
            except Exception:
                pass
        return APIResponse(success=True, message="Scripts generated successfully", data=result)
    except Exception as e:
        logger.error(f"Script generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/iterate")
async def iterate_script(request: IterateScriptRequest):
    """Improve a script based on feedback"""
    try:
        generator = ScriptGeneratorService()
        result = await generator.iterate_script(
            original_script=request.original_script,
            feedback=request.feedback,
            preserve_elements=request.preserve_elements,
        )
        return APIResponse(success=True, message="Script iteration completed", data=result)
    except Exception as e:
        logger.error(f"Script iteration failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frameworks")
async def get_frameworks():
    """Get all available copywriting frameworks"""
    try:
        generator = ScriptGeneratorService()
        frameworks = generator.get_available_frameworks()
        return APIResponse(success=True, message="Frameworks retrieved", data=frameworks)
    except Exception as e:
        logger.error(f"Failed to get frameworks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/triggers")
async def get_triggers():
    """Get all available psychological triggers"""
    try:
        generator = ScriptGeneratorService()
        triggers = generator.get_available_triggers()
        return APIResponse(success=True, message="Triggers retrieved", data=triggers)
    except Exception as e:
        logger.error(f"Failed to get triggers: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
