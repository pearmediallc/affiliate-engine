"""Character registry routes — manage brand characters for consistent video generation."""
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
from ..models.campaign import Character

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "uploads",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("")
async def create_character(
    name: str = Form(...),
    description: str = Form(default=""),
    portrait: Optional[UploadFile] = File(default=None),
    background_tasks: BackgroundTasks = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new character. Optionally upload a portrait image.
    If portrait is uploaded, auto-generates a consistency_prompt via Pixtral.
    """
    portrait_path = None
    if portrait and portrait.filename:
        ext = os.path.splitext(portrait.filename)[1] or ".jpg"
        fname = f"char_{uuid.uuid4().hex[:8]}{ext}"
        portrait_path = os.path.join(UPLOAD_DIR, fname)
        with open(portrait_path, "wb") as f:
            shutil.copyfileobj(portrait.file, f)

    char = Character(
        user_id=user.id,
        name=name,
        description=description,
        portrait_path=portrait_path,
    )
    db.add(char)
    db.commit()
    db.refresh(char)

    # Analyze portrait in background to generate consistency_prompt
    if portrait_path and background_tasks:
        background_tasks.add_task(_analyze_portrait_bg, char.id, portrait_path)

    return APIResponse(
        success=True,
        message="Character created",
        data=_to_dict(char),
    )


@router.get("")
async def list_characters(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chars = db.query(Character).filter(Character.user_id == user.id).order_by(Character.created_at.desc()).all()
    return APIResponse(
        success=True,
        message=f"{len(chars)} characters",
        data={"characters": [_to_dict(c) for c in chars]},
    )


@router.get("/{character_id}")
async def get_character(
    character_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _get_or_404(db, character_id, user.id)
    return APIResponse(success=True, message="Character found", data=_to_dict(char))


class UpdateCharacterRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    consistency_prompt: Optional[str] = None


@router.patch("/{character_id}")
async def update_character(
    character_id: str,
    body: UpdateCharacterRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _get_or_404(db, character_id, user.id)
    if body.name is not None:
        char.name = body.name
    if body.description is not None:
        char.description = body.description
    if body.consistency_prompt is not None:
        char.consistency_prompt = body.consistency_prompt
    db.commit()
    db.refresh(char)
    return APIResponse(success=True, message="Character updated", data=_to_dict(char))


@router.delete("/{character_id}")
async def delete_character(
    character_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _get_or_404(db, character_id, user.id)
    db.delete(char)
    db.commit()
    return APIResponse(success=True, message="Character deleted")


# ─────────────────────────────────────────────── Helpers

def _get_or_404(db: Session, char_id: str, user_id: str) -> Character:
    char = db.query(Character).filter(Character.id == char_id, Character.user_id == user_id).first()
    if not char:
        raise HTTPException(404, detail="Character not found")
    return char


def _to_dict(char: Character) -> dict:
    portrait_url = None
    if char.portrait_path and os.path.isfile(char.portrait_path):
        portrait_url = f"/api/v1/uploads/{os.path.basename(char.portrait_path)}"
    return {
        "id": char.id,
        "name": char.name,
        "description": char.description,
        "portrait_url": portrait_url,
        "consistency_prompt": char.consistency_prompt,
        "created_at": str(char.created_at),
    }


def _analyze_portrait_bg(char_id: str, portrait_path: str):
    """Background task: analyze portrait with Pixtral to generate consistency_prompt."""
    from ..database import SessionLocal
    from ..services.reference_analyzer import ReferenceAnalyzerService

    db = SessionLocal()
    try:
        char = db.query(Character).filter(Character.id == char_id).first()
        if not char:
            return
        analysis = ReferenceAnalyzerService.analyze_image(portrait_path, context="character portrait")
        char_data = analysis.get("character", {})
        consistency = char_data.get("consistency_prompt") or analysis.get("description", "")
        if consistency:
            char.consistency_prompt = consistency
            db.commit()
    except Exception as e:
        logger.error(f"Portrait analysis failed for char {char_id}: {e}")
    finally:
        db.close()
