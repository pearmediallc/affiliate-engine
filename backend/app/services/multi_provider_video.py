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
# Kie.ai Runway Gen-4 is primary — works for text-to-video and image-to-video.
# Higgsfield is secondary (needs key:secret auth configured to activate).
_ROUTING = {
    "hero":         ["runway-gen4", "veo-3.1", "higgsfield-v1"],
    "lip_sync":     ["runway-gen4", "veo-3.1", "higgsfield-v1"],
    "spokesperson": ["higgsfield-v1", "runway-gen4", "veo-3.1"],
    "action":       ["runway-gen4", "kling-v3", "higgsfield-v1"],
    "motion":       ["runway-gen4", "kling-v3", "higgsfield-v1"],
    "b_roll":       ["runway-gen4", "hailuo-02", "wan-2.2"],
    "transition":   ["runway-gen4", "wan-2.2", "hailuo-02"],
}

# Higgsfield endpoint slugs per model — POST https://platform.higgsfield.ai/{slug}
# Higgsfield has no native text-to-video endpoint; for T2V we chain
# T2I (Soul) → I2V (DoP). The 'v1/' prefixed paths below come from the official
# higgsfield-js SDK. Older slugs (bytedance/seedance/...) return 404.
_HIGGSFIELD_T2I_SOUL_SLUG = "v1/text2image/soul"
_HIGGSFIELD_I2V_DOP_SLUG  = "v1/image2video/dop"

# I2V path per model_id. Models other than higgsfield-v1 aren't currently
# exercised by the iteration engine; leave them mapped to the DoP slug so any
# accidental call still hits a real endpoint instead of 404.
_HIGGSFIELD_I2V = {
    "higgsfield-v1": _HIGGSFIELD_I2V_DOP_SLUG,
    "kling-v3":      _HIGGSFIELD_I2V_DOP_SLUG,
    "wan-2.2":       _HIGGSFIELD_I2V_DOP_SLUG,
    "hailuo-02":     _HIGGSFIELD_I2V_DOP_SLUG,
    "luma-ray-2":    _HIGGSFIELD_I2V_DOP_SLUG,
    "seedance-2":    _HIGGSFIELD_I2V_DOP_SLUG,
}


def _persist_video(local_path: str, filename: str) -> str:
    s3_url = StorageService.upload_file(local_path, f"videos/{filename}")
    return s3_url if s3_url else f"/api/v1/video/download/{filename}"


def _available_keys() -> set[str]:
    keys = set()
    if settings.gemini_api_key:
        keys.add("google")
    # Higgsfield requires Key key:secret — mark available only when auth is complete
    hf_key = settings.higgsfield_api_key or ""
    hf_secret = settings.higgsfield_api_secret or ""
    if hf_key and (hf_secret or ":" in hf_key):
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
    if model_id in _HIGGSFIELD_I2V:
        return "higgsfield"
    return "higgsfield"  # default to higgsfield for unknown models


def _pick_model(shot_type: str, preferred_model: Optional[str] = None) -> str:
    available = _available_keys()
    # Routing table is authoritative — preferred_model from storyboard may be stale
    candidates = list(_ROUTING.get(shot_type, _ROUTING["b_roll"]))

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


def _higgsfield_submit(slug: str, payload: dict, headers: dict) -> str:
    """POST to platform.higgsfield.ai/{slug}, return request_id."""
    url = f"{_HIGGSFIELD_BASE}/{slug.lstrip('/')}"
    r = httpx.post(url, headers=headers, json=payload, timeout=30)
    if not r.is_success:
        logger.error(f"Higgsfield POST {slug} returned {r.status_code}: {r.text[:500]}")
    r.raise_for_status()
    data = r.json()
    logger.debug(f"Higgsfield submit {slug} response: {data}")
    inner = data.get("data") or data
    request_id = (
        inner.get("request_id") or inner.get("id")
        or inner.get("generation_id") or inner.get("taskId")
        or data.get("request_id") or data.get("id")
    )
    if not request_id:
        raise RuntimeError(f"No request_id in Higgsfield response: {data}")
    return request_id


