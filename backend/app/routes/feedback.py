import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..schemas import APIResponse
from ..models.feedback import GenerationFeedback
from ..models.image import Image
from ..middleware.auth import get_optional_user, log_usage
from ..services.learning_service import LearningService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class FeedbackSubmitRequest(BaseModel):
    image_id: str
    rating: str  # "positive" or "negative"
    issues: List[str] = []
    comment: Optional[str] = None


@router.post("/submit")
async def submit_feedback(
    request: FeedbackSubmitRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Submit feedback for a generated image"""
    if request.rating not in ("positive", "negative"):
        raise HTTPException(status_code=400, detail="Rating must be 'positive' or 'negative'")

    # Look up the image to get vertical and prompt_used
    image = db.query(Image).filter(Image.id == request.image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    feedback = GenerationFeedback(
        id=f"fb_{uuid.uuid4().hex[:12]}",
        image_id=request.image_id,
        rating=request.rating,
        issues=",".join(request.issues) if request.issues else None,
        comment=request.comment,
        vertical=image.vertical,
        prompt_used=image.prompt_used,
    )
    db.add(feedback)
    db.commit()

    # Record feedback in learning system
    try:
        LearningService.record_feedback(
            db=db,
            image_id=request.image_id,
            rating=request.rating,
            issues=request.issues,
            comment=request.comment,
        )
    except Exception as learn_err:
        logger.warning(f"Failed to record feedback in learning: {learn_err}")

    if user:
        log_usage("feedback_submit", user.id, db, cost_usd=0.0)

    return APIResponse(
        success=True,
        message="Feedback submitted",
        data={"feedback_id": feedback.id},
    )


@router.get("/summary/{vertical}")
async def get_feedback_summary(
    vertical: str,
    db: Session = Depends(get_db),
):
    """Get feedback summary for a vertical"""
    base_query = db.query(GenerationFeedback).filter(GenerationFeedback.vertical == vertical)

    positive_count = base_query.filter(GenerationFeedback.rating == "positive").count()
    negative_count = base_query.filter(GenerationFeedback.rating == "negative").count()

    # Top issues from negative feedback
    negative_with_issues = (
        base_query
        .filter(GenerationFeedback.rating == "negative")
        .filter(GenerationFeedback.issues.isnot(None))
        .all()
    )

    issue_counts: dict[str, int] = {}
    for fb in negative_with_issues:
        for issue in fb.issues.split(","):
            tag = issue.strip()
            if tag:
                issue_counts[tag] = issue_counts.get(tag, 0) + 1

    top_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Recent negative feedback
    recent_negative = (
        base_query
        .filter(GenerationFeedback.rating == "negative")
        .order_by(GenerationFeedback.created_at.desc())
        .limit(10)
        .all()
    )

    recent_list = [
        {
            "id": fb.id,
            "image_id": fb.image_id,
            "issues": fb.issues,
            "comment": fb.comment,
            "prompt_used": fb.prompt_used,
            "created_at": fb.created_at.isoformat() if fb.created_at else None,
        }
        for fb in recent_negative
    ]

    return APIResponse(
        success=True,
        message=f"Feedback summary for {vertical}",
        data={
            "vertical": vertical,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "top_issues": [{"issue": issue, "count": count} for issue, count in top_issues],
            "recent_negative": recent_list,
        },
    )
