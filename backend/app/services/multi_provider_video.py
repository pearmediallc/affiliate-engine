"""
Multi-provider video generation service.

Routing (shot_type → preferred model → fallback):
  hero / lip_sync    → veo-3.1 → higgsfield-v1
  spokesperson       → higgsfield-v1 → veo-3.1
  action / motion    → kling-v3 → higgsfield-v1 → veo-3.1-fast
  b_roll             → hailuo-02 → wan-2.2 → veo-3.1-fast
  transition         → wan-2.2 → hailuo-02

Provider mapping:
  google     — VideoCreatorService (Veo via Google AI Studio)
  higgsfield — Higgsfield Cloud API (Kling, Wan, Hailuo, Veo, own models)
  kieai      — Kie.ai API (Runway Gen-4, Veo fallback)

Replicate dependency removed. All models now route through Higgsfield or Kie.ai.
"""
import os
import time
import uuid
import logging
import httpx
from typing import Optional
from ..config import settings
from .pricing import Pricing
from .storage import StorageService

logger = logging.getLogger(__name__)

VIDEOS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "generated_videos",
)
os.makedirs(VIDEOS_DIR, exist_ok=True)

# Higgsfield Platform API — https://platform.higgsfield.ai
_HIGGSFIELD_BASE = "https://platform.higgsfield.ai"

# Shot-type routing: ordered list of model_ids to try
_ROUTING = {
    "hero":         ["veo-3.1", "higgsfield-v1"],
    "lip_sync":     ["veo-3.1", "higgsfield-v1"],
    "spokesperson": ["higgsfield-v1", "veo-3.1"],
    "action":       ["kling-v3", "higgsfield-v1", "veo-3.1-fast"],
    "motion":       ["kling-v3", "higgsfield-v1", "veo-3.1-fast"],
    "b_roll":       ["hailuo-02", "wan-2.2", "veo-3.1-fast"],
    "transition":   ["wan-2.2", "hailuo-02"],
}

# Higgsfield endpoint slugs per model — text-to-video (t2v) and image-to-video (i2v)
# Endpoints: POST https://platform.higgsfield.ai/{slug}
# NOTE: higgsfield-ai/dop/* is image-to-video ONLY — use kling for t2v
_HIGGSFIELD_T2V = {
    "higgsfield-v1": "kling-video/v2.1/pro/text-to-video",   # dop is i2v-only; kling is t2v fallback
    "kling-v3":      "kling-video/v2.1/pro/text-to-video",
    "wan-2.2":       "kling-video/v2.1/pro/text-to-video",    # wan t2v slug unconfirmed; use kling
    "hailuo-02":     "kling-video/v2.1/pro/text-to-video",    # hailuo t2v slug unconfirmed; use kling
    "luma-ray-2":    "kling-video/v2.1/pro/text-to-video",
    "seedance-2":    "bytedance/seedance/v1/pro/text-to-video",
}

_HIGGSFIELD_I2V = {
    "higgsfield-v1": "higgsfield-ai/dop/standard",
    "kling-v3":      "kling-video/v2.1/pro/image-to-video",
    "wan-2.2":       "kling-video/v2.1/pro/image-to-video",   # wan i2v slug unconfirmed; use kling
    "hailuo-02":     "kling-video/v2.1/pro/image-to-video",   # hailuo i2v slug unconfirmed; use kling
    "luma-ray-2":    "kling-video/v2.1/pro/image-to-video",
    "seedance-2":    "bytedance/seedance/v1/pro/image-to-video",
}


def _persist_video(local_path: str, filename: str) -> str:
    s3_url = StorageService.upload_file(local_path, f"videos/{filename}")
    return s3_url if s3_url else f"/api/v1/video/download/{filename}"


def _available_keys() -> set[str]:
    keys = set()
    if settings.gemini_api_key:
        keys.add("google")
    if settings.higgsfield_api_key:
        keys.add("higgsfield")
    if settings.kie_api_key:
        keys.add("kieai")
    return keys