def _higgsfield_poll(request_id: str, headers: dict, timeout: int = 600) -> dict:
    """Poll until the request reaches a terminal state; return the result dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(6)
        poll = httpx.get(
            f"{_HIGGSFIELD_BASE}/requests/{request_id}/status",
            headers=headers, timeout=15,
        )
        if not poll.is_success:
            logger.error(f"Higgsfield poll {request_id} returned {poll.status_code}: {poll.text[:300]}")
        poll.raise_for_status()
        sd_raw = poll.json()
        sd = sd_raw.get("data") or sd_raw
        status = (sd.get("status") or sd.get("state") or "").lower()
        if status in ("completed", "succeeded", "success", "done"):
            return sd
        if status in ("failed", "error", "canceled", "nsfw", "cancelled"):
            raise RuntimeError(f"Higgsfield request {request_id} failed: {sd}")
    raise TimeoutError(f"Higgsfield request {request_id} timed out")


def _higgsfield_extract_url(sd: dict, prefer: str = "video") -> Optional[str]:
    """Pull image_url / video_url out of a Higgsfield completed payload.
    Higgsfield response shapes vary by model — walk the common spots."""
    primary = ["video_url", "videoUrl"] if prefer == "video" else ["image_url", "imageUrl"]
    candidates = primary + ["url"]
    for k in candidates:
        v = sd.get(k)
        if v: return v
    container = sd.get("output") or sd.get("result") or sd.get("results") or {}
    if isinstance(container, dict):
        for k in candidates:
            v = container.get(k)
            if v: return v
        raw = container.get("raw")
        if isinstance(raw, dict) and raw.get("url"):
            return raw["url"]
    if isinstance(container, list) and container:
        first = container[0]
        if isinstance(first, dict):
            for k in candidates:
                v = first.get(k)
                if v: return v
            raw = first.get("raw")
            if isinstance(raw, dict) and raw.get("url"):
                return raw["url"]
    return None


def _higgsfield_t2i(prompt: str, headers: dict, size: str = "1080x1920") -> str:
    """Generate a still image via Soul T2I; return the resulting image URL.
    Used as step 1 of the T2I → I2V chain when no reference image is supplied.
    Higgsfield Soul wants `width_and_height` as 'WxH', not `aspect_ratio`."""
    payload = {"params": {"prompt": prompt, "width_and_height": size}}
    rid = _higgsfield_submit(_HIGGSFIELD_T2I_SOUL_SLUG, payload, headers)
    sd = _higgsfield_poll(rid, headers, timeout=180)
    image_url = _higgsfield_extract_url(sd, prefer="image")
    if not image_url:
        raise RuntimeError(f"No image_url in Higgsfield Soul T2I result: {sd}")
    return image_url


def _generate_higgsfield(
    model_id: str,
    prompt: str,
    image_url: Optional[str],
    duration: int,
) -> dict:
    """Generate video via Higgsfield Platform API.

    Platform has no native text-to-video. If no reference image is provided,
    we chain: T2I (Soul) → I2V (DoP). With an image we go straight to DoP I2V.

    Endpoints: POST https://platform.higgsfield.ai/{slug}
    Auth:      Authorization: Key {api_key}:{api_secret}
    Polling:   GET  https://platform.higgsfield.ai/requests/{request_id}/status
    """
    headers = _higgsfield_headers()

    if not image_url:
        logger.info(f"Higgsfield T2V-via-chain: Soul T2I first for model={model_id}")
        image_url = _higgsfield_t2i(prompt, headers)

    slug = _HIGGSFIELD_I2V.get(model_id, _HIGGSFIELD_I2V_DOP_SLUG)
    payload = {
        "params": {
            "model": "dop-turbo",
            "prompt": prompt,
            "duration": duration,
            "input_images": [{"type": "image_url", "image_url": image_url}],
        }
    }
    rid = _higgsfield_submit(slug, payload, headers)
    sd = _higgsfield_poll(rid, headers, timeout=600)
    video_url = _higgsfield_extract_url(sd, prefer="video")
    if not video_url:
        raise RuntimeError(f"No video_url in Higgsfield DoP I2V result: {sd}")

    filename = f"hf_{model_id.replace('-','_')}_{uuid.uuid4().hex[:8]}.mp4"
    local_path = _download_video(video_url, filename)
    return {
        "video_path": local_path,
        "video_filename": filename,
        "download_url": _persist_video(local_path, filename),
        "model_id": model_id,
        "provider": "higgsfield",
        "generation_id": rid,
        "cost_usd": Pricing.video(model_id, duration),
    }


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
