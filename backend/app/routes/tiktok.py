"""TikTok Symphony routes - script generation + avatar video creation"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_optional_user, log_usage
from ..services.tiktok_symphony import TikTokSymphonyService
import logging
import requests as http_req
import io

logger = logging.getLogger(__name__)
router = APIRouter()


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

        if user:
            log_usage("tiktok_video", user.id, db, cost_usd=0.0)
        return APIResponse(success=True, message="Avatar video task created", data=response_data)
    except Exception as e:
        print(f"[UGC] Create error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/videos/status")
async def video_status(task_ids: str = Query(...)):
    try:
        print(f"[UGC] Status check - raw task_ids param: {task_ids}")
        import json
        ids = json.loads(task_ids)
        print(f"[UGC] Parsed task IDs: {ids}")
        result = TikTokSymphonyService.get_avatar_video_status(ids)
        print(f"[UGC] TikTok status response: {str(result)[:500]}")

        response_data = result.get("data", result)
        print(f"[UGC] Extracted status data: {str(response_data)[:500]}")

        return APIResponse(success=True, message="Video status", data=response_data)
    except Exception as e:
        print(f"[UGC] Status error: {e}")
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