def _model_provider(model_id: str) -> str:
    m = model_id.lower()
    if "veo" in m:
        return "google"
    if "runway" in m:
        return "kieai"
    if model_id in _HIGGSFIELD_T2V or model_id in _HIGGSFIELD_I2V:
        return "higgsfield"
    return "higgsfield"  # default to higgsfield for unknown models


def _pick_model(shot_type: str, preferred_model: Optional[str] = None) -> str:
    available = _available_keys()
    candidates = []
    if preferred_model:
        candidates.append(preferred_model)
    candidates.extend(_ROUTING.get(shot_type, _ROUTING["b_roll"]))

    for model_id in candidates:
        provider = _model_provider(model_id)
        if provider in available:
            return model_id

    if "google" in available:
        return "veo-3.1-fast"
    if "higgsfield" in available:
        return "hailuo-02"
    raise RuntimeError("No video generation provider configured (need HIGGSFIELD_API_KEY, GEMINI_API_KEY, or KIE_API_KEY)")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _download_video(url: str, filename: str) -> str:
    path = os.path.join(VIDEOS_DIR, filename)
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return path


# ── Higgsfield provider ───────────────────────────────────────────────────────

def _higgsfield_auth() -> str:
    """Build Higgsfield auth string: 'key:secret' or just 'key' if no secret configured."""
    key = settings.higgsfield_api_key or ""
    # If key already contains ':' it's stored as 'key:secret' in one env var
    if ":" in key:
        return key
    secret = settings.higgsfield_api_secret or ""
    return f"{key}:{secret}" if secret else key


def _higgsfield_headers() -> dict:
    return {
        "Authorization": f"Key {_higgsfield_auth()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _generate_higgsfield(
    model_id: str,
    prompt: str,
    image_url: Optional[str],
    duration: int,
) -> dict:
    """Generate video via Higgsfield Platform API.

    Endpoint: POST https://platform.higgsfield.ai/{model_slug}
    Auth:     Authorization: Key {api_key}:{api_secret}
    Polling:  GET  https://platform.higgsfield.ai/request/{request_id}
    """
    use_i2v = bool(image_url)
    slug_map = _HIGGSFIELD_I2V if use_i2v else _HIGGSFIELD_T2V
    slug = slug_map.get(model_id) or _HIGGSFIELD_T2V.get(model_id, "higgsfield-ai/dop/standard")
    headers = _higgsfield_headers()

    payload: dict = {"prompt": prompt, "duration": duration}
    if image_url:
        payload["image_url"] = image_url

    r = httpx.post(f"{_HIGGSFIELD_BASE}/{slug}", headers=headers, json=payload, timeout=30)
    if not r.is_success:
        logger.error(f"Higgsfield {slug} returned {r.status_code}: {r.text[:500]}")
    r.raise_for_status()
    data = r.json()
    request_id = (
        data.get("request_id")
        or data.get("id")
        or data.get("generation_id")
        or data.get("taskId")
    )
    if not request_id:
        raise RuntimeError(f"No request_id in Higgsfield response: {data}")

    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(6)
        poll = httpx.get(f"{_HIGGSFIELD_BASE}/request/{request_id}", headers=headers, timeout=15)
        poll.raise_for_status()
        sd = poll.json()
        status = (sd.get("status") or "").lower()
        if status in ("completed", "succeeded", "success", "done"):
            video_url = (
                sd.get("video_url")
                or sd.get("videoUrl")
                or (sd.get("output") or {}).get("video_url")
                or (sd.get("output") or {}).get("url")
            )
            if not video_url:
                raise RuntimeError(f"No video_url in Higgsfield result: {sd}")
            filename = f"hf_{model_id.replace('-','_')}_{uuid.uuid4().hex[:8]}.mp4"
            local_path = _download_video(video_url, filename)
            return {
                "video_path": local_path,
                "video_filename": filename,
                "download_url": _persist_video(local_path, filename),
                "model_id": model_id,
                "provider": "higgsfield",
                "generation_id": request_id,
                "cost_usd": Pricing.video(model_id, duration),
            }
        if status in ("failed", "error", "canceled"):
            raise RuntimeError(f"Higgsfield generation failed: {sd}")

    raise TimeoutError(f"Higgsfield generation {request_id} timed out")


