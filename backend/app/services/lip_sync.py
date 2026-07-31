"""
Lip-sync service — generates talking-head videos from portrait + audio.

Provider routing:
  1. Higgsfield Visual Effects API (primary) — cinematic quality, native lip-sync
  2. Kie.ai InfiniteTalk API (fallback) — image-to-talking-video
  3. Replicate SadTalker (legacy fallback, only if REPLICATE_API_TOKEN set)

Replicate is no longer the primary path. HIGGSFIELD_API_KEY or KIE_API_KEY required.
"""
import os
import json
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
# Split into SUBMIT (returns a provider job id) + POLL (one check), so the caller can persist
# the job id and a resumer can re-poll it after an AE restart — long renders never get orphaned.
def _sync_so_submit(video_url: str, audio_url: str, model: str = "lipsync-2") -> str:
    key = settings.sync_so_api_key
    if not key:
        raise RuntimeError("no sync.so key")
    body = {"model": model, "input": [{"type": "video", "url": video_url}, {"type": "audio", "url": audio_url}]}
    # free tier = 1 concurrent render → on a 429 concurrency limit, WAIT for the other to finish
    # and retry instead of hard-failing (auto-queues near-parallel/repeat requests).
    for attempt in range(8):
        r = requests.post("https://api.sync.so/v2/generate",
                          headers={"x-api-key": key, "Content-Type": "application/json"}, json=body, timeout=30)
        if r.status_code in (200, 201):
            gid = r.json().get("id")
            if not gid:
                raise RuntimeError(f"sync.so no id: {r.text[:160]}")
            return gid
        if r.status_code == 429 and "concurren" in r.text.lower():
            logger.info(f"sync.so busy (1-render free limit) — waiting to queue (try {attempt + 1})")
            time.sleep(25)
            continue
        raise RuntimeError(f"sync.so {r.status_code}: {r.text[:200]}")
    raise RuntimeError("sync.so still busy after waiting (concurrency limit)")


def _sync_so_status(gid: str):
    key = settings.sync_so_api_key
    s = requests.get(f"https://api.sync.so/v2/generate/{gid}", headers={"x-api-key": key}, timeout=30).json()
    st = (s.get("status") or "").upper()
    if st in ("COMPLETED", "DONE", "SUCCEEDED"):
        out = s.get("outputUrl") or s.get("output_url") or (s.get("output") or {}).get("url")
        if not out:
            raise RuntimeError(f"sync.so completed without output: {s}")
        return ("done", out)
    if st in ("FAILED", "ERROR", "REJECTED", "CANCELED", "TIMED_OUT"):
        raise RuntimeError(f"sync.so {st}: {s.get('error') or s.get('message')}")
    return ("processing", None)


def _fal_submit(video_url: str, audio_url: str) -> str:
    key = settings.fal_key
    if not key:
        raise RuntimeError("no fal key")
    r = requests.post("https://queue.fal.run/veed/lipsync",
                      headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
                      json={"video_url": video_url, "audio_url": audio_url}, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"fal {r.status_code}: {r.text[:200]}")
    rid = r.json().get("request_id")
    if not rid:
        raise RuntimeError(f"fal no request_id: {r.text[:160]}")
    return rid


# fal hosts SEVERAL lip-sync models at different prices for the same job. REAL rates below are from
# fal's ACTUAL invoice, NOT the docs sticker price ($0.07/sec for veed overstates real billing ~7x):
#   veed/lipsync             ≈ $0.60/min   ← cheapest WORKING lane → leads the bulk chain
#   sync-1.9-beta (falsync)  ≈ $0.70/min   ← mid tier
#   kling  $0.014 / 5s block ≈ $0.17/min   ← headline-cheap but rejects >10s clips (dead end for UGC)
# Endpoint choice IS the cost model.
FAL_LIPSYNC_ENDPOINTS = {
    "kling": "fal-ai/kling-video/lipsync/audio-to-video",   # ~$0.17/min — >10s clips rejected
    "falsync": "fal-ai/sync-lipsync",                        # ~$0.70/min — mid tier
    "veed": "veed/lipsync",                                  # ~$0.60/min real — cheapest working lane (bulk lead)
}
# Per-minute $ actually billed by fal for each lip-sync endpoint. Defaults are what we OBSERVED on
# fal's real invoices — NOT the docs sticker ($0.07/sec for veed = $4.20/min, which overstates real
# billing ~7x and is what inflated the office cost). SET THESE FROM YOUR OWN fal invoice via env
# (PRICE_LIPSYNC_VEED_PER_MIN etc.) so the number shown is grounded in reality, never a guessed sticker.
def _env_rate(name: str, default: float) -> float:
    try:
        v = os.getenv(name, "")
        return float(v) if v else float(default)
    except (TypeError, ValueError):
        return float(default)

