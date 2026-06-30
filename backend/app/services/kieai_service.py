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
    """Poll Kie.ai task status. `endpoint` is the full polling path (e.g. /api/v1/runway/record-detail).
    Kie.ai uses taskId as a query parameter, NOT a path parameter."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(5)
        r = httpx.get(f"{_BASE}{endpoint}", params={"taskId": task_id}, headers=_headers(), timeout=15)
        if not r.is_success:
            logger.error(f"Kie.ai poll {endpoint}?taskId={task_id} returned {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
        data = r.json()
        inner = data.get("data") or data
        # Kie.ai uses "successFlag": 0=processing, 1=success, 2=failed, OR string "status"
        success_flag = inner.get("successFlag")
        status = (inner.get("status") or inner.get("state") or "").lower()
        if success_flag == 1 or status in ("completed", "succeeded", "success", "done"):
            return inner
        if success_flag in (2, 3) or status in ("failed", "error", "canceled"):
            raise RuntimeError(f"Kie.ai task failed: {inner.get('errorMessage') or inner.get('message') or inner}")
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
        quality: str = "720p",
    ) -> dict:
        """Submit a Runway Gen-4 video task via Kie.ai. Returns task info with download_url."""
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY not configured")

        # Runway Gen-4 only accepts 5, 8, or 10 seconds
        valid_durations = (5, 8, 10)
        snapped = min(valid_durations, key=lambda x: abs(x - duration))

        payload: dict = {
            "prompt": prompt,
            "duration": snapped,
            "ratio": ratio,
            "quality": quality,
            "model": "gen4_turbo",
        }
        if image_url:
            payload["imageUrl"] = image_url

        r = httpx.post(f"{_BASE}/api/v1/runway/generate", headers=_headers(), json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        logger.debug(f"Kie.ai runway generate response: {data}")
        task_id = _extract_task_id(data)
        if not task_id:
            raise RuntimeError(f"No task_id in Kie.ai Runway response: {data}")

        result = _poll("/api/v1/runway/record-detail", task_id, timeout=600)
        # Runway results may put the URL inside response.videoUrl or videoInfo.videoUrl
        response_data = result.get("response") or result.get("videoInfo") or {}
        video_url = (
            result.get("videoUrl")
            or result.get("video_url")
            or response_data.get("videoUrl")
            or response_data.get("video_url")
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

    # ── Image (FLUX / Market createTask) ──────────────────────────────────────

    @staticmethod
    def generate_image_portrait(prompt: str, aspect_ratio: str = "9:16") -> dict:
        """Generate a portrait via Kie.ai's market createTask.

        Used for the character-consistency Soul T2I replacement now that
        Higgsfield is out of credits. Tries the documented qwen2 image
        model first (we know createTask + qwen2/* works from Kie.ai docs),
        then falls back to the legacy /flux/generate endpoint.
        """
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY not configured")

        # Try Market createTask first (documented + actively maintained)
        market_url = f"{_BASE}/api/v1/jobs/createTask"
        for model_name in ("qwen2/text-to-image", "qwen2/image-edit"):
            payload = {
                "model": model_name,
                "input": {
                    "prompt": prompt,
                    "image_size": aspect_ratio,
                    "output_format": "jpeg",
                    "nsfw_checker": False,
                },
            }
            try:
                r = httpx.post(market_url, headers=_headers(), json=payload, timeout=30)
                if r.status_code != 200:
                    continue
                data = r.json()
                if data.get("code") and data["code"] not in (0, 200):
                    # 422 model not supported, 402 not enough credits, etc.
                    continue
                task_id = _extract_task_id(data)
                if not task_id:
                    continue
                result = _poll("/api/v1/jobs/recordInfo", task_id, timeout=180)
                image_url = (
                    result.get("resultUrls", [None])[0] if isinstance(result.get("resultUrls"), list) else None
                ) or result.get("imageUrl") or result.get("image_url") or result.get("url")
                if image_url:
                    logger.info(f"Kie.ai portrait via Market createTask model={model_name}")
                    return {"url": image_url, "model": model_name, "provider": "kieai"}
            except Exception as e:
                logger.warning(f"Kie.ai Market createTask {model_name} failed: {e}")
                continue

        # Fall back to legacy FLUX endpoint
        return KieAIService.generate_image_flux(prompt)

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
        inner = data.get("data") or data
        image_url = inner.get("imageUrl") or inner.get("image_url") or inner.get("url")
        if not image_url:
            task_id = _extract_task_id(data)
            if not task_id:
                raise RuntimeError(f"No image_url or task_id in Kie.ai FLUX response: {data}")
            result = _poll("/api/v1/flux/record-info", task_id, timeout=120)
            response_data = result.get("response") or {}
            image_url = (
                result.get("imageUrl") or result.get("image_url") or result.get("url")
                or response_data.get("imageUrl")
                or (response_data.get("resultUrls") or [None])[0]
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

        # NOTE: endpoint slug is `infinitetalk` (the model name has an 'e' in
        # 'infinite'). Older internal docs/code used the typo `infinitalk` which
        # 404s in production.
        payload = {"imageUrl": image_url, "audioUrl": audio_url}
        r = httpx.post(f"{_BASE}/api/v1/infinitetalk/generate", headers=_headers(), json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        task_id = _extract_task_id(data)
        if not task_id:
            raise RuntimeError(f"No task_id in Kie.ai InfiniteTalk response: {data}")
        return task_id

    @staticmethod
    def check_lip_sync(task_id: str) -> dict:
        """Poll InfiniteTalk task status."""
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY not configured")

        r = httpx.get(f"{_BASE}/api/v1/infinitetalk/record-info", params={"taskId": task_id}, headers=_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        inner = data.get("data") or data
        success_flag = inner.get("successFlag")
        status = (inner.get("status") or "").lower()
        response_data = inner.get("response") or {}

        result: dict = {"task_id": task_id, "status": status, "provider": "kieai"}
        if success_flag == 1 or status in ("completed", "succeeded", "success", "done"):
            result["status"] = "succeeded"
            video_url = (
                inner.get("videoUrl") or inner.get("video_url")
                or response_data.get("videoUrl")
                or (response_data.get("resultUrls") or [None])[0]
            )
            if video_url:
                result["video_url"] = video_url
                filename = f"infinitalk_{uuid.uuid4().hex[:8]}.mp4"
                result["local_path"] = _download(video_url, filename)
                result["download_filename"] = filename
        elif success_flag in (2, 3) or status in ("failed", "error"):
            result["status"] = "failed"
            result["error"] = inner.get("errorMessage") or inner.get("message") or "InfiniteTalk generation failed"

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

        result = _poll("/api/v1/veo/record-info", task_id, timeout=600)
        response_data = result.get("response") or {}
        video_url = (
            result.get("videoUrl")
            or result.get("video_url")
            or response_data.get("videoUrl")
            or (response_data.get("resultUrls") or [None])[0]
        )
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

    # ── Seedance 2.0 (ByteDance) — reference-image + reference-video → video ──────
    @staticmethod
    def generate_video_seedance(
        prompt: str,
        image_urls: Optional[list] = None,
        video_urls: Optional[list] = None,
        duration: int = 8,
        resolution: str = "720p",
        aspect_ratio: str = "9:16",
        model: str = "bytedance/seedance-2",
    ) -> dict:
        """Generate via ByteDance Seedance 2.0 on Kie.ai's universal Market createTask.
        Reference assets are passed as image_urls/video_urls and @-mentioned in the prompt
        (e.g. 'the person from @Image1 ...'). Returns {video_path, model_id, provider}."""
        if not settings.kie_api_key:
            raise ValueError("KIE_API_KEY not configured")
        inp = {"prompt": prompt, "duration": duration,
               "resolution": resolution, "aspect_ratio": aspect_ratio}
        if image_urls:
            inp["image_urls"] = image_urls
        if video_urls:
            inp["video_urls"] = video_urls
        r = httpx.post(f"{_BASE}/api/v1/jobs/createTask", headers=_headers(),
                       json={"model": model, "input": inp}, timeout=30)
        r.raise_for_status()
        data = r.json()
        logger.debug(f"Kie.ai seedance createTask response: {data}")
        task_id = _extract_task_id(data)
        if not task_id:
            raise RuntimeError(f"No task_id in Kie.ai Seedance response: {data}")

        result = _poll("/api/v1/jobs/recordInfo", task_id, timeout=900)
        response_data = result.get("response") or result.get("resultJson") or {}
        if isinstance(response_data, str):
            try:
                import json as _json
                response_data = _json.loads(response_data)
            except Exception:
                response_data = {}
        video_url = (
            result.get("videoUrl") or result.get("video_url")
            or response_data.get("videoUrl")
            or (response_data.get("resultUrls") or [None])[0]
            or (response_data.get("video_urls") or [None])[0]
        )
        if not video_url:
            raise RuntimeError(f"No video_url in Kie.ai Seedance result: {result}")

        filename = f"seedance_{uuid.uuid4().hex[:8]}.mp4"
        local_path = _download(video_url, filename)
        return {
            "video_path": local_path,
            "video_filename": filename,
            "model_id": "seedance-2",
            "provider": "kieai",
            "task_id": task_id,
        }
