"""Job routes - persistent job tracking for all async generations"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_current_user, require_admin
from ..services.job_service import JobService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/my")
async def get_my_jobs(
    job_type: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=50),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current user's jobs"""
    jobs = JobService.get_user_jobs(
        db, user.id,
        job_type=job_type or None,
        status=status or None,
        limit=limit,
    )
    return APIResponse(
        success=True,
        message=f"Found {len(jobs)} jobs",
        data={
            "jobs": [
                {
                    "id": j.id,
                    "job_type": j.job_type,
                    "status": j.status,
                    "provider": j.provider,
                    "input_data": j.input_data,
                    "result_data": j.result_data,
                    "result_url": j.result_url,
                    "error_message": j.error_message,
                    "cost_usd": j.cost_usd,
                    "vertical": j.vertical,
                    "created_at": str(j.created_at),
                }
                for j in jobs
            ]
        },
    )


@router.get("/active")
async def get_active_jobs(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's currently processing jobs"""
    jobs = JobService.get_active_jobs(db, user.id)
    return APIResponse(
        success=True,
        message=f"{len(jobs)} active jobs",
        data={
            "jobs": [
                {
                    "id": j.id,
                    "job_type": j.job_type,
                    "status": j.status,
                    "provider": j.provider,
                    "provider_job_id": j.provider_job_id,
                    "created_at": str(j.created_at),
                }
                for j in jobs
            ]
        },
    )


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific job by ID"""
    job = JobService.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != user.id and not (user.role and user.role.name == "admin"):
        raise HTTPException(status_code=403, detail="Not your job")

    return APIResponse(
        success=True,
        message=f"Job {job.status}",
        data={
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "provider": job.provider,
            "provider_job_id": job.provider_job_id,
            "input_data": job.input_data,
            "result_data": job.result_data,
            "result_url": job.result_url,
            "error_message": job.error_message,
            "cost_usd": job.cost_usd,
            "vertical": job.vertical,
            "admin_feedback_rating": job.admin_feedback_rating,
            "admin_feedback_comment": job.admin_feedback_comment,
            "created_at": str(job.created_at),
            "updated_at": str(job.updated_at),
        },
    )


# --- Admin endpoints ---

@router.get("/admin/all")
async def admin_get_all_jobs(
    user_id: str = Query(default=""),
    job_type: str = Query(default=""),
    status: str = Query(default=""),
    vertical: str = Query(default=""),
    page: int = Query(default=1),
    page_size: int = Query(default=50),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin: get all jobs with filtering"""
    result = JobService.get_all_jobs_admin(
        db,
        user_id=user_id or None,
        job_type=job_type or None,
        status=status or None,
        vertical=vertical or None,
        page=page,
        page_size=page_size,
    )
    return APIResponse(success=True, message=f"Found {result['total']} jobs", data=result)


class AdminFeedbackRequest(BaseModel):
    rating: str  # positive or negative
    comment: str = ""


@router.post("/admin/{job_id}/feedback")
async def admin_feedback_on_job(
    job_id: str,
    request: AdminFeedbackRequest,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin gives feedback on a user's generation --- feeds into learning engine"""
    job = JobService.admin_feedback(
        db=db,
        job_id=job_id,
        admin_id=admin.id,
        rating=request.rating,
        comment=request.comment,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return APIResponse(
        success=True,
        message=f"Admin feedback recorded ({request.rating})",
        data={"job_id": job_id, "rating": request.rating},
    )