FAL_LIPSYNC_PER_MIN = {
    "kling":   _env_rate("PRICE_LIPSYNC_KLING_PER_MIN", 0.168),
    "falsync": _env_rate("PRICE_LIPSYNC_FALSYNC_PER_MIN", 0.70),
    "veed":    _env_rate("PRICE_LIPSYNC_VEED_PER_MIN", 0.60),
}


def _fal_submit_ep(video_url: str, audio_url: str, ep_key: str = "kling") -> str:
    """Submit to a SPECIFIC fal lip-sync endpoint (price varies 25x across them)."""
    key = settings.fal_key
    if not key:
        raise RuntimeError("no fal key")
    slug = FAL_LIPSYNC_ENDPOINTS.get(ep_key) or FAL_LIPSYNC_ENDPOINTS["kling"]
    r = requests.post(f"https://queue.fal.run/{slug}",
                      headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
                      json={"video_url": video_url, "audio_url": audio_url}, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"fal {ep_key} {r.status_code}: {r.text[:200]}")
    try:
        sub = r.json() or {}
    except Exception:
        raise RuntimeError(f"fal {ep_key} non-JSON response: {r.text[:200]}")
    rid = sub.get("request_id")
    if not rid:
        raise RuntimeError(f"fal {ep_key} no request_id: {r.text[:160]}")
    # CRITICAL: multi-segment slugs (fal-ai/kling-video/lipsync/audio-to-video) CANNOT have their
    # status URL rebuilt from the base path — fal collapses them to the app prefix and the rebuilt
    # URL 404s/HTMLs, surfacing as "Expecting value: line 1 column 1". Carry fal's OWN status_url /
    # response_url through the job id so polling always hits the right queue. (Same bug already
    # fixed once in fal_video.py — do not rebuild fal queue URLs by hand.)
    su, ru = sub.get("status_url"), sub.get("response_url")
    logger.info(f"lipsync submitted via fal:{ep_key} (~${FAL_LIPSYNC_PER_MIN.get(ep_key, 0):.2f}/min)")
    if su and ru:
        return json.dumps({"id": rid, "status_url": su, "response_url": ru})
    return rid


def _fal_status_ep(rid: str, ep_key: str = "kling"):
    key = settings.fal_key
    h = {"Authorization": f"Key {key}"}
    # Prefer fal's OWN urls (carried from submit) — never rebuild them for multi-segment slugs.
    status_url = response_url = None
    if isinstance(rid, str) and rid.startswith("{"):
        try:
            _j = json.loads(rid)
            rid, status_url, response_url = _j.get("id"), _j.get("status_url"), _j.get("response_url")
        except Exception:
            pass
    if not status_url:
        slug = FAL_LIPSYNC_ENDPOINTS.get(ep_key) or FAL_LIPSYNC_ENDPOINTS["kling"]
        base = f"https://queue.fal.run/{slug}"
        status_url, response_url = f"{base}/requests/{rid}/status", f"{base}/requests/{rid}"
    _r = requests.get(status_url, headers=h, timeout=30)
    try:
        s = _r.json()
    except Exception:
        raise RuntimeError(f"fal {ep_key} status non-JSON ({_r.status_code}): {_r.text[:160]}")
    st = (s.get("status") or "").upper()
    if st == "COMPLETED":
        res = requests.get(response_url, headers=h, timeout=30).json()
        # endpoints differ: veed → {"video":{"url"}}, kling/sync → sometimes {"video_url"} / {"output"}
        out = ((res.get("video") or {}).get("url") if isinstance(res.get("video"), dict) else None) \
              or res.get("video_url") or res.get("url") \
              or ((res.get("output") or {}).get("url") if isinstance(res.get("output"), dict) else None)
        if not out:
            raise RuntimeError(f"fal {ep_key} completed without video url: {str(res)[:200]}")
        return ("done", out)
    if st in ("FAILED", "ERROR"):
        raise RuntimeError(f"fal {ep_key} {st}: {str(s)[:200]}")
    return ("processing", None)


def _fal_status(rid: str):
    key = settings.fal_key
    base = "https://queue.fal.run/veed/lipsync"
    h = {"Authorization": f"Key {key}"}
    s = requests.get(f"{base}/requests/{rid}/status", headers=h, timeout=30).json()
    st = (s.get("status") or "").upper()
    if st == "COMPLETED":
        res = requests.get(f"{base}/requests/{rid}", headers=h, timeout=30).json()
        out = (res.get("video") or {}).get("url")
        if not out:
            raise RuntimeError(f"fal completed without video url: {res}")
        return ("done", out)
    if st in ("FAILED", "ERROR"):
        raise RuntimeError(f"fal {st}: {s}")
    return ("processing", None)


