"""
Pexels stock footage — free API, no attribution required for commercial use.
API docs: https://www.pexels.com/api/documentation/#videos-search

Used as a fallback when AI-generated B-roll quality is insufficient.
"""
import os
import logging
import hashlib
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

STOCK_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "stock_cache",
)
os.makedirs(STOCK_CACHE_DIR, exist_ok=True)

PEXELS_API_BASE = "https://api.pexels.com/videos/search"


def _pexels_key() -> Optional[str]:
    from ..config import settings
    return settings.pexels_api_key


class StockFootageService:
    """Search and download B-roll stock footage from Pexels (free commercial use)."""

    @staticmethod
    def search(
        query: str,
        orientation: str = "portrait",   # portrait (9:16) | landscape (16:9) | square
        duration_max: int = 15,
        duration_min: int = 5,
        per_page: int = 10,
    ) -> list[dict]:
        """
        Search Pexels for stock videos. Returns list of clip dicts.
        orientation: portrait = 9:16, landscape = 16:9, square = 1:1
        """
        api_key = _pexels_key()
        if not api_key:
            logger.warning("PEXELS_API_KEY not configured — returning empty stock results")
            return []

        params = {
            "query": query,
            "orientation": orientation,
            "size": "medium",
            "per_page": per_page,
        }

        try:
            resp = httpx.get(
                PEXELS_API_BASE,
                params=params,
                headers={"Authorization": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for v in data.get("videos", []):
                dur = v.get("duration", 0)
                if not (duration_min <= dur <= duration_max):
                    continue
                # Pick best quality file
                files = sorted(
                    [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"],
                    key=lambda x: x.get("width", 0),
                    reverse=True,
                )
                if not files:
                    continue
                best = files[0]
                results.append({
                    "id": str(v["id"]),
                    "duration": dur,
                    "width": best.get("width"),
                    "height": best.get("height"),
                    "download_url": best.get("link"),
                    "thumbnail": (v.get("image") or ""),
                    "photographer": v.get("user", {}).get("name", ""),
                    "license": "Pexels Free",
                })
            return results
        except Exception as e:
            logger.error(f"Pexels search failed: {e}")
            return []

    @staticmethod
    def download(download_url: str, clip_id: str = "") -> Optional[str]:
        """Download a clip to local cache. Returns local path."""
        cache_key = hashlib.md5(download_url.encode()).hexdigest()[:12]
        filename = f"pexels_{clip_id or cache_key}.mp4"
        local_path = os.path.join(STOCK_CACHE_DIR, filename)

        if os.path.isfile(local_path):
            return local_path

        api_key = _pexels_key()
        try:
            with httpx.stream(
                "GET", download_url,
                headers={"Authorization": api_key} if api_key else {},
                follow_redirects=True,
                timeout=120,
            ) as r:
                r.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            return local_path
        except Exception as e:
            logger.error(f"Pexels clip download failed: {e}")
            return None

    @staticmethod
    def get_broll(
        query: str,
        orientation: str = "portrait",
        duration_max: int = 10,
    ) -> Optional[dict]:
        """
        Convenience: search + download a single B-roll clip for a given query.
        Returns clip dict with local_path, or None.
        """
        clips = StockFootageService.search(
            query=query,
            orientation=orientation,
            duration_max=duration_max,
            per_page=5,
        )
        if not clips:
            return None

        clip = clips[0]
        local_path = StockFootageService.download(clip["download_url"], clip["id"])
        if not local_path:
            return None

        clip["local_path"] = local_path
        return clip
