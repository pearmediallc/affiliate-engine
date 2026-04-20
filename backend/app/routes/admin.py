"""Admin routes - dashboard, feedback review, AI suggestions, learning stats"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import require_admin
from ..models.image import Image
from ..models.feedback import GenerationFeedback
from ..models.user import User, UsageLog
from ..models.learning import LearningRecord, VerticalKnowledge, AISuggestion
from ..services.learning_service import LearningService

router = APIRouter()


@router.get("/dashboard")
async def admin_dashboard(
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Overview stats: total users, generations, spend, satisfaction by vertical"""
    total_users = db.query(func.count(User.id)).scalar()
    total_generations = db.query(func.count(Image.id)).scalar()
    total_spend = db.query(func.coalesce(func.sum(Image.cost_usd), 0.0)).scalar()

    # Satisfaction by vertical
    verticals = (
        db.query(
            GenerationFeedback.vertical,
            func.count(GenerationFeedback.id).label("total"),
            func.count(
                case((GenerationFeedback.rating == "positive", 1))
            ).label("positive"),
        )
        .group_by(GenerationFeedback.vertical)
        .all()
    )

    satisfaction_by_vertical = {}
    for v in verticals:
        satisfaction_by_vertical[v.vertical] = {
            "total_feedback": v.total,
            "positive": v.positive,
            "satisfaction": v.positive / v.total if v.total > 0 else None,
        }

    pending_suggestions = db.query(func.count(AISuggestion.id)).filter(
        AISuggestion.status == "pending"
    ).scalar()

    return APIResponse(
        success=True,
        message="Admin dashboard",
        data={
            "total_users": total_users,
            "total_generations": total_generations,
            "total_spend": float(total_spend),
            "satisfaction_by_vertical": satisfaction_by_vertical,
            "pending_suggestions": pending_suggestions,
        },
    )


