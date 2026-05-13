"""Variation routes — create and manage campaign variants."""
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_current_user
from ..models.campaign import Campaign, Variation
from ..services.variation_engine import VariationEngine
from ..services.auto_editor import AutoEditorService

logger = logging.getLogger(__name__)
router = APIRouter()


class PlanVariantsRequest(BaseModel):
    strategies: list[str] = ["hook", "style"]
    num_per_strategy: int = 3


@router.post("/{campaign_id}/plan")
async def plan_variants(
    campaign_id: str,
    body: PlanVariantsRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview variant plans with cost estimates — no generation yet."""
    _check_campaign(db, campaign_id, user.id)
    plans = VariationEngine.plan_variants(
        db, campaign_id,
        strategies=body.strategies,
        num_per_strategy=body.num_per_strategy,
    )
    return APIResponse(
        success=True,
        message=f"{len(plans)} variant plans",
        data={"plans": plans},
    )


class CreateVariationRequest(BaseModel):
    strategy: str           # hook | character | style | setting | vertical_port
    label: str = ""
    new_character_id: Optional[str] = None
    new_setting_id: Optional[str] = None
    style_model: Optional[str] = None
    new_vertical: Optional[str] = None
    auto_generate: bool = True    # immediately start generation after creating
    auto_edit: bool = False       # immediately run editing after generation


@router.post("/{campaign_id}/create")
async def create_variation(
    campaign_id: str,
    body: CreateVariationRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a variant and optionally start generation."""
    campaign = _check_campaign(db, campaign_id, user.id)
    label = body.label or f"{body.strategy.title()} variant"

    variation = VariationEngine.create_variation(
        db=db,
        campaign=campaign,
        strategy=body.strategy,
        label=label,
        new_character_id=body.new_character_id,
        new_setting_id=body.new_setting_id,
        style_model=body.style_model,
        new_vertical=body.new_vertical,
    )

    if body.auto_generate:
        VariationEngine.start_generation(db, variation, background_tasks=background_tasks)

    return APIResponse(
        success=True,
        message="Variation created",
        data=VariationEngine.to_dict(variation, include_shots=True, db=db),
    )


@router.get("/{campaign_id}/list")
async def list_variations(
    campaign_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_campaign(db, campaign_id, user.id)
    variations = VariationEngine.get_variations(db, campaign_id)
    return APIResponse(
        success=True,
        message=f"{len(variations)} variations",
        data={"variations": [VariationEngine.to_dict(v) for v in variations]},
    )


@router.get("/{campaign_id}/{variation_id}")
async def get_variation(
    campaign_id: str,
    variation_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_campaign(db, campaign_id, user.id)
    variation = _get_variation_or_404(db, variation_id, campaign_id)
    return APIResponse(
        success=True,
        message="Variation found",
        data=VariationEngine.to_dict(variation, include_shots=True, db=db),
    )


class EditVariationRequest(BaseModel):
    color_grade: str = "cinematic"
    music_mood: str = "motivational"
    music_volume: float = 0.12


@router.post("/{campaign_id}/{variation_id}/edit")
async def edit_variation(
    campaign_id: str,
    variation_id: str,
    body: EditVariationRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run auto-editor on a completed variation."""
    _check_campaign(db, campaign_id, user.id)
    variation = _get_variation_or_404(db, variation_id, campaign_id)

    background_tasks.add_task(
        AutoEditorService.render_variation,
        variation_id=variation.id,
        color_grade=body.color_grade,
        music_mood=body.music_mood,
        music_volume=body.music_volume,
    )
    return APIResponse(
        success=True,
        message="Editing started",
        data={"variation_id": variation_id},
    )


class ReviewRequest(BaseModel):
    action: str  # approve | reject


@router.post("/{campaign_id}/{variation_id}/review")
async def review_variation(
    campaign_id: str,
    variation_id: str,
    body: ReviewRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve or reject a variation after review."""
    _check_campaign(db, campaign_id, user.id)
    variation = _get_variation_or_404(db, variation_id, campaign_id)

    if body.action == "approve":
        variation = VariationEngine.approve(db, variation)
    elif body.action == "reject":
        variation = VariationEngine.reject(db, variation)
    else:
        raise HTTPException(400, detail="action must be 'approve' or 'reject'")

    return APIResponse(
        success=True,
        message=f"Variation {body.action}d",
        data={"variation_id": variation_id, "review_status": variation.review_status},
    )


# ─────────────────────────────────────────────── Helpers

def _check_campaign(db: Session, campaign_id: str, user_id: str) -> Campaign:
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.user_id == user_id).first()
    if not campaign:
        raise HTTPException(404, detail="Campaign not found")
    return campaign


def _get_variation_or_404(db: Session, variation_id: str, campaign_id: str) -> Variation:
    v = db.query(Variation).filter(Variation.id == variation_id, Variation.campaign_id == campaign_id).first()
    if not v:
        raise HTTPException(404, detail="Variation not found")
    return v
