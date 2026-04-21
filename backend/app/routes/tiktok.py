"""TikTok Symphony routes - script generation + avatar video creation"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_optional_user, log_usage
from ..services.tiktok_symphony import TikTokSymphonyService
from ..services.job_service import JobService
import logging
import os
import uuid
import requests as http_req
import io

logger = logging.getLogger(__name__)
router = APIRouter()

UGC_VIDEOS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "generated_videos", "ugc",
)
UGC_THUMBS_DIR = os.path.join(UGC_VIDEOS_DIR, "thumbs")
os.makedirs(UGC_VIDEOS_DIR, exist_ok=True)
os.makedirs(UGC_THUMBS_DIR, exist_ok=True)


def _generate_thumbnail(video_path: str, thumb_path: str) -> bool:
    """Extract first frame of video as JPEG thumbnail via ffmpeg. Returns True on success."""
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-ss", "00:00:01", "-vframes", "1",
             "-vf", "scale=480:-2", "-q:v", "3", thumb_path],
            capture_output=True, timeout=30,
        )
        return result.returncode == 0 and os.path.exists(thumb_path)
    except Exception as e:
        logger.warning(f"[UGC] Thumbnail generation failed: {e}")
        return False


class ScriptTaskRequest(BaseModel):
    mode: str = "CUSTOM"
    custom_prompt: Optional[str] = None
    script_count: int = 3
    script_info: Optional[dict] = None
    product_info: Optional[dict] = None
    video_duration: Optional[str] = None

class AvatarVideoRequest(BaseModel):
    avatar_id: str
    script: str
    video_name: Optional[str] = None


@router.post("/scripts/generate")
async def generate_scripts(request: ScriptTaskRequest, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    try:
        result = TikTokSymphonyService.create_script_task(
            mode=request.mode, custom_prompt=request.custom_prompt,
            script_count=request.script_count, script_info=request.script_info,
            product_info=request.product_info, video_duration=request.video_duration,
        )
        if user:
            log_usage("tiktok_script", user.id, db, cost_usd=0.0)
        return APIResponse(success=True, message="Script generation task created", data=result.get("data", result))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scripts/status")
async def script_status(task_id: str = Query(...)):
    try:
        result = TikTokSymphonyService.get_script_task_status(task_id)
        return APIResponse(success=True, message="Task status", data=result.get("data", result))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scripts/list")
async def list_scripts(page: int = Query(1), page_size: int = Query(20)):
    try:
        result = TikTokSymphonyService.list_scripts(page, page_size)
        return APIResponse(success=True, message="Scripts listed", data=result.get("data", result))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/avatars")
async def get_avatars(page: int = Query(1), page_size: int = Query(50)):
    try:
        result = TikTokSymphonyService.get_avatars(page, page_size)
        return APIResponse(success=True, message="Avatars loaded", data=result.get("data", result))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/videos/create")
async def create_avatar_video(request: AvatarVideoRequest, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    try:
        print(f"[UGC] Creating video: avatar={request.avatar_id}, script_len={len(request.script)}")
        result = TikTokSymphonyService.create_avatar_video(
            avatar_id=request.avatar_id, script=request.script, video_name=request.video_name,
        )
        print(f"[UGC] TikTok create response: {result}")

        response_data = result.get("data", result)
        print(f"[UGC] Extracted data: {response_data}")

        # Extract task_id for job tracking
        task_id = ""
        task_list = response_data.get("list", []) if isinstance(response_data, dict) else []
        if task_list and isinstance(task_list, list):
            task_id = task_list[0].get("task_id", "") if isinstance(task_list[0], dict) else ""

        # Persist job record so videos never get lost across tab switches / disconnects
        if user and task_id:
            try:
                JobService.create_job(
                    db=db, user_id=user.id, job_type="ugc_video",
                    provider="tiktok", provider_job_id=task_id,
                    input_data={
                        "avatar_id": request.avatar_id,
                        "script": request.script[:500],
                        "video_name": request.video_name or "",
                    },
                    cost_usd=0.0,
                )
            except Exception as je:
                logger.warning(f"[UGC] Failed to create job record: {je}")

        if user:
            log_usage("tiktok_video", user.id, db, cost_usd=0.0)
        return APIResponse(success=True, message="Avatar video task created", data=response_data)
    except Exception as e:
        print(f"[UGC] Create error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/videos/status")
async def video_status(task_ids: str = Query(...), user=Depends(get_optional_user), db: Session = Depends(get_db)):
    try:
        print(f"[UGC] Status check - raw task_ids param: {task_ids}")
        import json
        ids = json.loads(task_ids)
        print(f"[UGC] Parsed task IDs: {ids}")
        result = TikTokSymphonyService.get_avatar_video_status(ids)
        print(f"[UGC] TikTok status response: {str(result)[:500]}")

        response_data = result.get("data", result)
        print(f"[UGC] Extracted status data: {str(response_data)[:500]}")

        # If any task finished, download mp4 + mark the corresponding job complete
        task_list = response_data.get("list", []) if isinstance(response_data, dict) else []
        for task in (task_list or []):
            if not isinstance(task, dict):
                continue
            status_val = (task.get("status") or "").upper()
            task_id = task.get("task_id", "")
            if status_val not in ("SUCCESS", "COMPLETED", "COMPLETE"):
                continue

            video_info = task.get("video_info") or task.get("video") or task
            video_url = video_info.get("video_url") or video_info.get("url") or video_info.get("preview_url") or ""
            cover_url = video_info.get("cover_url") or video_info.get("thumbnail_url") or ""

            # Save locally so TikTok URL expiry doesn't lose us the video
            local_filename = None
            thumb_filename = None
            if video_url:
                try:
                    local_filename = f"ugc_{task_id or uuid.uuid4().hex[:8]}.mp4"
                    filepath = os.path.join(UGC_VIDEOS_DIR, local_filename)
                    if not os.path.exists(filepath):
                        r = http_req.get(video_url, timeout=60, stream=True)
                        if r.status_code == 200:
                            with open(filepath, "wb") as f:
                                for chunk in r.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            logger.info(f"[UGC] Saved video locally: {filepath}")
                        else:
                            local_filename = None
                            logger.warning(f"[UGC] Download failed status={r.status_code}")

                    # Generate thumbnail (ffmpeg) so the My Videos grid is not blank
                    if local_filename:
                        thumb_filename = local_filename.replace(".mp4", ".jpg")
                        thumb_path = os.path.join(UGC_THUMBS_DIR, thumb_filename)
                        if not os.path.exists(thumb_path):
                            if not _generate_thumbnail(filepath, thumb_path):
                                thumb_filename = None
                except Exception as de:
                    logger.warning(f"[UGC] Download error: {de}")
                    local_filename = None

            # Mark the matching job completed (if we have a user + job exists)
            if user and task_id:
                try:
                    from ..models.job import Job
                    from sqlalchemy import and_
                    job = db.query(Job).filter(and_(
                        Job.user_id == user.id,
                        Job.provider_job_id == task_id,
                        Job.job_type == "ugc_video",
                    )).first()
                    if job and job.status != "completed":
                        result_url = f"/api/v1/tiktok/videos/local/{local_filename}" if local_filename else video_url
                        JobService.complete_job(
                            db=db, job_id=job.id,
                            result_data={
                                "video_url": video_url,
                                "cover_url": cover_url,
                                "local_filename": local_filename,
                                "thumb_filename": thumb_filename,
                            },
                            result_url=result_url,
                        )
                except Exception as je:
                    logger.warning(f"[UGC] Failed to complete job: {je}")

        return APIResponse(success=True, message="Video status", data=response_data)
    except Exception as e:
        print(f"[UGC] Status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/videos/local/{filename}")
async def get_local_video(filename: str):
    """Stream a locally-saved UGC video"""
    safe_name = os.path.basename(filename)
    filepath = os.path.join(UGC_VIDEOS_DIR, safe_name)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Video not found locally")
    return FileResponse(filepath, media_type="video/mp4")


@router.get("/videos/thumb/{filename}")
async def get_local_thumb(filename: str):
    """Serve a locally-generated UGC thumbnail"""
    safe_name = os.path.basename(filename)
    filepath = os.path.join(UGC_THUMBS_DIR, safe_name)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(filepath, media_type="image/jpeg")


@router.get("/avatars/debug")
async def avatars_debug(page: int = Query(1), page_size: int = Query(10)):
    """
    Raw TikTok avatar response for diagnosing premium/custom avatar access.
    Premium/custom avatars typically appear with avatar_type='CUSTOM' or tier fields.
    """
    try:
        result = TikTokSymphonyService.get_avatars(page, page_size)
        data = result.get("data", result)
        raw_list = data.get("digital_avatar_list") or data.get("list") or data.get("avatars") or []

        # Collect all unique field names across avatars - this exposes tier/type fields
        all_fields = set()
        tier_values = {}
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            all_fields.update(item.keys())
            for key in ("avatar_type", "tier", "type", "premium", "is_premium", "access_type", "package_type"):
                if key in item:
                    tier_values.setdefault(key, set()).add(str(item.get(key)))

        return APIResponse(success=True, message="Avatar diagnostics", data={
            "total_avatars": len(raw_list),
            "fields_present": sorted(all_fields),
            "tier_fields_found": {k: list(v) for k, v in tier_values.items()},
            "first_three_raw": raw_list[:3],
            "note": "Look at 'tier_fields_found' to see if premium/custom tier is exposed. If empty, premium avatars require a separate TikTok Symphony Custom Avatar tier - contact TikTok sales.",
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/videos/list")
async def list_videos(page: int = Query(1), page_size: int = Query(20)):
    try:
        result = TikTokSymphonyService.list_avatar_videos(page, page_size)
        print(f"[UGC] List videos response: {str(result)[:500]}")
        response_data = result.get("data", result)
        return APIResponse(success=True, message="Videos listed", data=response_data)
    except Exception as e:
        print(f"[UGC] List error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/videos/info")
async def video_info(video_ids: str = Query(...)):
    try:
        import json
        ids = json.loads(video_ids)
        result = TikTokSymphonyService.get_video_info(ids)
        return APIResponse(success=True, message="Video info", data=result.get("data", result))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proxy-image")
async def proxy_image(url: str = Query(...)):
    """Proxy external images (TikTok CDN) to avoid CORS/CSP blocking"""
    try:
        r = http_req.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer': 'https://www.tiktok.com/',
        })
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch image")

        content_type = r.headers.get('content-type', 'image/jpeg')
        return StreamingResponse(io.BytesIO(r.content), media_type=content_type)
    except http_req.RequestException as e:
        raise HTTPException(status_code=502, detail=str(e))