# ── Kie.ai provider ───────────────────────────────────────────────────────────

def _generate_kieai_runway(
    prompt: str,
    image_url: Optional[str],
    duration: int,
) -> dict:
    from .kieai_service import KieAIService
    result = KieAIService.generate_video_runway(prompt, duration=duration, image_url=image_url)
    filename = result["video_filename"]
    local_path = result["video_path"]
    return {
        "video_path": local_path,
        "video_filename": filename,
        "download_url": _persist_video(local_path, filename),
        "model_id": "runway-gen4",
        "provider": "kieai",
        "cost_usd": Pricing.video("runway-gen4", duration),
    }


def _generate_kieai_veo(
    prompt: str,
    duration: int,
    fast: bool = False,
) -> dict:
    from .kieai_service import KieAIService
    result = KieAIService.generate_video_veo(prompt, duration=duration, fast=fast)
    filename = result["video_filename"]
    local_path = result["video_path"]
    model_id = "veo-3.1-fast" if fast else "veo-3.1"
    return {
        "video_path": local_path,
        "video_filename": filename,
        "download_url": _persist_video(local_path, filename),
        "model_id": model_id,
        "provider": "kieai",
        "cost_usd": Pricing.video(model_id, duration),
    }


# ── Google / Veo provider ─────────────────────────────────────────────────────

def _generate_veo(prompt: str, image_path: Optional[str], duration: int, fast: bool = False) -> dict:
    from .video_creator import VideoCreatorService
    model_id = "veo-3.1-fast" if fast else "veo-3.1"
    if image_path and os.path.isfile(image_path):
        result = VideoCreatorService.generate_from_image(image_path, prompt, aspect_ratio="9:16", duration=duration)
    else:
        result = VideoCreatorService.generate_video(prompt, aspect_ratio="9:16", resolution="720p", duration=str(duration))
    return {
        "operation_name": result["operation_name"],
        "model_id": model_id,
        "provider": "google",
        "status": "generating",
        "cost_usd": result["cost_usd"],
        "async": True,
    }


# ── Public API ────────────────────────────────────────────────────────────────

class MultiProviderVideoService:

    @staticmethod
    def route_model(shot_type: str, preferred_model: Optional[str] = None) -> str:
        return _pick_model(shot_type, preferred_model)

    @staticmethod
    def generate(
        prompt: str,
        shot_type: str = "b_roll",
        preferred_model: Optional[str] = None,
        image_path: Optional[str] = None,
        image_url: Optional[str] = None,
        duration: int = 6,
    ) -> dict:
        model_id = _pick_model(shot_type, preferred_model)
        provider = _model_provider(model_id)
        logger.info(f"Generating shot type={shot_type} model={model_id} provider={provider} duration={duration}s")

        if provider == "google":
            fast = "fast" in model_id
            return _generate_veo(prompt, image_path, duration, fast=fast)

        if provider == "kieai":
            if "runway" in model_id:
                return _generate_kieai_runway(prompt, image_url or image_path, duration)
            fast = "fast" in model_id
            return _generate_kieai_veo(prompt, duration, fast=fast)

        # higgsfield covers everything else
        return _generate_higgsfield(model_id, prompt, image_url or image_path, duration)

    @staticmethod
    def estimate_cost(shot_type: str, duration: int = 6, preferred_model: Optional[str] = None) -> dict:
        model_id = _pick_model(shot_type, preferred_model)
        return {
            "model_id": model_id,
            "provider": _model_provider(model_id),
            "estimated_cost_usd": Pricing.video(model_id, duration),
            "duration": duration,
        }

    @staticmethod
    def routing_table() -> dict:
        available = _available_keys()
        return {
            shot_type: [
                {
                    "model_id": m,
                    "provider": _model_provider(m),
                    "available": _model_provider(m) in available,
                }
                for m in models
            ]
            for shot_type, models in _ROUTING.items()
        }
