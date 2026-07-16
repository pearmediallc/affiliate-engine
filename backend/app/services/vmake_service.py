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
    """Build the SDK-HMAC-SHA256 signed headers — matches Vmake's official SDK signer exactly.

    The one detail every naive implementation misses: the Authorization value is base64-encoded
    and prefixed with 'Bearer '. Verified live against /skill/config.json → meta.code 0.
    """
    ak, sk = settings.vmake_ak, settings.vmake_sk
    if not ak or not sk:
        raise RuntimeError("Vmake keys missing — set MT_AK / MT_SK on the backend env")

    t = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    headers = {"Host": _HOST, "X-Sdk-Date": t}
    if body:
        headers["Content-Type"] = "application/json"

    signed_names = sorted(k.lower() for k in headers)                 # e.g. content-type;host;x-sdk-date
    low = {k.lower(): v.strip() for k, v in headers.items()}
    canon_headers = "\n".join(f"{n}:{low[n]}" for n in signed_names)  # NO trailing newline (SDK style)
    signed_headers = ";".join(signed_names)
    canon_uri = path if path.endswith("/") else path + "/"           # SDK forces a trailing slash
    canonical_request = f"{method}\n{canon_uri}\n\n{canon_headers}\n{signed_headers}\n{_sha256_hex(body)}"
    string_to_sign = f"SDK-HMAC-SHA256\n{t}\n{_sha256_hex(canonical_request.encode())}"
    signature = hmac.new(sk.encode(), string_to_sign.encode(), hashlib.sha256).hexdigest()

    raw_auth = f"SDK-HMAC-SHA256 Access={ak}, SignedHeaders={signed_headers}, Signature={signature}"
    import base64
    headers["Authorization"] = "Bearer " + base64.b64encode(raw_auth.encode()).decode()
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
    """Fetch skill config — the cheapest call that proves auth works (code 0 = keys good).
    Per WAPI docs config.json takes {gid, version}, not a task."""
    return _post("/skill/config.json", {"gid": "", "version": "v1.0.0"})


# ─── signing diagnostic ──────────────────────────────────────────────────────────────────────
# Both real keys and dummy keys return the same 10021, so a rejection can't tell us whether the
# KEYS are wrong or the SIGNING is wrong. This tries a matrix of signing variants server-side
# (where the real keys live) and reports which — if any — Vmake accepts. Never exposes the keys.

def _sign_variant(method: str, path: str, body: bytes, *, trail_slash: bool,
                  sign_ct: bool, hash_empty: bool) -> dict:
    ak, sk = settings.vmake_ak, settings.vmake_sk
    t = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    headers = {"Host": _HOST, "X-Sdk-Date": t}
    if sign_ct:
        headers["Content-Type"] = "application/json"
    signed_names = sorted(k.lower() for k in headers)
    canon_headers = "".join(
        f"{n}:{[headers[k] for k in headers if k.lower() == n][0].strip()}\n" for n in signed_names)
    signed_headers = ";".join(signed_names)
    canon_uri = (path + "/") if (trail_slash and not path.endswith("/")) else path
    payload_hash = _sha256_hex(b"" if hash_empty else body)
    canonical_request = "\n".join([method, canon_uri, "", canon_headers, signed_headers, payload_hash])
    string_to_sign = "\n".join(["SDK-HMAC-SHA256", t, _sha256_hex(canonical_request.encode())])
    sig = hmac.new(sk.encode(), string_to_sign.encode(), hashlib.sha256).hexdigest()
    out = {**headers, "Content-Type": "application/json",
           "Authorization": f"SDK-HMAC-SHA256 Access={ak}, SignedHeaders={signed_headers}, Signature={sig}"}
    return out


def diag(task: str = "videoscreenclear") -> dict:
    """Try a matrix of signing variants against /skill/config.json. Returns each variant's result
    code so we can see which signing Vmake accepts (code 0) — or that ALL fail (keys are wrong)."""
    body = json.dumps({"task": task}).encode()
    results = []
    for trail in (True, False):
        for sign_ct in (True, False):
            for hash_empty in (False, True):
                label = f"slash={int(trail)},ct={int(sign_ct)},emptyhash={int(hash_empty)}"
                try:
                    h = _sign_variant("POST", "/skill/config.json", body,
                                      trail_slash=trail, sign_ct=sign_ct, hash_empty=hash_empty)
                    r = requests.post(BASE_URL + "/skill/config.json", data=body, headers=h, timeout=30)
                    meta = {}
                    try:
                        meta = r.json().get("meta", {})
                    except Exception:
                        meta = {"raw": r.text[:120]}
                    results.append({"variant": label, "code": meta.get("code"), "msg": meta.get("msg")})
                    if meta.get("code") == 0:
                        return {"winner": label, "results": results}
                except Exception as e:
                    results.append({"variant": label, "error": str(e)[:120]})
    return {"winner": None, "results": results,
            "note": "All variants rejected — if none is code 0 the KEY VALUES are likely wrong "
                    "(typo / AK-SK swapped / stray whitespace in Render env)."}


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

def remove_captions_video(video_url: str, poll_seconds: int = 900) -> Optional[str]:
    """Return a clean (caption-free) video URL, or None so the caller falls back to ffmpeg-blur.

    NOT wired yet: the real task is NOT a consume.json call. Per Vmake's SDK the flow is
    config → OSS-upload the input (STS creds) → consume.json (quota only) → invoke to a dynamic
    AI host → poll status until done. That needs the official SDK vendored + the alibabacloud_oss_v2
    dependency. Auth/signing (the hard part) is solved and proven; this is the remaining plumbing.
    """
    logger.info("vmake remove_captions_video not wired yet (needs vendored SDK + OSS upload); "
                "falling back to ffmpeg-blur")
    return None
