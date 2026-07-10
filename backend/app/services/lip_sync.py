"""
Lip-sync service — generates talking-head videos from portrait + audio.

Provider routing:
  1. Higgsfield Visual Effects API (primary) — cinematic quality, native lip-sync
  2. Kie.ai InfiniteTalk API (fallback) — image-to-talking-video
  3. Replicate SadTalker (legacy fallback, only if REPLICATE_API_TOKEN set)

Replicate is no longer the primary path. HIGGSFIELD_API_KEY or KIE_API_KEY required.
"""
import os
import uuid
import time
import logging
import requests
import httpx
from typing import Optional
from ..config import settings
from .pricing import Pricing
from .storage import StorageService

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "downloads",
)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

_HIGGSFIELD_BASE = "https://cloud.higgsfield.ai/api/v1"


def _persist(local_path: str, filename: str) -> str:
    s3 = StorageService.upload_file(local_path, f"videos/{filename}")
    return s3 if s3 else f"/api/v1/lip-sync/download/{filename}"


def _download(url: str, filename: str) -> str:
    path = os.path.join(DOWNLOADS_DIR, filename)
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return path


# ── Higgsfield Visual Effects ─────────────────────────────────────────────────

def _start_higgsfield(image_url: str, audio_url: str) -> str:
    headers = {
        "Authorization": f"Bearer {settings.higgsfield_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "visual-effects",
        "image_url": image_url,
        "audio_url": audio_url,
        "effect": "lip_sync",
    }
    r = httpx.post(f"{_HIGGSFIELD_BASE}/generations", headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("id") or data.get("generation_id") or data.get("taskId")


def _check_higgsfield(gen_id: str) -> dict:
    headers = {"Authorization": f"Bearer {settings.higgsfield_api_key}"}
    r = httpx.get(f"{_HIGGSFIELD_BASE}/generations/{gen_id}", headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    status = (data.get("status") or "").lower()
    result = {"generation_id": gen_id, "status": status, "provider": "higgsfield"}

    if status in ("completed", "succeeded", "success", "done"):
        result["status"] = "succeeded"
        video_url = data.get("video_url") or data.get("videoUrl")
        if video_url:
            result["video_url"] = video_url
            filename = f"lipsync_hf_{uuid.uuid4().hex[:8]}.mp4"
            local_path = _download(video_url, filename)
            result["local_path"] = local_path
            result["download_filename"] = filename
    elif status in ("failed", "error", "canceled"):
        result["status"] = "failed"
        result["error"] = data.get("message") or "Higgsfield generation failed"

    return result


# ── Kie.ai InfiniteTalk ───────────────────────────────────────────────────────

def _start_kieai(image_url: str, audio_url: str) -> str:
    from .kieai_service import KieAIService
    return KieAIService.start_lip_sync(image_url, audio_url)


def _check_kieai(task_id: str) -> dict:
    from .kieai_service import KieAIService
    return KieAIService.check_lip_sync(task_id)


# ── Replicate legacy (SadTalker / Wav2Lip) ────────────────────────────────────

_REPLICATE_MODELS = {
    "sadtalker": {"owner": "cjwbw", "model": "sadtalker", "input_keys": {"image": "source_image", "audio": "driven_audio"}, "extras": {"enhancer": "gfpgan"}},
    "wav2lip":   {"owner": "cjwbw", "model": "wav2lip",   "input_keys": {"image": "face", "audio": "audio"}, "extras": {}},
    # LatentSync — video→video re-lipsync (the CapCut equivalent): feed the avatar's
    # own footage as `video` + the new voice as `audio`; the mouth is re-synced.
    "latentsync": {"owner": "bytedance", "model": "latentsync", "input_keys": {"image": "video", "audio": "audio"}, "extras": {}},
}


def _start_replicate(image_url: str, audio_url: str, model: str = "sadtalker") -> str:
    token = settings.replicate_api_token
    info = _REPLICATE_MODELS.get(model, _REPLICATE_MODELS["sadtalker"])
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    keys = info["input_keys"]
    payload = {keys["image"]: image_url, keys["audio"]: audio_url, **info.get("extras", {})}
    owner, name = info["owner"], info["model"]
    r = requests.post(
        f"https://api.replicate.com/v1/models/{owner}/{name}/predictions",
        headers=headers, json={"input": payload}, timeout=30,
    )
    if r.status_code not in (200, 201):
        raise Exception(f"Replicate API error: {r.status_code} - {r.text[:300]}")
    return r.json().get("id")


def _check_replicate(prediction_id: str) -> dict:
    token = settings.replicate_api_token
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"https://api.replicate.com/v1/predictions/{prediction_id}", headers=headers, timeout=30)
    if r.status_code != 200:
        raise Exception(f"Replicate status check failed: {r.status_code}")
    data = r.json()
    status = data.get("status")
    result = {"prediction_id": prediction_id, "status": status, "provider": "replicate"}

    if status == "succeeded":
        output = data.get("output")
        video_url = output if isinstance(output, str) else (output[0] if isinstance(output, list) else None)
        if video_url:
            result["video_url"] = video_url
            try:
                resp = requests.get(video_url, timeout=60)
                if resp.status_code == 200:
                    filename = f"lipsync_{uuid.uuid4().hex[:8]}.mp4"
                    filepath = os.path.join(DOWNLOADS_DIR, filename)
                    with open(filepath, "wb") as f:
                        f.write(resp.content)
                    result["local_path"] = filepath
                    result["download_filename"] = filename
            except Exception as e:
                logger.warning(f"Failed to download Replicate lip-sync result: {e}")

    predict_time = (data.get("metrics") or {}).get("predict_time")
    result["predict_time_sec"] = predict_time
    result["cost_usd"] = Pricing.lip_sync(predict_time, hardware="t4")
    return result


# ── Available models list ─────────────────────────────────────────────────────

MODELS = {
    "higgsfield": {
        "name": "Higgsfield Visual Effects",
        "description": "Cinematic lip-sync and talking-head generation",
        "provider": "higgsfield",
    },
    "infinitalk": {
        "name": "InfiniteTalk (Kie.ai)",
        "description": "Image-to-talking-video with accurate lip sync",
        "provider": "kieai",
    },
    "sadtalker": {
        "name": "SadTalker",
        "description": "Audio-driven talking face (legacy, via Replicate)",
        "provider": "replicate",
    },
    "wav2lip": {
        "name": "Wav2Lip",
        "description": "Fast lip-sync for existing video clips (legacy, via Replicate)",
        "provider": "replicate",
    },
    "latentsync": {
        "name": "LatentSync",
        "description": "High-quality video→video re-lipsync (CapCut equivalent) — avatar footage + new voice",
        "provider": "replicate",
    },
}


# ── Video→video re-lipsync (reuse OUR footage, change only the mouth = the CapCut flow) ──
def _sync_so_relipsync(video_url: str, audio_url: str, model: str = "lipsync-2") -> str:
    """sync.so — true video→video lip-sync. Returns the output video URL."""
    key = settings.sync_so_api_key
    if not key:
        raise RuntimeError("no sync.so key")
    r = requests.post("https://api.sync.so/v2/generate",
                      headers={"x-api-key": key, "Content-Type": "application/json"},
                      json={"model": model, "input": [
                          {"type": "video", "url": video_url},
                          {"type": "audio", "url": audio_url}]}, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"sync.so {r.status_code}: {r.text[:200]}")
    gid = r.json().get("id")
    if not gid:
        raise RuntimeError(f"sync.so no id: {r.text[:160]}")
    for _ in range(150):   # up to ~10 min
        time.sleep(4)
        s = requests.get(f"https://api.sync.so/v2/generate/{gid}",
                         headers={"x-api-key": key}, timeout=30).json()
        st = (s.get("status") or "").upper()
        if st in ("COMPLETED", "DONE", "SUCCEEDED"):
            out = s.get("outputUrl") or s.get("output_url") or (s.get("output") or {}).get("url")
            if out:
                return out
            raise RuntimeError(f"sync.so completed without output: {s}")
        if st in ("FAILED", "ERROR", "REJECTED", "CANCELED", "TIMED_OUT"):
            raise RuntimeError(f"sync.so {st}: {s.get('error')}")
    raise RuntimeError("sync.so timed out")


def _fal_veed_relipsync(video_url: str, audio_url: str) -> str:
    """fal.ai veed/lipsync — video→video. Returns the output video URL."""
    key = settings.fal_key
    if not key:
        raise RuntimeError("no fal key")
    base = "https://queue.fal.run/veed/lipsync"
    h = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    r = requests.post(base, headers=h, json={"video_url": video_url, "audio_url": audio_url}, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"fal {r.status_code}: {r.text[:200]}")
    d = r.json()
    rid = d.get("request_id")
    status_url = d.get("status_url") or f"{base}/requests/{rid}/status"
    resp_url = d.get("response_url") or f"{base}/requests/{rid}"
    for _ in range(150):
        time.sleep(4)
        s = requests.get(status_url, headers=h, timeout=30).json()
        st = (s.get("status") or "").upper()
        if st == "COMPLETED":
            res = requests.get(resp_url, headers=h, timeout=30).json()
            out = (res.get("video") or {}).get("url")
            if out:
                return out
            raise RuntimeError(f"fal completed without video url: {res}")
        if st in ("FAILED", "ERROR"):
            raise RuntimeError(f"fal {st}: {s}")
    raise RuntimeError("fal timed out")


def relipsync_video(video_url: str, audio_url: str, prefer: str = None) -> dict:
    """
    Reuse our REAL footage and re-sync only the mouth to `audio_url`. Provider chain,
    free/cheapest first: sync.so (free tier) → fal veed → Replicate LatentSync → Wav2Lip.
    Returns {provider, video_url|local_path}. Never touches Replicate unless the free
    providers are unavailable/failed.
    """
    order, seen, errors = [], set(), []
    for p in ([prefer] if prefer else []) + ["sync", "fal", "latentsync", "wav2lip"]:
        if not p or p in seen:
            continue
        seen.add(p)
        order.append(p)
    for p in order:
        try:
            if p == "sync":
                url = _sync_so_relipsync(video_url, audio_url)
            elif p == "fal":
                url = _fal_veed_relipsync(video_url, audio_url)
            elif p in ("latentsync", "wav2lip"):
                if not settings.replicate_api_token:
                    raise RuntimeError("no replicate token")
                job = _start_replicate(video_url, audio_url, model=p)
                url = None
                for _ in range(120):
                    time.sleep(4)
                    st = _check_replicate(job)
                    if st.get("local_path"):
                        return {"provider": p, "local_path": st["local_path"]}
                    if st.get("video_url"):
                        url = st["video_url"]; break
                    if st.get("status") in ("failed", "canceled"):
                        raise RuntimeError(st.get("error") or f"{p} failed")
                if not url:
                    raise RuntimeError(f"{p} timed out")
            else:
                continue
            logger.info(f"relipsync via {p}")
            return {"provider": p, "video_url": url}
        except Exception as e:
            errors.append(f"{p}: {e}")
            logger.warning(f"relipsync {p} unavailable/failed: {e}")
    raise RuntimeError("all video lip-sync providers failed → " + " | ".join(errors[-4:]))


class LipSyncService:

    @staticmethod
    def get_available_models() -> list:
        available = []
        for k, v in MODELS.items():
            p = v["provider"]
            is_avail = (
                (p == "higgsfield" and bool(settings.higgsfield_api_key))
                or (p == "kieai" and bool(settings.kie_api_key))
                or (p == "replicate" and bool(settings.replicate_api_token))
            )
            available.append({"id": k, **v, "available": is_avail})
        return available

    @staticmethod
    def _best_provider() -> str:
        # Kie.ai InfiniteTalk is preferred — Higgsfield's lip-sync endpoint
        # (cloud.higgsfield.ai/api/v1/generations) returns 404 in current
        # production. Their actual speak endpoint is on platform.higgsfield.ai
        # but uses a different request shape; not yet wired here.
        if settings.kie_api_key:
            return "kieai"
        if settings.higgsfield_api_key:
            return "higgsfield"
        if settings.replicate_api_token:
            return "replicate"
        raise ValueError("No lip-sync provider configured — set KIE_API_KEY or HIGGSFIELD_API_KEY")

    @staticmethod
    def start_generation(image_url: str, audio_url: str, model: str = "auto") -> dict:
        """
        Start a lip-sync generation job.
        model: 'auto' | 'higgsfield' | 'infinitalk' | 'sadtalker' | 'wav2lip'
        Returns dict with provider, job_id (prediction_id or generation_id or task_id).
        """
        if model == "auto":
            provider = LipSyncService._best_provider()
        elif model == "higgsfield":
            provider = "higgsfield"
        elif model == "infinitalk":
            provider = "kieai"
        else:
            provider = "replicate"

        if provider == "higgsfield":
            gen_id = _start_higgsfield(image_url, audio_url)
            return {"provider": "higgsfield", "generation_id": gen_id, "status": "starting", "model": "higgsfield"}

        if provider == "kieai":
            task_id = _start_kieai(image_url, audio_url)
            return {"provider": "kieai", "task_id": task_id, "status": "starting", "model": "infinitalk"}

        # replicate legacy
        pred_id = _start_replicate(image_url, audio_url, model=model)
        return {"provider": "replicate", "prediction_id": pred_id, "status": "starting", "model": model}

    @staticmethod
    def check_status(job: dict) -> dict:
        """
        Poll status. job must contain the dict returned by start_generation.
        Returns status dict with optional video_url / local_path.
        """
        provider = job.get("provider", "replicate")

        if provider == "higgsfield":
            return _check_higgsfield(job["generation_id"])

        if provider == "kieai":
            return _check_kieai(job["task_id"])

        return _check_replicate(job["prediction_id"])

    @staticmethod
    def upload_file_to_provider(file_path: str) -> str:
        """
        Upload a local file and return a public URL.
        Tries S3 first (if configured), then Replicate file hosting as last resort.
        """
        s3_url = StorageService.upload_file(file_path, f"uploads/{os.path.basename(file_path)}")
        if s3_url:
            return s3_url

        # Legacy: Replicate file hosting
        if settings.replicate_api_token:
            headers = {"Authorization": f"Bearer {settings.replicate_api_token}"}
            with open(file_path, "rb") as f:
                r = requests.post(
                    "https://api.replicate.com/v1/files",
                    headers=headers,
                    files={"content": (os.path.basename(file_path), f)},
                    timeout=60,
                )
            if r.status_code in (200, 201):
                return r.json().get("urls", {}).get("get", "")

        raise ValueError("Cannot upload file: no S3 configured and no Replicate token")
