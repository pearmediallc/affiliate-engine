"""Lip-sync routes - generate talking-head videos from portrait + audio"""
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_optional_user, log_usage
from ..services.lip_sync import LipSyncService, DOWNLOADS_DIR
from ..services.job_service import JobService
from ..services.pricing import Pricing
from ..services.cost_tracker import update_job_cost
from ..models.job import Job
import tempfile
import os
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/generate")
async def generate_lip_sync(
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    model: str = Form(default="sadtalker"),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Generate a talking-head video from portrait image + audio file"""
    try:
        # Save uploaded files temporarily
        img_suffix = f".{image.filename.split('.')[-1]}" if image.filename else ".png"
        audio_suffix = f".{audio.filename.split('.')[-1]}" if audio.filename else ".mp3"

        with tempfile.NamedTemporaryFile(delete=False, suffix=img_suffix) as img_tmp:
            img_content = await image.read()
            img_tmp.write(img_content)
            img_path = img_tmp.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=audio_suffix) as audio_tmp:
            audio_content = await audio.read()
            audio_tmp.write(audio_content)
            audio_path = audio_tmp.name

        try:
            # Upload files to Replicate
            image_url = LipSyncService.upload_file_to_replicate(img_path)
            audio_url = LipSyncService.upload_file_to_replicate(audio_path)

            # Start generation
            result = LipSyncService.start_generation(
                image_url=image_url,
                audio_url=audio_url,
                model=model,
            )

            if user:
                # Estimate cost up front; we'll true-up on /status when Replicate
                # reports actual predict_time.
                est_cost = Pricing.lip_sync(predict_time_sec=None, hardware="t4")
                log_usage("lip_sync", user.id, db, cost_usd=est_cost,
                          metadata={"prediction_id": result.get("prediction_id"), "model": model})
                try:
                    JobService.create_job(
                        db=db, user_id=user.id, job_type="talking_head",
                        provider="replicate", provider_job_id=result.get("prediction_id", ""),
                        input_data={"model": model},
                        cost_usd=est_cost,
                    )
                except Exception as je:
                    logger.warning(f"Lip-sync job record failed: {je}")

            return APIResponse(
                success=True,
                message="Lip-sync generation started",
                data=result,
            )
        finally:
            # Clean up temp files
            try:
                os.unlink(img_path)
                os.unlink(audio_path)
            except:
                pass

    except Exception as e:
        logger.error(f"Lip-sync generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{prediction_id}")
async def lip_sync_status(
    prediction_id: str,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Check the status of a lip-sync generation job. True-up cost from
    Replicate's reported predict_time when complete."""
    try:
        result = LipSyncService.check_status(prediction_id)

        # On success, true-up Job.cost_usd from real predict_time and
        # mark the job complete with the result URL.
        if result.get("status") == "succeeded" and user:
            try:
                job = db.query(Job).filter(
                    Job.user_id == user.id,
                    Job.provider_job_id == prediction_id,
                    Job.job_type == "talking_head",
                ).first()
                if job:
                    actual_cost = float(result.get("cost_usd") or 0.0)
                    if actual_cost > 0:
                        # Replace estimate with actual
                        job.cost_usd = actual_cost
                        db.add(job)
                        db.commit()
                    if job.status != "completed":
                        result_url = (f"/api/v1/lip-sync/download/{result['download_filename']}"
                                      if result.get("download_filename") else result.get("video_url", ""))
                        JobService.complete_job(
                            db=db, job_id=job.id,
                            result_data={
                                "video_url": result.get("video_url"),
                                "download_filename": result.get("download_filename"),
                                "predict_time_sec": result.get("predict_time_sec"),
                            },
                            result_url=result_url,
                        )
            except Exception as je:
                logger.warning(f"Lip-sync job complete failed: {je}")

        return APIResponse(
            success=True,
            message=f"Status: {result['status']}",
            data=result,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{filename}")
async def download_lip_sync(filename: str):
    """Download a generated lip-sync video"""
    filepath = os.path.join(DOWNLOADS_DIR, os.path.basename(filename))
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        filepath, media_type="video/mp4",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/models")
async def list_models():
    """List available lip-sync models"""
    return APIResponse(
        success=True,
        message="Available models",
        data={"models": LipSyncService.get_available_models()},
    )
