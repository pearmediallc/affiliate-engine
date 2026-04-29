"""
Long-video engine: chains Veo 3.1 base + extensions + optional ffmpeg stitch.

State machine lives in Job.result_data["segments"] so it survives restarts.
The /long/status endpoint reads state (fast); background task advances it.

The base segment can optionally start from an uploaded image (image-to-video).
Extensions are always text-only (Veo extension API doesn't take images).
"""
import os
import uuid
import logging
import subprocess
import threading
import shutil
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional
from sqlalchemy.orm import Session
from .video_creator import VideoCreatorService, VIDEOS_DIR
from .job_service import JobService
from .pricing import Pricing
from .cost_tracker import update_job_cost
from ..models.job import Job

logger = logging.getLogger(__name__)

# Per-job advance lock. Non-blocking: if locked, skip (next poll tries again).
_advance_locks: dict = defaultdict(threading.Lock)

# A segment stuck in "generating" for >STUCK_TIMEOUT is marked failed.
STUCK_TIMEOUT = timedelta(minutes=10)

LONG_VIDEOS_DIR = os.path.join(VIDEOS_DIR, "long")
LONG_STITCHED_DIR = os.path.join(VIDEOS_DIR, "long", "stitched")
LONG_BASE_IMAGES_DIR = os.path.join(VIDEOS_DIR, "long", "base_images")
os.makedirs(LONG_VIDEOS_DIR, exist_ok=True)
os.makedirs(LONG_STITCHED_DIR, exist_ok=True)
os.makedirs(LONG_BASE_IMAGES_DIR, exist_ok=True)


