"""Audit-log routes.

- POST /audit/track-screen — frontend reports a page view (any logged-in user).
- GET  /admin/audit-log    — admin reads the audit timeline (paginated, filterable).
                              Mounted under /admin in main router.
"""
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_optional_user, require_admin
from ..models.audit_log import AuditLog, ACTION_PAGE_VIEW
from ..services.audit_log_service import record, record_for_user

router = APIRouter()


class TrackScreenRequest(BaseModel):
    screen: str
    referrer: Optional[str] = None
    metadata: Optional[dict] = None


@router.post("/track-screen")
async def track_screen(
    body: TrackScreenRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Frontend hook posts here whenever the route changes. Records a page-view
    audit row tagged with the current user (if any)."""
    record_for_user(
        db, user,
        action=ACTION_PAGE_VIEW,
        category="navigation",
        screen=body.screen,
        metadata={
            "referrer": body.referrer,
            **(body.metadata or {}),
        },
    )
    return APIResponse(success=True, message="recorded", data={"screen": body.screen})


# ---- Admin endpoints (mounted under /admin in main router) -------------------

@router.get("/audit-log")
async def list_audit_log(
    user_id: Optional[str] = Query(None),
    user_email: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    screen: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    status_code: Optional[int] = Query(None),
    ip: Optional[str] = Query(None),
    since_hours: Optional[int] = Query(None, ge=1, le=720),
    search: Optional[str] = Query(None, description="Free-text search across path/screen/email"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Read paginated audit-log entries. Admin only."""
    q = db.query(AuditLog)

    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if user_email:
        q = q.filter(AuditLog.user_email == user_email)
    if action:
        q = q.filter(AuditLog.action == action)
    if category:
        q = q.filter(AuditLog.category == category)
    if screen:
        q = q.filter(AuditLog.screen == screen)
    if method:
        q = q.filter(AuditLog.method == method.upper())
    if status_code is not None:
        q = q.filter(AuditLog.status_code == status_code)
    if ip:
        q = q.filter(AuditLog.ip == ip)
    if since_hours:
        cutoff = datetime.utcnow() - timedelta(hours=since_hours)
        q = q.filter(AuditLog.timestamp >= cutoff)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            AuditLog.path.like(like),
            AuditLog.screen.like(like),
            AuditLog.user_email.like(like),
            AuditLog.action.like(like),
        ))

    total = q.count()
    rows = (
        q.order_by(desc(AuditLog.timestamp))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return APIResponse(
        success=True,
        message=f"{total} audit entries",
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "entries": [_serialize(e) for e in rows],
        },
    )


@router.get("/audit-log/summary")
async def audit_log_summary(
    since_hours: int = Query(24, ge=1, le=720),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Top-level rollups for the audit-log dashboard."""
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    base = db.query(AuditLog).filter(AuditLog.timestamp >= cutoff)

    total = base.count()
    by_action = (
        base.with_entities(AuditLog.action, func.count(AuditLog.id))
        .group_by(AuditLog.action).order_by(desc(func.count(AuditLog.id))).limit(20).all()
    )
    by_user = (
        base.with_entities(AuditLog.user_email, func.count(AuditLog.id))
        .filter(AuditLog.user_email.isnot(None))
        .group_by(AuditLog.user_email).order_by(desc(func.count(AuditLog.id))).limit(10).all()
    )
    by_screen = (
        base.with_entities(AuditLog.screen, func.count(AuditLog.id))
        .filter(AuditLog.screen.isnot(None))
        .group_by(AuditLog.screen).order_by(desc(func.count(AuditLog.id))).limit(10).all()
    )
    failed_logins = base.filter(AuditLog.action == "login_failed").count()

    return APIResponse(
        success=True,
        message="audit summary",
        data={
            "since_hours": since_hours,
            "total_events": total,
            "failed_logins": failed_logins,
            "by_action": [{"action": a or "unknown", "count": c} for a, c in by_action],
            "by_user": [{"user_email": e, "count": c} for e, c in by_user],
            "by_screen": [{"screen": s, "count": c} for s, c in by_screen],
        },
    )


def _serialize(e: AuditLog) -> dict:
    return {
        "id": e.id,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "user_id": e.user_id,
        "user_email": e.user_email,
        "role": e.role,
        "action": e.action,
        "category": e.category,
        "resource_type": e.resource_type,
        "resource_id": e.resource_id,
        "screen": e.screen,
        "method": e.method,
        "path": e.path,
        "status_code": e.status_code,
        "duration_ms": e.duration_ms,
        "ip": e.ip,
        "user_agent": e.user_agent,
        "metadata": e.metadata_json,
    }
