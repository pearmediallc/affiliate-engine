"""
Long-video engine: chains Veo 3.1 base + extensions + optional ffmpeg stitch.

State machine lives in Job.result_data["segments"] so it survives restarts.
The /long/status endpoint drives progress forward lazily on each poll.
"""
import os
import uuid
import logging
import subprocess
from typing import Optional
from sqlalchemy.orm import Session
from .video_creator import VideoCreatorService, VIDEOS_DIR
from .job_service import JobService
from ..models.job import Job

logger = logging.getLogger(__name__)

LONG_VIDEOS_DIR = os.path.join(VIDEOS_DIR, "long")
LONG_STITCHED_DIR = os.path.join(VIDEOS_DIR, "long", "stitched")
os.makedirs(LONG_VIDEOS_DIR, exist_ok=True)
os.makedirs(LONG_STITCHED_DIR, exist_ok=True)

# Cost model (approximate, Veo 3.1 standard)
COST_PER_BASE_CLIP = 0.40  # 8s base
COST_PER_EXTENSION = 0.35  # 7s extension


class LongVideoService:

    @staticmethod
    def estimate_cost(segment_count: int) -> float:
        if segment_count <= 0:
            return 0.0
        return COST_PER_BASE_CLIP + (segment_count - 1) * COST_PER_EXTENSION

    @staticmethod
    def max_segments_for_budget(budget_usd: float) -> int:
        """Inverse: how many segments fit in the budget?"""
        if budget_usd <= COST_PER_BASE_CLIP:
            return 1
        remaining = budget_usd - COST_PER_BASE_CLIP
        return 1 + int(remaining / COST_PER_EXTENSION)

    @staticmethod
    def start_job(
        db: Session,
        user_id: str,
        segments_plan: list,
        aspect_ratio: str,
        auto_stitch: bool,
        budget_usd: float,
        raw_script: str,
    ) -> Job:
        """
        Create Job record and kick off the first (base) segment.
        Returns the Job. Frontend polls /long/status/{job_id} to drive progress.
        """
        if not segments_plan:
            raise ValueError("Segments plan is empty")

        # Kick off base clip (8s)
        first = segments_plan[0]
        result = VideoCreatorService.generate_video(
            prompt=first["prompt"],
            aspect_ratio=aspect_ratio,
            resolution="720p",   # must be 720p to allow later extensions
            duration="8",
        )
        first["operation_name"] = result["operation_name"]
        first["status"] = "generating"

        job = JobService.create_job(
            db=db, user_id=user_id, job_type="long_video",
            provider="google", provider_job_id=result["operation_name"],
            input_data={
                "aspect_ratio": aspect_ratio,
                "auto_stitch": auto_stitch,
                "budget_usd": budget_usd,
                "raw_script": raw_script[:2000],
                "segment_count": len(segments_plan),
            },
            cost_usd=COST_PER_BASE_CLIP,
        )
        # Store segment plan in result_data
        JobService.update_job(db=db, job_id=job.id, result_data={
            "segments": segments_plan,
            "stitched_filename": None,
            "stitched_url": None,
            "cost_so_far": COST_PER_BASE_CLIP,
            "error": None,
        })
        return job

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
        budget = (job.input_data or {}).get("budget_usd", 3.5)
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
            next_cost = COST_PER_BASE_CLIP if active["kind"] == "base" else COST_PER_EXTENSION
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
                cost_so_far += next_cost
                result_data["cost_so_far"] = cost_so_far
                JobService.update_job(db=db, job_id=job.id, result_data=result_data,
                                      provider_job_id=result["operation_name"])
                return LongVideoService._snapshot(job, result_data)
            except Exception as e:
                logger.error(f"Failed to kick off segment {active_idx}: {e}", exc_info=True)
                active["status"] = "failed"
                active["error"] = str(e)
                result_data["error"] = f"Segment {active_idx}: {e}"
                JobService.update_job(db=db, job_id=job.id, result_data=result_data)
                return LongVideoService._snapshot(job, result_data)

        # active.status == "generating" -> poll
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
        return {
            "job_id": job.id,
            "status": job.status,
            "segment_count": len(segments),
            "completed_count": done,
            "failed_count": failed,
            "skipped_budget_count": skipped,
            "cost_so_far": result_data.get("cost_so_far", 0.0),
            "segments": [
                {
                    "index": s["index"],
                    "prompt": s["prompt"],
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
