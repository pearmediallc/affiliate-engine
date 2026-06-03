"""Campaign pipeline routes — full end-to-end creative production."""
import os
import uuid
import shutil
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_current_user
from ..services.campaign_service import CampaignService

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "uploads",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ─────────────────────────────────────────────── Create campaign

@router.post("")
async def create_campaign(
    name: str = Form(...),
    vertical: str = Form(...),
    brief_text: str = Form(default=""),
    reference_video: Optional[UploadFile] = File(default=None),
    reference_image: Optional[UploadFile] = File(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new campaign with optional reference video/image upload."""
    ref_video_path = None
    ref_image_path = None

    if reference_video and reference_video.filename:
        ext = os.path.splitext(reference_video.filename)[1] or ".mp4"
        fname = f"ref_video_{uuid.uuid4().hex[:8]}{ext}"
        ref_video_path = os.path.join(UPLOAD_DIR, fname)
        with open(ref_video_path, "wb") as f:
            shutil.copyfileobj(reference_video.file, f)

    if reference_image and reference_image.filename:
        ext = os.path.splitext(reference_image.filename)[1] or ".jpg"
        fname = f"ref_img_{uuid.uuid4().hex[:8]}{ext}"
        ref_image_path = os.path.join(UPLOAD_DIR, fname)
        with open(ref_image_path, "wb") as f:
            shutil.copyfileobj(reference_image.file, f)

    campaign = CampaignService.create(
        db=db,
        user_id=user.id,
        name=name,
        vertical=vertical,
        brief_text=brief_text,
        reference_video_path=ref_video_path,
        reference_image_path=ref_image_path,
    )
    return APIResponse(success=True, message="Campaign created", data=CampaignService.to_dict(campaign))


@router.get("")
async def list_campaigns(
    limit: int = Query(default=50),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaigns = CampaignService.list_for_user(db, user.id, limit=limit)
    return APIResponse(
        success=True,
        message=f"{len(campaigns)} campaigns",
        data={"campaigns": [CampaignService.to_dict(c) for c in campaigns]},
    )


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaign = _get_or_404(db, campaign_id, user.id)
    return APIResponse(
        success=True,
        message="Campaign found",
        data=CampaignService.to_dict(campaign, include_shots=True, db=db),
    )


# ─────────────────────────────────────────────── Phase transitions

@router.post("/{campaign_id}/brief")
async def run_briefing(
    campaign_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 1: analyze reference video/image and extract structured brief."""
    campaign = _get_or_404(db, campaign_id, user.id)
    campaign = CampaignService.run_briefing(db, campaign)
    return APIResponse(
        success=True,
        message="Brief analysis complete",
        data={"analyzed_brief": campaign.analyzed_brief, "status": campaign.status},
    )


class ScriptingRequest(BaseModel):
    target_duration: int = 30
    extra_instructions: str = ""


@router.post("/{campaign_id}/script")
async def run_scripting(
    campaign_id: str,
    body: ScriptingRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 2: generate ad script from brief."""
    campaign = _get_or_404(db, campaign_id, user.id)
    campaign = CampaignService.run_scripting(
        db, campaign,
        target_duration=body.target_duration,
        extra_instructions=body.extra_instructions,
    )
    return APIResponse(
        success=True,
        message="Script generated",
        data={"script": campaign.script, "status": campaign.status},
    )


class StoryboardRequest(BaseModel):
    character_ids: list[str] = []
    setting_ids: list[str] = []
    target_duration: int = 30


@router.post("/{campaign_id}/storyboard")
async def run_storyboarding(
    campaign_id: str,
    body: StoryboardRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 3: generate shot list storyboard from script."""
    campaign = _get_or_404(db, campaign_id, user.id)
    campaign = CampaignService.run_storyboarding(
        db, campaign,
        character_ids=body.character_ids,
        setting_ids=body.setting_ids,
        target_duration=body.target_duration,
    )
    return APIResponse(
        success=True,
        message="Storyboard generated",
        data={
            "storyboard": campaign.storyboard,
            "status": campaign.status,
            "shots": CampaignService.to_dict(campaign, include_shots=True, db=db).get("shots", []),
        },
    )


@router.post("/{campaign_id}/generate")
async def start_generation(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 4: kick off video generation for all shots."""
    campaign = _get_or_404(db, campaign_id, user.id)
    if campaign.status not in ("storyboarding", "generating", "editing"):
        raise HTTPException(400, detail="Campaign must have a storyboard before generating")
    campaign = CampaignService.start_generation(db, campaign, background_tasks=background_tasks)
    return APIResponse(
        success=True,
        message="Generation started — poll /campaigns/{id} for progress",
        data={"status": campaign.status, "campaign_id": campaign_id},
    )


class EditRequest(BaseModel):
    color_grade: str = "cinematic"
    music_mood: str = "motivational"
    music_volume: float = 0.12


@router.post("/{campaign_id}/edit")
async def run_editing(
    campaign_id: str,
    body: EditRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 5: stitch shots, color grade, add music, export multi-aspect."""
    campaign = _get_or_404(db, campaign_id, user.id)
    if campaign.status != "editing":
        raise HTTPException(400, detail=f"Campaign status is '{campaign.status}', expected 'editing'")

    # Run in background — creates default Variation if none exists
    background_tasks.add_task(
        _run_editing_bg,
        campaign_id=campaign_id,
        color_grade=body.color_grade,
        music_mood=body.music_mood,
        music_volume=body.music_volume,
        user_id=user.id,
    )
    return APIResponse(
        success=True,
        message="Editing started — variations will appear when complete",
        data={"campaign_id": campaign_id},
    )


@router.get("/{campaign_id}/cost")
async def get_cost_estimate(
    campaign_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_or_404(db, campaign_id, user.id)
    return APIResponse(
        success=True,
        message="Cost estimate",
        data=CampaignService.get_cost_estimate(db, campaign_id),
    )


# ─────────────────────────────────────────────── Helpers

def _get_or_404(db: Session, campaign_id: str, user_id: str):
    campaign = CampaignService.get(db, campaign_id, user_id)
    if not campaign:
        raise HTTPException(404, detail="Campaign not found")
    return campaign


def _run_editing_bg(campaign_id: str, color_grade: str, music_mood: str, music_volume: float, user_id: str):
    """Background task: create default variation and run auto-editor."""
    from ..database import SessionLocal
    from ..models.campaign import Campaign, Shot, Variation
    from ..services.variation_engine import VariationEngine
    from ..services.auto_editor import AutoEditorService

    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            return

        # Create a "base" variation if none exists, OR refresh an existing one
        # whose shot copies are stale. Staleness happens when /storyboard is
        # re-run after a failed edit — the base shots get deleted + recreated
        # while the variation's shot copies survive with dead video_paths
        # pointing at files that never existed.
        variation = (
            db.query(Variation)
            .filter(Variation.campaign_id == campaign_id)
            .order_by(Variation.created_at.desc())
            .first()
        )
        if variation is None:
            variation = Variation(
                campaign_id=campaign_id,
                variation_type="base",
                label="Base edit",
                status="editing",
            )
            db.add(variation)
            db.flush()

        # Always refresh the variation's shot copies from current base shots.
        # Cheap (the variation row + shot rows are small) and guarantees the
        # AutoEditor sees video_paths matching what /generate actually produced.
        db.query(Shot).filter(Shot.variation_id == variation.id).delete()
        base_shots = (
            db.query(Shot)
            .filter(Shot.campaign_id == campaign_id, Shot.variation_id == None)
            .order_by(Shot.sequence_num)
            .all()
        )
        from ..models.campaign import Shot as ShotModel
        for shot in base_shots:
            vs = ShotModel(
                campaign_id=campaign_id,
                variation_id=variation.id,
                sequence_num=shot.sequence_num,
                shot_type=shot.shot_type,
                prompt=shot.prompt,
                model_id=shot.model_id,
                duration=shot.duration,
                video_path=shot.video_path,
                video_url=shot.video_url,
                status=shot.status,
                cost_usd=shot.cost_usd,
            )
            db.add(vs)
        variation.status = "editing"
        db.commit()

        AutoEditorService.render_variation(
            variation_id=variation.id,
            color_grade=color_grade,
            music_mood=music_mood,
            music_volume=music_volume,
        )

        campaign.status = "review"
        db.commit()

    except Exception as e:
        logger.error(f"Editing background task failed for {campaign_id}: {e}", exc_info=True)
        db.query(Campaign).filter(Campaign.id == campaign_id).update({"status": "editing"})
        db.commit()
    finally:
        db.close()
