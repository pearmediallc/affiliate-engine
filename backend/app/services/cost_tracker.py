"""
Universal cost tracker — single entry point for recording API spend.

Writes to:
  - Image.cost_usd (when source='image')
  - Job.cost_usd  (when source='job', additive)
  - UsageLog (always, as the audit trail)

All other code calls track() with a typed source, never SQL directly.
"""
import logging
import uuid
from typing import Optional, Any
from sqlalchemy.orm import Session
from ..models.user import UsageLog

logger = logging.getLogger(__name__)


def track_usage_log(
    db: Session,
    user_id: Optional[str],
    feature: str,
    cost_usd: float,
    metadata: Optional[dict] = None,
) -> None:
    """
    Append a UsageLog row. user_id may be None for anonymous calls
    (those just won't be summed against any user but stay in audit).
    Safe to call repeatedly; failures are logged, never raised.
    """
    if not user_id:
        return
    try:
        log = UsageLog(
            id=str(uuid.uuid4()),
            user_id=user_id,
            feature=feature,
            cost_usd=float(cost_usd or 0.0),
            metadata_json=metadata or {},
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"track_usage_log failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def update_job_cost(db: Session, job_id: str, additional_cost_usd: float) -> None:
    """Add to Job.cost_usd. Used by long-video extensions and any pipeline
    where a single Job aggregates multiple paid sub-calls."""
    if not job_id or additional_cost_usd is None:
        return
    try:
        from ..models.job import Job
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return
        job.cost_usd = float(job.cost_usd or 0.0) + float(additional_cost_usd)
        db.add(job)
        db.commit()
    except Exception as e:
        logger.warning(f"update_job_cost failed for job {job_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def update_image_cost(db: Session, image_id: str, cost_usd: float) -> None:
    """Set Image.cost_usd to the actual cost for this generation."""
    if not image_id or cost_usd is None:
        return
    try:
        from ..models.image import Image
        img = db.query(Image).filter(Image.id == image_id).first()
        if not img:
            return
        img.cost_usd = float(cost_usd)
        db.add(img)
        db.commit()
    except Exception as e:
        logger.warning(f"update_image_cost failed for image {image_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def track(
    db: Session,
    *,
    user_id: Optional[str],
    feature: str,
    cost_usd: float,
    source: str = "log",          # "log" | "image" | "job"
    image_id: Optional[str] = None,
    job_id: Optional[str] = None,
    additive_job_cost: bool = False,
    metadata: Optional[dict] = None,
) -> None:
    """
    Single entry point. Writes UsageLog audit trail and (optionally)
    updates the matching Image or Job row.

    - source='log'   → only UsageLog (use for sync stuff with no DB row to update).
    - source='image' → updates Image.cost_usd to cost_usd, plus UsageLog.
    - source='job'   → if additive_job_cost=True, INCREMENTS Job.cost_usd by cost_usd
                        (long-video extensions); otherwise sets it.
                        Plus UsageLog.
    """
    cost = float(cost_usd or 0.0)
    track_usage_log(db, user_id, feature, cost, metadata)

    if source == "image" and image_id:
        update_image_cost(db, image_id, cost)
    elif source == "job" and job_id:
        if additive_job_cost:
            update_job_cost(db, job_id, cost)
        else:
            try:
                from ..models.job import Job
                job = db.query(Job).filter(Job.id == job_id).first()
                if job:
                    job.cost_usd = cost
                    db.add(job)
                    db.commit()
            except Exception as e:
                logger.warning(f"set Job.cost_usd failed: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass


def estimate_audio_seconds_from_path(audio_path: str) -> Optional[float]:
    """
    Best-effort duration probe via ffprobe. Returns None if probe fails.
    Used for transcription cost where duration is the input.
    """
    if not audio_path:
        return None
    try:
        import subprocess
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, timeout=15,
        )
        if r.returncode != 0:
            return None
        return float(r.stdout.decode().strip())
    except Exception:
        return None


def estimate_audio_seconds_from_text(text: str, wpm: int = 150) -> float:
    """Rough estimate: words / wpm * 60. Used as TTS-output duration proxy when no probe."""
    words = max(1, len((text or "").split()))
    return round((words / max(1, wpm)) * 60.0, 2)
