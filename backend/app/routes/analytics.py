from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..services import AnalyticsService
from ..middleware.auth import get_optional_user

router = APIRouter()


@router.get("/overview")
async def get_analytics_overview(
    client_id: str = Query("demo-client", description="Client ID"),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Get overall analytics for the current user.

    Combines per-client image spend with per-user job spend (Veo videos,
    lip-sync, TTS, transcription, long-video).
    """
    user_id = user.id if user else None
    analytics = AnalyticsService.get_client_analytics(db, client_id, user_id=user_id)
    return APIResponse(success=True, message="Analytics retrieved", data=analytics)


@router.get("/vertical/{vertical}")
async def get_vertical_analytics(
    vertical: str,
    client_id: str = Query("demo-client", description="Client ID"),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Get analytics for a specific vertical (image + job spend)."""
    user_id = user.id if user else None
    analytics = AnalyticsService.get_vertical_analytics(db, client_id, vertical, user_id=user_id)
    return APIResponse(success=True, message=f"Analytics for {vertical}", data=analytics)


@router.get("/top-templates")
async def get_top_templates(
    client_id: str = Query("demo-client", description="Client ID"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Get top performing templates"""
    templates = AnalyticsService.get_top_templates(db, client_id, limit)
    return APIResponse(success=True, message="Top templates retrieved", data={"templates": templates})


@router.get("/billing")
async def get_billing_breakdown(
    client_id: str = Query("demo-client", description="Client ID"),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Get per-provider billing breakdown — combines image + job spend."""
    user_id = user.id if user else None
    billing = AnalyticsService.get_billing_breakdown(db, client_id, user_id=user_id)
    return APIResponse(success=True, message="Billing breakdown retrieved", data=billing)


@router.get("/time-series")
async def get_time_series(
    client_id: str = Query("demo-client", description="Client ID"),
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Get analytics over time"""
    user_id = user.id if user else None
    data = AnalyticsService.get_time_series_analytics(db, client_id, days, user_id=user_id)
    return APIResponse(success=True, message="Time series data retrieved", data={"timeseries": data})