def submit_relipsync(video_url: str, audio_url: str, prefer: str = None, quality: str = "bulk") -> dict:
    """Submit a video→video re-lipsync, routed by cost/quality. Returns {provider, job} WITHOUT
    waiting — the caller persists this + polls. bulk = cheapest-first (Replicate per-render is
    cheapest for volume); premium = best-quality-first (sync.so). `prefer` overrides."""
    # bulk (default): veed (fal veed/lipsync) LEADS — at ~$0.60/min real it is the cheapest WORKING
    #   lane (fal-kling is cheaper on paper but rejects >10s clips) → falsync → Replicate.
    # premium: sync.so FIRST (blends the mouth/jaw seam best) but it is EXPENSIVE per job (~$1.5–5),
    #   so it leads ONLY when premium is explicitly requested → then veed → falsync → Replicate.
    # Replicate lanes are dropped entirely unless the account is funded (REPLICATE_ENABLED) —
    # an unfunded token 402s on every render, which just burns time and falls through anyway.
    # REAL per-lane rates (fal's ACTUAL invoice, not docs sticker):
    #   veed ~$0.60/min · falsync ~$0.70/min · kling ~$0.17/min · latentsync ~$0.09/render · wav2lip ~$0.03
    #   sync.so (direct) ~$1.5–5/job — priciest, best seam → premium lead only.
    # NOTE: fal-kling is NOT in any chain. Per fal's docs it accepts only 2-10 SECOND source videos
    # (ours are 20-45s), so it rejects every real avatar clip with "Video size is too large" after a
    # ~12min wait — a guaranteed dead end. Kept selectable via `prefer` for short clips only.
    #   bulk:    veed → falsync → latentsync → wav2lip
    #   premium: sync → veed → falsync → latentsync → wav2lip
    chain = (["sync", "veed", "falsync", "latentsync", "wav2lip"] if quality == "premium"
             else ["veed", "falsync", "latentsync", "wav2lip"])
    if not settings.replicate_usable:
        chain = [p for p in chain if p not in ("latentsync", "wav2lip")]
    order, seen, errors = [], set(), []
    for p in ([prefer] if prefer else []) + chain:
        if p and p not in seen:
            seen.add(p); order.append(p)
    for p in order:
        try:
            if p == "sync":
                job = _sync_so_submit(video_url, audio_url)
            elif p in ("kling", "falsync", "veed"):
                job = _fal_submit_ep(video_url, audio_url, p)
            elif p == "fal":       # legacy alias — keep working, but on the CHEAP endpoint now
                p = "kling"
                job = _fal_submit_ep(video_url, audio_url, "kling")
            elif p in ("latentsync", "wav2lip"):
                if not settings.replicate_usable:
                    raise RuntimeError("Replicate not enabled (unfunded account) — using fal/sync.so instead")
                job = _start_replicate(video_url, audio_url, model=p)
            else:
                continue
            logger.info(f"relipsync submitted via {p} (job {job})")
            return {"provider": p, "job": str(job)}
        except Exception as e:
            errors.append(f"{p}: {e}")
            logger.warning(f"relipsync submit {p} failed: {e}")
    raise RuntimeError("all lip-sync providers rejected the submit → " + " | ".join(errors[-4:]))


def poll_relipsync(provider: str, job: str):
    """One status poll. Returns ('processing', None) | ('done', {video_url|local_path}). Raises on failure."""
    if provider == "sync":
        st, url = _sync_so_status(job); return (st, {"video_url": url} if url else None)
    if provider in ("kling", "falsync", "veed"):
        st, url = _fal_status_ep(job, provider); return (st, {"video_url": url} if url else None)
    if provider == "fal":   # legacy rows persisted before the endpoint split → veed queue
        st, url = _fal_status(job); return (st, {"video_url": url} if url else None)
    if provider in ("latentsync", "wav2lip"):
        r = _check_replicate(job)
        if r.get("local_path"):
            return ("done", {"local_path": r["local_path"]})
        if r.get("video_url"):
            return ("done", {"video_url": r["video_url"]})
        if r.get("status") in ("failed", "canceled"):
            raise RuntimeError(r.get("error") or f"{provider} failed")
        return ("processing", None)
    raise RuntimeError(f"unknown lip-sync provider {provider}")


def relipsync_video(video_url: str, audio_url: str, prefer: str = None) -> dict:
    """Blocking convenience wrapper (submit → poll to done). Returns {provider, video_url|local_path}."""
    sub = submit_relipsync(video_url, audio_url, prefer)
    for _ in range(150):   # ~10 min
        time.sleep(4)
        st, res = poll_relipsync(sub["provider"], sub["job"])
        if st == "done":
            return {"provider": sub["provider"], **res}
    raise RuntimeError(f"lip-sync via {sub['provider']} timed out")


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
