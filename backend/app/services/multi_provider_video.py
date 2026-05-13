"""
Multi-provider video generation service.

Routing table (shot_type → preferred model → fallback):
  hero / lip_sync    → veo-3.1 → luma-ray-2
  spokesperson       → higgsfield-v1 → luma-ray-2 → veo-3.1
  action / motion    → kling-v3 → luma-ray-2 → veo-3.1-fast
  b_roll             → hailuo-02 → wan-2.2 → veo-3.1-fast
  transition         → ltx-2 → wan-2.2

Providers and their APIs:
  google    — VideoCreatorService (existing, Veo 3.1)
  higgsfield — Higgsfield REST API
  replicate  — Replicate REST API (Luma, Hailuo, Wan, LTX, Kling)
  kling      — Kling API (if key present, else Replicate fallback)
  runway     — Runway Gen-4 REST API
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


def _persist_video(local_path: str, filename: str) -> str:
    """Upload to S3 if configured, else return local download URL."""
    s3_url = StorageService.upload_file(local_path, f"videos/{filename}")
    return s3_url if s3_url else f"/api/v1/video/download/{filename}"

# Shot-type routing: ordered list of model_ids to try
_ROUTING = {
    "hero":        ["veo-3.1", "luma-ray-2"],
    "lip_sync":    ["veo-3.1", "luma-ray-2"],
    "spokesperson": ["higgsfield-v1", "luma-ray-2", "veo-3.1"],
    "action":      ["kling-v3", "luma-ray-2", "veo-3.1-fast"],
    "motion":      ["kling-v3", "luma-ray-2", "veo-3.1-fast"],
    "b_roll":      ["hailuo-02", "wan-2.2", "veo-3.1-fast"],
    "transition":  ["ltx-2", "wan-2.2", "hailuo-02"],
}

# Replicate model versions (pinned)
_REPLICATE_VERSIONS = {
    "luma-ray-2":  "luma-ai/ray-2-720p",
    "hailuo-02":   "minimax/hailuo-02",
    "wan-2.2":     "wan-ai/wan2.2-t2v-480p",
    "ltx-2":       "Lightricks/LTX-Video",
}


def _available_keys() -> set[str]:
    """Return which provider keys are configured."""
    keys = set()
    if settings.gemini_api_key:
        keys.add("google")
    if settings.higgsfield_api_key:
        keys.add("higgsfield")
    if settings.replicate_api_token:
        keys.add("replicate")
    if settings.kling_api_key:
        keys.add("kling")
    if settings.runway_api_key:
        keys.add("runway")
    return keys


def _model_provider(model_id: str) -> str:
    m = model_id.lower()
    if "veo" in m:
        return "google"
    if "higgsfield" in m:
        return "higgsfield"
    if "kling" in m:
        return "kling"
    if "runway" in m:
        return "runway"
    return "replicate"


def _pick_model(shot_type: str, preferred_model: Optional[str] = None) -> str:
    """Pick the best available model for the given shot type."""
    available = _available_keys()
    candidates = []
    if preferred_model:
        candidates.append(preferred_model)
    candidates.extend(_ROUTING.get(shot_type, _ROUTING["b_roll"]))

    for model_id in candidates:
        provider = _model_provider(model_id)
        if provider in available:
            return model_id

    # Last-resort fallback
    if "google" in available:
        return "veo-3.1-fast"
    if "replicate" in available:
        return "wan-2.2"
    raise RuntimeError("No video generation provider configured")


# ────────────────────────────────────────────────── Provider implementations

class _ReplicateRunner:
    """Thin async-friendly Replicate runner."""

    @staticmethod
    def start(model_slug: str, input_data: dict) -> str:
        """Submit prediction, return prediction_id."""
        token = settings.replicate_api_token
        headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
        resp = httpx.post(
            "https://api.replicate.com/v1/models/" + model_slug + "/predictions",
            headers=headers,
            json={"input": input_data},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    @staticmethod
    def poll(prediction_id: str, timeout: int = 300) -> dict:
        """Poll until completed. Returns full prediction dict."""
        token = settings.replicate_api_token
        headers = {"Authorization": f"Token {token}"}
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(5)
            resp = httpx.get(
                f"https://api.replicate.com/v1/predictions/{prediction_id}",
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data["status"] == "succeeded":
                return data
            if data["status"] in ("failed", "canceled"):
                raise RuntimeError(f"Replicate prediction failed: {data.get('error')}")
        raise TimeoutError(f"Replicate prediction {prediction_id} timed out")

    @staticmethod
    def download_output(url: str, filename: str) -> str:
        """Download output video URL to local VIDEOS_DIR."""
        path = os.path.join(VIDEOS_DIR, filename)
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return path


def _generate_replicate(model_id: str, prompt: str, image_url: Optional[str], duration: int) -> dict:
    slug = _REPLICATE_VERSIONS.get(model_id, model_id)
    input_data: dict = {"prompt": prompt, "num_frames": duration * 8}
    if image_url:
        input_data["image"] = image_url

    pred_id = _ReplicateRunner.start(slug, input_data)
    prediction = _ReplicateRunner.poll(pred_id, timeout=300)

    output = prediction.get("output")
    if isinstance(output, list):
        video_url = output[0]
    else:
        video_url = output

    filename = f"{model_id.replace('.', '_')}_{uuid.uuid4().hex[:8]}.mp4"
    local_path = _ReplicateRunner.download_output(video_url, filename)

    predict_time = (prediction.get("metrics") or {}).get("predict_time")
    cost = Pricing.video(model_id, duration)

    return {
        "video_path": local_path,
        "video_filename": filename,
        "download_url": _persist_video(local_path, filename),
        "model_id": model_id,
        "provider": "replicate",
        "prediction_id": pred_id,
        "cost_usd": cost,
        "predict_time_sec": predict_time,
    }


def _generate_higgsfield(prompt: str, image_url: Optional[str], duration: int) -> dict:
    """Higgsfield API — spokesperson/avatar video."""
    api_key = settings.higgsfield_api_key
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    payload = {
        "prompt": prompt,
        "duration": duration,
        "resolution": "1080p",
    }
    if image_url:
        payload["image_url"] = image_url

    resp = httpx.post(
        "https://api.higgsfield.ai/v1/generations",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    gen_id = data.get("id") or data.get("generation_id")

    # Poll
    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(5)
        poll = httpx.get(
            f"https://api.higgsfield.ai/v1/generations/{gen_id}",
            headers=headers,
            timeout=15,
        )
        poll.raise_for_status()
        status_data = poll.json()
        if status_data.get("status") == "completed":
            video_url = status_data.get("video_url") or status_data.get("output", {}).get("video_url")
            filename = f"higgsfield_{uuid.uuid4().hex[:8]}.mp4"
            local_path = _ReplicateRunner.download_output(video_url, filename)
            return {
                "video_path": local_path,
                "video_filename": filename,
                "download_url": _persist_video(local_path, filename),
                "model_id": "higgsfield-v1",
                "provider": "higgsfield",
                "generation_id": gen_id,
                "cost_usd": Pricing.video("higgsfield-v1", duration),
            }
        if status_data.get("status") in ("failed", "error"):
            raise RuntimeError(f"Higgsfield generation failed: {status_data}")
    raise TimeoutError("Higgsfield generation timed out")


def _generate_veo(prompt: str, image_path: Optional[str], duration: int, fast: bool = False) -> dict:
    """Delegate to existing VideoCreatorService."""
    from .video_creator import VideoCreatorService

    model_id = "veo-3.1-fast" if fast else "veo-3.1"

    if image_path and os.path.isfile(image_path):
        result = VideoCreatorService.generate_from_image(image_path, prompt, aspect_ratio="9:16", duration=duration)
    else:
        result = VideoCreatorService.generate_video(prompt, aspect_ratio="9:16", resolution="720p", duration=str(duration))

    # For Veo we return the operation_name — caller must poll via VideoCreatorService.check_status
    return {
        "operation_name": result["operation_name"],
        "model_id": model_id,
        "provider": "google",
        "status": "generating",
        "cost_usd": result["cost_usd"],
        "async": True,  # caller needs to poll
    }


# ────────────────────────────────────────────────── Public API

class MultiProviderVideoService:
    """Generate a single shot using the best available provider."""

    @staticmethod
    def route_model(shot_type: str, preferred_model: Optional[str] = None) -> str:
        """Return which model would be used for a given shot_type without generating."""
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
        """
        Generate a video shot. Returns a result dict with at minimum:
          video_path, video_filename, download_url, model_id, provider, cost_usd
        For async providers (Veo), also includes operation_name + async=True.
        """
        model_id = _pick_model(shot_type, preferred_model)
        provider = _model_provider(model_id)

        logger.info(f"Generating shot type={shot_type} model={model_id} duration={duration}s")

        if provider == "google":
            fast = "fast" in model_id
            return _generate_veo(prompt, image_path, duration, fast=fast)

        if provider == "higgsfield":
            return _generate_higgsfield(prompt, image_url or image_path, duration)

        if provider == "replicate":
            return _generate_replicate(model_id, prompt, image_url, duration)

        raise RuntimeError(f"Unknown provider: {provider} for model {model_id}")

    @staticmethod
    def estimate_cost(shot_type: str, duration: int = 6, preferred_model: Optional[str] = None) -> dict:
        """Return cost estimate before generating."""
        model_id = _pick_model(shot_type, preferred_model)
        return {
            "model_id": model_id,
            "provider": _model_provider(model_id),
            "estimated_cost_usd": Pricing.video(model_id, duration),
            "duration": duration,
        }

    @staticmethod
    def routing_table() -> dict:
        """Return full routing table with availability flags."""
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
