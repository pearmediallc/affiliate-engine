"""
Kie.ai API service — unified gateway for Runway video, FLUX images, InfiniteTalk lip-sync.

API reference: https://kie.ai/
Auth: Authorization: Bearer <key>
All requests use JSON bodies; polling uses task IDs.
"""
import os
import time
import uuid
import logging
import httpx
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.kie.ai"

VIDEOS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "generated_videos",
)
os.makedirs(VIDEOS_DIR, exist_ok=True)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.kie_api_key}",
        "Content-Type": "application/json",
    }


def _download(url: str, filename: str) -> str:
    path = os.path.join(VIDEOS_DIR, filename)
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return path


def _extract_task_id(data: dict) -> Optional[str]:
    """Extract task ID from Kie.ai response — handles both flat and nested {data:{}} envelopes."""
    inner = data.get("data") or {}
    return (
        data.get("taskId") or data.get("task_id") or data.get("id")
        or inner.get("taskId") or inner.get("task_id") or inner.get("id")
    )


def _poll(endpoint: str, task_id: str, timeout: int = 300) -> dict:
    """Generic poller — GET endpoint/task_id until status is completed/failed."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(5)
        r = httpx.get(f"{_BASE}{endpoint}/{task_id}", headers=_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        # Kie.ai wraps results in a nested "data" envelope
        inner = data.get("data") or data
        status = (inner.get("status") or inner.get("state") or "").lower()
        if status in ("completed", "succeeded", "success", "done"):
            return inner
        if status in ("failed", "error", "canceled"):
            raise RuntimeError(f"Kie.ai task failed: {inner.get('message') or inner}")
    raise TimeoutError(f"Kie.ai task {task_id} timed out after {timeout}s")


class KieAIService:
    """
    Thin wrapper around Kie.ai REST API.
    All methods are synchronous (intended to run in asyncio.to_thread).
    """

    # ── Video (Runway Gen-4) ──────────────────────────────────────────────────

    @staticmethod
    def generate_video_runway(
        prompt: str,
        duration: int = 5,
        image_url: Optional[str] = None,
        ratio: str = "9:16",
    ) -> dict:
        """Submit a Runway Gen-4 video task via Kie.ai. Returns task info with download_url."""
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY not configured")

        payload: dict = {
            "prompt": prompt,
            "duration": duration,
            "ratio": ratio,
            "model": "runway-gen4",
        }
        if image_url:
            payload["image_url"] = image_url

        r = httpx.post(f"{_BASE}/api/v1/runway/generate", headers=_headers(), json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        logger.debug(f"Kie.ai runway generate response: {data}")
        task_id = _extract_task_id(data)
        if not task_id:
            raise RuntimeError(f"No task_id in Kie.ai Runway response: {data}")

        result = _poll("/api/v1/runway/task", task_id, timeout=300)
        video_url = (
            result.get("videoUrl")
            or result.get("video_url")
            or (result.get("output") or {}).get("video_url")
        )
        if not video_url:
            raise RuntimeError(f"No video_url in Kie.ai Runway result: {result}")

        filename = f"runway_{uuid.uuid4().hex[:8]}.mp4"
        local_path = _download(video_url, filename)
        return {
            "video_path": local_path,
            "video_filename": filename,
            "model_id": "runway-gen4",
            "provider": "kieai",
            "task_id": task_id,
        }

    # ── Image (FLUX) ──────────────────────────────────────────────────────────

    @staticmethod
    def generate_image_flux(
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        model: str = "flux-dev",
        steps: int = 28,
    ) -> dict:
        """Generate an image using FLUX via Kie.ai. Returns url + local path."""
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY not configured")

        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "model": model,
            "steps": steps,
        }
        r = httpx.post(f"{_BASE}/api/v1/flux/generate", headers=_headers(), json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()

        # Some endpoints return image directly, others use task polling
        image_url = data.get("imageUrl") or data.get("image_url") or data.get("url")
        if not image_url:
            task_id = data.get("taskId") or data.get("task_id") or data.get("id")
            result = _poll("/api/v1/flux/task", task_id, timeout=120)
            image_url = (
                result.get("imageUrl")
                or result.get("image_url")
                or result.get("url")
            )

        return {
            "url": image_url,
            "model": f"flux/{model}",
            "provider": "kieai",
            "cost_usd": 0.008,
        }

    # ── Lip-sync (InfiniteTalk) ───────────────────────────────────────────────

    @staticmethod
    def start_lip_sync(image_url: str, audio_url: str) -> str:
        """Submit InfiniteTalk lip-sync job. Returns task_id."""
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY not configured")

        payload = {"imageUrl": image_url, "audioUrl": audio_url}
        r = httpx.post(f"{_BASE}/api/v1/infinitalk/generate", headers=_headers(), json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("taskId") or data.get("task_id") or data.get("id")

    @staticmethod
    def check_lip_sync(task_id: str) -> dict:
        """Poll InfiniteTalk task status."""
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY not configured")

        r = httpx.get(f"{_BASE}/api/v1/infinitalk/task/{task_id}", headers=_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        status = (data.get("status") or "").lower()

        result: dict = {"task_id": task_id, "status": status, "provider": "kieai"}
        if status in ("completed", "succeeded", "success", "done"):
            result["status"] = "succeeded"
            video_url = data.get("videoUrl") or data.get("video_url")
            if video_url:
                result["video_url"] = video_url
                filename = f"infinitalk_{uuid.uuid4().hex[:8]}.mp4"
                result["local_path"] = _download(video_url, filename)
                result["download_filename"] = filename
        elif status in ("failed", "error"):
            result["status"] = "failed"
            result["error"] = data.get("message") or "InfiniteTalk generation failed"

        return result

    # ── Veo 3.1 via Kie.ai ───────────────────────────────────────────────────

    @staticmethod
    def generate_video_veo(
        prompt: str,
        duration: int = 8,
        ratio: str = "9:16",
        fast: bool = False,
    ) -> dict:
        """Generate with Veo 3.1 / Veo 3.1 Fast via Kie.ai."""
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY not configured")

        model = "veo-3-fast" if fast else "veo-3"
        payload = {"prompt": prompt, "duration": duration, "ratio": ratio, "model": model}
        r = httpx.post(f"{_BASE}/api/v1/veo/generate", headers=_headers(), json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        logger.debug(f"Kie.ai veo generate response: {data}")
        task_id = _extract_task_id(data)
        if not task_id:
            raise RuntimeError(f"No task_id in Kie.ai Veo response: {data}")

        result = _poll("/api/v1/veo/task", task_id, timeout=600)
        video_url = result.get("videoUrl") or result.get("video_url")
        if not video_url:
            raise RuntimeError(f"No video_url in Kie.ai Veo result: {result}")

        filename = f"veo_{uuid.uuid4().hex[:8]}.mp4"
        local_path = _download(video_url, filename)
        model_id = "veo-3.1-fast" if fast else "veo-3.1"
        return {
            "video_path": local_path,
            "video_filename": filename,
            "model_id": model_id,
            "provider": "kieai",
            "task_id": task_id,
        }
