"""Scene settings registry routes — manage location/setting references."""
import os
import uuid
import shutil
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_current_user
from ..models.campaign import SceneSetting

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "uploads",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("")
async def create_setting(
    name: str = Form(...),
    description: str = Form(default=""),
    location_type: str = Form(default="interior"),
    reference_image: Optional[UploadFile] = File(default=None),
    background_tasks: BackgroundTasks = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    image_path = None
    if reference_image and reference_image.filename:
        ext = os.path.splitext(reference_image.filename)[1] or ".jpg"
        fname = f"setting_{uuid.uuid4().hex[:8]}{ext}"
        image_path = os.path.join(UPLOAD_DIR, fname)
        with open(image_path, "wb") as f:
            shutil.copyfileobj(reference_image.file, f)

    setting = SceneSetting(
        user_id=user.id,
        name=name,
        description=description,
        location_type=location_type,
        reference_image_path=image_path,
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)

    if image_path and background_tasks:
        background_tasks.add_task(_analyze_setting_bg, setting.id, image_path)

    return APIResponse(success=True, message="Setting created", data=_to_dict(setting))


@router.get("")
async def list_settings(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = db.query(SceneSetting).filter(SceneSetting.user_id == user.id).order_by(SceneSetting.created_at.desc()).all()
    return APIResponse(
        success=True,
        message=f"{len(settings)} settings",
        data={"settings": [_to_dict(s) for s in settings]},
    )


@router.get("/{setting_id}")
async def get_setting(
    setting_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    setting = _get_or_404(db, setting_id, user.id)
    return APIResponse(success=True, message="Setting found", data=_to_dict(setting))


class UpdateSettingRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    location_type: Optional[str] = None
    style_tags: Optional[list[str]] = None


@router.patch("/{setting_id}")
async def update_setting(
    setting_id: str,
    body: UpdateSettingRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    setting = _get_or_404(db, setting_id, user.id)
    if body.name is not None:
        setting.name = body.name
    if body.description is not None:
        setting.description = body.description
    if body.location_type is not None:
        setting.location_type = body.location_type
    if body.style_tags is not None:
        setting.style_tags = body.style_tags
    db.commit()
    db.refresh(setting)
    return APIResponse(success=True, message="Setting updated", data=_to_dict(setting))


@router.delete("/{setting_id}")
async def delete_setting(
    setting_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    setting = _get_or_404(db, setting_id, user.id)
    db.delete(setting)
    db.commit()
    return APIResponse(success=True, message="Setting deleted")


# ─────────────────────────────────────────────── Helpers

def _get_or_404(db, setting_id, user_id):
    s = db.query(SceneSetting).filter(SceneSetting.id == setting_id, SceneSetting.user_id == user_id).first()
    if not s:
        raise HTTPException(404, detail="Setting not found")
    return s


def _to_dict(s: SceneSetting) -> dict:
    img_url = None
    if s.reference_image_path and os.path.isfile(s.reference_image_path):
        img_url = f"/api/v1/uploads/{os.path.basename(s.reference_image_path)}"
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "location_type": s.location_type,
        "style_tags": s.style_tags or [],
        "reference_image_url": img_url,
        "created_at": str(s.created_at),
    }


def _analyze_setting_bg(setting_id: str, image_path: str):
    """Background task: analyze setting reference image to extract style_tags + description.
    Retries once on transient failure."""
    from ..database import SessionLocal
    from ..services.reference_analyzer import ReferenceAnalyzerService
    import time

    last_err = None
    for attempt in range(2):
        db = SessionLocal()
        try:
            setting = db.query(SceneSetting).filter(SceneSetting.id == setting_id).first()
            if not setting:
                return
            analysis = ReferenceAnalyzerService.analyze_image(image_path, context="location/setting reference")
            setting_data = analysis.get("setting", {})
            if setting_data.get("style_tags"):
                setting.style_tags = setting_data["style_tags"]
            if setting_data.get("description") and not setting.description:
                setting.description = setting_data["description"]
            db.commit()
            return
        except Exception as e:
            last_err = e
            logger.warning(f"Setting analysis attempt {attempt+1} failed {setting_id}: {e}")
        finally:
            db.close()
        time.sleep(3)
    logger.error(f"Setting analysis gave up for {setting_id} after 2 attempts: {last_err}")
