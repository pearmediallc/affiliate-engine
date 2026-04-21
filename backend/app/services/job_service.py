"""Job service - manages persistent async job queue"""
import uuid
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from ..models.job import Job

logger = logging.getLogger(__name__)


class JobService:
    """Persistent job queue for all async generation tasks"""

    @staticmethod
    def create_job(
        db: Session,
        user_id: str,
        job_type: str,
        provider: str = "",
        provider_job_id: str = "",
        input_data: dict = None,
        cost_usd: float = 0.0,
        vertical: str = "",
    ) -> Job:
        """Create a new job record. Returns the Job object."""
        job = Job(
            id=str(uuid.uuid4()),
            user_id=user_id,
            job_type=job_type,
            status="processing",
            provider=provider,
            provider_job_id=provider_job_id,
            input_data=input_data,
            cost_usd=cost_usd,
            vertical=vertical,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        logger.info(f"Job created: {job.id} ({job_type}) for user {user_id}")
        return job

    @staticmethod
    def update_job(
        db: Session,
        job_id: str,
        status: str = None,
        result_data: dict = None,
        result_url: str = None,
        error_message: str = None,
        provider_job_id: str = None,
    ) -> Optional[Job]:
        """Update a job's status and/or result."""
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        if status:
            job.status = status
        if result_data:
            job.result_data = result_data
        if result_url:
            job.result_url = result_url
        if error_message:
            job.error_message = error_message
        if provider_job_id:
            job.provider_job_id = provider_job_id
        job.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def complete_job(db: Session, job_id: str, result_data: dict = None, result_url: str = None) -> Optional[Job]:
        return JobService.update_job(db, job_id, status="completed", result_data=result_data, result_url=result_url)

    @staticmethod
    def fail_job(db: Session, job_id: str, error_message: str = "") -> Optional[Job]:
        return JobService.update_job(db, job_id, status="failed", error_message=error_message)

    @staticmethod
    def get_job(db: Session, job_id: str) -> Optional[Job]:
        return db.query(Job).filter(Job.id == job_id).first()

    @staticmethod
    def get_user_jobs(
        db: Session,
        user_id: str,
        job_type: str = None,
        status: str = None,
        limit: int = 50,
    ) -> list:
        query = db.query(Job).filter(Job.user_id == user_id)
        if job_type:
            query = query.filter(Job.job_type == job_type)
        if status:
            query = query.filter(Job.status == status)
        return query.order_by(desc(Job.created_at)).limit(limit).all()

    @staticmethod
    def get_active_jobs(db: Session, user_id: str = None) -> list:
        """Get all jobs that are still processing"""
        query = db.query(Job).filter(Job.status == "processing")
        if user_id:
            query = query.filter(Job.user_id == user_id)
        return query.order_by(desc(Job.created_at)).all()

    @staticmethod
    def get_all_jobs_admin(
        db: Session,
        user_id: str = None,
        job_type: str = None,
        status: str = None,
        vertical: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """Admin: get all jobs with filtering"""
        query = db.query(Job)
        if user_id:
            query = query.filter(Job.user_id == user_id)
        if job_type:
            query = query.filter(Job.job_type == job_type)
        if status:
            query = query.filter(Job.status == status)
        if vertical:
            query = query.filter(Job.vertical == vertical)

        total = query.count()
        jobs = query.order_by(desc(Job.created_at)).offset((page - 1) * page_size).limit(page_size).all()

        return {
            "jobs": [
                {
                    "id": j.id,
                    "user_id": j.user_id,
                    "job_type": j.job_type,
                    "status": j.status,
                    "provider": j.provider,
                    "input_data": j.input_data,
                    "result_data": j.result_data,
                    "result_url": j.result_url,
                    "error_message": j.error_message,
                    "cost_usd": j.cost_usd,
                    "vertical": j.vertical,
                    "admin_feedback_rating": j.admin_feedback_rating,
                    "admin_feedback_comment": j.admin_feedback_comment,
                    "created_at": str(j.created_at),
                    "updated_at": str(j.updated_at),
                }
                for j in jobs
            ],
            "total": total,
            "page": page,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @staticmethod
    def admin_feedback(
        db: Session,
        job_id: str,
        admin_id: str,
        rating: str,
        comment: str = "",
    ) -> Optional[Job]:
        """Admin gives feedback on a user's generation"""
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        job.admin_feedback_rating = rating
        job.admin_feedback_comment = comment
        job.admin_feedback_by = admin_id
        db.commit()

        # Also feed into the learning engine
        try:
            from .learning_service import LearningService
            LearningService.record_generation(
                db=db,
                user_id=job.user_id,
                vertical=job.vertical or "general",
                feature=job.job_type,
                input_data=job.input_data or {},
                output_data={
                    "result_url": job.result_url,
                    "provider": job.provider,
                    "cost": job.cost_usd,
                    "admin_reviewed": True,
                },
            )
            # Find the record we just created and add feedback
            from ..models.learning import LearningRecord
            record = db.query(LearningRecord).filter(
                LearningRecord.user_id == job.user_id,
                LearningRecord.feature == job.job_type,
            ).order_by(desc(LearningRecord.created_at)).first()
            if record:
                record.feedback_rating = rating
                record.feedback_comment = comment
                record.feedback_issues = ["admin_flagged"] if rating == "negative" else None
                db.commit()
        except Exception as e:
            logger.warning(f"Failed to record admin feedback in learning: {e}")

        return job

    @staticmethod
    def save_sync_result(
        db: Session,
        user_id: str,
        job_type: str,
        input_data: dict,
        result_data: dict,
        result_url: str = "",
        cost_usd: float = 0.0,
        vertical: str = "",
        provider: str = "gemini",
    ) -> Job:
        """Save a synchronous generation result (scripts, ad copy, landing pages, angles) as a completed job"""
        job = Job(
            id=str(uuid.uuid4()),
            user_id=user_id,
            job_type=job_type,
            status="completed",
            provider=provider,
            input_data=input_data,
            result_data=result_data,
            result_url=result_url,
            cost_usd=cost_usd,
            vertical=vertical,
        )
        db.add(job)
        db.commit()
        return job
