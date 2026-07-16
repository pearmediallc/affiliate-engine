"""
Vmake caption/watermark removal — the same tool our editors use in the vmake.ai UI, via its API.

Auth: SDK-HMAC-SHA256 (Huawei APIG signing scheme). Keys come from Render env MT_AK / MT_SK
(exposed as settings.vmake_ak / settings.vmake_sk). NEVER hard-code them.

API-key surface (confirmed by live probing — these two accept the AK/SK signature; the
query/task/status endpoints are web-session only and are NOT reachable with an API key):
  POST /skill/config.json   → skill config / cost for a task
  POST /skill/consume.json  → run a task; async tasks return a task id we poll via the same route

Video caption/watermark removal task = `videoscreenclear` (async).
Image watermark erase task = `eraser_watermark` (sync).

Response envelope: {"meta": {"code": 0, "msg": "..."}, "response": {...}}. meta.code == 0 = OK.
"""
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from ..config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://wapi-skill.vmake.ai"
_HOST = "wapi-skill.vmake.ai"


def is_configured() -> bool:
    return bool(settings.vmake_ak and settings.vmake_sk)


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sign(method: str, path: str, body: bytes) -> dict:
    """Build the SDK-HMAC-SHA256 Authorization header (Huawei APIG scheme).

    Structurally verified live against /skill/config.json: with a well-formed signature the API
    stops replying 'missing Authorization header' and validates the key instead.
    """
    ak, sk = settings.vmake_ak, settings.vmake_sk
    if not ak or not sk:
        raise RuntimeError("Vmake keys missing — set MT_AK / MT_SK on the backend env")

    t = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    headers = {"Host": _HOST, "Content-Type": "application/json", "X-Sdk-Date": t}

    signed_names = sorted(k.lower() for k in headers)
    canon_headers = "".join(
        f"{n}:{[headers[k] for k in headers if k.lower() == n][0].strip()}\n" for n in signed_names
    )
    signed_headers = ";".join(signed_names)
    canon_uri = path if path.endswith("/") else path + "/"
    canonical_request = "\n".join([method, canon_uri, "", canon_headers, signed_headers, _sha256_hex(body)])
    string_to_sign = "\n".join(["SDK-HMAC-SHA256", t, _sha256_hex(canonical_request.encode())])
    signature = hmac.new(sk.encode(), string_to_sign.encode(), hashlib.sha256).hexdigest()

    headers["Authorization"] = (
        f"SDK-HMAC-SHA256 Access={ak}, SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


def _post(path: str, payload: dict, timeout: int = 60) -> dict:
    """Signed POST. Returns the parsed envelope dict (does NOT raise on meta.code != 0 — the
    caller decides, since the test endpoint wants to see raw error codes)."""
    body = json.dumps(payload or {}).encode()
    headers = _sign("POST", path, body)
    r = requests.post(BASE_URL + path, data=body, headers=headers, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"meta": {"code": -1, "msg": f"non-JSON HTTP {r.status_code}: {r.text[:200]}"}}


def _ok(env: dict) -> bool:
    return isinstance(env, dict) and env.get("meta", {}).get("code") == 0


def get_config(task: str = "videoscreenclear") -> dict:
    """Fetch a task's config — the cheapest call that proves auth works (code 0 = keys good)."""
    return _post("/skill/config.json", {"task": task})


def consume(url: str, task: str, gid: str = "", params: Optional[dict] = None) -> dict:
    """Run a task on a media URL. For async tasks the first call returns a task/gid to poll."""
    body = {"url": url, "task": task, "gid": gid or ""}
    if params:
        body["parameter"] = params
    return _post("/skill/consume.json", body)


# ─── high-level: remove burned-in captions/watermark from a video ────────────────────────────
# The async poll contract (which field carries the task id, which carries the result url, and the
# terminal status value) is read from the FIRST real consume.json response via /regen/vmake-test,
# then finalized here. Until then this uses the best-known field names and degrades safely.

def remove_captions_video(video_url: str, poll_seconds: int = 240) -> Optional[str]:
    """Returns a clean (caption-free) video URL, or None on any failure so the caller falls back
    to the ffmpeg-blur path. Never raises."""
    if not is_configured():
        return None
    try:
        env = consume(video_url, "videoscreenclear", params={"rsp_media_type": "url"})
        if not _ok(env):
            logger.warning(f"vmake videoscreenclear spawn failed: {env.get('meta')}")
            return None
        resp = env.get("response", {}) or {}
        # Direct result (some tasks return synchronously)
        done = _extract_result_url(resp)
        if done:
            return done
        # Otherwise poll by the returned task/gid
        task_id = resp.get("gid") or resp.get("task_id") or resp.get("taskId") or resp.get("id")
        if not task_id:
            logger.warning(f"vmake videoscreenclear: no task id in {resp}")
            return None
        deadline = time.time() + poll_seconds
        while time.time() < deadline:
            time.sleep(6)
            p = consume(video_url, "videoscreenclear", gid=str(task_id), params={"rsp_media_type": "url"})
            if not _ok(p):
                continue
            r = p.get("response", {}) or {}
            u = _extract_result_url(r)
            if u:
                return u
            if str(r.get("status", "")).lower() in ("failed", "error"):
                logger.warning(f"vmake task {task_id} failed: {r}")
                return None
        logger.warning(f"vmake task {task_id} timed out after {poll_seconds}s")
        return None
    except Exception as e:
        logger.warning(f"vmake remove_captions_video error: {e}")
        return None


def _extract_result_url(resp: dict) -> Optional[str]:
    """Best-effort pull of a result media URL out of the response envelope."""
    if not isinstance(resp, dict):
        return None
    for k in ("url", "result_url", "resultUrl", "output_url", "media_url", "download_url"):
        v = resp.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    # nested {result: {url}} / {data: {url}} / list forms
    for k in ("result", "data", "output", "media"):
        v = resp.get(k)
        if isinstance(v, dict):
            u = _extract_result_url(v)
            if u:
                return u
        if isinstance(v, list) and v and isinstance(v[0], dict):
            u = _extract_result_url(v[0])
            if u:
                return u
        if isinstance(v, str) and v.startswith("http"):
            return v
    return None