class LongVideoService:
    # Real Veo 3.1 pricing — sourced from Pricing module (env-overridable).
    COST_PER_BASE_CLIP = Pricing.veo_video(8)              # 8s base clip
    COST_PER_EXTENSION = Pricing.veo_extension(7)          # 7s extension

    @staticmethod
    def estimate_cost(segment_count: int) -> float:
        if segment_count <= 0:
            return 0.0
        return LongVideoService.COST_PER_BASE_CLIP + (segment_count - 1) * LongVideoService.COST_PER_EXTENSION

    @staticmethod
    def max_segments_for_budget(budget_usd: float) -> int:
        """Inverse: how many segments fit in the budget?"""
        base = LongVideoService.COST_PER_BASE_CLIP
        ext = LongVideoService.COST_PER_EXTENSION
        if budget_usd < base:
            return 0
        if budget_usd < base + ext:
            return 1
        remaining = budget_usd - base
        return 1 + int(remaining / ext)

    @staticmethod
    def start_job(
        db: Session,
        user_id: str,
        segments_plan: list,
        aspect_ratio: str,
        auto_stitch: bool,
        budget_usd: float,
        raw_script: str,
        base_image_path: Optional[str] = None,
    ) -> Job:
        """
        Create Job record and kick off the first (base) segment.

        If base_image_path is provided, segment 0 uses Veo image-to-video
        (animating that image). Otherwise text-to-video as before.

        Returns the Job. Frontend polls /long/status/{job_id} to drive progress.
        """
        if not segments_plan:
            raise ValueError("Segments plan is empty")

        # Persist the base image (if any) so we can reference it from segment metadata.
        # Veo's image-to-video is one-shot — extensions don't reuse the image — so we
        # only need it for the first call. Copy into long base_images dir for trace.
        persisted_base_image = None
        if base_image_path and os.path.exists(base_image_path):
            ext = (os.path.splitext(base_image_path)[1] or ".png").lower()
            persisted_base_image = os.path.join(
                LONG_BASE_IMAGES_DIR, f"{uuid.uuid4().hex[:12]}{ext}"
            )
            try:
                shutil.copy(base_image_path, persisted_base_image)
            except Exception as e:
                logger.warning(f"Failed to persist base image: {e}")
                persisted_base_image = None

        # Kick off base clip (8s) — image-to-video if base image present, else text-to-video.
        first = segments_plan[0]
        if persisted_base_image:
            result = VideoCreatorService.generate_from_image(
                image_path=persisted_base_image,
                prompt=first["prompt"],
                aspect_ratio=aspect_ratio,
                duration=8,
            )
            first["kind"] = "base_image"
        else:
            result = VideoCreatorService.generate_video(
                prompt=first["prompt"],
                aspect_ratio=aspect_ratio,
                resolution="720p",   # must be 720p to allow later extensions
                duration="8",
            )
        first["operation_name"] = result["operation_name"]
        first["status"] = "generating"
        first["started_at"] = datetime.utcnow().isoformat()

        first_cost = float(result.get("cost_usd") or LongVideoService.COST_PER_BASE_CLIP)

        job = JobService.create_job(
            db=db, user_id=user_id, job_type="long_video",
            provider="google", provider_job_id=result["operation_name"],
            input_data={
                "aspect_ratio": aspect_ratio,
                "auto_stitch": auto_stitch,
                "budget_usd": budget_usd,
                "raw_script": raw_script[:2000],
                "segment_count": len(segments_plan),
                "base_image": persisted_base_image,  # path on disk (server-side only)
            },
            cost_usd=first_cost,
        )
        # Store segment plan in result_data
        JobService.update_job(db=db, job_id=job.id, result_data={
            "segments": segments_plan,
            "stitched_filename": None,
            "stitched_url": None,
            "cost_so_far": first_cost,
            "error": None,
        })
        return job

    @staticmethod
    def cancel(db: Session, job: Job) -> dict:
        """Mark job + any pending/generating segments as cancelled."""
        result_data = job.result_data or {}
        segments = result_data.get("segments", [])
        for s in segments:
            if s["status"] in ("pending", "generating"):
                s["status"] = "cancelled"
        result_data["segments"] = segments
        result_data["cancelled_at"] = datetime.utcnow().isoformat()
        JobService.update_job(
            db=db, job_id=job.id,
            result_data=result_data, status="cancelled",
            error_message="Cancelled by user",
        )
        return LongVideoService._snapshot(job, result_data)

    @staticmethod
    def advance_in_background(session_factory, job_id: str) -> None:
        """
        Thread-safe advance entry point.
        Acquires a per-job lock (non-blocking) to prevent concurrent advances.
        Short-circuits on cancelled/completed/failed jobs.
        """
        lock = _advance_locks[job_id]
        if not lock.acquire(blocking=False):
            return  # Another advance is already running for this job
        try:
            db = session_factory()
            try:
                job = JobService.get_job(db, job_id)
                if not job:
                    return
                if job.status in ("cancelled", "completed", "failed"):
                    return
                LongVideoService.advance(db, job)
            except Exception as e:
                logger.error(f"advance_in_background({job_id}): {e}", exc_info=True)
            finally:
                db.close()
        finally:
            lock.release()

    @staticmethod
    def advance(db: Session, job: Job) -> dict:
        """
        Driven by /long/status. For the currently-generating segment:
          - poll its Veo operation
          - if done: save mp4, mark complete
          - if more segments + budget remains: kick off next extension
          - if all done + auto_stitch: run ffmpeg concat

        Returns the current state snapshot for the frontend.
        """
        result_data = job.result_data or {}
        segments = result_data.get("segments", [])
        if not segments:
            return {"status": "failed", "error": "No segments"}

        auto_stitch = (job.input_data or {}).get("auto_stitch", False)
        budget = (job.input_data or {}).get("budget_usd", 20.0)
        cost_so_far = result_data.get("cost_so_far", 0.0)

        # Find the segment to act on (the one currently generating, or first pending)
        active_idx = None
        for i, s in enumerate(segments):
            if s["status"] == "generating":
                active_idx = i
                break
        if active_idx is None:
            for i, s in enumerate(segments):
                if s["status"] == "pending":
                    active_idx = i
                    break

        if active_idx is None:
            # All segments either completed or failed -> check if we should stitch
            all_done = all(s["status"] == "completed" for s in segments)
            if all_done and auto_stitch and not result_data.get("stitched_filename"):
                try:
                    stitched = LongVideoService._stitch(segments, job.id)
                    result_data["stitched_filename"] = stitched
                    result_data["stitched_url"] = f"/api/v1/video/long/download/{stitched}"
                    JobService.update_job(db=db, job_id=job.id, result_data=result_data,
                                          status="completed",
                                          result_url=result_data["stitched_url"])
                except Exception as e:
                    logger.error(f"Stitch failed: {e}", exc_info=True)
                    result_data["error"] = f"Stitch failed: {e}"
                    JobService.update_job(db=db, job_id=job.id, result_data=result_data,
                                          status="completed")
            elif all_done and not auto_stitch:
                # Mark completed without stitching
                if job.status != "completed":
                    JobService.update_job(db=db, job_id=job.id, result_data=result_data,
                                          status="completed")
            return LongVideoService._snapshot(job, result_data)

        active = segments[active_idx]

        # If the active segment is still pending (no operation_name), kick it off now
        if active["status"] == "pending":
            # Budget check BEFORE kicking off extension
            next_cost = (
                LongVideoService.COST_PER_BASE_CLIP
                if active["kind"] in ("base", "base_image")
                else LongVideoService.COST_PER_EXTENSION
            )
            if cost_so_far + next_cost > budget + 0.01:
                active["status"] = "skipped_budget"
                logger.info(f"Long-video job {job.id}: budget hit, skipping segment {active_idx}")
                result_data["cost_so_far"] = cost_so_far
                JobService.update_job(db=db, job_id=job.id, result_data=result_data)
                return LongVideoService.advance(db, job)  # recurse to handle remaining state

            try:
                prev_seg = segments[active_idx - 1]
                prev_op = prev_seg.get("operation_name")
                if not prev_op:
                    raise RuntimeError(f"Previous segment {active_idx-1} has no operation_name")

                result = VideoCreatorService.extend_video(
                    previous_operation_name=prev_op,
                    prompt=active["prompt"],
                )
                active["operation_name"] = result["operation_name"]
                active["status"] = "generating"
                active["started_at"] = datetime.utcnow().isoformat()
                # Use real cost reported by service if present
                actual_cost = float(result.get("cost_usd") or LongVideoService.COST_PER_EXTENSION)
                cost_so_far += actual_cost
                result_data["cost_so_far"] = cost_so_far
                JobService.update_job(db=db, job_id=job.id, result_data=result_data,
                                      provider_job_id=result["operation_name"])
                # Increment Job.cost_usd so analytics queries reflect real spend
                update_job_cost(db, job.id, actual_cost)
                return LongVideoService._snapshot(job, result_data)
            except Exception as e:
                logger.error(f"Failed to kick off segment {active_idx}: {e}", exc_info=True)
                active["status"] = "failed"
                active["error"] = str(e)
                result_data["error"] = f"Segment {active_idx}: {e}"
                JobService.update_job(db=db, job_id=job.id, result_data=result_data)
                return LongVideoService._snapshot(job, result_data)

        # active.status == "generating" -> poll

        # Stuck-detection: if the segment has been generating for too long, fail it.
        started_at_str = active.get("started_at")
        if started_at_str:
            try:
                started_at = datetime.fromisoformat(started_at_str)
                if datetime.utcnow() - started_at > STUCK_TIMEOUT:
                    logger.warning(f"Segment {active_idx} stuck >{STUCK_TIMEOUT} - marking failed")
                    active["status"] = "failed"
                    active["error"] = f"Timed out after {STUCK_TIMEOUT}"
                    result_data["error"] = f"Segment {active_idx} timed out"
                    JobService.update_job(db=db, job_id=job.id, result_data=result_data)
                    return LongVideoService._snapshot(job, result_data)
            except Exception:
                pass
        else:
            # Backfill started_at for segments that didn't record it (pre-upgrade)
            active["started_at"] = datetime.utcnow().isoformat()

        try:
            status = VideoCreatorService.check_status(active["operation_name"])
        except Exception as e:
            logger.error(f"Status check failed for {active['operation_name']}: {e}")
            return LongVideoService._snapshot(job, result_data)

        if status.get("done"):
            if status.get("error"):
                active["status"] = "failed"
                active["error"] = status["error"]
                result_data["error"] = f"Segment {active_idx} failed: {status['error']}"
            else:
                # Move the generated file into our long-video directory with a predictable name
                src_filename = status.get("video_filename")
                if src_filename:
                    src_path = os.path.join(VIDEOS_DIR, src_filename)
                    # Name: long_<jobid>_<idx>.mp4 so stitching order is deterministic
                    new_name = f"long_{job.id[:8]}_{active_idx:02d}.mp4"
                    new_path = os.path.join(LONG_VIDEOS_DIR, new_name)
                    try:
                        if os.path.exists(src_path) and not os.path.exists(new_path):
                            os.rename(src_path, new_path)
                        active["video_filename"] = new_name
                        active["download_url"] = f"/api/v1/video/long/download/{new_name}"
                    except Exception as e:
                        logger.warning(f"Move failed: {e}")
                        active["video_filename"] = src_filename
                        active["download_url"] = f"/api/v1/video/download/{src_filename}"
                active["status"] = "completed"

            JobService.update_job(db=db, job_id=job.id, result_data=result_data)
            # Recurse to immediately kick off next segment (saves a poll cycle)
            return LongVideoService.advance(db, job)

        # Still generating
        return LongVideoService._snapshot(job, result_data)

    @staticmethod
    def _stitch(segments: list, job_id: str) -> str:
        """Concat all completed segment mp4s into a single mp4 via ffmpeg."""
        completed = [s for s in segments if s["status"] == "completed" and s.get("video_filename")]
        if not completed:
            raise RuntimeError("No completed segments to stitch")

        # Build concat list file
        list_path = os.path.join(LONG_VIDEOS_DIR, f"concat_{job_id[:8]}.txt")
        with open(list_path, "w") as f:
            for s in completed:
                fp = os.path.join(LONG_VIDEOS_DIR, s["video_filename"])
                if not os.path.exists(fp):
                    raise RuntimeError(f"Missing segment file: {fp}")
                f.write(f"file '{fp}'\n")

        out_name = f"long_{job_id[:8]}_stitched.mp4"
        out_path = os.path.join(LONG_STITCHED_DIR, out_name)

        # ffmpeg concat demuxer, re-encode to guarantee seamless concat
        # (stream-copy can fail if segments have different encoding params)
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k",
             "-movflags", "+faststart",
             out_path],
            capture_output=True, timeout=600,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg stderr: {result.stderr.decode()[:500]}")
            raise RuntimeError(f"ffmpeg concat failed (code {result.returncode})")

        try:
            os.remove(list_path)
        except Exception:
            pass

        return out_name

    @staticmethod
    def _snapshot(job: Job, result_data: dict) -> dict:
        segments = result_data.get("segments", [])
        done = sum(1 for s in segments if s["status"] == "completed")
        failed = sum(1 for s in segments if s["status"] == "failed")
        skipped = sum(1 for s in segments if s["status"] == "skipped_budget")
        cancelled = sum(1 for s in segments if s["status"] == "cancelled")
        return {
            "job_id": job.id,
            "status": job.status,
            "segment_count": len(segments),
            "completed_count": done,
            "failed_count": failed,
            "skipped_budget_count": skipped,
            "cancelled_count": cancelled,
            "cost_so_far": result_data.get("cost_so_far", 0.0),
            "with_base_image": bool((job.input_data or {}).get("base_image")),
            "segments": [
                {
                    "index": s["index"],
                    # Trim long prompts to keep response lightweight
                    "prompt": (s.get("prompt") or "")[:240] + ("..." if len(s.get("prompt") or "") > 240 else ""),
                    "duration": s["duration"],
                    "kind": s["kind"],
                    "status": s["status"],
                    "download_url": s.get("download_url"),
                    "error": s.get("error"),
                }
                for s in segments
            ],
            "stitched_url": result_data.get("stitched_url"),
            "auto_stitch": (job.input_data or {}).get("auto_stitch", False),
            "error": result_data.get("error"),
        }


# Backwards-compatible legacy module-level constants (used by older imports if any)
COST_PER_BASE_CLIP = LongVideoService.COST_PER_BASE_CLIP
COST_PER_EXTENSION = LongVideoService.COST_PER_EXTENSION
