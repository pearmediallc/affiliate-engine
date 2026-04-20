"""TikTok Symphony service - AI script generation + digital avatar UGC videos"""
import logging
import requests
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)

TIKTOK_BASE = "https://business-api.tiktok.com/open_api/v1.3"


def _tt_headers(access_token: str = None):
    token = access_token or settings.tiktok_access_token
    return {"Access-Token": token, "Content-Type": "application/json"}


class TikTokSymphonyService:
    """Wraps TikTok Business API for script generation and avatar video creation"""

    @staticmethod
    def create_script_task(
        mode: str = "CUSTOM",
        custom_prompt: str = None,
        script_count: int = 3,
        script_info: dict = None,
        product_info: dict = None,
        video_duration: str = None,
    ) -> dict:
        token = settings.tiktok_access_token
        if not token:
            raise ValueError("TIKTOK_ACCESS_TOKEN not configured")

        payload = {"script_generation_count": min(max(script_count, 1), 8)}

        if mode.upper() == "CUSTOM":
            if not custom_prompt:
                raise ValueError("custom_prompt required for CUSTOM mode")
            payload["script_source"] = "CUSTOM"
            payload["custom_prompt"] = custom_prompt
        else:
            payload["script_source"] = "PRODUCT"
            payload["script_info"] = script_info or {
                "tone": "Friendly", "style": "Product focused",
                "point_of_view": "From consumer", "script_language": "en",
                "relevant_industry": "All",
            }
            if not product_info:
                raise ValueError("product_info required for PRODUCT mode")
            payload["product_info"] = product_info

        if video_duration in ("15S", "30S"):
            payload["video_duration"] = video_duration

        r = requests.post(
            f"{TIKTOK_BASE}/creative/aigc/script_generation/task/create/",
            headers=_tt_headers(), json=payload, timeout=30,
        )
        data = r.json()
        if str(data.get("code")) != "0":
            raise Exception(f"TikTok API error: {data.get('message', 'Unknown')}")
        return data

    @staticmethod
    def get_script_task_status(task_id: str) -> dict:
        r = requests.get(
            f"{TIKTOK_BASE}/creative/aigc/script/task/get/",
            headers={"Access-Token": settings.tiktok_access_token},
            params={"task_id": task_id}, timeout=30,
        )
        return r.json()

    @staticmethod
    def list_scripts(page: int = 1, page_size: int = 20) -> dict:
        r = requests.get(
            f"{TIKTOK_BASE}/creative/aigc/script/list/",
            headers={"Access-Token": settings.tiktok_access_token},
            params={"page": page, "page_size": page_size}, timeout=30,
        )
        return r.json()

    @staticmethod
    def get_avatars(page: int = 1, page_size: int = 50) -> dict:
        r = requests.get(
            f"{TIKTOK_BASE}/creative/digital_avatar/get/",
            headers={"Access-Token": settings.tiktok_access_token},
            params={"page": page, "page_size": page_size}, timeout=30,
        )
        return r.json()

    @staticmethod
    def create_avatar_video(avatar_id: str, script: str, video_name: str = None) -> dict:
        if not avatar_id or not script:
            raise ValueError("avatar_id and script are required")

        package = {"avatar_id": avatar_id, "script": script[:2000]}
        if video_name:
            package["video_name"] = video_name

        r = requests.post(
            f"{TIKTOK_BASE}/creative/digital_avatar/video/task/create/",
            headers=_tt_headers(),
            json={"material_packages": [package]}, timeout=30,
        )
        data = r.json()
        if str(data.get("code")) != "0":
            raise Exception(f"TikTok API error: {data.get('message', 'Unknown')}")
        return data

    @staticmethod
    def get_avatar_video_status(task_ids: list) -> dict:
        import json
        r = requests.get(
            f"{TIKTOK_BASE}/creative/digital_avatar/video/task/get/",
            headers={"Access-Token": settings.tiktok_access_token},
            params={"task_ids": json.dumps(task_ids)}, timeout=30,
        )
        return r.json()

    @staticmethod
    def list_avatar_videos(page: int = 1, page_size: int = 20, avatar_id: str = None) -> dict:
        params = {"page": page, "page_size": page_size}
        if avatar_id:
            params["filtering"] = {"avatar_id": avatar_id}
        r = requests.get(
            f"{TIKTOK_BASE}/creative/digital_avatar/video/list/",
            headers={"Access-Token": settings.tiktok_access_token},
            params=params, timeout=30,
        )
        return r.json()

    @staticmethod
    def get_video_info(video_ids: list) -> dict:
        import json
        r = requests.get(
            f"{TIKTOK_BASE}/file/video/ad/info/",
            headers={"Access-Token": settings.tiktok_access_token},
            params={
                "advertiser_id": settings.tiktok_advertiser_id,
                "video_ids": json.dumps(video_ids),
            }, timeout=30,
        )
        return r.json()