@router.get("/feedback")
async def list_feedback(
    vertical: Optional[str] = Query(None),
    rating: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all feedback with image details, prompt, cost, user info"""
    query = (
        db.query(GenerationFeedback, Image)
        .join(Image, GenerationFeedback.image_id == Image.id)
    )

    if vertical:
        query = query.filter(GenerationFeedback.vertical == vertical)
    if rating:
        query = query.filter(GenerationFeedback.rating == rating)

    total = query.count()
    results = (
        query
        .order_by(GenerationFeedback.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []
    for fb, img in results:
        # Look up user via image's client_id (best-effort)
        user_info = None
        if img.client_id:
            user = db.query(User).filter(User.id == img.client_id).first()
            if user:
                user_info = {
                    "email": user.email,
                    "role": user.role.name if user.role else None,
                }

        items.append({
            "image_id": img.id,
            "image_url": img.image_url,
            "prompt_used": img.prompt_used,
            "provider": img.generation_provider,
            "model": img.generation_model,
            "cost": img.cost_usd,
            "vertical": fb.vertical,
            "style": img.image_path,  # style info if available
            "feedback": {
                "rating": fb.rating,
                "issues": fb.issues.split(",") if fb.issues else [],
                "comment": fb.comment,
            },
            "user": user_info,
            "created_at": fb.created_at.isoformat() if fb.created_at else None,
        })

    return APIResponse(
        success=True,
        message=f"Feedback list ({total} total)",
        data={"items": items, "total": total, "limit": limit, "offset": offset},
    )


@router.get("/feedback/{image_id}")
async def get_feedback_detail(
    image_id: str,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Detailed view of a single generation with all linked assets"""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    feedback_list = (
        db.query(GenerationFeedback)
        .filter(GenerationFeedback.image_id == image_id)
        .order_by(GenerationFeedback.created_at.desc())
        .all()
    )

    # Get linked assets
    from ..models.learning import Asset
    assets = (
        db.query(Asset)
        .filter(Asset.related_image_id == image_id)
        .all()
    )

    # Get linked learning records
    learning_records = db.query(LearningRecord).all()
    linked_records = []
    for r in learning_records:
        if r.output_data and isinstance(r.output_data, dict):
            if r.output_data.get("image_id") == image_id:
                linked_records.append({
                    "id": r.id,
                    "feature": r.feature,
                    "input_data": r.input_data,
                    "output_data": r.output_data,
                    "feedback_rating": r.feedback_rating,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })

    return APIResponse(
        success=True,
        message=f"Detail for image {image_id}",
        data={
            "image": {
                "id": image.id,
                "image_url": image.image_url,
                "image_path": image.image_path,
                "prompt_used": image.prompt_used,
                "provider": image.generation_provider,
                "model": image.generation_model,
                "cost": image.cost_usd,
                "vertical": image.vertical,
                "quality_score": image.quality_score,
                "created_at": image.created_at.isoformat() if image.created_at else None,
            },
            "feedback": [
                {
                    "id": fb.id,
                    "rating": fb.rating,
                    "issues": fb.issues.split(",") if fb.issues else [],
                    "comment": fb.comment,
                    "created_at": fb.created_at.isoformat() if fb.created_at else None,
                }
                for fb in feedback_list
            ],
            "assets": [
                {
                    "id": a.id,
                    "asset_type": a.asset_type,
                    "original_filename": a.original_filename,
                    "mime_type": a.mime_type,
                    "size_bytes": a.size_bytes,
                    "metadata": a.metadata_json,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in assets
            ],
            "learning_records": linked_records,
        },
    )


@router.get("/ai-suggestions")
async def list_ai_suggestions(
    status: Optional[str] = Query("pending"),
    vertical: Optional[str] = Query(None),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List AI suggestions, default to pending"""
    query = db.query(AISuggestion)
    if status:
        query = query.filter(AISuggestion.status == status)
    if vertical:
        query = query.filter(AISuggestion.vertical == vertical)

    suggestions = query.order_by(AISuggestion.created_at.desc()).all()

    return APIResponse(
        success=True,
        message=f"{len(suggestions)} suggestions",
        data={
            "suggestions": [
                {
                    "id": s.id,
                    "category": s.category,
                    "vertical": s.vertical,
                    "suggestion_text": s.suggestion_text,
                    "suggested_change": s.suggested_change,
                    "evidence": s.evidence,
                    "status": s.status,
                    "reviewed_by": s.reviewed_by,
                    "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in suggestions
            ]
        },
    )


@router.post("/ai-suggestions/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: str,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve an AI suggestion"""
    suggestion = db.query(AISuggestion).filter(AISuggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    suggestion.status = "approved"
    suggestion.reviewed_by = admin.id
    suggestion.reviewed_at = datetime.utcnow()
    db.commit()

    return APIResponse(
        success=True,
        message=f"Suggestion {suggestion_id} approved",
        data={"id": suggestion_id, "status": "approved"},
    )


@router.post("/ai-suggestions/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reject an AI suggestion"""
    suggestion = db.query(AISuggestion).filter(AISuggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    suggestion.status = "rejected"
    suggestion.reviewed_by = admin.id
    suggestion.reviewed_at = datetime.utcnow()
    db.commit()

    return APIResponse(
        success=True,
        message=f"Suggestion {suggestion_id} rejected",
        data={"id": suggestion_id, "status": "rejected"},
    )


@router.post("/ai-suggestions/analyze/{vertical}")
async def trigger_analysis(
    vertical: str,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Trigger learning analysis for a vertical, then generate suggestions"""
    result = await LearningService.analyze_vertical(db, vertical)

    suggestions = []
    if result.get("status") == "analyzed":
        suggestion_objects = await LearningService.generate_suggestions(db, vertical)
        suggestions = [
            {"id": s.id, "text": s.suggestion_text, "category": s.category}
            for s in suggestion_objects
        ]

    return APIResponse(
        success=True,
        message=f"Analysis complete for {vertical}",
        data={**result, "new_suggestions": suggestions},
    )


@router.get("/learning/{vertical}")
async def get_learning_stats(
    vertical: str,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get learning stats for a vertical"""
    stats = LearningService.get_vertical_stats(db, vertical)
    return APIResponse(
        success=True,
        message=f"Learning stats for {vertical}",
        data=stats,
    )


@router.get("/usage")
async def get_usage_logs(
    user_id: Optional[str] = Query(None),
    feature: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Usage logs grouped by user and feature"""
    # Summary: usage grouped by user and feature
    summary_query = (
        db.query(
            UsageLog.user_id,
            UsageLog.feature,
            func.count(UsageLog.id).label("count"),
        )
    )

    if user_id:
        summary_query = summary_query.filter(UsageLog.user_id == user_id)
    if feature:
        summary_query = summary_query.filter(UsageLog.feature == feature)

    summary = (
        summary_query
        .group_by(UsageLog.user_id, UsageLog.feature)
        .all()
    )

    # Recent logs
    log_query = db.query(UsageLog)
    if user_id:
        log_query = log_query.filter(UsageLog.user_id == user_id)
    if feature:
        log_query = log_query.filter(UsageLog.feature == feature)

    total = log_query.count()
    logs = (
        log_query
        .order_by(UsageLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Look up user emails for the summary
    user_ids = list({s.user_id for s in summary})
    users = {u.id: u.email for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    return APIResponse(
        success=True,
        message=f"Usage logs ({total} total)",
        data={
            "summary": [
                {
                    "user_id": s.user_id,
                    "email": users.get(s.user_id),
                    "feature": s.feature,
                    "count": s.count,
                }
                for s in summary
            ],
            "recent_logs": [
                {
                    "id": log.id,
                    "user_id": log.user_id,
                    "feature": log.feature,
                    "cost_usd": log.cost_usd,
                    "metadata": log.metadata_json,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in logs
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    )


@router.get("/model-config")
async def get_model_config(admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Get current AI model priority configuration"""
    from ..config import settings
    return APIResponse(
        success=True,
        message="Model configuration",
        data={
            "image_generation": {
                "primary": settings.image_provider,
                "models": {
                    "gemini": {"model": settings.gemini_image_model, "status": "available" if settings.gemini_api_key else "no_key"},
                    "openai": {"model": "dall-e-3", "status": "available" if settings.openai_api_key else "no_key"},
                    "fal": {"model": "flux-dev", "status": "available" if settings.fal_api_key else "no_key"},
                },
            },
            "text_ai": {
                "model": settings.gemini_model,
            },
            "image_model": settings.gemini_image_model,
            "hook_analyzer": "gemini-2.5-flash",
        },
    )


@router.put("/model-config")
async def update_model_config(
    request: dict,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update AI model priority configuration (runtime only, resets on restart)"""
    from ..config import settings

    if "primary_provider" in request:
        settings.image_provider = request["primary_provider"]
    if "gemini_image_model" in request:
        settings.gemini_image_model = request["gemini_image_model"]
    if "gemini_model" in request:
        settings.gemini_model = request["gemini_model"]

    return APIResponse(
        success=True,
        message="Model configuration updated (runtime only)",
        data={"primary_provider": settings.image_provider, "image_model": settings.gemini_image_model},
    )


@router.get("/models/registry")
async def get_model_registry(admin=Depends(require_admin)):
    """Get the full model registry with availability status"""
    from ..services.model_registry import ModelRegistryService
    return APIResponse(
        success=True,
        message="Model registry",
        data={
            "registry": ModelRegistryService.get_all(),
            "summary": ModelRegistryService.get_available_count(),
        },
    )
