"""
Creative Regeneration orchestrator.

Two endpoints power the admin "Variation Studio" in creative-library:

  POST /regen/interpret  — Gemini turns a free-text "what I expect" + the creative's
                           metrics/diagnosis into a STRICT JSON directive.
  POST /regen/run        — runs the recipe for the chosen variation type in the
                           background and POSTs the produced variants back to the
                           caller's callback_url.

Recipes are ordered chains over the engine's EXISTING separate features
(tiktok_symphony avatar, stock_footage, speech_generator, auto_editor, ...).
"""
import os
import re
import random
import json
import math
import base64
import time
import logging
import asyncio
import tempfile
import subprocess
import contextvars
from typing import Optional, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Depends, File, Form, UploadFile
from pydantic import BaseModel

from ..config import settings
from ..services.tiktok_symphony import TikTokSymphonyService
from ..services.stock_footage import StockFootageService
from ..services.multi_provider_video import MultiProviderVideoService

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_MODEL = "gemini-2.5-flash"
# CROSS-FAMILY semantic judge for the EVAL GATE — deliberately NOT Gemini (which grades in-flight),
# so the final examiner can't self-grade its own family's output. Pinned here as one source of truth.
EVAL_JUDGE_MODEL = "gpt-4o"
CALLBACK_SECRET = os.getenv("REGEN_CALLBACK_SECRET", "change-me-regen-callback")

# HARD COST CEILING for a single job's paid render. Projected (never actual-after-the-fact) spend is
# computed BEFORE any paid submit; over the ceiling we refuse instead of burning credits.
# Above this projected spend we ASK the user before spending (never a silent refusal).
CONFIRM_JOB_USD = float(os.getenv("CONFIRM_JOB_USD", "5.00"))


def _lipsync_projected_usd(provider: str, seconds: float) -> float:
    """Projected lip-sync spend for `seconds` of output on `provider`, at the verified 2026 rates."""
    s = max(0.0, float(seconds or 0))
    # ONE rate table, sourced from lip_sync (env-configurable, defaults = fal's REAL invoice rates).
    # This model used to keep its own copy with veed at $0.07/s — 7x high — which inflated the office.
    try:
        from ..services.lip_sync import FAL_LIPSYNC_PER_MIN as _PM
    except Exception:
        _PM = {"kling": 0.168, "falsync": 0.70, "veed": 0.60}
    per_min = {"sync": _PM.get("falsync", 0.70), "fal": _PM.get("veed", 0.60), **_PM}
    if provider == "kling":                               # billed in WHOLE 5s blocks
        return round(math.ceil(s / 5.0) * (_PM.get("kling", 0.168) * 5.0 / 60.0), 4)
    if provider in ("latentsync", "wav2lip"):             # Replicate — per-render flat
        return {"latentsync": 0.088, "wav2lip": 0.03}[provider]
    return round(s / 60.0 * per_min.get(provider, 0.70), 4)


# Kie Seedance OFFICIAL per-second rates by resolution → (with-input, text-only). ONE source of truth
# for both the pre-flight cost gate and the post-render cost record.
_KIE_RATE_PER_SEC = {"480p": (0.0575, 0.095), "720p": (0.125, 0.205),
                     "1080p": (0.31, 0.51), "4k": (0.64, 1.04)}


def _t2v_projected_usd(resolution: str, with_input: bool, seconds: float) -> float:
    """Projected Kie-Seedance spend for `seconds` of text-to-video at `resolution`."""
    _rr = _KIE_RATE_PER_SEC.get(str(resolution).lower(), _KIE_RATE_PER_SEC["720p"])
    return round((_rr[0] if with_input else _rr[1]) * max(0.0, float(seconds or 0)), 4)


def _gate_job_cost(request_id: str, what: str, projected_usd: float, assets: dict = None) -> None:
    """ALWAYS report the projected spend (log + Team Room finance feed) BEFORE any money is spent.
    Above CONFIRM_JOB_USD, stop and ask the user instead of silently spending: the job fails fast
    with a structured COST_CONFIRM_REQUIRED error that the UI turns into a
    'this will cost ~$X — proceed?' prompt. Confirming re-runs with cost_confirmed=true.
    Nothing is refused outright — the user decides. Applies to EVERY paid lane (t2v, lip-sync,
    voice-only) since every caller routes through here."""
    logger.info(f"[cost] {request_id} {what}: projected ~${projected_usd:.4f}")
    try:
        from ..services import creative_team_activity as _act
        _ts = _act.start("finance", request_id, "projecting spend")
        _act.finish("finance", request_id, _ts,
                    detail=f"projected ~${projected_usd:.2f} · {what}")
    except Exception:
        pass   # reporting must never affect the job
    if projected_usd > CONFIRM_JOB_USD and not (assets or {}).get("cost_confirmed"):
        raise RuntimeError(
            f"COST_CONFIRM_REQUIRED|{projected_usd:.2f}|{what} — this generation is projected to "
            f"cost about ${projected_usd:.2f}, over the ${CONFIRM_JOB_USD:.2f} confirmation "
            f"threshold. Nothing has been spent. Confirm to go ahead.")

# The current regen request_id, so low-level Gemini helpers can attribute their token spend to the
# right job WITHOUT threading request_id through every call site. Set at each recipe's entry.
_CURRENT_RID = contextvars.ContextVar("regen_request_id", default=None)


def _track_gemini_cost(data: dict, step: str):
    """Best-effort: read usageMetadata off a Gemini response and log its token cost against the
    current request (contextvar). Prices via the central Pricing class (the ONE rate source) so the
    reasoning/vision spend uses the same authoritative, env-overridable rates as everything else —
    NOT a hand-typed number. No-op if usage is absent or no request is in context. Never raises."""
    try:
        rid = _CURRENT_RID.get()
        if not rid:
            return
        u = (data or {}).get("usageMetadata") or {}
        pt = int(u.get("promptTokenCount") or 0)
        ct = int(u.get("candidatesTokenCount") or 0)
        if not (pt or ct):
            return
        from ..services.pricing import Pricing
        cost = Pricing.text(input_tokens=pt, output_tokens=ct, model=GEMINI_MODEL)
        _track_cost(rid, step, "gemini", model=GEMINI_MODEL, units=pt + ct, unit_type="tokens",
                    cost_usd=cost, note=f"{pt}in+{ct}out")
    except Exception:
        pass
AE_PUBLIC_URL = os.getenv("AE_PUBLIC_URL", "https://affiliate-engine-pl4p.onrender.com")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── media helpers ─────────────────────────────────────────────────────────────
def _extract_frames(video: str, times: list, outdir: str) -> list:
    """Extract a few JPEG frames at the given timestamps (for vision analysis)."""
    paths = []
    for i, t in enumerate(times):
        p = os.path.join(outdir, f"vf_{i}.jpg")
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", video,
                            "-frames:v", "1", "-vf", "scale=360:-1", p],
                           check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if os.path.isfile(p):
                paths.append(p)
        except Exception:
            pass
    return paths


def _frame_to_public_url(video_path: str, t: float = 1.0) -> Optional[str]:
    """Extract one frame and serve it from the engine's public /uploads so a generation
    provider (Kie/Seedance) can fetch it as an @Image1 identity reference. Returns URL or None."""
    try:
        import uuid as _uuid
        name = f"ref_{_uuid.uuid4().hex[:8]}.jpg"
        out = os.path.join(UPLOAD_DIR, name)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", video_path,
                        "-frames:v", "1", "-vf", "scale=720:-1", out],
                       check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if os.path.isfile(out):
            return f"{AE_PUBLIC_URL}/api/v1/uploads/{name}"
    except Exception as e:
        logger.warning(f"_frame_to_public_url failed: {e}")
    return None


def _speech_end_sec(path: str) -> Optional[float]:
    """#4 End of the last speech in a clip (= start of the trailing silence), via ffmpeg silencedetect.
    Used to trim the frozen/silent tail off a NON-final clip so clips butt-join cleanly instead of
    showing the character standing idle for ~1s at each cut. CONSERVATIVE: only reports a trim point
    when there's a clear ≥0.4s silence running to the very end, and keeps a 0.2s margin so the last
    word is never clipped. Returns None (keep the full clip) on anything ambiguous."""
    try:
        import re as _re
        p = subprocess.run(["ffmpeg", "-i", path, "-af", "silencedetect=noise=-40dB:d=0.4", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=60)
        dur = _ffprobe_duration(path) or 0.0
        starts = [float(m) for m in _re.findall(r"silence_start:\s*([0-9.]+)", p.stderr)]
        ends = [float(m) for m in _re.findall(r"silence_end:\s*([0-9.]+)", p.stderr)]
        if starts and dur:
            last_start = starts[-1]
            # trailing silence = the final silence_start has no silence_end after it (runs to EOF)
            if (not ends or ends[-1] < last_start) and (dur - last_start) >= 0.4:
                return round(min(dur, last_start + 0.2), 2)   # keep 0.2s so the last word lands fully
    except Exception as e:
        logger.warning(f"_speech_end_sec failed: {e}")
    return None


async def _select_references(video_path: str, work: str, offer_desc: str) -> list:
    """Vision-pick the BEST identity + product/proof frames from a video and serve them from
    the public /uploads dir as @Image references. This is what makes winner-clones look right —
    a clean face + the product/offer, not a random timestamp. Returns a list of public URLs."""
    import uuid as _uuid, shutil
    dur = await asyncio.to_thread(_ffprobe_duration, video_path)
    d = dur or 8.0
    times = [max(0.2, d * f) for f in (0.05, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9)]
    frames = await asyncio.to_thread(_extract_frames, video_path, times, work)
    if not frames:
        return []
    idxs = []
    try:
        r = await _gemini_vision(frames,
            f'These are numbered frames (0-indexed, in order) from a video ad for: "{offer_desc[:200]}". '
            'Choose the SINGLE best frame that clearly shows the main spokesperson/person FACE '
            '(sharp, front-facing — for an identity reference), and the SINGLE best frame showing '
            'the PRODUCT / offer / proof (a document, product, result, or key visual). '
            'Return STRICT JSON {"person_idx": <int or -1>, "product_idx": <int or -1>}.')
        for k in ("person_idx", "product_idx"):
            v = r.get(k)
            if isinstance(v, int) and 0 <= v < len(frames):
                idxs.append(v)
    except Exception as e:
        logger.warning(f"reference selection vision failed: {e}")
    if not idxs:
        idxs = [len(frames) // 3]  # sensible fallback
    urls = []
    for i in list(dict.fromkeys(idxs)):   # dedup, keep order
        name = f"ref_{_uuid.uuid4().hex[:8]}.jpg"
        try:
            shutil.copy(frames[i], os.path.join(UPLOAD_DIR, name))
            urls.append(f"{AE_PUBLIC_URL}/api/v1/uploads/{name}")
        except Exception:
            continue
    logger.info(f"selected {len(urls)} reference frames")
    return urls


async def _prep_winner_clip(winner_url: str, work: str, max_sec: int = 12) -> str:
    """Download a winner ad, SCRUB its burned captions (so Seedance won't mimic/garble them),
    trim to <=max_sec + downscale (Seedance caps reference video at 15s/50MB), re-serve from
    /uploads. Returns the prepared URL, or the raw url on failure."""
    import uuid as _uuid
    try:
        wp = await _download_to_temp(winner_url)
        dur = await asyncio.to_thread(_ffprobe_duration, wp)
        W, H = await asyncio.to_thread(_ffprobe_dims, wp)
        # detect + blur the winner's burned captions so the reference is text-free
        wframes = await asyncio.to_thread(_extract_frames, wp,
                    [0.5, max(0.6, (dur or 6) * 0.5), max(1.0, (dur or 6) * 0.85)], work)
        delogo = _delogo_chain(await _detect_caption_boxes(wframes), W, H)
        name = f"win_{_uuid.uuid4().hex[:8]}.mp4"
        out = os.path.join(UPLOAD_DIR, name)
        await asyncio.to_thread(_ffmpeg,
            ["-i", wp, "-t", str(min(max_sec, int(dur) if dur else max_sec)),
             "-vf", f"{delogo}scale=480:-2", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", out])
        try: os.remove(wp)
        except OSError: pass
        if not os.path.isfile(out) or os.path.getsize(out) < 1000:
            raise RuntimeError("trimmed winner clip empty")
        return f"{AE_PUBLIC_URL}/api/v1/uploads/{name}"
    except Exception as e:
        # Do NOT fall back to the raw winner url — it may be >15s/>50MB and Seedance will 422.
        logger.warning(f"winner clip prep failed ({e}); skipping winner video reference")
        return None


async def _openai_vision(frame_paths: list, prompt: str) -> dict:
    """OpenAI GPT-4o(-mini) vision fallback for _gemini_vision (same STRICT-JSON contract)."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    if not frame_paths:
        raise RuntimeError("no frames to analyze")
    def _call() -> str:
        from openai import OpenAI
        oai = OpenAI(api_key=settings.openai_api_key)
        content = [{"type": "text", "text": prompt}]
        for fp in frame_paths:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        resp = oai.chat.completions.create(
            model="gpt-4o-mini", temperature=0.2,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": content}])
        return resp.choices[0].message.content or "{}"
    return json.loads(await asyncio.to_thread(_call))


async def _gemini_vision(frame_paths: list, prompt: str) -> dict:
    """Vision → STRICT JSON. Gemini first, with an OpenAI GPT-4o-mini vision fallback so a Gemini outage /
    missing key / quota / 5xx doesn't leave EVERY render flagged UNVERIFIED (the recurring 'vision QA
    unavailable' failure). Raises only if BOTH providers fail."""
    try:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")
        parts = [{"text": prompt}]
        for fp in frame_paths:
            with open(fp, "rb") as f:
                parts.append({"inline_data": {"mime_type": "image/jpeg",
                                              "data": base64.b64encode(f.read()).decode()}})
        body = {"contents": [{"parts": parts}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={settings.gemini_api_key}"
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(url, json=body)
            r.raise_for_status()
            data = r.json()
        _track_gemini_cost(data, "vision")
        return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as ge:
        try:
            result = await _openai_vision(frame_paths, prompt)
            logger.warning(f"_gemini_vision: Gemini failed ({ge}) — used OpenAI vision fallback")
            return result
        except Exception as oe:
            logger.error(f"_gemini_vision: Gemini ({ge}) and OpenAI vision ({oe}) both failed")
            raise ge


# ── Clean state-map hook renderer (caption-free, correct geo) ─────────────────
US_BBOX = (-125.0, 24.0, -66.5, 49.5)  # lon_min, lat_min, lon_max, lat_max (continental)
_MAP_SKIP = {"Alaska", "Hawaii", "Puerto Rico"}
STATE_ABBR = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATES_GEO = None

def _load_states():
    global _STATES_GEO
    if _STATES_GEO is None:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "us_states.geojson")
        with open(p) as f:
            _STATES_GEO = json.load(f)
    return _STATES_GEO

def _detect_state(text: str):
    """Find a US state (abbr or full name) in a filename/transcript token stream."""
    up = (text or "").upper()
    toks = set(t for t in up.replace("-", " ").replace("_", " ").replace(".", " ").split() if t)
    for ab in STATE_ABBR:
        if ab in toks:
            return ab
    for ab, full in STATE_ABBR.items():
        if full.upper() in up:
            return ab
    return None

def _state_feature(name, data):
    for f in data["features"]:
        if str(f["properties"].get("name", "")).lower() == str(name).lower():
            return f
    return None

def _rings(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "Polygon":
        return [c[0]]
    if t == "MultiPolygon":
        return [poly[0] for poly in c]
    return []

def _render_state_map(state: str, W: int, H: int, out_path: str, fill_frac: float = 0.5) -> bool:
    """Render a clean US map CENTERED on the target state (highlighted red, undistorted,
    caption-free). Returns False if the state can't be found."""
    import math
    from PIL import Image, ImageDraw, ImageFont
    name = STATE_ABBR.get((state or "").upper(), state)
    data = _load_states()
    tf = _state_feature(name, data)
    if not tf:
        return False

    tpts = [(lon, lat) for r in _rings(tf["geometry"]) for lon, lat in r]
    los = [p[0] for p in tpts]; las = [p[1] for p in tpts]
    clon = (min(los) + max(los)) / 2; clat = (min(las) + max(las)) / 2
    dlon = max(los) - min(los); dlat = max(las) - min(las)
    cosl = math.cos(math.radians(clat)) or 1.0
    dpp = max(dlon * cosl / (fill_frac * W), dlat / (fill_frac * H)) or 1e-6  # degrees/pixel

    def proj(lon, lat):
        return (W / 2 + (lon - clon) * cosl / dpp, H / 2 - (lat - clat) / dpp)

    img = Image.new("RGB", (W, H), (236, 240, 245))
    d = ImageDraw.Draw(img)
    for f in data["features"]:
        nm = f["properties"].get("name", "")
        if nm in _MAP_SKIP:
            continue
        is_t = str(nm).lower() == str(name).lower()
        fill = (214, 40, 40) if is_t else (178, 194, 210)
        for ring in _rings(f["geometry"]):
            pts = [proj(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                d.polygon(pts, fill=fill, outline=(255, 255, 255))

    # Label the highlighted state (our own clean label — not a donor caption)
    try:
        fs = max(26, W // 22)
        font = None
        for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                  "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
            if os.path.exists(p):
                font = ImageFont.truetype(p, fs); break
        if font is None:
            font = ImageFont.load_default()
        label = str(name).upper()
        px, py = proj(clon, clat)
        b = d.textbbox((0, 0), label, font=font); tw, th = b[2] - b[0], b[3] - b[1]
        lx, ly = int(px - tw / 2), int(py - th / 2)
        pad = int(fs * 0.3)
        d.rounded_rectangle([lx - pad, ly - pad, lx + tw + pad, ly + th + pad],
                            radius=int(fs * 0.25), fill=(255, 255, 255, 230))
        d.text((lx, ly), label, font=font, fill=(20, 20, 20))
    except Exception:
        pass
    img.save(out_path)
    return True


async def _detect_caption_boxes(frame_paths: list) -> list:
    """Vision-detect burned-in caption/overlay TEXT regions (any position) as normalized
    {x,y,w,h} boxes, so they can be masked out before reuse."""
    if not frame_paths:
        return []
    try:
        r = await _gemini_vision(frame_paths,
            'These frames are from a video ad. Find EVERY burned-in caption / subtitle / overlay '
            'TEXT region (text added on top of the video, NOT text that is part of the real scene). '
            'Return STRICT JSON {"boxes":[{"x":<left 0-1>,"y":<top 0-1>,"w":<width 0-1>,"h":<height 0-1>}]} '
            'as fractions of the frame. Pad each box ~4%. Return {"boxes":[]} if there is no overlay text.')
        return [b for b in (r.get("boxes") or []) if all(k in b for k in ("x", "y", "w", "h"))]
    except Exception as e:
        # FAIL SAFE, not fail open. Returning [] on an ERROR meant "this clip has no burned-in
        # captions", so a library clip's ORIGINAL captions survived underneath the new ones — two
        # contradicting caption tracks on screen. A detector ERROR is not evidence of a clean clip:
        # mask the bottom third (where burned captions almost always sit) so ours is the only text.
        # NOTE: a genuine {"boxes":[]} response still returns [] above — this is the error path only.
        logger.error(f"caption-box detect FAILED ({e}) — masking the bottom third as a safety net "
                     f"(cannot confirm the clip is caption-free)")
        return [{"x": 0.0, "y": 0.66, "w": 1.0, "h": 0.30}]


async def _asset_is_relevant(frame_paths: list, offer_desc: str) -> bool:
    """On-offer relevance gate. Vision-checks a candidate visual against the actual
    product/offer and REJECTS loose-keyword mismatches (the 'leaf-blower on a
    weight-loss ad' failure). Fails open (allow) only if the check itself errors."""
    if not frame_paths or not offer_desc:
        return True
    try:
        r = await _gemini_vision(frame_paths,
            f'This image is a candidate opening visual for a video ad whose product/offer is: '
            f'"{offer_desc[:300]}". Would a professional media buyer accept this visual as clearly '
            'ON-TOPIC and on-brand for THAT specific offer (not generic or unrelated)? '
            'Be strict — reject anything a buyer would call irrelevant. '
            'Return STRICT JSON {"relevant": true|false, "why": "<=6 words"}.')
        ok = bool(r.get("relevant", True))
        if not ok:
            logger.info(f"relevance gate REJECTED asset: {r.get('why')}")
        return ok
    except Exception as e:
        logger.warning(f"relevance check failed (allowing): {e}")
        return True


async def _generate_clip(offer_desc: str, shot_type: str = "b_roll", duration: int = 6,
                         model: Optional[str] = None, reference_video_urls: Optional[list] = None,
                         reference_image_urls: Optional[list] = None, winner_hook: Optional[str] = None,
                         vertical: Optional[str] = None, request_type: str = "ugc") -> Optional[str]:
    """Generate a CONVERSION-FIRST clip.

    WINNER-CLONE mode (preferred, when a winning reference VIDEO is supplied): recreate a
    proven winning ad's hook/pacing/structure for THIS offer, keeping the real spokesperson/
    product (@Image1). This is what a media buyer actually does — clone a winner, swap the
    offer/person — not "generate a nice scene". Requires Seedance (reference-to-video).

    SCENE mode (last-resort fallback, no winner): a plain on-offer B-roll scene.
    Returns a local mp4 path or None. Costs real generation credits (intentional)."""
    _generate_clip.last_error = ""
    cloning = bool(reference_video_urls)
    # cloning needs a reference-to-video capable model → route by capability (user pick wins)
    if cloning:
        model = MultiProviderVideoService.route_capability("reference_to_video", model)
    seedance = bool(model and "seedance" in model.lower())
    # Realism Prompt Engine: anti-slop, front-loaded, one-action, entity-consistent, per-model.
    from ..services import realism_prompt_engine as rpe
    nimg = len(reference_image_urls or [])
    try:
        if cloning:
            prompt = rpe.build_winner_clone_prompt(
                model=(model or "seedance-2"), offer_desc=offer_desc, winner_hook=(winner_hook or ""),
                vertical=(vertical or ""), n_reference_images=nimg, request_type=request_type)
        else:
            prompt = rpe.build_prompt(
                model=(model or "higgsfield-v1"), request_type=request_type,
                action=f"a real-world scene that sells this offer: {offer_desc[:200]}",
                environment="authentic lived-in real-world setting relevant to the offer",
                vertical=(vertical or ""),
                n_reference_images=nimg, has_reference_video=bool(reference_video_urls))
    except Exception as e:
        logger.warning(f"realism prompt build failed, using offer_desc: {e}")
        prompt = offer_desc[:500]
    try:
        result = await asyncio.to_thread(
            MultiProviderVideoService.generate,
            prompt=prompt, shot_type=shot_type, duration=duration,
            preferred_model=(model or MultiProviderVideoService.route_capability("b_roll")),
            reference_video_urls=(reference_video_urls if seedance else None),
            reference_image_urls=(reference_image_urls if seedance else None),
            s3_prefix="regen")
    except Exception as e:
        logger.warning(f"generative clip failed: {e}")
        _generate_clip.last_error = f"{type(e).__name__}: {str(e)[:180]}"   # surfaced to the recipe
        return None
    if not result:
        return None
    # async path (Google Veo) → poll; sync providers (Higgsfield/Kie) return a local path
    if result.get("async"):
        from ..services.video_creator import VideoCreatorService
        op = result.get("operation_name")
        for _ in range(60):
            await asyncio.sleep(8)
            st = await asyncio.to_thread(VideoCreatorService.check_status, op)
            if st.get("done"):
                vp = st.get("video_path")
                if vp and os.path.exists(vp):
                    return vp
                du = st.get("download_url")
                return await _download_to_temp(du) if du and du.startswith("http") else None
        return None
    vp = result.get("video_path")
    if vp and os.path.exists(vp):
        return vp
    du = result.get("download_url") or ""
    if du.startswith("http"):
        return await _download_to_temp(du)
    if du.startswith("/"):
        return await _download_to_temp(f"{AE_PUBLIC_URL}{du}")
    return None


def _boxes_area(boxes: list) -> float:
    """Total normalized area covered by detected caption boxes (0-1)."""
    tot = 0.0
    for b in boxes or []:
        try:
            tot += max(0.0, float(b["w"])) * max(0.0, float(b["h"]))
        except Exception:
            continue
    return tot


def _pick_caption_y(boxes: list, est_h: float = 0.22) -> float:
    """Choose a vertical position (as a fraction of H) for a NEW caption that does NOT
    overlap the base video's existing burned-in captions. Tries lower-third, then top,
    then mid. This is the fix for the double-caption clash."""
    occ = []
    for b in boxes or []:
        try:
            y = float(b["y"]); occ.append((y, y + float(b["h"])))
        except Exception:
            continue
    def clear(y0):
        y1 = y0 + est_h
        return all(y1 <= a or y0 >= b for a, b in occ)
    for cand in (0.66, 0.06, 0.40):
        if clear(cand):
            return cand
    return 0.06  # top least likely to clash with the usual lower-third captions


async def _download_to_temp(url: str, suffix: str = ".mp4") -> str:
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
        r = await c.get(url); r.raise_for_status(); data = r.content
    fd, path = tempfile.mkstemp(suffix=suffix); os.close(fd)
    with open(path, "wb") as f:
        f.write(data)
    return path

async def _transcribe_file(path: str) -> str:
    from ..services.transcription_service import TranscriptionService
    # Whisper API caps uploads at 25MB; a full video easily exceeds that. Extract
    # compact mono audio first (a few hundred KB even for long ads).
    fd, apath = tempfile.mkstemp(suffix=".mp3"); os.close(fd)
    try:
        await asyncio.to_thread(_ffmpeg, ["-i", path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", apath])
        res = await TranscriptionService().transcribe_audio(apath, provider="openai")
        return (res or {}).get("transcription") or (res or {}).get("text") or ""
    finally:
        try: os.remove(apath)
        except OSError: pass

def _clean_ref_wav(raw_path: str, out_wav: str, lo: float = 6.0, hi: float = 11.0) -> str:
    """Extract a CLEAN F5-TTS reference: mono 24k, STARTING at the first speech onset and ENDING on a
    natural silence in [lo,hi]s — never the old hard mid-word `-t 15` cut. THAT is the root of the
    repeated-word echo: a long, mid-word reference makes f5 re-prime on the ref and inject a reference
    word at every sentence boundary. A clean, phrase-bounded ~6-11s ref lets f5 separate ref from gen.
    Falls back to a <=hi hard cut. Synchronous; returns out_wav."""
    buf = out_wav + ".buf.wav"
    _ffmpeg(["-i", raw_path, "-vn", "-ac", "1", "-ar", "24000", "-t", f"{hi + 2.0:.1f}", buf], 120)
    start, end = 0.0, hi
    try:
        p = subprocess.run(["ffmpeg", "-i", buf, "-af", "silencedetect=noise=-32dB:d=0.15", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=60)
        s_starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", p.stderr)]
        s_ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", p.stderr)]
        for e in s_ends:                       # skip any leading silence → start on the first word
            if e <= 1.5:
                start = e
        cand = [s for s in s_starts if lo <= s <= hi and s > start + 3.0]   # end on a real phrase boundary
        if cand:
            end = cand[-1]
    except Exception:
        pass
    _ffmpeg(["-ss", f"{start:.2f}", "-i", buf, "-t", f"{max(3.0, end - start):.2f}",
             "-ac", "1", "-ar", "24000", out_wav], 120)
    try:
        os.remove(buf)
    except OSError:
        pass
    return out_wav


async def _audio_matches_script(audio_path: str, script: str):
    """Clone-QA: transcribe synthesized audio and compare to the intended script. Returns (ok, reason).
    Garbled when token overlap is low (< 0.65) OR a dollar amount / number in the script did not survive
    in the audio. Best-effort — any error returns (True, ...) so the caller keeps the original audio."""
    try:
        heard = (await _transcribe_file(audio_path) or "").lower()
        want = (script or "").lower()
        if not heard or not want:
            return True, "qa: empty transcript"
        _tok = lambda s: [w for w in re.findall(r"[a-z0-9$%.]+", s) if any(c.isalnum() for c in w)]
        wt = _tok(want)
        ht = set(_tok(heard))
        if not wt:
            return True, "qa: no tokens"
        overlap = sum(1 for w in wt if w in ht) / len(wt)
        if overlap < 0.65:
            return False, f"low similarity {overlap:.2f}"
        # NUMBERS/PRICES must survive. Only enforce when BOTH sides used digit form (if the model spelled
        # a number out — "twenty nine" — there's nothing to compare, so we don't false-flag it).
        _norm = lambda n: re.sub(r"[^0-9.]", "", n).strip(".")
        NUMPAT = r"\$?\d[\d,]*(?:\.\d+)?%?"
        want_nums = {x for x in (_norm(n) for n in re.findall(NUMPAT, want)) if x}
        heard_nums = {x for x in (_norm(n) for n in re.findall(NUMPAT, heard)) if x}
        if want_nums and heard_nums:
            missing = [n for n in want_nums if n not in heard_nums]
            if missing:
                return False, f"number(s) not spoken: {missing[:3]}"
        return True, f"ok {overlap:.2f}"
    except Exception as e:
        return True, f"qa error: {e}"

def _ffprobe_dims(path: str):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
        capture_output=True, text=True, timeout=60).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)

def _ffprobe_duration(path: str) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=noprint_wrappers=1:nokey=1", path],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except Exception:
        return 0.0

def _stream_duration(path: str, kind: str = "v") -> float:
    """Duration of a SPECIFIC stream (kind='v' video | 'a' audio) in seconds, 0.0 if unknown.
    format=duration reports only the LONGEST stream, so it cannot tell a short video from a longer
    audio — this reads the per-stream duration so a video that ends before the narration is caught."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"{kind}:0",
                              "-show_entries", "stream=duration",
                              "-of", "default=noprint_wrappers=1:nokey=1", path],
                             capture_output=True, text=True, timeout=60).stdout.strip().splitlines()
        return float(out[0]) if out and out[0] not in ("", "N/A") else 0.0
    except Exception:
        return 0.0

def _speech_end_ts(path: str, video_end: float) -> Optional[float]:
    """Timestamp where the FINAL trailing silence begins (i.e. the last spoken word ends), or None if
    the audio runs sound-to-end (no trailing dead-air). Uses ffmpeg `silencedetect` (noise=-35dB, d=0.6)
    and finds the LAST non-silent moment. Robust to ffmpeg builds that emit a silence_end at EOF: a
    silence only counts as 'trailing' when it extends to within 0.35s of the clip end (or has no matching
    end at all). Best-effort — returns None on any error so the caller keeps the original clip."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-af", "silencedetect=noise=-35dB:d=0.6", "-f", "null", "-"],
            capture_output=True, text=True, timeout=180)
        log = (proc.stderr or "") + (proc.stdout or "")
        starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", log)]
        ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", log)]
        if not starts:
            return None
        # trailing silence only if the LAST detected silence runs to (near) the clip end:
        #   • more starts than ends → a dangling silence_start ran to EOF, or
        #   • the last silence_end lands within 0.35s of the clip end (EOF-flushed silence).
        runs_to_eof = len(starts) > len(ends)
        if not runs_to_eof and ends and video_end:
            runs_to_eof = (video_end - ends[-1]) <= 0.35
        return starts[-1] if runs_to_eof else None
    except Exception:
        return None

def _probe_audio(path: str):
    """DETERMINISTIC tri-state: True (has an audio stream) / False (definitely none) / None (probe
    failed — unknown). A vision/frame critic literally cannot hear, so 'the fallback shipped silent
    video' is invisible to it — this ffprobe is the correct check. Returning None on error (instead
    of a blind True) lets the caller fall back to the CAPABILITY matrix rather than mislabel a silent
    clip as narrated. Retries once before giving up."""
    for _ in range(2):
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                                  "stream=codec_type", "-of", "default=noprint_wrappers=1:nokey=1", path],
                                 capture_output=True, text=True, timeout=30).stdout.strip()
            return "audio" in out
        except Exception:
            continue
    return None

def _ffmpeg(args, timeout: int = 600):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                   check=True, timeout=timeout,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def _make_caption_png(text: str, W: int, H: int, out_path: str, y_frac: float = 0.66):
    """Render a centered, wrapped caption (white text on a dark rounded box) as a
    transparent PNG. y_frac sets the vertical position so callers can place it clear
    of the base video's existing captions."""
    from PIL import Image, ImageDraw, ImageFont
    text = (text or "").strip().upper()
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fs = max(30, W // 15)
    font = None
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
        if os.path.exists(p):
            font = ImageFont.truetype(p, fs); break
    if font is None:
        font = ImageFont.load_default()
    # word-wrap to ~86% width
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textbbox((0, 0), t, font=font)[2] <= W * 0.86:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    lines = lines[:3] or ["WATCH THIS"]
    line_h = int(fs * 1.3)
    total_h = line_h * len(lines)
    y0 = int(H * max(0.04, min(y_frac, 0.80)))
    pad = int(fs * 0.45)
    box_w = max(d.textbbox((0, 0), l, font=font)[2] for l in lines) + pad * 2
    x0 = (W - box_w) // 2
    d.rounded_rectangle([x0, y0 - pad, x0 + box_w, y0 + total_h + pad],
                        radius=int(fs * 0.3), fill=(0, 0, 0, 180))
    for i, l in enumerate(lines):
        lw = d.textbbox((0, 0), l, font=font)[2]
        d.text(((W - lw) // 2, y0 + i * line_h), l, font=font, fill=(255, 255, 255, 255))
    img.save(out_path)
# Shared service key — only callers that know it (i.e. creative-library) may trigger work.
SERVICE_KEY = os.getenv("REGEN_SERVICE_KEY", "change-me-regen-service-key")


def require_service_key(x_service_key: str = Header(default="")):
    if x_service_key != SERVICE_KEY:
        raise HTTPException(status_code=403, detail="invalid service key")
    return True

VARIATION_TYPES = [
    "Caption Change Only", "Hook Change Only", "Reclean/Minor Mod", "Script",
    "Broll", "Stock Video", "Avatar/UGC", "Avatar Lipsync", "map + ugc", "Image",
    "Image + Voiceover", "Special Request",
]


# ── Models ────────────────────────────────────────────────────────────────────
class InterpretRequest(BaseModel):
    context: dict
    expectation: str = ""
    variation_type: Optional[str] = None


class RunRequest(BaseModel):
    request_id: str
    context: dict
    variation_type: Optional[str] = None
    expectation: str = ""
    directive: dict = {}
    preserve: list = []
    variant_count: int = 3
    model: Optional[str] = None      # user-chosen generation model (overrides default routing)
    phase: Optional[str] = None
    node: Optional[str] = None
    callback_url: Optional[str] = None
    active_url: Optional[str] = None
    assets: dict = {}                # "Create from Assets": {image_urls:[], script, do_voiceover}


class CreativeTeamRequest(BaseModel):
    offer_desc: str
    job_id: Optional[str] = None
    vertical: str = ""
    request_type: str = "ugc"
    model: str = "seedance-2"
    loser_transcript: str = ""
    winner_hook: str = ""
    winner_transcript: str = ""
    has_real_character: bool = False
    has_winner_video: bool = False


class Cancelled(Exception):
    """Raised when the user cancelled the job; stops before spending more credits."""


async def _still_active(req: "RunRequest") -> bool:
    """Ask creative-library whether this request is still active. Fail-open on
    transient errors (don't abort a good job over a flaky check)."""
    if not getattr(req, "active_url", None):
        return True
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(req.active_url, headers={"x-regen-secret": CALLBACK_SECRET})
            return bool(r.json().get("active", True))
    except Exception:
        return True


async def _abort_if_cancelled(req: "RunRequest", where: str):
    if not await _still_active(req):
        raise Cancelled(f"cancelled before {where}")


# ── Gemini intent interpreter ─────────────────────────────────────────────────
def _interpret_prompt(context: dict, expectation: str, variation_type: Optional[str]) -> str:
    return f"""You are the intent interpreter for an ad-creative regeneration engine.
Convert the user's free-text expectation into a STRICT JSON directive the pipeline can execute.
Do NOT invent product claims (testimonials, guarantees, stats) that aren't in the offer — flag them instead.

AVAILABLE VARIATION TYPES: {VARIATION_TYPES}

CONTEXT (attached automatically):
{json.dumps(context, indent=2)}

USER-SELECTED TYPE (may be null — you may override with reason): {variation_type}

USER FREE-TEXT EXPECTATION:
"{expectation}"

Return ONLY JSON:
{{
  "chosen_variation_type": "<one of AVAILABLE VARIATION TYPES>",
  "recipe_steps": ["<ordered existing features>"],
  "target_segment": "<hook|body|cta|whole>",
  "preserve": ["spokesperson"|"voice"|"script"|"style"|"captions"],
  "asset_directive": "<what visual/source to use, referencing context assets>",
  "tone_directive": "<emotional tone>",
  "script_directive": "<copy/script change or 'none'>",
  "variant_count": <int>,
  "conflicts_or_clarifications": ["<questions only if genuinely ambiguous/risky>"],
  "rationale": "<1 sentence tying choice to the user's words + the diagnosis>"
}}"""


async def _openai_json(prompt: str) -> dict:
    """OpenAI strict-JSON fallback for _gemini_json (same JSON contract)."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    def _call() -> str:
        from openai import OpenAI
        oai = OpenAI(api_key=settings.openai_api_key)
        resp = oai.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or "{}"
    return json.loads(await asyncio.to_thread(_call))


async def _gemini_json(prompt: str) -> dict:
    """Gemini → strict JSON, with an OpenAI fallback so a Gemini outage / quota /
    401 / 429 / 5xx doesn't sink the recipe that calls it. Raises only if BOTH fail."""
    try:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={settings.gemini_api_key}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(url, json=body)
            r.raise_for_status()
            data = r.json()
        _track_gemini_cost(data, "reasoning")
        txt = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(txt)
    except Exception as ge:
        try:
            result = await _openai_json(prompt)
            logger.warning(f"_gemini_json: Gemini failed ({ge}) — used OpenAI fallback")
            return result
        except Exception as oe:
            logger.error(f"_gemini_json: Gemini ({ge}) and OpenAI fallback ({oe}) both failed")
            raise ge


@router.post("/seedance-test")
async def seedance_test(
    prompt: str = Form(...),
    resolution: str = Form("480p"),
    aspect_ratio: str = Form("9:16"),
    duration: int = Form(8),
    generate_audio: bool = Form(True),
    images: list[UploadFile] = File(default=[]),
    reference_video_url: str = Form(""),
    _auth: bool = Depends(require_service_key),
):
    """ISOLATED pure-Seedance test — no recipe, no stitch. Saves uploaded reference images to
    the public /uploads dir, then calls Kie Seedance exactly per the docs. Returns the taskId;
    poll GET /seedance-test/{taskId} for the raw result URL."""
    import uuid as _uuid
    ref_img_urls = []
    for up in (images or []):
        ext = os.path.splitext(up.filename or "")[1].lower() or ".png"
        name = f"seedref_{_uuid.uuid4().hex[:8]}{ext}"
        dest = os.path.join(UPLOAD_DIR, name)
        with open(dest, "wb") as f:
            f.write(await up.read())
        ref_img_urls.append(f"{AE_PUBLIC_URL}/api/v1/uploads/{name}")

    inp = {
        "prompt": prompt, "duration": int(duration), "resolution": resolution,
        "aspect_ratio": aspect_ratio, "generate_audio": bool(generate_audio), "nsfw_checker": False,
    }
    if ref_img_urls:
        inp["reference_image_urls"] = ref_img_urls
    if reference_video_url:
        inp["reference_video_urls"] = [reference_video_url]

    r = httpx.post("https://api.kie.ai/api/v1/jobs/createTask",
                   headers={"Authorization": f"Bearer {settings.kie_api_key}", "Content-Type": "application/json"},
                   json={"model": "bytedance/seedance-2", "input": inp}, timeout=30)
    body = r.json()
    task_id = (body.get("data") or {}).get("taskId")
    return {"success": bool(task_id), "taskId": task_id, "reference_image_urls": ref_img_urls,
            "sent_input": inp, "raw": body}


@router.get("/seedance-test/{task_id}")
async def seedance_test_status(task_id: str, _auth: bool = Depends(require_service_key)):
    """Poll the pure-Seedance test task; returns state + raw resultUrl when done."""
    r = httpx.get("https://api.kie.ai/api/v1/jobs/recordInfo", params={"taskId": task_id},
                  headers={"Authorization": f"Bearer {settings.kie_api_key}"}, timeout=20)
    d = (r.json() or {}).get("data") or {}
    result_url = None
    rj = d.get("resultJson")
    if isinstance(rj, str) and rj:
        try:
            result_url = (json.loads(rj).get("resultUrls") or [None])[0]
        except Exception:
            pass
    return {"success": True, "state": d.get("state"), "result_url": result_url,
            "failMsg": d.get("failMsg"), "costTime": d.get("costTime")}


# ── tag-asset cache ───────────────────────────────────────────────────────────
# The clip content behind an S3 key never changes, so a full ffprobe+Whisper+Gemini
# pass is paid ONCE and every later call (preview re-reads, re-generation) is a DB read.
def _s3_key_from_url(url: str) -> str:
    """Stable cache key = the S3 object (host + path) WITHOUT the presign query string.
    Presigned URLs carry X-Amz-Signature/Expires that change on every call, so keying on
    the raw url would never hit. We strip the query and key on host+path only."""
    try:
        from urllib.parse import urlsplit, unquote
        u = urlsplit(url or "")
        return unquote(f"{u.netloc}{u.path}").strip().strip("/")
    except Exception:
        return ""


def _asset_tag_get(s3_key: str):
    """Return the cached tag-asset dict for a key, or None. Never raises (a cache miss must
    never break preview or generation)."""
    if not s3_key:
        return None
    try:
        from ..database import SessionLocal
        from ..models.asset_tag import AssetTag
        db = SessionLocal()
        try:
            row = db.query(AssetTag).filter(AssetTag.s3_key == s3_key).first()
            return json.loads(row.tags_json) if row else None
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"tag-asset cache read failed: {e}")
        return None


def _asset_tag_put(s3_key: str, result: dict) -> None:
    """Upsert a tag-asset result by key. Never raises — a cache-write failure must not break
    the generation we just paid for."""
    if not s3_key or not isinstance(result, dict):
        return
    try:
        from ..database import SessionLocal
        from ..models.asset_tag import AssetTag
        payload = json.dumps(result)
        db = SessionLocal()
        try:
            row = db.query(AssetTag).filter(AssetTag.s3_key == s3_key).first()
            if row:
                row.tags_json = payload
            else:
                db.add(AssetTag(s3_key=s3_key, tags_json=payload))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"tag-asset cache write failed: {e}")


@router.post("/tag-asset")
async def tag_asset(url: str = Form(...), kind: str = Form("broll"), vertical: str = Form(""),
                    age_band: str = Form(""), gender: str = Form(""), state: str = Form(""),
                    cached_only: bool = Form(False),
                    _auth: bool = Depends(require_service_key)):
    """Index one asset: ffprobe + transcribe + vision-tag so the brain can pick the RIGHT reference.
    Folder-priors (age_band/gender/state/kind/vertical) come in as ground truth; vision confirms +
    enriches (face_score, wardrobe, setting, style, captions). Returns the full tag record.

    Cached per stable S3 key: a cache hit returns immediately (no download/transcribe/vision).
    cached_only=true makes this READ-ONLY — on a miss it returns instantly WITHOUT paying to
    compute, so the CL preview can ask for analysis only if it already exists."""
    s3_key = _s3_key_from_url(url)
    cached = _asset_tag_get(s3_key)
    if cached is not None:
        return {**cached, "cached": True}
    if cached_only:
        # preview asked for read-only: never download/transcribe/vision on a miss.
        return {"success": True, "cached": False, "num_faces": None, "url": url, "kind": kind}
    work = tempfile.mkdtemp()
    p = None
    try:
        p = await _download_to_temp(url, suffix=os.path.splitext(url.split("?")[0])[1] or ".mp4")
        dur = await asyncio.to_thread(_ffprobe_duration, p)
        try:
            W_, H_ = await asyncio.to_thread(_ffprobe_dims, p)
        except Exception:
            W_, H_ = 0, 0
        aspect = "9:16" if (H_ and W_ and H_ > W_) else ("16:9" if W_ else "")
        transcript = ""
        try:
            transcript = await _transcribe_file(p)
        except Exception as e:
            logger.warning(f"tag-asset transcribe failed: {e}")
        d = dur or 6.0
        frames = await asyncio.to_thread(_extract_frames, p, [max(0.3, d*f) for f in (0.1, 0.4, 0.7, 0.9)], work)
        tags = {}
        if frames:
            try:
                tags = await _gemini_vision(frames,
                    'These frames are from a creative-library reference clip (often B-ROLL: no talking '
                    'head — just a scene/action used to intercut over a voiceover). Tag it precisely so a '
                    'script can be matched to the RIGHT clip. Return STRICT JSON: '
                    '{"role":"talking_head|map|broll|product|proof", '
                    '"age_band":"<one of: under35|35-44|45-55|55plus, or none>", '
                    '"gender":"<male|female|none>", "ethnicity":"<short or none>", '
                    '"wardrobe":"<short or none>", '
                    '"scene":"<the SPECIFIC setting + action, <=10 words, NAME THE ACTION CONCRETELY — '
                    'e.g. \'pressure-washing a concrete driveway\', \'styling a wood dining table with '
                    'flowers\', \'excavator demolishing a house roof\', \'trimming a tall hedge\'>", '
                    '"description":"<1-2 full sentences: who/what is on screen and what happens>", '
                    '"action":"<primary action snake_case: pressure_washing|hedge_trimming|lawn_mowing|'
                    'paving|painting|tiling|demolition|digging|landscaping|decor_styling|table_setting|'
                    'cleaning|driving|walking|none>", '
                    '"indoor_outdoor":"<indoor|outdoor>", '
                    '"geo":"<US|UK|other|unknown — infer from architecture, cars, signage>", '
                    '"mood":"<satisfying|dramatic|cozy|aspirational|neutral>", '
                    '"hook":<true if an attention-grabbing oddly-satisfying or dramatic OPENER '
                    '(cleaning/transformation/demolition/build), false if a calm interior or scenic>, '
                    '"keywords":["<up to 8 salient search terms: objects, materials, setting, action>"], '
                    '"style":"<ugc_handheld|cinematic|animated|studio, or none>", '
                    '"face_score":<0.0-1.0 how clean/front-facing a single talking face is; 0 if no face>, '
                    '"num_faces":<int count of distinct human faces clearly visible in frame; 0 if none>, '
                    '"num_people":<int>, '
                    '"on_screen":"<key objects e.g. driveway, pressure washer, house, dining table, '
                    'excavator, lawn, document, phone, cash, or none>", '
                    '"emotion":"<energy/expression in 1-2 words>"}')
            except Exception as e:
                logger.warning(f"tag-asset vision failed: {e}")
        # The model occasionally returns a JSON ARRAY (e.g. one object per frame) instead of a single
        # object — coerce to the first dict so `tags.get(...)` never throws "'list' object has no
        # attribute 'get'" (which 500'd the whole ingest for that clip).
        if isinstance(tags, list):
            tags = next((t for t in tags if isinstance(t, dict)), {})
        if not isinstance(tags, dict):
            tags = {}
        has_caps = _boxes_area(await _detect_caption_boxes(frames)) > 0.03 if frames else False
        role = tags.get("role") or kind
        face = float(tags.get("face_score") or 0)
        # usable_as: a clean front-facing talker is a lip-sync avatar; else its role
        usable_as = "avatar_lipsync" if (role == "talking_head" and face >= 0.6) else role
        # reusable talking length ≈ duration when it's a talker (approx; refined by clean-seg later)
        max_talk_sec = round(dur or 0, 1) if usable_as == "avatar_lipsync" else 0
        result = {"success": True, "url": url, "kind": kind, "vertical": vertical,
                "duration": round(dur or 0, 1), "aspect": aspect, "has_captions": has_caps,
                "transcript": (transcript or "")[:1500],
                "role": role, "usable_as": usable_as, "face_score": round(face, 2),
                "age_band": age_band or tags.get("age_band") or "",
                "gender": gender or tags.get("gender") or "",
                "state": state or "", "max_talk_sec": max_talk_sec,
                "ethnicity": tags.get("ethnicity") or "", "wardrobe": tags.get("wardrobe") or "",
                "style": tags.get("style") or "", "num_people": tags.get("num_people"),
                # distinct faces in frame → CL warns when a clip has 2+ people (they'd share one
                # voice today). null when the vision model didn't return it (never fail on absence).
                "num_faces": tags.get("num_faces"),
                "character": tags.get("character") or ((f"{age_band} {gender}".strip()) or ""),
                "scene": tags.get("scene") or "", "on_screen": tags.get("on_screen") or "",
                "emotion": tags.get("emotion") or "",
                # ── rich b-roll index (for script→clip matching; additive, safe for other callers) ──
                "description": tags.get("description") or "",
                "action": tags.get("action") or "",
                "indoor_outdoor": tags.get("indoor_outdoor") or "",
                "geo": tags.get("geo") or "",
                "mood": tags.get("mood") or "",
                "hook": bool(tags.get("hook")),
                "keywords": tags.get("keywords") or []}
        _asset_tag_put(s3_key, result)   # persist so the next call (preview/re-gen) is a DB read
        return {**result, "cached": False}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {str(e)[:180]}"}
    finally:
        try:
            if p: os.remove(p)
        except OSError: pass
        import shutil; shutil.rmtree(work, ignore_errors=True)


@router.get("/winners")
async def winners(vertical: str = "", limit: int = 12, _auth: bool = Depends(require_service_key)):
    """List competitor winners (scraper library) for a vertical — playable video_url + hook +
    score. Powers the Creative Library 'Scraper Winners' section."""
    from ..services import winner_library
    if vertical and vertical != "unknown":
        wins = winner_library.fetch_winners(vertical, limit=limit)
    else:
        # "All verticals": the Creative Library default sends vertical="". fetch_winners is
        # vertical-keyed and returns [] for an empty vertical, so without this the default view
        # always showed 0 winners even when the library IS seeded. Fan out concurrently across the
        # known verticals, then merge + rank by score. Still [] if the library is genuinely
        # unseeded/unconfigured — this never fabricates winners.
        vsets = ["home_insurance", "auto_insurance", "medicare", "final_expense",
                 "bizop", "refinance", "life_insurance", "debt_relief"]
        results = await asyncio.gather(
            *[asyncio.to_thread(winner_library.fetch_winners, v, limit) for v in vsets],
            return_exceptions=True)
        seen, merged = set(), []
        for res in results:
            if isinstance(res, Exception):
                continue
            for w in res:
                u = w.get("url")
                if u and u not in seen:
                    seen.add(u); merged.append(w)
        merged.sort(key=lambda w: w.get("score") or 0, reverse=True)
        wins = merged[:limit]
    return {"success": True, "vertical": vertical, "winners": wins}


@router.get("/winner-db-test")
async def winner_db_test(vertical: str = "", _auth: bool = Depends(require_service_key)):
    """Prove the Winning Reference Library (adforge Postgres) is reachable + has winners."""
    from ..services import winner_library
    vs = [vertical] if vertical else None
    return {"success": True, **winner_library.health(vs)}


@router.get("/vmake-test")
async def vmake_test(url: str = "", _auth: bool = Depends(require_service_key)):
    """Confirm the Vmake keys (MT_AK/MT_SK) actually authenticate, and reveal the real async
    contract. Step 1 always runs: signed config.json → meta.code 0 means auth OK. If ?url= is
    given, step 2 fires one real videoscreenclear consume.json and returns its RAW response so
    the async spawn/poll shape can be finalized from fact instead of guessed."""
    from ..services import vmake_service as vm
    if not vm.is_configured():
        return {"success": False, "configured": False,
                "hint": "Set MT_AK and MT_SK on the affiliate-engine Render env, then redeploy."}
    config_env = await asyncio.to_thread(vm.get_config, "videoscreenclear")
    auth_ok = vm._ok(config_env)
    out = {"success": auth_ok, "configured": True, "auth_ok": auth_ok,
           "config_response": config_env}
    if not auth_ok:
        # keys set but rejected — run the signing matrix so we can see if ANY variant authenticates
        out["diagnostic"] = await asyncio.to_thread(vm.diag, "videoscreenclear")
    if url:
        out["consume_raw"] = await asyncio.to_thread(vm.consume, url, "videoscreenclear", "",
                                                     {"rsp_media_type": "url"})
    return out


@router.post("/upload-images")
async def upload_images(payload: dict, _auth: bool = Depends(require_service_key)):
    """Save base64 scenic images to the public /uploads dir and return their public URLs, so the
    'Create from Assets' recipe (and image-to-video providers) can fetch them. Input:
    {images:[{name, data_b64}]} → {urls:[...]}"""
    import uuid as _uuid
    urls = []
    for im in (payload.get("images") or []):
        data_b64 = im.get("data_b64") or ""
        if "," in data_b64 and data_b64.strip().startswith("data:"):
            data_b64 = data_b64.split(",", 1)[1]           # strip data URI prefix if present
        try:
            raw = base64.b64decode(data_b64)
        except Exception:
            continue
        ext = os.path.splitext(im.get("name") or "")[1].lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = ".png"
        name = f"asset_{_uuid.uuid4().hex[:8]}{ext}"
        with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
            f.write(raw)
        urls.append(f"{AE_PUBLIC_URL}/api/v1/uploads/{name}")
    return {"success": bool(urls), "urls": urls}


# ── Creative Team "office" (live feed + reports) ──────────────────────────────
@router.get("/creative-team/activity")
async def creative_team_activity(job_id: str = "", _auth: bool = Depends(require_service_key)):
    """Live office state for ONE job (the same room shows whichever job is selected): each persona's
    desk, status, current task, the feed, plus that job's progress % + ETA. Omit job_id for the most
    recent running job."""
    from ..services import creative_team_activity as act
    return {"success": True, **act.snapshot(job_id or None)}


@router.get("/creative-team/jobs")
async def creative_team_jobs(_auth: bool = Depends(require_service_key)):
    """List recent jobs with live progress % + ETA — powers the job switcher."""
    from ..services import creative_team_activity as act
    return {"success": True, "jobs": act.jobs_list()}


@router.get("/creative-team/playbook")
async def creative_team_playbook(_auth: bool = Depends(require_service_key)):
    """The brain's full knowledge: every style/engine/resource + policy + the learned lessons."""
    from ..services import creative_playbook as pb
    from ..services import creative_learning as learn
    return {"success": True, "playbook": pb.describe(), "lessons": learn.get_lessons(limit=50)}


@router.get("/creative-team/lessons")
async def creative_team_lessons(scope: str = "", style: str = "", vertical: str = "",
                                _auth: bool = Depends(require_service_key)):
    """The self-learning failure memory — what went wrong, why, and the corrective rule."""
    from ..services import creative_learning as learn
    return {"success": True, "lessons": learn.get_lessons(scope=scope, style=style, vertical=vertical, limit=100)}


@router.get("/thumb")
async def thumb(url: str = "", key: str = "", _auth: bool = Depends(require_service_key)):
    """Stable JPG poster for a video (ffmpeg frame → cached in S3 at a deterministic key). Fixes the
    black 9:16 cards: same source → same poster URL, generated once, served forever. Never black."""
    import hashlib
    from ..services.storage import StorageService
    src = (key or url or "").strip()
    if not src:
        raise HTTPException(status_code=400, detail="key or url required")
    h = hashlib.sha1(src.encode()).hexdigest()[:20]
    tkey = f"thumbnails/{h}.jpg"
    if StorageService.object_exists(tkey):
        return {"success": True, "url": StorageService.presign_url(tkey, expires=604800), "cached": True}
    fetch = url or StorageService.presign_url(key)
    if not fetch:
        raise HTTPException(status_code=400, detail="cannot resolve source video")
    out = os.path.join(UPLOAD_DIR, f"thumb_{h}.jpg")
    raw = None
    try:
        # download first (reliable for presigned/spaced keys), then extract a frame locally
        raw = await _download_to_temp(fetch, ".mp4")
        try:
            await asyncio.to_thread(_ffmpeg, ["-ss", "0.6", "-i", raw, "-frames:v", "1",
                                              "-vf", "scale=360:-2", "-q:v", "5", "-y", out], 60)
        except Exception:
            await asyncio.to_thread(_ffmpeg, ["-i", raw, "-frames:v", "1",
                                              "-vf", "scale=360:-2", "-q:v", "5", "-y", out], 60)
        StorageService.upload_file(out, tkey)
        return {"success": True, "url": StorageService.presign_url(tkey, expires=604800) or "", "cached": False}
    except Exception as e:
        logger.warning(f"thumb generation failed for {src}: {e}")
        return {"success": False, "url": "", "error": str(e)[:160]}
    finally:
        for p in (raw, out):
            try:
                if p:
                    os.remove(p)
            except OSError:
                pass


@router.get("/providers")
async def available_providers(_auth: bool = Depends(require_service_key)):
    """Which providers are ACTUALLY usable (detected from configured keys — never assumed), per
    step, so the UI offers only real options and the router never picks an unconfigured lane."""
    s = settings
    lip = []
    if s.fal_key: lip.append({"id": "fal", "name": "fal · lip-sync (cheapest)", "cost": "$"})
    if s.sync_so_api_key: lip.append({"id": "sync", "name": "sync.so — video→video (premium)", "cost": "$$"})
    # Replicate lanes only when the account is FUNDED — an unfunded token 402s on every call
    if s.replicate_usable:
        lip += [{"id": "latentsync", "name": "Replicate LatentSync (cheap, video→video)", "cost": "$"},
                {"id": "wav2lip", "name": "Replicate Wav2Lip (cheapest)", "cost": "¢"}]
    voice = [{"id": "openai", "name": "OpenAI TTS", "cost": "¢"}]
    if s.deepgram_api_key: voice.append({"id": "deepgram", "name": "Deepgram Aura", "cost": "¢"})
    if s.elevenlabs_api_key: voice.append({"id": "elevenlabs", "name": "ElevenLabs (premium)", "cost": "$"})
    if s.replicate_usable: voice.append({"id": "kokoro", "name": "Kokoro (Replicate)", "cost": "¢"})
    video = []
    if s.kie_api_key: video += [{"id": "kie-seedance", "name": "Kie · Seedance 2.0", "cost": "$$"},
                                {"id": "kie-seedance-fast", "name": "Kie · Seedance 2.0 Fast", "cost": "$"}]
    if s.fal_key: video += [{"id": "fal-seedance", "name": "fal · Seedance (cheaper)", "cost": "$"},
                            {"id": "fal-kling", "name": "fal · Kling 2.0", "cost": "$"},
                            {"id": "fal-wan", "name": "fal · Wan 2.6 (budget)", "cost": "¢"}]
    image = []
    if s.gemini_api_key: image.append({"id": "gemini", "name": "Gemini Imagen 4", "cost": "¢"})
    if s.openai_api_key: image.append({"id": "openai", "name": "OpenAI DALL·E 3", "cost": "¢"})
    if s.ideogram_api_key: image.append({"id": "ideogram", "name": "Ideogram 3 (text-heavy)", "cost": "¢"})
    captions = [{"id": "clean", "name": "ffmpeg — accurate, free", "cost": "free"}]
    if s.fal_key: captions.append({"id": "veed", "name": "VEED styled (fal)", "cost": "$"})
    return {"success": True, "lipsync": lip, "voice": voice, "video": video, "image": image, "captions": captions,
            "default_quality": _ENGINE["default_quality"]}


@router.get("/engine-config")
async def get_engine_config(_auth: bool = Depends(require_service_key)):
    """Live engine dials: concurrency cap, monthly budget ceiling, default quality + spend-to-date."""
    spent = _month_spend()
    cap = _ENGINE["monthly_budget_usd"]
    return {"success": True, "concurrency_cap": _ENGINE["cap"], "active": _ENGINE["active"],
            "default_quality": _ENGINE["default_quality"], "monthly_budget_usd": cap,
            "month_spend_usd": round(spent, 2), "budget_remaining_usd": round(max(0, cap - spent), 2) if cap else None}


@router.post("/engine-config")
async def set_engine_config(payload: dict, _auth: bool = Depends(require_service_key)):
    """Admin dial: set concurrency cap (1–30), monthly budget ceiling, default quality (bulk|premium)."""
    if "concurrency_cap" in payload:
        _ENGINE["cap"] = max(1, min(30, int(payload["concurrency_cap"])))
    if "monthly_budget_usd" in payload:
        _ENGINE["monthly_budget_usd"] = max(0.0, float(payload["monthly_budget_usd"]))
    if payload.get("default_quality") in ("bulk", "premium"):
        _ENGINE["default_quality"] = payload["default_quality"]
    # wake any queued jobs in case the cap was raised
    try:
        cond = _engine_cond()
        async with cond:
            cond.notify_all()
    except Exception:
        pass
    logger.info(f"[regen] engine-config set → {_ENGINE}")
    return {"success": True, "concurrency_cap": _ENGINE["cap"], "monthly_budget_usd": _ENGINE["monthly_budget_usd"],
            "default_quality": _ENGINE["default_quality"]}


async def _parse_intent_text(cmd: str) -> dict:
    """Shared parse-intent logic: LLM-parse a plain-language creative command into structured intent
    (gender/age_band/vertical/scene/tone/…). Returns {} on empty input or LLM failure — never raises."""
    cmd = (cmd or "").strip()
    if not cmd:
        return {}
    from ..services import creative_playbook as pb
    verticals = "|".join(sorted(pb.VERTICALS.keys()))
    prompt = (
        "Extract structured intent from this creative-ad request. Map age words to bands: "
        "under35, 35-44, 45-55, 55plus (grandma/elderly/60s/70s→55plus; middle-aged/40s/50→45-55; "
        "20s/25-35/young→under35). "
        "Return STRICT JSON only: {\"gender\":\"female|male\",\"age_band\":\"under35|35-44|45-55|55plus|null\","
        f"\"vertical\":\"{verticals}|null\",\"offer_value\":\"e.g. $29 or null\","
        "\"seconds\":number-or-null,\"script_ref\":\"S<number> or null\",\"scene\":\"short setting like "
        "kitchen/living room/outdoor or null\","
        # tone + energy drive CASTING: a serious, informational script needs a calm, static
        # talking-head — not a high-energy, camera-moving clip. The avatar must fit the words.
        "\"tone\":\"serious|warm|urgent|upbeat|conversational|null\","
        "\"energy\":\"static|moderate|dynamic|null\","
        "\"count\":number(default 1),\"wants_image\":true/false}. "
        f"Request: \"{cmd[:800]}\""
    )
    try:
        d = await _gemini_json(prompt)
        return d or {}
    except Exception as e:
        logger.warning(f"parse-intent failed: {e}")
        return {}


@router.post("/parse-intent")
async def parse_intent(payload: dict, _auth: bool = Depends(require_service_key)):
    """LLM-parse a plain-language creative command into structured intent (robust to odd phrasings
    like 'grandma', 'guy in his 60s', multi-clause briefs). Falls back to {} if the LLM is down."""
    return {"success": True, "intent": await _parse_intent_text((payload.get("command") or "").strip())}


@router.post("/interpret-workorder")
async def interpret_workorder(payload: dict, _auth: bool = Depends(require_service_key)):
    """LLM work-order interpreter: read the FULL essence of a file request (description + canvas brief
    + attachment names + vertical) and return an executable per-variation plan — so a 7-state ask
    fans out one state PER variation instead of collapsing to the first. Robust to mixed briefs the
    regex can't parse ('S2-S3-S4 for CO,GA,MN with garage-man variation'). Returns {} on LLM failure
    so the caller falls back to the regex parser (never breaks intake)."""
    text = (payload.get("text") or "").strip()
    vertical = (payload.get("vertical") or "").strip()
    attachments = payload.get("attachments") or []       # list of filenames / labels (optional)
    if not text and not attachments:
        return {"success": True, "plan": {}}
    ask = (
        "You interpret an internal ad-creative WORK ORDER into an executable plan. Read the brief + any "
        "attachment names and output STRICT JSON only.\n\n"
        f"VERTICAL: {vertical or 'unknown'}\n"
        f"ATTACHMENTS: {json.dumps(attachments)[:600]}\n"
        f"WORK ORDER: \"\"\"{text[:2000]}\"\"\"\n\n"
        "Extract:\n"
        "- video_type: UGC | B-Roll | MAP | Avatar | Image (best fit)\n"
        "- script_ref: the script code if named (e.g. 'S3'), else null\n"
        "- character: {gender: male|female|null, age: under35|35-44|45-55|55plus|null, new: true if the "
        "brief says NEW/fresh avatar}\n"
        "- axis: what the variations differ by — state | script | character | hook | format\n"
        "- variations: an ARRAY, ONE object per creative the brief asks for. If it lists N states "
        "(e.g. CA, IL, NJ...), make ONE variation PER state in that exact order. Each: "
        "{state: <2-letter or null>, script_ref: <code or null>, note: <short>}\n"
        "- count: variations.length\n\n"
        'Return ONLY: {"video_type":"...","script_ref":"...","character":{...},"axis":"...",'
        '"count":N,"variations":[{"state":"CA","script_ref":"S3","note":"..."}, ...]}'
    )
    try:
        out = await _gemini_json(ask)
        plan = out if isinstance(out, dict) else {}
        vs = plan.get("variations")
        if not isinstance(vs, list) or not vs:
            return {"success": True, "plan": {}}
        plan["count"] = len(vs)
        return {"success": True, "plan": plan}
    except Exception as e:
        logger.warning(f"interpret_workorder failed: {e}")
        return {"success": True, "plan": {}}


@router.post("/learn/roi")
async def learn_roi(payload: dict, _auth: bool = Depends(require_service_key)):
    """Close the loop: stitch platform ROI onto the decisions for a delivered creative.
    body: {creative_ref, roi}  (or {items:[{creative_ref, roi}]}). This is the objective metric
    the loop optimizes — set from the ad platform, never by a model."""
    from ..database import SessionLocal
    from ..services import learning_loop as learn
    items = payload.get("items") or ([payload] if payload.get("creative_ref") else [])
    db = SessionLocal()
    try:
        n = sum(learn.attach_roi(db, it["creative_ref"], float(it.get("roi") or 0))
                for it in items if it.get("creative_ref"))
        return {"success": True, "updated_rows": n}
    finally:
        db.close()


@router.post("/learn/verdict")
async def learn_verdict(payload: dict, _auth: bool = Depends(require_service_key)):
    """The human's judgment as a label, used wherever ROI is absent.
    body: {creative_ref, verdict: accepted|regenerated, reason?}"""
    from ..database import SessionLocal
    from ..services import learning_loop as learn
    ref = payload.get("creative_ref"); verdict = payload.get("verdict")
    if not ref or verdict not in ("accepted", "regenerated", "rejected"):
        raise HTTPException(status_code=400, detail="creative_ref + verdict(accepted|regenerated) required")
    db = SessionLocal()
    try:
        n = learn.record_verdict(db, ref, verdict, payload.get("reason") or "")
        return {"success": True, "updated_rows": n}
    finally:
        db.close()


@router.get("/learn/summary")
async def learn_summary(vertical: str = "", _auth: bool = Depends(require_service_key)):
    """What the brain has learned — per-brain win-rates (anti-noise labels) PLUS each brain's
    governed-rule promotion state (suggest vs assert). Proof it's learning."""
    from ..database import SessionLocal
    from ..services import learning_loop as learn
    from ..models.learning import CreativeBrainRule
    db = SessionLocal()
    try:
        summ = learn.summary(db, vertical or None)
        promotion = {}
        try:
            q = db.query(CreativeBrainRule)
            if vertical:
                q = q.filter(CreativeBrainRule.vertical == vertical)
            for r in q.all():
                # mode reflects the ADMIN-APPROVAL gate: only an active (approved) rule is asserted;
                # a promoted-but-unapproved brain is 'proposed' (awaiting admin), else 'suggest'.
                promotion[r.brain] = {"vertical": r.vertical, "promoted": bool(r.promoted),
                                      "active": bool(r.active),
                                      "mode": ("assert" if r.active else "proposed" if r.promoted else "suggest"),
                                      "promotion_metrics": r.promotion_metrics}
        except Exception as e:
            logger.warning(f"[learn] promotion state read failed: {e}")
        return {"success": True, "vertical": vertical or "all", "summary": summ, "promotion": promotion}
    finally:
        db.close()


@router.get("/learn/events")
async def learn_events(brain: str = "", vertical: str = "", limit: int = 50,
                       _auth: bool = Depends(require_service_key)):
    """The changelog, newest-first. Merges the tuner's governed-rule keep/reject events
    (LearningEvent) with the LIVING activity that actually accumulates on EVERY run: critic +
    final-video QA verdicts, human verdicts and stitched ROI (creative_decisions), and the
    corrective lessons those failures produced (creative_lessons). This is why the tab is populated
    from day one — before the nightly tuner has ever promoted a rule. Each source is guarded so a
    schema-drift in one store never blanks the whole feed. Filterable by brain/vertical."""
    from datetime import datetime as _dt
    from ..database import SessionLocal
    cap = min(max(limit, 1), 200)
    db = SessionLocal()
    merged = []   # list of (sort_dt, event_dict)

    def _iso(d):
        return d.isoformat() if d else None

    try:
        # 1) Tuner governed-rule events (the original source).
        try:
            from ..models.learning import LearningEvent
            q = db.query(LearningEvent)
            if brain:
                q = q.filter(LearningEvent.brain == brain)
            if vertical:
                q = q.filter(LearningEvent.vertical == vertical)
            for r in q.order_by(LearningEvent.created_at.desc()).limit(cap).all():
                merged.append((r.created_at or _dt.min, {
                    "brain": r.brain, "vertical": r.vertical, "summary": r.summary,
                    "agreement_before": r.agreement_before, "agreement_after": r.agreement_after,
                    "detail": r.detail_json, "source": "tuner",
                    "created_at": _iso(r.created_at)}))
        except Exception as e:
            db.rollback()
            logger.warning(f"[learn] events: LearningEvent read failed: {e}")

        # 2) Critic + final-video QA verdicts, human verdicts, stitched ROI (creative_decisions).
        # Only rows that ARE an event — a QA fail, a human verdict, or an ROI attach; a plain passing
        # decision is state, not news. Decisions carry no brain column, so a brain filter ⇒ tuner-only.
        if not brain:
            try:
                from ..models.creative_team import CreativeDecision
                dq = db.query(CreativeDecision)
                if vertical:
                    dq = dq.filter(CreativeDecision.vertical == vertical)
                for r in dq.order_by(CreativeDecision.created_at.desc()).limit(cap).all():
                    try:
                        _reasons = json.loads(r.qc_reasons) if r.qc_reasons else {}
                    except Exception:
                        _reasons = {}
                    _stage = _reasons.get("stage") or "clip"
                    _iss = _reasons.get("issues") or []
                    when = r.verdict_at or r.roi_updated_at or r.created_at
                    if r.human_verdict:
                        summary = "human verdict: " + r.human_verdict + (f" — {r.human_reason}" if r.human_reason else "")
                        b = "human"
                    elif r.qc_passed is False:
                        summary = (f"{_stage} QA FAILED"
                                   + (f": {'; '.join(str(i) for i in _iss[:2])}" if _iss else ""))
                        b = "final_qa" if _stage == "final_video" else "critic"
                    elif r.roi is not None:
                        summary = f"ROI attached: {r.roi}"
                        b = "roi"
                    else:
                        continue
                    merged.append((when or _dt.min, {
                        "brain": b, "vertical": r.vertical, "summary": summary,
                        "agreement_before": None, "agreement_after": None,
                        "detail": {"request_id": r.request_id, "creative_ref": r.creative_ref,
                                   "roi": r.roi, "qc_passed": r.qc_passed}, "source": "decision",
                        "created_at": _iso(when)}))
            except Exception as e:
                db.rollback()
                logger.warning(f"[learn] events: CreativeDecision read failed: {e}")

        # 3) The corrective lessons those failures produced (creative_lessons) — what the brain now obeys.
        try:
            from ..models.creative_team import CreativeLesson
            lq = db.query(CreativeLesson).filter(CreativeLesson.active == True)  # noqa: E712
            if vertical:
                lq = lq.filter(CreativeLesson.vertical == vertical)
            for r in lq.order_by(CreativeLesson.updated_at.desc()).limit(cap).all():
                if brain and r.scope != brain:
                    continue
                summary = ((r.rule or r.reason or r.trigger or "lesson")
                           + (f"  [seen {r.hits}x]" if (r.hits or 0) > 1 else ""))
                merged.append((r.updated_at or r.created_at or _dt.min, {
                    "brain": r.scope or "lesson", "vertical": r.vertical, "summary": summary,
                    "agreement_before": None, "agreement_after": None,
                    "detail": {"trigger": r.trigger, "reason": r.reason, "rule": r.rule, "hits": r.hits},
                    "source": "lesson", "created_at": _iso(r.updated_at or r.created_at)}))
        except Exception as e:
            db.rollback()
            logger.warning(f"[learn] events: CreativeLesson read failed: {e}")
    finally:
        db.close()

    merged.sort(key=lambda t: t[0], reverse=True)
    items = [e for _, e in merged[:cap]]
    return {"success": True, "count": len(items), "events": items}


@router.post("/learn/run-tuning")
async def learn_run_tuning(payload: dict = None, _auth: bool = Depends(require_service_key)):
    """Admin: run every brain's holdout-gated tuner once (nightly-scheduler entry point too).
    body: {verticals?: [..]}. Each brain mines rules from TRAIN, keeps them only if holdout
    agreement improves, and writes a LearningEvent either way. Never mutates the render path."""
    from ..database import SessionLocal
    from ..services import creative_tuner as ctun
    verticals = (payload or {}).get("verticals") or None
    db = SessionLocal()
    try:
        results = ctun.run_all(db, verticals)
        return {"success": True, "ran": len(results), "results": results}
    finally:
        db.close()


def _proposal_dict(p) -> dict:
    return {"id": p.id, "brain": p.brain, "vertical": p.vertical, "status": p.status,
            "agreement_before": p.agreement_before, "agreement_after": p.agreement_after,
            "evidence": p.detail_json, "reviewed_by": p.reviewed_by,
            "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
            "review_reason": p.review_reason,
            "created_at": p.created_at.isoformat() if p.created_at else None}


@router.get("/learn/proposals")
async def learn_proposals(status: str = "pending_admin", brain: str = "", vertical: str = "",
                          limit: int = 100, _auth: bool = Depends(require_service_key)):
    """The ADMIN-APPROVAL queue: RuleProposals with their FULL evidence bundle (why/what/when/how).
    Filter by status (pending_admin|applied|rejected) — pass status='' for all. Newest-first."""
    from ..database import SessionLocal
    from ..models.learning import RuleProposal
    db = SessionLocal()
    try:
        q = db.query(RuleProposal)
        if status:
            q = q.filter(RuleProposal.status == status)
        if brain:
            q = q.filter(RuleProposal.brain == brain)
        if vertical:
            q = q.filter(RuleProposal.vertical == vertical)
        rows = q.order_by(RuleProposal.created_at.desc()).limit(min(max(limit, 1), 500)).all()
        return {"success": True, "count": len(rows), "proposals": [_proposal_dict(p) for p in rows]}
    finally:
        db.close()


@router.post("/learn/proposals/{proposal_id}/approve")
async def learn_proposal_approve(proposal_id: str, payload: dict = None,
                                 _auth: bool = Depends(require_service_key)):
    """ADMIN approves: ACTIVATE the brain's CreativeBrainRule (the engine now reads it), mark the
    proposal 'applied', and write a LearningEvent. This is the ONLY path that sets a rule active."""
    from ..database import SessionLocal
    from ..models.learning import RuleProposal, CreativeBrainRule, LearningEvent
    from datetime import datetime as _dt
    import uuid as _uuid
    approver = (payload or {}).get("approver") or "admin"
    db = SessionLocal()
    try:
        p = db.query(RuleProposal).filter(RuleProposal.id == proposal_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="proposal not found")
        if p.status != "pending_admin":
            raise HTTPException(status_code=409, detail=f"proposal already {p.status}")
        proposed = ((p.detail_json or {}).get("proposed_change")) or {}
        row = db.query(CreativeBrainRule).filter(
            CreativeBrainRule.brain == p.brain,
            CreativeBrainRule.vertical == (p.vertical or None)).first()
        if not row:
            row = CreativeBrainRule(id=str(_uuid.uuid4()), brain=p.brain, vertical=(p.vertical or None))
            db.add(row)
        row.rules_json = {"preferred": dict(proposed.get("preferred") or {}),
                          "avoided": list(proposed.get("avoided") or [])}
        row.active = True                # ← the engine may now read this rule
        p.status = "applied"
        p.reviewed_by = approver
        p.reviewed_at = _dt.utcnow()
        db.add(LearningEvent(
            id=str(_uuid.uuid4()), vertical=(p.vertical or "all"), brain=p.brain,
            summary=(f"[{p.brain}/{p.vertical or 'all'}] admin approved rule proposal — now ACTIVE "
                     f"({len(proposed.get('preferred') or {})} preferred, {len(proposed.get('avoided') or [])} avoided); "
                     f"holdout {p.agreement_before} → {p.agreement_after}. Approver: {approver}."),
            agreement_before=p.agreement_before, agreement_after=p.agreement_after,
            detail_json={"proposal_id": p.id, "action": "approved", "approver": approver,
                         "activated_rule": row.rules_json}))
        db.commit()
        return {"success": True, "proposal": _proposal_dict(p), "active_rule": row.rules_json}
    finally:
        db.close()


@router.post("/learn/proposals/{proposal_id}/reject")
async def learn_proposal_reject(proposal_id: str, payload: dict = None,
                                _auth: bool = Depends(require_service_key)):
    """ADMIN rejects: mark 'rejected', keep the OLD behavior (no rule activated), write a
    LearningEvent. body: {reason?, approver?}."""
    from ..database import SessionLocal
    from ..models.learning import RuleProposal, LearningEvent
    from datetime import datetime as _dt
    import uuid as _uuid
    reason = (payload or {}).get("reason") or ""
    approver = (payload or {}).get("approver") or "admin"
    db = SessionLocal()
    try:
        p = db.query(RuleProposal).filter(RuleProposal.id == proposal_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="proposal not found")
        if p.status != "pending_admin":
            raise HTTPException(status_code=409, detail=f"proposal already {p.status}")
        p.status = "rejected"
        p.reviewed_by = approver
        p.reviewed_at = _dt.utcnow()
        p.review_reason = (reason or "")[:500]
        db.add(LearningEvent(
            id=str(_uuid.uuid4()), vertical=(p.vertical or "all"), brain=p.brain,
            summary=(f"[{p.brain}/{p.vertical or 'all'}] admin REJECTED rule proposal — engine unchanged. "
                     f"Reason: {reason or 'n/a'}. Reviewer: {approver}."),
            agreement_before=p.agreement_before, agreement_after=p.agreement_after,
            detail_json={"proposal_id": p.id, "action": "rejected", "approver": approver, "reason": reason}))
        db.commit()
        return {"success": True, "proposal": _proposal_dict(p)}
    finally:
        db.close()


@router.get("/learn/brains")
async def learn_brains(vertical: str = "", _auth: bool = Depends(require_service_key)):
    """Per-brain audit for the learning tab: status (gathering|suggesting|promoted), labeled count,
    holdout agreement, promotion_metrics, current ACTIVE rule (if any), pending/applied proposal
    counts. Cold start → every brain 'gathering', no active rule."""
    from ..database import SessionLocal
    from ..services import learning_loop as learn
    from ..services import creative_tuner as ctun
    from ..models.learning import CreativeBrainRule, RuleProposal
    db = SessionLocal()
    try:
        vt = vertical or None
        out = []
        for brain in ctun.TUNABLE_BRAINS:
            # GUARDED per-brain: _labelled_rows / the rule+proposal queries SELECT columns that a
            # schema-drifted prod DB may not have (a legacy creative_decisions predating caption_method
            # / variation_axis / creative_ref, or missing learning tables entirely). Any such
            # OperationalError/ProgrammingError must degrade THIS brain to a 'gathering' default and
            # roll back the broken txn — NOT 500 the whole endpoint. Same class as /learn/decisions.
            try:
                labeled = len(ctun._labelled_rows(db, brain, vt))
                row = db.query(CreativeBrainRule).filter(
                    CreativeBrainRule.brain == brain,
                    CreativeBrainRule.vertical == (vt or None)).first()
                pending = db.query(RuleProposal).filter(
                    RuleProposal.brain == brain, RuleProposal.status == "pending_admin")
                applied = db.query(RuleProposal).filter(
                    RuleProposal.brain == brain, RuleProposal.status == "applied")
                if vt:
                    pending = pending.filter(RuleProposal.vertical == vt)
                    applied = applied.filter(RuleProposal.vertical == vt)
                n_pending, n_applied = pending.count(), applied.count()
                promoted = bool(row.promoted) if row else False
                active = bool(row.active) if row else False
                # status: promoted (cleared bar) > suggesting (pending proposal) > gathering
                status = "promoted" if promoted else ("suggesting" if n_pending else "gathering")
                metrics = (row.promotion_metrics if row else None) or {}
                out.append({
                    "brain": brain, "vertical": vt or "all", "status": status,
                    "labeled_count": labeled, "promoted": promoted,
                    "holdout_agreement": metrics.get("live_agreement"),
                    "promotion_metrics": metrics or None,
                    "active_rule": (row.rules_json if (row and active and row.rules_json) else None),
                    "has_active_rule": active,
                    "pending_proposals": n_pending, "applied_proposals": n_applied,
                    "last_analyzed_at": row.last_analyzed_at.isoformat() if (row and row.last_analyzed_at) else None,
                })
            except Exception as e:
                try:
                    db.rollback()   # a failed SELECT leaves the session in a broken txn on Postgres
                except Exception:
                    pass
                logger.warning(f"[learn] brains status failed for brain={brain} vertical={vt}: {e}")
                out.append({
                    "brain": brain, "vertical": vt or "all", "status": "gathering",
                    "labeled_count": 0, "promoted": False,
                    "holdout_agreement": None, "promotion_metrics": None,
                    "active_rule": None, "has_active_rule": False,
                    "pending_proposals": 0, "applied_proposals": 0,
                    "last_analyzed_at": None,
                })
        return {"success": True, "vertical": vt or "all", "brains": out}
    except Exception as e:
        # Anything OUTSIDE the per-brain guard (TUNABLE_BRAINS drift, missing learning
        # tables/models, broken session) must NOT 500 the learning tab — degrade to an
        # empty-but-valid payload. Same class as /learn/decisions.
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"[learn] brains endpoint failed vertical={vertical}: {e}")
        return {"success": True, "vertical": vertical or "all", "brains": []}
    finally:
        db.close()


@router.get("/learn/decisions/{request_id}")
async def learn_decisions(request_id: str, _auth: bool = Depends(require_service_key)):
    """The per-generation decision trace for ONE job: what each brain decided, the human feedback,
    blamed_brains, the label (win/loss/pending), ROI — plus a per-brain breakdown so the UI can show
    'voice: chosen=nova, verdict=loss, reason=too young'. Read-only; never raises into anything."""
    from ..database import SessionLocal
    from ..services import learning_loop as learn
    db = SessionLocal()
    try:
        decisions = learn.decisions_for_job(db, request_id)   # already defensive → [] on any error
        breakdown = []
        # brain-level breakdown per decision row. GUARDED: this query SELECTs the per-brain columns,
        # so a schema-drift OperationalError/UndefinedColumn in prod (a creative_decisions table that
        # predates a migrated column, e.g. caption_method) must degrade to [] here — NOT 500 the
        # endpoint. The docstring promise ("never raises") only holds because of this guard.
        try:
            from ..models.creative_team import CreativeDecision
            rows = (db.query(CreativeDecision)
                      .filter(CreativeDecision.request_id == request_id)
                      .order_by(CreativeDecision.created_at.asc()).all())
            for r in rows:
                blamed = learn._blamed(r) or set()
                brains = {}
                for brain, col in learn.BRAIN_COLUMN.items():
                    chosen = getattr(r, col, None)
                    if chosen is None:
                        continue
                    lab = learn._brain_label(r, brain)
                    brains[brain] = {"chosen": chosen,
                                     "verdict": ("win" if lab == 1 else "loss" if lab == 0 else "pending"),
                                     "blamed": brain in blamed}
                breakdown.append({"creative_ref": r.creative_ref, "vertical": r.vertical,
                                  "human_verdict": r.human_verdict, "reason": r.human_reason,
                                  "roi": r.roi, "brains": brains})
        except Exception as e:
            try:
                db.rollback()   # a failed SELECT leaves the session in a broken txn on Postgres
            except Exception:
                pass
            logger.warning(f"[learn] decisions breakdown failed for {request_id}: {e}")
            breakdown = []
        return {"success": True, "request_id": request_id, "decisions": decisions,
                "brain_breakdown": breakdown}
    finally:
        db.close()


@router.get("/costs")
async def creation_costs(request_id: str = "", _auth: bool = Depends(require_service_key)):
    """Per-creation spend breakdown: total + by provider + by step. Drives the credit UI."""
    from ..database import SessionLocal
    from ..models.creative_team import CreationCost
    db = SessionLocal()
    try:
        q = db.query(CreationCost)
        if request_id:
            q = q.filter(CreationCost.request_id == request_id)
        rows = q.order_by(CreationCost.created_at.asc()).limit(500).all()
        items = [{"step": r.step, "provider": r.provider, "model": r.model, "units": r.units,
                  "unit_type": r.unit_type, "cost_usd": round(r.cost_usd or 0, 5), "note": r.note,
                  "request_id": r.request_id} for r in rows]
        total = round(sum(r.cost_usd or 0 for r in rows), 4)
        by_provider = {}
        for r in rows:
            by_provider[r.provider] = round(by_provider.get(r.provider, 0) + (r.cost_usd or 0), 5)
        return {"success": True, "request_id": request_id or None, "total_usd": total,
                "by_provider": by_provider, "items": items}
    finally:
        db.close()


def _api_key_for(provider: str, model: str) -> str:
    """Which API KEY / env a cost row bills against — so the ledger shows which key cost what."""
    p = (provider or "").lower(); m = (model or "").lower()
    if "gemini" in p or "gemini" in m or "google" in p:        return "GEMINI_API_KEY"
    if "eleven" in p or "eleven" in m:                          return "ELEVENLABS_API_KEY"
    if p in ("openai", "whisper") or "whisper" in p or "gpt" in m or "openai" in m: return "OPENAI_API_KEY"
    if p in ("fal-clone", "veed", "falsync", "fal", "kling") or "fal" in p or "f5" in m or "veed" in m: return "FAL_API_KEY"
    if p == "sync" or "sync.so" in p:                           return "sync.so (fal credit)"
    if p in ("latentsync", "wav2lip", "replicate") or "replicate" in p: return "REPLICATE_API_TOKEN"
    if "kie" in p or "seedance" in m or "kie" in m:             return "KIE_API_KEY"
    return "—"


@router.get("/finance/ledger")
async def finance_ledger(_auth: bool = Depends(require_service_key)):
    """FINANCE LEDGER: per provider+model — total $ spent, # generations produced (distinct request),
    # calls, and the API KEY it bills against. Plus a per-key roll-up and grand total. Straight off the
    creation_costs ledger (same rows the office cost pill sums), so it reflects real, reconciled rates."""
    from ..database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT provider, COALESCE(model,'') AS model, "
            "       SUM(COALESCE(cost_usd,0)) AS total_usd, "
            "       COUNT(DISTINCT request_id) AS generations, "
            "       COUNT(*) AS calls, MAX(created_at) AS last_used "
            "FROM creation_costs GROUP BY provider, COALESCE(model,'') "
            "ORDER BY SUM(COALESCE(cost_usd,0)) DESC")).fetchall()
        items, gtotal, by_key = [], 0.0, {}
        for r in rows:
            prov, model = (r[0] or ""), (r[1] or "")
            total, gens, calls = float(r[2] or 0), int(r[3] or 0), int(r[4] or 0)
            key = _api_key_for(prov, model)
            gtotal += total
            items.append({"provider": prov, "model": model or None, "api_key": key,
                          "total_usd": round(total, 4), "generations": gens, "calls": calls,
                          "last_used": (str(r[5]) if r[5] else None)})
            e = by_key.setdefault(key, {"api_key": key, "total_usd": 0.0, "calls": 0})
            e["total_usd"] = round(e["total_usd"] + total, 4); e["calls"] += calls
        return {"success": True, "grand_total_usd": round(gtotal, 4),
                "by_key": sorted(by_key.values(), key=lambda x: -x["total_usd"]),
                "items": items}
    finally:
        db.close()


@router.get("/voices")
async def list_voices(gender: str = "", age_band: str = "", _auth: bool = Depends(require_service_key)):
    """The full pickable voice catalog (Kokoro/OpenAI/Deepgram presets, casting-tagged),
    plus the brain's recommended voice for the given casting. More options than 11Labs, cheapest-first."""
    from ..services import voice_studio as vs
    # only voices we can ACTUALLY synthesize — never offer one whose key isn't configured,
    # or the user picks it and silently gets a different voice.
    voices = vs.list_voices(only_available=True)
    if gender: voices = [v for v in voices if v.get("gender") == gender]
    if age_band: voices = [v for v in voices if v.get("age_band") == age_band]
    # Only recommend when a gender is actually specified — pick_voice refuses to guess gender,
    # so an unspecified/absent gender means no recommendation (the picker shows the full list).
    recommended = None
    if gender:
        try:
            recommended = vs.pick_voice(gender=gender, age_band=age_band or None)
        except ValueError:
            recommended = None
    return {"success": True, "count": len(voices), "voices": voices,
            "clone_available": vs.clone_available(),
            "recommended": recommended}


@router.post("/tts")
async def tts(payload: dict, _auth: bool = Depends(require_service_key)):
    """Synthesize a voice-over, cheapest-first with automatic fallback (ElevenLabs last).
    body: {text, voice_id?, style?, sample_url?}  → {url, provider, voice, cost_usd, fallback}."""
    from ..services import voice_studio as vs
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    try:
        res = vs.synthesize(text, voice_id=payload.get("voice_id"), style=payload.get("style"),
                            sample_url=payload.get("sample_url"))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"tts failed: {e}")
    url = None
    try:
        from ..services.storage import StorageService
        url = StorageService.upload_file(res["path"], f"voice/{os.path.basename(res['path'])}")
    except Exception as e:
        logger.warning(f"tts s3 upload failed: {e}")
    return {"success": True, "url": url, "provider": res.get("provider"), "voice": res.get("voice"),
            "cost_usd": res.get("cost_usd"), "fallback": res.get("fallback")}


@router.post("/voice/clone")
async def voice_clone(payload: dict, _auth: bool = Depends(require_service_key)):
    """Register a reusable cloned voice from a ~10s sample (Chatterbox; ElevenLabs fallback).
    body: {sample_url, name} → {voice_id, provider, sample_url, name}."""
    from ..services import voice_studio as vs
    sample_url = (payload.get("sample_url") or "").strip()
    name = (payload.get("name") or "Cloned voice").strip()
    if not sample_url:
        raise HTTPException(status_code=400, detail="sample_url required")
    try:
        ref = vs.clone_voice(sample_url, name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"clone failed: {e}")
    return {"success": True, **ref}


@router.post("/image")
async def regen_image(payload: dict, _auth: bool = Depends(require_service_key)):
    """Generate a STATIC image via the Gemini Imagen → OpenAI → FAL chain (NOT Kie video).
    Wraps the prompt with anti-slop realism so we get authentic, non-AI-looking creative.
    body: {prompt, vertical?} → {url, provider, model, cost_usd}."""
    from ..services.image_generator import ImageGeneratorService
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    # anti-slop realism wrapper (adaptive). Text-aware: if the user actually wants a
    # headline/CTA, keep it so the chain smart-routes to Ideogram; else forbid on-screen text.
    wants_text = any(k in prompt.lower() for k in ('"', 'headline', 'cta', 'text', 'caption', 'banner', 'title', 'sign that says'))
    notext = "" if wants_text else "NO on-screen text, captions or watermark; "
    full = (f"{prompt}. "
            "Photorealistic, authentic UGC/editorial look — natural skin texture with real pores, "
            "realistic lighting and depth, believable everyday setting, correct anatomy and hands. "
            f"{notext}no plastic AI skin, no over-smoothing, no distorted hands, no cartoon/3D-render look; "
            # models love to draw a picture-of-the-subject INSIDE the subject's own flyer/screen
            "do NOT put a picture of the same people inside any flyer, poster, card or screen in the "
            "image; no picture-in-picture, no duplicated subjects, no gibberish/garbled lettering.")
    # ad creatives are VERTICAL — 16:9 was hardcoded, which is why the image came back letterboxed
    aspect = (payload.get("aspect") or payload.get("aspect_ratio") or "9:16").strip()
    svc = ImageGeneratorService()
    try:
        data = await svc._generate_with_provider(full, aspect)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"image generation failed: {e}")
    url, path = data.get("url"), data.get("path")
    download_url = None
    if path:
        try:
            from ..services.storage import StorageService
            key = f"regen/image_{os.path.basename(path)}"
            u = StorageService.upload_file(path, key)
            # our bucket is PRIVATE — the raw object URL 403s (AccessDenied) in the browser,
            # so hand back a presigned URL the user can actually open.
            if u:
                url = StorageService.presign_url(key, expires=604800) or u
                # a second presign that SAVES instead of opening a tab (the `download` attribute
                # is ignored cross-origin, so the header has to do the work)
                download_url = StorageService.presign_url(key, expires=604800,
                                                          download_as=os.path.basename(path))
        except Exception as e:
            logger.warning(f"image s3 upload failed: {e}")
    model = data.get("model") or ""
    provider = ("gemini" if ("imagen" in model or "gemini" in model)
                else "openai" if ("dall" in model or "gpt" in model)
                else "fal" if "flux" in model else (model or "image"))
    rid = payload.get("request_id")
    if rid:
        _track_cost(rid, "image", provider, model=model, unit_type="run", cost_usd=data.get("cost_usd") or 0)
    return {"success": True, "url": url, "download_url": download_url or url, "aspect": aspect,
            "provider": provider, "model": model, "cost_usd": data.get("cost_usd")}


@router.post("/recast-avatar")
async def recast_avatar(payload: dict, _auth: bool = Depends(require_service_key)):
    """RECAST a NEW avatar face when the avatar-lipsync path found no near-similar REAL library clip.
    Nano Banana (Gemini image) portrait of the SAME type+setup → Seedance image-to-video talking head
    → returns a SHORT clip URL the normal lip-sync recipe drives (it loops/extends the clip to cover
    the VO). DEFENSIVE: returns {success:false} on any failure so the caller falls back to the
    original attached face — this never hard-fails a live request.
    body: {traits:{gender,age_band,scene,wardrobe,ethnicity,style,vertical}, seconds?, request_id?}"""
    traits = payload.get("traits") or {}
    clip_sec = max(4, min(int(payload.get("seconds") or 5), 8))   # keep it SHORT — lip-sync loops it
    try:
        from ..services.image_generator import ImageGeneratorService
        from ..services.storage import StorageService
        from ..services import fal_video as fv
        # 1) PORTRAIT — Nano Banana / Gemini image, same type+setup, front-facing, neutral mouth
        age = str(traits.get("age_band") or "").replace("plus", "+")
        head = " ".join(x for x in [age, traits.get("ethnicity") or "", traits.get("gender") or "person"] if x).strip()
        parts = [f"Photorealistic vertical 9:16 portrait of a {head}"]
        if traits.get("wardrobe"): parts.append(f"wearing {traits['wardrobe']}")
        if traits.get("scene"):    parts.append(f"in {traits['scene']}")
        parts.append("front-facing talking-head framing, head and shoulders, looking straight at the "
                     "camera, neutral closed mouth, relaxed natural expression, even soft lighting")
        from ..services import prompt_craft as _pc
        portrait_prompt = (", ".join(parts) + ". " + _pc.UGC_PORTRAIT_TAGS +
            " ONE single person only; NO on-screen text, no watermark.")
        svc = ImageGeneratorService()
        img = await svc._generate_with_provider(portrait_prompt, "9:16")
        portrait_url, img_path = img.get("url"), img.get("path")
        if img_path:
            key = f"regen/recast_portrait_{os.path.basename(img_path)}"
            u = StorageService.upload_file(img_path, key)
            if u:
                portrait_url = StorageService.presign_url(key, expires=604800) or u
        if not portrait_url:
            return {"success": False, "error": "portrait generation returned no image"}

        # 2) TALKING HEAD — Seedance image-to-video (portrait is the true first frame; cheapest i2v)
        motion = ("The person looks straight at the camera and talks naturally to it, subtle head "
                  "movement, natural blinking, gentle mouth motion, static background, locked-off "
                  "talking-head shot.")
        vid = await asyncio.to_thread(
            fv.generate_video, "fal-seedance", motion,
            image_url=portrait_url, seconds=clip_sec, aspect_ratio="9:16", resolution="480p")
        video_url, local = vid.get("video_url"), vid.get("local_path")
        if local:
            key = f"regen/recast_talkinghead_{os.path.basename(local)}"
            u = StorageService.upload_file(local, key)
            if u:
                video_url = StorageService.presign_url(key, expires=604800) or u
        if not video_url:
            return {"success": False, "error": "talking-head generation returned no video"}

        cost = float(vid.get("cost_usd") or 0) + float(img.get("cost_usd") or 0)
        rid = payload.get("request_id")
        if rid:
            _track_cost(rid, "recast_avatar", "fal+gemini", model="seedance-i2v", unit_type="run", cost_usd=cost)
        return {"success": True, "video_url": video_url, "portrait_url": portrait_url,
                "clip_seconds": clip_sec, "cost_usd": round(cost, 4)}
    except Exception as e:
        logger.warning(f"[recast-avatar] generation failed: {e}")
        return {"success": False, "error": f"{type(e).__name__}: {str(e)[:180]}"}


@router.post("/creative-team/enhance")
async def creative_team_enhance(payload: dict, _auth: bool = Depends(require_service_key)):
    """LLM assist for the Studio composer:
      • mode='enhance' → rewrite the user's prompt into a vivid, front-loaded, anti-slop engine prompt.
      • mode='script'  → expand it into a time-frame-wise scene script (one scene per line w/ timing),
        which the user approves and we then generate from.
    Returns {text}. Falls back to the original prompt if the LLM is unavailable."""
    prompt = (payload.get("prompt") or "").strip()
    mode = (payload.get("mode") or "enhance").lower()
    engine = (payload.get("engine") or "seedance").lower()
    vertical = payload.get("vertical") or ""
    seconds = int(payload.get("seconds") or 15)
    if not prompt:
        return {"success": False, "error": "prompt required"}
    from ..services import realism_prompt_engine as rpe  # noqa (rules reference)
    if mode == "script":
        seg = 7 if engine == "veo-extend" else max(4, min(15, seconds))
        n = max(1, round(seconds / seg))
        ask = (f"You are a direct-response video director. Expand this idea into a SHORT shot script of "
               f"{n} scene(s) for a {vertical} ad, ONE scene per line, each line prefixed with its time "
               f"window (e.g. '0-{seg}s:'). Each line = one continuous action, front-loaded (camera → "
               f"subject → environment → lighting → action), candid/anti-slop, no on-screen text. "
               f"Idea: \"{prompt}\". Return STRICT JSON {{\"script\": \"line1\\nline2\"}}.")
    else:
        ask = (f"Rewrite this into ONE vivid, front-loaded video-generation prompt (camera → subject → "
               f"environment → lighting → single continuous action), candid consumer-camera realism, "
               f"anti-slop, no on-screen text, for a {vertical} ad. Keep it faithful to the intent. "
               f"Idea: \"{prompt}\". Return STRICT JSON {{\"prompt\": \"...\"}}.")
    try:
        out = await _gemini_json(ask)
        text = (out.get("script") if mode == "script" else out.get("prompt")) or prompt
        return {"success": True, "text": str(text).strip(), "mode": mode}
    except Exception as e:
        logger.warning(f"enhance failed: {e}")
        return {"success": True, "text": prompt, "mode": mode, "fallback": True}


def _fit_script_to_seconds(text: str, seconds: int) -> str:
    """DETERMINISTIC word-budget cap for a spoken script (~2.5 words/sec, 150 wpm). If the script runs
    over the duration's budget, TRIM it WITHOUT breaking a sentence: keep the first sentence (hook) and
    the last (CTA), and drop whole MIDDLE sentences (nearest the CTA first) until it fits. Never cuts
    mid-sentence, never drops the CTA. Returns the text unchanged when it already fits or can't be
    trimmed safely (only a hook+CTA)."""
    text = (text or "").strip()
    if not text or not seconds or seconds <= 0:
        return text
    budget = round(2.5 * seconds)
    if len(text.split()) <= budget * 1.15:            # allow a small margin before trimming
        return text
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sents) <= 2:                                # only hook + CTA — trimming would break a sentence
        return text
    hook, cta, middle = sents[0], sents[-1], sents[1:-1]
    base = len(hook.split()) + len(cta.split())
    while middle and base + sum(len(s.split()) for s in middle) > budget:
        middle.pop()                                   # drop the middle sentence nearest the CTA
    return " ".join([hook, *middle, cta])


@router.post("/studio/route")
async def studio_route(payload: dict, background: BackgroundTasks,
                       _auth: bool = Depends(require_service_key)):
    """ChatGPT-style Studio router. Given the recent thread history + the new message, classify into
    ONE strict-JSON action AND (for write actions) produce the content inline, so Node needs a single
    round-trip. Always degrades to a plain reply on any failure."""
    history = payload.get("history") or []
    message = (payload.get("message") or "").strip()
    vertical = payload.get("vertical") or ""
    user_id = str(payload.get("user_id") or "").strip()   # CL passes req.user.id — memory is scoped to it
    logger.info(f"[studio/route] user_id={user_id!r} msg_len={len(message)}")
    if not message:
        return {"action": "reply", "text": "What would you like to make?"}
    lines = []
    for h in history[-20:]:
        role = h.get("role") or "user"
        kind = h.get("kind") or "text"
        txt = (h.get("text") or "").replace("\n", " ")[:300]
        tag = f"[{kind}]" if kind and kind != "text" else ""
        lines.append(f"{role}{tag}: {txt}")
    hist_text = "\n".join(lines) or "(empty)"
    # #5 CONFIRMATION HANDSHAKE (deterministic backstop). The parser was a dumb box: it re-ran the brief
    # interview even when the user PASTED a full script — and separately we must never spend on a paid
    # render until the user has CONFIRMED the plan. So: (1) a pasted script + make-video intent → RESTATE
    # the plan and ask for a GO (no interview, no spend yet); (2) a bare "go/yes/make it" right after we
    # proposed a plan → fire make_video VERBATIM from the script already in the thread. The LLM prompt
    # below also does this by judgment; this guarantees it even if the model slips.
    _msg = message.strip(); _low = _msg.lower()
    # Extract the quoted script by PAIRING quotes sequentially (1st–2nd, 3rd–4th, …), then take the
    # LONGEST paired segment. A naive `"..."` regex breaks when the scene line has a short inner quote
    # (e.g. "golden hour"): it eats the script's OPENING quote as the inner quote's closing quote, so
    # the script never becomes a match. Splitting on quote chars and taking alternate segments pairs
    # them correctly → ["golden hour", "<the real script>"] → longest = the script.
    _qparts = re.split(r'["“”]', _msg)
    _quoted = [_qparts[i].strip() for i in range(1, len(_qparts), 2)]
    _inline = max(_quoted, key=len) if _quoted else ""
    if len(_inline) < 40:   # too short to be a script (a stray inner quote) → fall through
        _inline = ""
    if not _inline:
        _body = re.sub(r'^\s*(?:make|create|generate|turn|use|render)\b.*?(?:script|video|this)\b[:\-\s]*',
                       '', _msg, flags=re.I).strip()
        if len(_body.split()) >= 25 and (_body.count('.') + _body.count('!') + _body.count('?')) >= 2:
            _inline = _body
    _wants_video = bool(re.search(r'\bvideo\b', _low) and re.search(r'\b(make|create|generate|turn|render|from\s+this)\b', _low))
    _is_go = bool(re.fullmatch(r"\s*(go|yes+|yep|yeah|ok(ay)?|sure|do it|make it|proceed|confirm|sounds good|perfect|let'?s go)[\s.!]*", _low))
    if _is_go:
        _prior, _src, _pdur = "", "", 0
        _allhist = " ".join((h.get("text") or "") for h in history)
        _pm = re.search(r'(\d{1,3})\s*(?:s\b|sec|second)', _allhist, re.I); _pdur = int(_pm.group(1)) if _pm else 0
        # Find the SCRIPT to speak. ONLY legit sources: a USER message, or an assistant message the
        # office actually WROTE as a script (kind=='script'). NEVER a plain assistant reply — walking
        # history newest-first and taking any 25-word/2-period text is how the avatar ended up reciting
        # our OWN "Got it — here's what I'll make… reply go" confirmation verbatim. Belt-and-suspenders:
        # also reject anything that starts with that confirmation signature.
        for h in reversed(history):
            _role = (h.get("role") or "user"); _kind = (h.get("kind") or "text")
            if _role != "user" and _kind != "script":
                continue
            t = (h.get("text") or "").strip()
            if t.startswith("Got it — here's what I'll make"):
                continue
            # Pair quotes sequentially + take the longest paired segment (see confirm path) so a short
            # inner scene quote ("golden hour") can't hijack the extraction.
            _qp = re.split(r'["“”]', t)
            _pqs = [_qp[i].strip() for i in range(1, len(_qp), 2)]
            _best = max(_pqs, key=len) if _pqs else ""
            cand = (_best if len(_best) >= 40 else (t if (len(t.split()) >= 25 and t.count('.') >= 2) else ""))
            if cand: _prior = cand; _src = t; break
        if _prior:
            # Carry the CAST + SETTING from the SAME message the script came from, so the render matches
            # the brief (e.g. "denim jacket, suburban sidewalk") instead of a fabricated default persona
            # (the "woman in a park with coffee" drift). Unset → AE casts from its defaults, as before.
            _sl = _src.lower()
            _g = ("female" if re.search(r'\b(woman|female|mom|mother|lady|girl|she|her)\b', _sl)
                  else "male" if re.search(r'\b(man|male|guy|dad|father|he|his)\b', _sl) else None)
            _am = re.search(r'\b(\d{2})\s*[-–]\s*(\d{2})\b', _src)
            if _am:
                _age = f"{_am.group(1)}-{_am.group(2)}"
            else:
                _am2 = re.search(r'\b(\d{2})\s*(?:years?\s*old|yo|y/?o)\b', _src, re.I)
                _age = _am2.group(1) if _am2 else None
            _scm = re.search(r'\bscenes?\b\s*[:\-]\s*(.+?)(?:\.\s|\bvertical\b|\bspeak\b|\bscript\b|["“]|$)',
                             _src, re.I | re.S)
            _scene_detail = (re.sub(r'\s+', ' ', _scm.group(1)).strip()[:300] if _scm else None)
            logger.info(f"[studio/route] user confirmed → make_video VERBATIM ({len(_prior.split())}w, "
                        f"{_pdur or 'auto'}s, gender={_g}, scene={'y' if _scene_detail else 'n'})")
            # source='last_script' keeps allow_rewrite:false (verbatim) on the CL side; seconds 0 → AE
            # auto-sizes from the (now correct) script instead of a forced crush.
            return {"action": "make_video", "source": "last_script", "prompt": _prior, "seconds": _pdur,
                    "request_type": "ugc", "gender": _g, "age_band": None, "age": _age,
                    "scene": None, "scene_detail": _scene_detail}
    if _inline and len(_inline.split()) >= 15 and _wants_video:
        _sm = re.search(r'(\d{1,3})\s*(?:s\b|sec|second)', _msg, re.I); _secs = int(_sm.group(1)) if _sm else 0
        _shown = _secs or max(8, round(len(_inline.split()) / 2.5))   # tell the user the length UP FRONT
        logger.info(f"[studio/route] pasted-script → CONFIRM ({len(_inline.split())}w, ~{_shown}s)")
        return {"action": "reply", "text":
                (f'Got it — here\'s what I\'ll make: a UGC video speaking your script **word-for-word**, '
                 f'**~{_shown} seconds** (sized to your script). Reply **"go"** to make it, or tell me '
                 f'anything to change (character, age, setting, length) first.')}
    # Tune Studio scripts to the vertical's PROVEN converting DNA (same as the orbit/file-request
    # path). Detect the vertical from the caller's hint OR the message/history, then inject the
    # distilled style-DNA so a "write me a home insurance script" ask yields a curated, on-style
    # script — not vague generic copy. No DNA for a vertical → degrades to generic (unchanged).
    from ..services import vertical_dna
    _vt = (vertical or "").strip().lower()
    if not _vt or _vt == "general":
        _blob = (message + " " + hist_text).lower()
        if re.search(r"home\s*insurance|homeowner", _blob):
            _vt = "home insurance"
        elif re.search(r"\bguns?\b|firearm|2a\b|second amendment|ammo|concealed carry", _blob):
            _vt = "guns"
        elif re.search(r"sweepstake|sweeps\b|giveaway|gift ?card", _blob):
            _vt = "sweeps"
    # ALWAYS returns the universal craft DNA (+ the vertical's need if we have it), so every script —
    # any vertical — carries the proven converting craft, not just home insurance.
    _dna = vertical_dna.style_guide(_vt)
    from ..services import script_brief
    _brief_checklist = script_brief.checklist_text()   # the factors a superb script needs (format, audience, setting, angle, offer, geo, tone, length)
    _dna_block = (f"STYLE DNA for this vertical — any write_script / write_ad_copy MUST follow it "
                  f"(match the tone/need/structure; use real specifics; never generic):\n{_dna}\n\n") if _dna else ""
    # NEVER emit bracket placeholders. A script is SPOKEN by a person on camera — "[Website/App Name]"
    # gets read aloud or has to be hand-edited, and if it survives to generation the avatar literally
    # says "bracket website app name". If the user has not given a brand/site, write a natural generic
    # CTA instead ("tap the link below", "click the link on this page", "check your rate at the link").
    _no_placeholder = (
        "NEVER write bracketed placeholders of ANY kind — no [Website], [Brand], [Website/App Name], "
        "[Company], [XX], [State]. The script is spoken aloud by a real person, so a placeholder is a "
        "defect, not a template. If the user did NOT give a website/brand name, do NOT invent one and "
        "do NOT leave a blank: write a natural generic call-to-action instead — e.g. 'tap the link "
        "below', 'click the link on this page', 'check your rate using the link below'. If the user "
        "DID give a site/brand, say it verbatim, naturally, and no more than twice.\n\n")
    # HARD word budget: if the user stated a duration ANYWHERE in the conversation, compute the exact
    # cap (2.5 words/sec) and state it as a hard limit in the write_script prompt. The deterministic
    # trim below (_fit_script_to_seconds) enforces it regardless; this just tells the model up front.
    _brief_secs_src = " ".join((h.get("text") or "") for h in history) + " " + message
    _bm = re.search(r"(\d{1,3})\s*(?:s\b|sec|second)", _brief_secs_src, re.I)
    _brief_secs = int(_bm.group(1)) if _bm else 0
    _budget_line = (
        f"   HARD LIMIT: the chosen duration is {_brief_secs} seconds → write NO MORE THAN "
        f"{round(2.5 * _brief_secs)} words per script for a {_brief_secs}-second read; going over the "
        f"budget is a defect. Keep the hook (first sentence) and the CTA (last sentence) tight.\n"
    ) if _brief_secs > 0 else ""
    # #5 BRIEF STATE (deterministic). Scan the WHOLE conversation for each brief factor and tell the
    # model exactly what's ANSWERED vs MISSING, so it NEVER re-asks something already given (the loop)
    # and stops interviewing once nothing's missing. The model still writes the questions; this just
    # removes its unreliable re-extraction of the history.
    _convo = _brief_secs_src.lower()
    def _has(_rx): return bool(re.search(_rx, _convo, re.I))
    _factors = {
        "format": _has(r"\b(ugc|b-?roll|avatar|image|map)\b"),
        "audience/age": _has(r"\b(\d{2}\s*[-–]\s*\d{2}|under\s*35|55\s*\+|[2-6]0s\b|late\s*[2-6]0s|young|senior|middle[- ]aged|adult|teen)\b"),
        "setting/scene": _has(r"\b(kitchen|porch|car|driving|couch|sofa|living\s*room|office|desk|walk|outdoor|front\s*of|his\s*house|her\s*house|home|yard|street|park)\b"),
        "hook/angle": _has(r"\b(personal\s*story|direct\s*question|question\s*to|neighbor|social\s*proof|shocking|\bstat\b|this\s*is\s*for\s*you)\b"),
        "offer/numbers": _has(r"\$\s*\d|\b\d+\s*(?:dollars|/mo|a\s*month|per\s*month|percent|%)\b"),
        "geo/state": _has(r"\b(nationwide|texas|california|florida|arizona|colorado|georgia|ohio|utah|nevada|new\s*york|\btx\b|\bca\b|\bfl\b|\baz\b|\bco\b|\bga\b|\boh\b|\but\b|\bnv\b|\bny\b)\b"),
        "length/duration": _brief_secs > 0,
    }
    _answered = [k for k, v in _factors.items() if v]
    _still = [k for k, v in _factors.items() if not v]
    # ADVISORY ONLY — this is a keyword scan of the whole conversation. It tests word PRESENCE, so it
    # can false-positive on the AD'S OWN SUBJECT MATTER (a home-insurance script contains "home"; a
    # car ad contains "car"; "$29" in the copy looks like an offer). YOU are the better reader: use it
    # as a hint to avoid re-asking, but if the scan flags a factor the user never actually SPECIFIED,
    # trust your own judgment and ask. Duration is the one reliable signal.
    _brief_state = (
        "BRIEF STATE — keyword scan of the conversation (a HINT, NOT authoritative; it can false-positive "
        "on the ad's own subject matter, so weigh it with your own reading):\n"
        f"  LIKELY ALREADY GIVEN (don't re-ask unless it was only the ad's topic, not a real answer): "
        f"{', '.join(_answered) or '(none yet)'}\n"
        f"  LIKELY STILL MISSING (ask ONLY the ones genuinely unspecified; if truly nothing's missing, "
        f"stop interviewing and confirm/act): {', '.join(_still) or '(seems enough — proceed)'}\n"
        f"  Reliable regardless of the above: duration = {str(_brief_secs)+'s' if _brief_secs else 'NOT stated'}.\n\n")
    # PER-USER LONG-TERM MEMORY (best-effort; NEVER blocks or breaks chat). Inject what we've learned
    # about THIS user (scoped by user_id) so the router personalizes + pre-fills the brief instead of
    # re-asking what they've historically always chosen. Empty (no-op) when we know nothing about them.
    _mem_block = ""
    if user_id:
        try:
            from ..services import user_memory
            _mems = await user_memory.retrieve(user_id, message)
            _prefs = user_memory.preferences(user_id)
            _mem_block = user_memory.render_context_block(_mems, _prefs)
        except Exception as _me:
            logger.warning(f"studio memory retrieve failed: {_me}")
    # How the router may USE that memory: for ONE optional suggestion line only. It must NEVER pre-fill,
    # auto-answer, or skip a brief question, and must NEVER auto-personalize the written script. Present
    # only when we actually know something about the user (else empty → no behavioral change).
    _mem_usage = (
        "USING WHAT WE KNOW ABOUT THIS USER (above): it is for ONE optional, friendly SUGGESTION only. "
        "When you return a 'reply' that gathers the brief, you MAY open with a single short suggestion "
        "line drawn from it — e.g. \"Last time you did a fast personal-story hook for home insurance and "
        "it performed well — want that again, or try something new?\" — and then ask the FULL numbered "
        "brief questions exactly as usual. NEVER use memory to pre-fill, auto-answer, or skip ANY brief "
        "question, and NEVER auto-personalize the written script from it. Always still ask everything.\n\n"
    ) if _mem_block else ""
    ask = (
        "You are the router for a creative video Studio. Read the conversation and the NEW user message, "
        "then output ONE strict-JSON action. Prefer acting over asking for edits/iterations — BUT for a "
        "NEW script/video request that lacks the creative brief, gathering the brief FIRST is the correct "
        "action, not a fallback (see FOLLOW-UP BEFORE WRITING — it is MANDATORY there).\n\n"
        + _no_placeholder + _dna_block + _mem_block + _mem_usage +
        f"CONVERSATION:\n{hist_text}\n\nNEW USER MESSAGE: \"{message}\"\n"
        f"DEFAULT VERTICAL: {_vt or 'general'}\n\n"
        "ACTIONS (pick exactly one; output JSON ONLY, no prose):\n"
        "1) write_script — user wants script(s)/variations/hooks for a video ad:\n"
        '   {"action":"write_script","vertical":"<vertical>","count":N,"seconds":<15|20|30|45|60>,"scripts":[{"title":"...","text":"..."}]}\n'
        "   Each script.text = a complete spoken UGC ad script (the spoken lines only, no scene labels). Cap N at 5.\n"
        "   SIZE THE SCRIPT TO THE REQUESTED LENGTH (~2.5 words/second, 150 wpm): 15s ≈ 40 words, 20s ≈ 50, "
        "   30s ≈ 75, 45s ≈ 110, 60s ≈ 150. Set `seconds` to the chosen duration so it carries to the video "
        "   AND caps the word budget. Do not overrun the word budget.\n"
        + _budget_line + _brief_state +
        "   DIVERSITY (mandatory): each script must use a DIFFERENT hook pattern (personal story | direct "
        "   question | shocking stat | neighbor / social-proof | 'this is for you if…') and FRESH phrasing "
        "   — never reuse the same opening sentence or the same sentence structure as a typical home-insurance "
        "   ad (do NOT default to 'my bill jumped again / a friend mentioned checking rates / two minutes / "
        "   enter your zip'). Rotate the angle. If count>1, the N scripts must be materially different from "
        "   each other — different hooks AND different wording, not minor edits.\n"
        "2) write_ad_copy — user wants ad copy / primary text / captions:\n"
        '   {"action":"write_ad_copy","count":N,"ad_copies":[{"title":"...","text":"..."}]}  Cap N at 5.\n'
        "3) make_video — user wants to make/generate a video/creative/clip:\n"
        '   {"action":"make_video","source":"last_script|last_ad_copy|none","prompt":"...","seconds":15,'
        '"request_type":"ugc|broll","gender":"female|male","age_band":"under35|45-55|55plus",'
        '"age":"the EXACT age the user said, verbatim (e.g. \'35-40\', \'38\', \'late 30s\'); null if unstated",'
        '"scene":"kitchen|porch|car|couch|office|walk|null",'
        '"scene_detail":"the EXACT setting/action the user described, verbatim (e.g. \'walking her dog on a suburban sidewalk\'); null if unstated"}\n'
        "   If the user references a prior script (e.g. \"make a video from that script\"), set source=\"last_script\" "
        "   and set prompt to that script's spoken content. Otherwise source=\"none\" and prompt is the video prompt.\n"
        "   CARRY THE BRIEF. request_type/gender/age_band/scene are the format + casting + SETTING the user "
        "   asked for ANYWHERE in this conversation (including the brief you interviewed them for) — 'b-roll' or "
        "   'no talking head' => request_type=broll, otherwise ugc; a stated person ('woman', 'under 35') "
        "   sets gender/age_band; a stated SETTING sets scene (kitchen/home→kitchen, porch/outdoors→porch, "
        "   car→car, couch/living room→couch, office→office, walk-and-talk→walk). These used to be dropped "
        "   here, so every request generated as UGC with no cast. Omit a field ONLY when the conversation "
        "   truly never indicated it.\n"
        "   CRITICAL — NEVER LOSE THE USER'S EXACT WORDS: age_band/scene are coarse buckets used only as a "
        "   fallback casting hint. You MUST ALSO fill `age` with the user's EXACT age phrase (e.g. '35-40', "
        "   '38', 'late 30s') and `scene_detail` with the user's EXACT setting/action (e.g. 'walking her dog "
        "   on a suburban sidewalk') — verbatim, never rounded to a bucket. If '35-40' has no matching "
        "   age_band bucket, still set age='35-40'; if 'walking her dog' isn't one of the scene words, set "
        "   scene='walk' AND scene_detail='walking her dog'. The office renders from age/scene_detail.\n"
        "4) make_image — user wants a still image/poster/photo:\n"
        '   {"action":"make_image","prompt":"..."}\n'
        "5) reply — conversational, a question, ambiguous, OR gathering the brief (see below):\n"
        '   {"action":"reply","text":"..."}\n\n'
        "USE JUDGMENT — YOU ARE A SMART ASSISTANT, NOT A FORM. Read what the user actually gave you and act:\n"
        "• If the user PASTED a full script (or references one they already wrote) and wants a video → do "
        "NOT interview. RESTATE the plan in one line and CONFIRM before spending: 'Here's what I'll make: "
        "a <length> UGC video speaking your script word-for-word — go, or change anything?' (action=reply). "
        "On the user's next 'go/yes/make it', return make_video (source=last_script, verbatim).\n"
        "• If the user gave ENOUGH to write a great script (see BRIEF STATE — STILL MISSING is empty or only "
        "minor) → WRITE it (or, for a video, RESTATE + confirm). Do NOT re-ask.\n"
        "• ONLY run the numbered brief interview when the request is a genuinely BARE topic with too little "
        "to work from (BRIEF STATE shows several core factors missing). Then ask ONLY the STILL-MISSING "
        "factors as a tight numbered list — NEVER the ALREADY-ANSWERED ones. Length + state are the two you "
        "most often need, but skip either if BRIEF STATE already has it.\n"
        "The point: never make the user repeat themselves, and never spend on a render until they've "
        "confirmed the plan. Trust BRIEF STATE above over your own re-reading of the history.\n"
        + _brief_checklist + "\n"
    )
    try:
        out = await _gemini_json(ask)
        action = str(out.get("action") or "reply").lower()
        # Learn this user's stable preferences + what they made from this turn. Runs as a FastAPI
        # BackgroundTask (NOT asyncio.create_task): a bare create_task is fire-and-forget with no strong
        # reference, so the loop can garbage-collect it before the ~1s Gemini+embed extraction finishes —
        # which is why nothing was ever stored. Starlette reliably awaits BackgroundTasks after the
        # response is sent, so this completes without delaying the reply. Best-effort — never breaks chat.
        if user_id:
            try:
                from ..services import user_memory
                _recent = [{"role": h.get("role") or "user", "text": h.get("text") or ""}
                           for h in history[-8:]]
                _recent.append({"role": "user", "text": message})
                _recent.append({"role": "assistant",
                                "text": f"[took action: {action}; vertical="
                                        f"{out.get('vertical') or _vt}; seconds="
                                        f"{out.get('seconds') or _brief_secs or ''}]"})
                background.add_task(user_memory.extract, user_id, _recent)
            except Exception as _xe:
                logger.warning(f"studio memory extract schedule failed: {_xe}")
        if action == "write_script":
            scripts = [s for s in (out.get("scripts") or []) if (s.get("text") or "").strip()][:5]
            if not scripts:
                return {"action": "reply", "text": "I couldn't draft that — name the product or vertical and I'll write the scripts."}
            _secs = int(out.get("seconds")) if str(out.get("seconds") or "").isdigit() else None
            if _secs and _secs > 0:   # HARD cap: deterministically trim any overrun to the duration's budget
                for s in scripts:
                    s["text"] = _fit_script_to_seconds(s.get("text") or "", _secs)
            return {"action": "write_script", "vertical": out.get("vertical") or vertical,
                    "count": len(scripts), "scripts": scripts, "seconds": _secs}
        if action == "write_ad_copy":
            copies = [c for c in (out.get("ad_copies") or []) if (c.get("text") or "").strip()][:5]
            if not copies:
                return {"action": "reply", "text": "I couldn't draft that — tell me the product and I'll write the ad copy."}
            return {"action": "write_ad_copy", "count": len(copies), "ad_copies": copies}
        if action == "make_video":
            src = str(out.get("source") or "none").lower()
            if src not in ("last_script", "last_ad_copy", "none"):
                src = "none"
            # CARRY THE BRIEF THROUGH. This dict used to whitelist prompt+seconds only, so the
            # format and casting the user asked for were parsed by the model and then dropped
            # right here — which is why every Studio job generated as UGC with no cast.
            _rt = str(out.get("request_type") or "").lower()
            _gd = str(out.get("gender") or "").lower()
            _ab = str(out.get("age_band") or "").lower()
            _sc = str(out.get("scene") or "").lower()
            # DURATION FROM THE BRIEF. The user may have stated the length earlier (e.g. a brief
            # answer "24 SECONDS") rather than in this message. The router's own `seconds` is
            # unreliable (it defaults to 15 on every classify), so it must NEVER win — parse a
            # duration the USER actually stated ANYWHERE in the conversation; if none was ever stated
            # return 0 (=Auto, so AE sizes runtime from the script), never a default.
            _user_said = " ".join((h.get("text") or "") for h in history
                                  if (h.get("role") or "user") == "user") + " " + message
            _sm = re.search(r"(\d{1,3})\s*(?:s\b|sec|second)", _user_said, re.I)
            _stated_secs = int(_sm.group(1)) if _sm else 0
            # CARRY EARLIER-MESSAGE TRAITS. "man, 45+, porch" is usually stated when WRITING the script,
            # not in the "make a video" message — so if the model didn't surface a trait, deterministically
            # recover it from the WHOLE conversation (never override a value the model DID return).
            _low = _user_said.lower()
            if _gd not in ("female", "male"):
                if re.search(r"\b(man|male|guy|gentleman|men|husband|dad|father)\b", _low):
                    _gd = "male"
                elif re.search(r"\b(woman|female|lady|women|wife|mom|mother)\b", _low):
                    _gd = "female"
            if _ab not in ("under35", "45-55", "55plus"):
                if re.search(r"\b(55\+|55 ?plus|60s|70s|senior|elderly|grandma|grandpa|retire)\b", _low):
                    _ab = "55plus"
                elif re.search(r"\b(45\+|45 ?plus|45-55|40s|50s|middle[- ]aged)\b", _low):
                    _ab = "45-55"
                elif re.search(r"\b(under ?35|20s|25-35|young)\b", _low):
                    _ab = "under35"
            if _sc not in ("kitchen", "porch", "car", "couch", "office", "walk"):
                _sc = (("porch" if re.search(r"\b(porch|outdoor|outside|yard|lawn|driveway)\b", _low)
                        else "kitchen" if re.search(r"\bkitchen\b", _low)
                        else "car" if re.search(r"\b(car|vehicle|driving|drive)\b", _low)
                        else "couch" if re.search(r"\b(couch|sofa|living room|living-room)\b", _low)
                        else "office" if re.search(r"\b(office|desk)\b", _low)
                        else "walk" if re.search(r"\b(walk|walking|walk[- ]and[- ]talk)\b", _low)
                        else ""))
            # #5/#6 FREE-TEXT age + scene travel ALONGSIDE the coarse enums so the office honors the
            # user's EXACT ask ("35-40", "38", "walking her dog") instead of a 3-bucket / 7-word default.
            # The enum is a fallback casting hint; the free-text is the source of truth downstream.
            _age_free = str(out.get("age") or "").strip()
            if not _age_free:
                _am = re.search(r"\b(\d{2}\s*[-–to]{1,3}\s*\d{2}|\d{2}\s*\+|(?:early|mid|late)\s*(?:20|30|40|50|60)s|\d{2}\s*(?:years?|yrs?|yo))\b", _low)
                if _am:
                    _age_free = _am.group(1).strip()
            _scene_free = str(out.get("scene_detail") or "").strip()
            return {"action": "make_video", "source": src,
                    "prompt": (out.get("prompt") or message).strip(), "seconds": _stated_secs,
                    "request_type": _rt if _rt in ("ugc", "broll") else None,
                    "gender": _gd if _gd in ("female", "male") else None,
                    "age_band": _ab if _ab in ("under35", "45-55", "55plus") else None,
                    "age": _age_free or None,
                    "scene": _sc if _sc in ("kitchen", "porch", "car", "couch", "office", "walk") else None,
                    "scene_detail": _scene_free or None}
        if action == "make_image":
            return {"action": "make_image", "prompt": (out.get("prompt") or message).strip()}
        return {"action": "reply", "text": (out.get("text") or "Tell me what you'd like to make.").strip()}
    except Exception as e:
        logger.warning(f"studio route failed: {e}")
        return {"action": "reply", "text": "I hit a snag routing that — could you rephrase?"}


@router.get("/studio/memory")
async def studio_memory(user_id: str = "", _auth: bool = Depends(require_service_key)):
    """Diagnostic: the long-term memory stored for ONE user (strict user_id scope). Verifies that writes
    are landing live — no DB access needed. Returns the factual preference map + every stored row."""
    from ..services import user_memory
    uid = str(user_id or "").strip()
    if not uid:
        return {"user_id": "", "preferences": {}, "memories": [], "count": 0}
    prefs = user_memory.preferences(uid)
    mems = user_memory.dump(uid)
    return {"user_id": uid, "preferences": prefs, "memories": mems, "count": len(mems)}


@router.get("/creative-team/reports")
async def creative_team_reports(_auth: bool = Depends(require_service_key)):
    """Per-persona performance ledger (durable, aggregated from Postgres): runs, accuracy,
    revise-rate, helpfulness, accountability, faults, coaching, avg time."""
    from ..services import creative_team_activity as act
    from ..services import creative_team as team
    return {"success": True, **act.reports(), "llm_health": team.llm_health()}


@router.get("/creative-team/audit")
async def creative_team_audit(job_id: str = "", persona: str = "", limit: int = 300,
                              _auth: bool = Depends(require_service_key)):
    """DURABLE per-task / per-persona audit trail (from Postgres). Pass job_id (=request_id) to see
    exactly what every persona did for that job — steps, evals, faults, coaching, retries."""
    from ..services import creative_team_activity as act
    return {"success": True, **act.audit(job_id or None, persona or None, limit)}


@router.get("/creative-team/decision")
async def creative_team_decision(job_id: str = "", _auth: bool = Depends(require_service_key)):
    """What the LEARNER recorded for one job (job_id = request_id): the per-job learning signal —
    QC gate result, ROI (once the platform reports it), the human verdict, and the casting/voice/model
    choices those outcomes attach to. Read-only surface over CreativeDecision (no new computation)."""
    from ..services import learning_loop as learn
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        rows = learn.decisions_for_job(db, job_id) if job_id else []
    finally:
        db.close()
    return {"success": True, "job_id": job_id or None, "count": len(rows), "decisions": rows}


@router.post("/creative-team/grade")
async def creative_team_grade(payload: dict, _auth: bool = Depends(require_service_key)):
    """Grade a LIVE creative's real metrics against the team model (ROI, $500 gate, offer-CR,
    EPC tiers, CPC/state) and COACH the faulted personas — closing the learning loop from real
    outcomes to persona accountability. Input: the metrics dict (+ is_image). Returns the verdict."""
    from ..services import creative_metrics as cm
    from ..services import creative_team_activity as act
    metrics = payload.get("metrics") or payload
    verdict = cm.judge_creative(metrics, is_image=bool(payload.get("is_image")))
    coached = []
    if verdict.get("eligible"):
        for f in verdict.get("faults", []):
            note = f"Live ROI review: {f.get('reason')} on a real creative (spend ${metrics.get('spend')})."
            for p in f.get("personas", []):
                act.coach(p, note)
                coached.append(p)
    return {"success": True, "verdict": verdict, "coached": coached}


@router.post("/creative-team/plan")
async def creative_team_plan(req: "CreativeTeamRequest", _auth: bool = Depends(require_service_key)):
    """Run the creative team to produce a shot PLAN (no generation) — useful to preview what the
    team decides and to drive the office UI on demand."""
    from ..services import creative_team as team
    try:
        plan = await team.run_creative_team(
            offer_desc=req.offer_desc, job_id=req.job_id or "plan-preview",
            vertical=req.vertical, request_type=req.request_type, model=req.model,
            loser_transcript=req.loser_transcript, winner_hook=req.winner_hook,
            winner_transcript=req.winner_transcript,
            has_real_character=req.has_real_character, has_winner_video=req.has_winner_video)
        return {"success": True, "plan": plan}
    except Exception as e:
        logger.error(f"creative-team plan failed: {e}")
        return {"success": False, "error": str(e)}


@router.post("/interpret")
async def interpret(req: InterpretRequest, _auth: bool = Depends(require_service_key)):
    try:
        directive = await _gemini_json(_interpret_prompt(req.context, req.expectation, req.variation_type))
        return {"success": True, "directive": directive}
    except Exception as e:
        logger.error(f"regen interpret failed: {e}")
        return {"success": False, "error": str(e)}


# ── Orchestrator ──────────────────────────────────────────────────────────────
@router.post("/run")
async def run(req: RunRequest, background: BackgroundTasks, _auth: bool = Depends(require_service_key)):
    """Accept the job and run the recipe in the background; return immediately."""
    job_id = req.request_id
    background.add_task(_execute, req)
    return {"success": True, "job_id": job_id, "status": "running"}


# rough per-recipe expected wall-clock (seconds) — seeds the progress bar / ETA; recipes refine it.
_EXPECTED_SEC = {
    "Full Ad": 300, "Create from Assets": 240, "Generate Video": 200,
    "Avatar/UGC": 180, "map + ugc": 180, "Avatar Lipsync": 220, "Script": 120, "Broll": 150, "Stock Video": 150,
    "Hook Change Only": 90, "Caption Change Only": 60, "Reclean/Minor Mod": 60,
    "Image": 120, "Image + Voiceover": 150, "Special Request": 180,
}


# ── Throughput gate + monthly budget guard ──────────────────────────────────
# 10+ jobs run in parallel, but BOUNDED so a burst never crashes the engine; a hard $ ceiling
# means it never burns money; default routing is cheapest-first. All admin-configurable.
_ENGINE = {
    "cap": int(os.getenv("GEN_CONCURRENCY", "10")),                       # max concurrent heavy jobs
    "monthly_budget_usd": float(os.getenv("MONTHLY_BUDGET_USD", "0") or 0),  # 0 = unlimited
    "default_quality": os.getenv("GEN_QUALITY", "bulk"),                  # bulk (cheapest) | premium
    "active": 0,
}
_ENGINE_COND = None


def _engine_cond():
    global _ENGINE_COND
    if _ENGINE_COND is None:
        _ENGINE_COND = asyncio.Condition()
    return _ENGINE_COND


def _month_spend() -> float:
    try:
        from ..database import SessionLocal
        from ..models.creative_team import CreationCost
        from sqlalchemy import func
        from datetime import datetime
        db = SessionLocal()
        try:
            start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            v = db.query(func.coalesce(func.sum(CreationCost.cost_usd), 0.0)).filter(CreationCost.created_at >= start).scalar()
            return float(v or 0)
        finally:
            db.close()
    except Exception:
        return 0.0


def _budget_blocked():
    cap = _ENGINE["monthly_budget_usd"]
    if not cap:
        return (False, 0.0, 0.0)
    spent = _month_spend()
    return (spent >= cap, spent, cap)


async def _execute(req: RunRequest):
    """Pick recipe by variation_type → produce variants → POST back to callback."""
    # SINGLE chokepoint: every recipe (generate / avatar-lipsync / avatar / special / router) is
    # dispatched from here, and this runs as the background task, so setting the request-id contextvar
    # ONCE here attributes ALL nested Gemini reasoning/vision spend (incl. creative_team's own helper)
    # to this job. Without this, any recipe not reached via a per-recipe set would bill to None and
    # silently vanish from the ledger. Per-recipe sets remain as defensive redundancy.
    _CURRENT_RID.set(req.request_id)
    from ..services import creative_team_activity as act
    vtype = (req.variation_type or req.directive.get("chosen_variation_type") or "Hook Change Only")
    label = f"{vtype} · {(req.context.get('creative_filename') or req.assets.get('prompt') or req.request_id)[:60]}"
    act.begin_job(req.request_id, label=label, expected_sec=_EXPECTED_SEC.get(vtype, 180))
    # HARD money guard: never exceed the monthly budget ceiling
    _blocked, _spent, _cap = _budget_blocked()
    if _blocked:
        msg = f"monthly budget reached (${_spent:.2f}/${_cap:.2f}) — generation paused to avoid overspend"
        logger.warning(f"[regen] BUDGET BLOCK {req.request_id}: {msg}")
        await _callback(req.callback_url, {"request_id": req.request_id, "status": "failed", "error": msg, "variants": []})
        act.end_job(req.request_id, ok=False, error=msg)
        return
    # THROUGHPUT GATE: cap concurrent heavy jobs; extras queue here and drain as lanes free
    _cond = _engine_cond()
    async with _cond:
        while _ENGINE["active"] >= _ENGINE["cap"]:
            act.tick(req.request_id, f"queued — {_ENGINE['active']}/{_ENGINE['cap']} lanes busy")
            await _cond.wait()
        _ENGINE["active"] += 1
    logger.info(f"[regen] JOB START id={req.request_id} type={vtype} model={req.model} lane={_ENGINE['active']}/{_ENGINE['cap']} label={label!r}")
    ok = False; err_msg = ""
    try:
        await _abort_if_cancelled(req, "start")
        recipe = _RECIPES.get(vtype, recipe_special)
        variants = await recipe(req)
        ok = True
        _ensure_cost_logged(req.request_id, vtype, len(variants or []))
        logger.info(f"[regen] JOB DONE id={req.request_id} type={vtype} variants={len(variants)}")
        await _callback(req.callback_url, {"request_id": req.request_id, "status": "ready", "variants": variants})
    except Cancelled as c:
        err_msg = str(c)
        logger.info(f"regen run cancelled for {req.request_id}: {c}")
        await _callback(req.callback_url, {"request_id": req.request_id, "status": "cancelled", "error": str(c), "variants": []})
    except Exception as e:
        err_msg = str(e)
        logger.exception(f"regen run failed for {req.request_id}")
        await _callback(req.callback_url, {"request_id": req.request_id, "status": "failed", "error": str(e), "variants": []})
    finally:
        # release the throughput lane so a queued job can start
        async with _cond:
            _ENGINE["active"] = max(0, _ENGINE["active"] - 1)
            _cond.notify(1)
        act.end_job(req.request_id, ok=ok, error=err_msg)
        if not ok and err_msg:   # SELF-LEARNING: record the failure + a corrective rule
            try:
                from ..services import creative_learning as learn
                learn.record_lesson("job", trigger=f"{vtype} generation", reason=err_msg,
                                    rule=f"When running '{vtype}', guard against: {err_msg[:160]}",
                                    style=vtype, vertical=(req.context.get('vertical') if isinstance(req.context, dict) else ''),
                                    job_id=req.request_id)
            except Exception:
                pass


async def _callback(url: Optional[str], payload: dict):
    """POST the result back to CL. A LOST callback orphans a fully-rendered, already-PAID job at
    'running' FOREVER (CL never hears it finished — exactly the "showing generating but never lands"
    bug), so delivery must be durable: retry with backoff, treat ANY non-2xx as a retryable failure
    (httpx does not raise on 4xx/5xx by default → a CL 500/502 would otherwise look like success and
    lose the variant), and log LOUDLY if every attempt fails. Never raises — a callback error must not
    get re-caught by _execute and flipped into a spurious 'failed' callback that buries a ready result."""
    if not url:
        logger.warning("no callback_url; dropping result")
        return
    rid = payload.get("request_id")
    last = None
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(url, json=payload, headers={"x-regen-secret": CALLBACK_SECRET})
            if r.status_code < 300:
                if attempt:
                    logger.info(f"[callback] {rid} delivered on retry #{attempt}")
                return
            last = f"HTTP {r.status_code}: {(r.text or '')[:200]}"
        except Exception as e:
            last = str(e)[:200]
        logger.warning(f"[callback] {rid} attempt {attempt + 1}/5 failed: {last}")
        await asyncio.sleep(min(2 ** attempt, 20))
    logger.error(f"[callback] {rid} PERMANENTLY UNDELIVERED after 5 attempts — a rendered/paid "
                 f"variant is now orphaned at 'running' in CL (self-heal will reconcile it). "
                 f"status={payload.get('status')} last_error={last}")


# ── Recipes (each returns a list of variant dicts) ────────────────────────────
async def _transcribe_original(download_url: str) -> str:
    """Download the ORIGINAL creative and transcribe it so generation is grounded
    in what the ad actually says — never a hardcoded/invented script."""
    if not download_url:
        return ""
    path = await _download_to_temp(download_url)
    try:
        return await _transcribe_file(path)   # extracts compact audio (handles 25MB cap)
    finally:
        try: os.remove(path)
        except OSError: pass


async def recipe_avatar(req: RunRequest) -> list:
    """Avatar/UGC + map+ugc: elderly-female avatar speaks the script with native
    lip-sync via TikTok Symphony. The script is ANCHORED to the original creative's
    real transcript (preserve topic/message); only modified per an explicit directive.
    NOTE: this is the *net-new* lane — it changes the spokesperson/setting. For
    fixing a loser while preserving its look, use a surgical recipe instead."""
    # 1) ground in the original's actual content
    original_script = await _transcribe_original(req.context.get("download_url", ""))
    # 2) explicit rewrite directive wins; else POLISH the transcript into a tighter UGC hook
    #    targeting the lagging metric (keeps the offer/claims); else use the raw transcript.
    directive_script = req.directive.get("script_directive")
    if directive_script and directive_script != "none":
        script = directive_script
    elif original_script:
        script = original_script
        hint = (req.context.get("diagnosis", {}) or {}).get("directive_hint", "")
        try:
            d = await _gemini_json(
                'Rewrite this into a tight, natural first-person UGC ad voiceover (~30-45s) that '
                'KEEPS the same offer and claims but hooks harder in the first line. '
                f'{("Focus: " + hint) if hint else ""} Original: "{original_script[:1200]}". '
                'Return JSON {"script":"..."}')
            script = (d.get("script") or original_script).strip()
        except Exception as e:
            logger.warning(f"avatar script polish failed, using transcript: {e}")
    else:
        raise RuntimeError("could not transcribe the original and no script directive given — refusing to generate unrelated content")

    # last credit-safety gate before the paid TikTok render (kept OUTSIDE the fallback guard
    # below so a real cancellation is never swallowed into a fallback).
    await _abort_if_cancelled(req, "avatar generation")

    # TikTok Symphony is the only synthetic-avatar provider. Wrap the whole render so a
    # Symphony outage / quota / API error degrades to our real-footage lip-sync lane
    # (when a character clip is available) instead of failing the entire job.
    try:
        # avatar persona from the directive (de-hardcoded); sensible default for this vertical
        avatar_id = await _pick_avatar(
            age=(req.directive.get("avatar_age") or "elderly"),
            gender=(req.directive.get("avatar_gender") or "female"),
            region=(req.directive.get("avatar_region") or "namer"))
        if not avatar_id:
            raise RuntimeError("no matching avatar found")

        # one avatar render per request (deterministic for a given script)
        loop = asyncio.get_event_loop()
        created = await loop.run_in_executor(None, lambda: TikTokSymphonyService.create_avatar_video(
            avatar_id=avatar_id, script=script, video_name=f"regen_{req.request_id[:8]}"
        ))
        task_id = (created.get("data", {}).get("list", [{}]) or [{}])[0].get("task_id")
        if not task_id:
            raise RuntimeError(f"avatar create returned no task_id: {created}")
        url = await _poll_avatar(task_id)
        if not url:
            raise RuntimeError("avatar render timed out/failed")
    except Exception as e:
        char_url = (req.assets or {}).get("character_video_url") or getattr(req, "active_url", None)
        if char_url:
            logger.warning(f"TikTok Symphony avatar failed ({e}) — degrading to real-footage lip-sync lane")
            try:
                return await recipe_avatar_lipsync(req)
            except Exception as e2:
                logger.error(f"avatar lip-sync fallback also failed: {e2}")
        raise RuntimeError(
            f"Avatar render failed via TikTok Symphony ({e}) and no fallback path was available. "
            f"Check TIKTOK_ACCESS_TOKEN / advertiser credits, or attach a character clip so the "
            f"real-footage lip-sync lane can be used instead.")

    # Remove the TikTok "AI-generated" watermark (bottom strip) + add ONE clean lower-third CTA
    # caption (the avatar speaks the exact script, so a CTA is coherent + never garbled).
    final_url = url
    work = tempfile.mkdtemp()
    try:
        raw = await _download_to_temp(url)
        W, H = await asyncio.to_thread(_ffprobe_dims, raw)
        keep_h = (int(H * 0.92) // 2) * 2  # even height for yuv420p, drops the watermark strip
        # clean CTA from the offer (imperative, drives click)
        cta = ""
        try:
            hint = (req.context.get("diagnosis", {}) or {}).get("directive_hint", "")
            dc = await _gemini_json(f'Write ONE punchy on-screen CTA caption (4-7 words, imperative) '
                                    f'for this UGC ad. {("Goal: "+hint) if hint else ""} '
                                    f'Script: "{script[:400]}". Return JSON {{"caption":"..."}}')
            cta = (dc.get("caption") or "").strip()
        except Exception:
            pass
        name, out_path, out_url = _out_url(req, "avatar")
        if cta:
            cta_png = os.path.join(work, "cta.png")
            await asyncio.to_thread(_make_caption_png, cta, W, H, cta_png)
            await asyncio.to_thread(_ffmpeg,
                ["-i", raw, "-i", cta_png, "-filter_complex",
                 f"[0:v]crop={W}:{keep_h}:0:0,scale={W}:{H}[v0];[v0][1:v]overlay=0:0[v]",
                 "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "21", "-pix_fmt", "yuv420p", "-threads", "2", "-c:a", "aac", "-b:a", "192k",
                 out_path], timeout=300)
        else:
            await asyncio.to_thread(_ffmpeg,
                ["-i", raw, "-vf", f"crop={W}:{keep_h}:0:0,scale={W}:{H}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                 "-threads", "2", "-c:a", "aac", "-b:a", "192k", out_path], timeout=300)
        final_url = out_url
        try: os.remove(raw)
        except OSError: pass
    except Exception as e:
        logger.warning(f"avatar post-process failed, serving raw: {e}")
    finally:
        import shutil; shutil.rmtree(work, ignore_errors=True)

    return [{
        "recipe": "Avatar/UGC (TikTok Symphony)",
        "video_url": final_url,
        "confidence": 0.6,
        "whats_changed": f"Net-new avatar ad (watermark removed). Script: {script[:120]}",
    }]


async def _pick_avatar(age: str, gender: str, region: str) -> Optional[str]:
    """Scan avatar pages for a tag match (age/gender/region)."""
    loop = asyncio.get_event_loop()
    for page in range(1, 8):
        res = await loop.run_in_executor(None, lambda: TikTokSymphonyService.get_avatars(page, 50))
        items = (res.get("data", {}) or {}).get("list", []) or []
        for a in items:
            tags = {g["tag_type"]: g.get("tags", []) for g in a.get("tag_groups", [])}
            if (age in tags.get("age", []) and gender in tags.get("gender", [])
                    and region in tags.get("region", [])):
                return a.get("avatar_id")
    # fallback: first elderly female anywhere
    res = await loop.run_in_executor(None, lambda: TikTokSymphonyService.get_avatars(1, 50))
    for a in (res.get("data", {}) or {}).get("list", []) or []:
        tags = {g["tag_type"]: g.get("tags", []) for g in a.get("tag_groups", [])}
        if "elderly" in tags.get("age", []) and "female" in tags.get("gender", []):
            return a.get("avatar_id")
    return None


async def _poll_avatar(task_id: str, tries: int = 40, delay: int = 8) -> Optional[str]:
    loop = asyncio.get_event_loop()
    for _ in range(tries):
        res = await loop.run_in_executor(None, lambda: TikTokSymphonyService.get_avatar_video_status([task_id]))
        lst = (res.get("data", {}) or {}).get("list", []) or []
        if lst:
            t = lst[0]
            if (t.get("status") or "").upper() == "SUCCESS":
                vi = t.get("video_info") or t
                return t.get("preview_url") or vi.get("video_url") or vi.get("url")
            if (t.get("status") or "").upper() in ("FAILED", "ERROR"):
                return None
        await asyncio.sleep(delay)
    return None


def _delogo_chain(boxes, W, H):
    """Build ffmpeg delogo filters that blur out detected caption regions (any position)."""
    parts = []
    for b in (boxes or []):
        try:
            x = max(1, int(W * float(b["x"]))); y = max(1, int(H * float(b["y"])))
            w = int(W * float(b["w"])); h = int(H * float(b["h"]))
            w = min(w, W - x - 1); h = min(h, H - y - 1)
            if w > 4 and h > 4:
                parts.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
        except Exception:
            continue
    return (",".join(parts) + ",") if parts else ""


async def _stitch_hook(stock, orig, cap_png, W, H, hook_end, fps, out_path, cover_boxes=None):
    """Replace [0:hook_end] visual with the source clip + ONE caption overlay; keep the
    original's hook audio + the entire body (a+v) untouched. Re-stitch.
    cover_boxes (for reused winner footage) blurs out the donor's burned caption regions
    wherever they are, so the source can't show its own (conflicting) text."""
    post = _delogo_chain(cover_boxes, W, H)   # blur donor captions after scaling to WxH
    fc = (
        f"[0:v]trim=0:{hook_end},setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},{post}fps={fps}[hk];"
        f"[hk][2:v]overlay=0:0[hv];"
        f"[1:a]atrim=0:{hook_end},asetpts=PTS-STARTPTS[ha];"
        f"[1:v]trim={hook_end},setpts=PTS-STARTPTS,scale={W}:{H},fps={fps}[bv];"
        f"[1:a]atrim={hook_end},asetpts=PTS-STARTPTS[ba];"
        f"[hv][ha][bv][ba]concat=n=2:v=1:a=1[outv][outa]"
    )
    await asyncio.to_thread(_ffmpeg,
        ["-i", stock, "-i", orig, "-loop", "1", "-t", str(hook_end), "-i", cap_png,
         "-filter_complex", fc, "-map", "[outv]", "-map", "[outa]",
         # lighter on a small instance: ultrafast preset + bounded mux queue + threads cap
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-threads", "2", "-max_muxing_queue_size", "1024",
         "-c:a", "aac", "-b:a", "192k", out_path], timeout=900)


async def recipe_hook_change(req: RunRequest) -> list:
    """SURGICAL fix — one accurate pass (no human-in-loop QA):
       ANALYZE the original (Vision) for the real hook boundary + an on-screen caption,
       pick a FORMAT-MATCHED proven winner, AUTO-STRIP that donor's burned captions so
       they can't clash, add ONE clean caption, and re-stitch. Keeps the original's
       voice + entire body; only the opening visual changes. Correct by construction."""
    FPS = 30
    download_url = req.context.get("download_url", "")
    if not download_url:
        raise RuntimeError("no original download_url in context")

    orig = await _download_to_temp(download_url)
    work = tempfile.mkdtemp()
    try:
        W, H = await asyncio.to_thread(_ffprobe_dims, orig)
        dur = await asyncio.to_thread(_ffprobe_duration, orig)
        transcript = await _transcribe_file(orig)

        # Metric-driven: the diagnosis tells us WHAT to fix and the target to lift.
        diag = req.context.get("diagnosis", {}) or {}
        hint = diag.get("directive_hint") or ""
        lagging = diag.get("lagging_metric") or ""

        # ── ANALYZE the original (one vision pass): real hook boundary + caption ──
        oframes = await asyncio.to_thread(_extract_frames, orig,
                    [0.3, 1.0, 2.5, 4.0, min(6.0, max(0.0, dur - 0.5))], work)
        analysis = {}
        try:
            analysis = await _gemini_vision(oframes,
                'You are analyzing frames (in order) from the START of a UGC video ad. '
                f'Its transcript: "{transcript[:1200]}". '
                + (f'This ad is underperforming on {lagging}. The fix should: {hint} '
                   'Write the hook_caption so it directly serves that goal. ' if hint else '')
                + 'Return STRICT JSON: '
                '{"hook_end_sec": <seconds where the opening hook shot ends, 2-6>, '
                '"hook_caption": "<a punchy 4-8 word ON-SCREEN caption that tells a scroller exactly what this ad is about/its offer>", '
                '"stock_queries": ["<3 simple 1-2 word stock-footage search terms for a relevant opening visual>"]}')
        except Exception as e:
            logger.warning(f"vision analyze failed: {e}")
        try:
            hook_end = float(analysis.get("hook_end_sec") or 3.5)
        except Exception:
            hook_end = 3.5
        hook_end = max(2.0, min(hook_end, 6.0, (dur - 1.0) if dur else 3.5))
        caption = (analysis.get("hook_caption") or "").strip() or (" ".join(transcript.split()[:7]) or "WATCH THIS")
        queries = [q for q in (analysis.get("stock_queries") or []) if isinstance(q, str) and q.strip()]
        queries += ["lifestyle", "people", "city"]

        # ── SOURCE selection (resolve ONE) ────────────────────────────────────
        await _abort_if_cancelled(req, "generation")
        src_path, src_label, is_winner = None, None, False

        # PRIMARY for MAP-format losers: render a CLEAN state map — caption-free, correct
        # geo, no donor text to scrub. This is the deterministic correct source for maps.
        fname = req.context.get("filename", "") or ""
        state = _detect_state(fname) or _detect_state(transcript)
        if state and "MAP" in fname.upper():
            map_png = os.path.join(work, "map.png")
            ok = await asyncio.to_thread(_render_state_map, state, W, H, map_png)
            if ok:
                map_clip = os.path.join(work, "map_clip.mp4")
                frames = max(1, int(hook_end * FPS))
                await asyncio.to_thread(_ffmpeg,
                    ["-loop", "1", "-t", str(hook_end), "-i", map_png,
                     "-vf", (f"scale={W*2}:{H*2},zoompan=z='min(zoom+0.0010,1.25)':d={frames}:"
                             f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}"),
                     "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                     "-t", str(hook_end), map_clip])
                src_path = map_clip
                src_label = f"clean {STATE_ABBR.get(state.upper(), state)} map"
                is_winner = False

        # On-offer relevance basis: what is THIS ad actually selling?
        offer_desc = (caption + " — " + transcript[:220]).strip()
        cover_boxes = []

        from ..services import winner_library
        lib_winners = winner_library.fetch_winners(req.context.get("vertical", ""), limit=8)

        # NOTE: Hook Change is a SURGICAL VISUAL swap that keeps the original AUDIO for the
        # hook seconds — so the new opening must be a NON-talking visual (map/b-roll/stock),
        # NOT a talking-head. A full talking winner-clone (its own voice) belongs in the
        # "Winner Clone" (Broll) lane, where it's used as a self-contained ad. So we do NOT
        # inject a Seedance talking-head here (that caused voice/caption/audio mismatch).

        # ── your OWN proven winner (same editor) — direct transplant, caption-masked ──
        if not src_path:
          for wh in (req.context.get("winner_hooks") or []):
            if not wh.get("download_url"):
                continue
            try:
                cand = await _download_to_temp(wh["download_url"])
            except Exception as e:
                logger.warning(f"winner download failed: {e}")
                continue
            wframes = await asyncio.to_thread(_extract_frames, cand,
                        [hook_end * 0.3, hook_end * 0.6, hook_end * 0.9], work)
            if not await _asset_is_relevant(wframes, offer_desc):
                continue
            boxes = await _detect_caption_boxes(wframes)
            if _boxes_area(boxes) > 0.16:
                continue
            src_path, src_label, is_winner, cover_boxes = cand, \
                f"your winner '{(wh.get('filename') or '')[:30]}' (roas {wh.get('roas')})", True, boxes
            break

        # else: stock footage — LAST resort, relevance-gated
        if not src_path:
            for q in queries:
                c = await asyncio.to_thread(StockFootageService.get_broll, q,
                                            ("portrait" if H >= W else "landscape"), 30)
                if not (c and c.get("local_path")):
                    continue
                sframes = await asyncio.to_thread(_extract_frames, c["local_path"], [0.5, 1.5], work)
                if not await _asset_is_relevant(sframes, offer_desc):
                    continue
                src_path, src_label, is_winner = c["local_path"], f"stock '{q}'", False
                break

        # else: GENERATE an on-offer clip (Veo / Higgsfield / Runway) — never fail for footage
        if not src_path:
            ref_vids = [lib_winners[0]["url"]] if lib_winners else None  # Seedance motion ref
            gen = await _generate_clip(offer_desc, shot_type="b_roll", duration=max(4, int(hook_end) + 1),
                                       model=req.model, reference_video_urls=ref_vids, request_type="broll")
            if gen:
                src_path, src_label, is_winner = gen, "an AI-generated on-offer clip (Veo/Higgsfield)", False
        if not src_path:
            raise RuntimeError("no on-offer hook source; generation failed: "
                               + (getattr(_generate_clip, "last_error", "") or "no provider configured (set HIGGSFIELD_API_KEY[:secret] on the engine)"))

        # ── GENERATE: one clean caption + stitch (donor captions masked if reusing a winner) ──
        cap_png = os.path.join(work, "cap.png")
        await asyncio.to_thread(_make_caption_png, caption, W, H, cap_png)
        await _abort_if_cancelled(req, "stitch")
        out_name = f"regen_hook_{req.request_id[:8]}.mp4"
        out_path = os.path.join(UPLOAD_DIR, out_name)
        await _stitch_hook(src_path, orig, cap_png, W, H, hook_end, FPS, out_path, cover_boxes=cover_boxes)

        return [{
            "recipe": "Hook Change Only (surgical)",
            "video_url": f"{AE_PUBLIC_URL}/api/v1/uploads/{out_name}",
            "confidence": 0.8,
            "whats_changed": (
                f"Replaced only the first {hook_end:.1f}s hook with {src_label}"
                + (" (its burned captions auto-removed)" if is_winner else "")
                + f", added on-screen caption \"{caption}\"; kept the original voice + entire body."
            ),
        }]
    finally:
        try: os.remove(orig)
        except OSError: pass
        try:
            import shutil; shutil.rmtree(work, ignore_errors=True)
        except Exception: pass


def _out_url(req, kind):
    name = f"regen_{kind}_{req.request_id[:8]}.mp4"
    return name, os.path.join(UPLOAD_DIR, name), f"{AE_PUBLIC_URL}/api/v1/uploads/{name}"


def _ae_persist(out_path: str, name: str) -> None:
    """Durable copy of a produced video into the AFFILIATE-ENGINE's own S3 bucket (best-effort), so
    the video lives in BOTH buckets (AE S3 + creative-library S3) — not just AE's ephemeral /uploads."""
    try:
        from ..services.storage import StorageService
        u = StorageService.upload_file(out_path, f"regen/{name}")
        if u:
            logger.info(f"[regen] AE S3 persisted {name} → {u}")
    except Exception as e:
        logger.warning(f"AE S3 persist failed for {name}: {e}")


async def recipe_caption_change(req: RunRequest) -> list:
    """Add/refresh a bold on-screen CTA caption over the original (drives CTR). Keeps
    everything else; overlays one new caption band across the video."""
    orig = await _download_to_temp(req.context.get("download_url", ""))
    work = tempfile.mkdtemp()
    try:
        W, H = await asyncio.to_thread(_ffprobe_dims, orig)
        dur = await asyncio.to_thread(_ffprobe_duration, orig)
        transcript = await _transcribe_file(orig)
        hint = (req.context.get("diagnosis", {}) or {}).get("directive_hint", "")
        cap = ""
        try:
            d = await _gemini_json(
                f'Write ONE punchy on-screen CTA caption (4-7 words, imperative, drives the click) for this ad. '
                f'{("Goal: " + hint) if hint else ""} Transcript: "{transcript[:900]}". Return JSON {{"caption":"..."}}')
            cap = (d.get("caption") or "").strip()
        except Exception:
            pass
        cap = cap or "TAP TO LEARN MORE"
        # caption-clash guard: place the new CTA clear of the ad's EXISTING burned captions
        bframes = await asyncio.to_thread(_extract_frames, orig,
                    [0.5, max(0.6, dur * 0.4), max(1.0, dur * 0.8)], work)
        y_frac = _pick_caption_y(await _detect_caption_boxes(bframes))
        cap_png = os.path.join(work, "cta.png")
        await asyncio.to_thread(_make_caption_png, cap, W, H, cap_png, y_frac=y_frac)
        name, out_path, url = _out_url(req, "caption")
        await asyncio.to_thread(_ffmpeg,
            ["-i", orig, "-i", cap_png, "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
             "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast",
             "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "2", "-c:a", "copy", out_path], timeout=900)
        return [{"recipe": "Caption Change Only", "video_url": url, "confidence": 0.7,
                 "whats_changed": f'Added on-screen CTA caption "{cap}" over the original to lift CTR; everything else unchanged.'}]
    finally:
        for p in (orig,):
            try: os.remove(p)
            except OSError: pass
        import shutil; shutil.rmtree(work, ignore_errors=True)


async def recipe_reclean(req: RunRequest) -> list:
    """Reclean / minor remaster: clean re-encode + light contrast/saturation lift +
    audio loudness normalization. Same content, crisper delivery."""
    orig = await _download_to_temp(req.context.get("download_url", ""))
    try:
        name, out_path, url = _out_url(req, "reclean")
        await asyncio.to_thread(_ffmpeg,
            ["-i", orig, "-vf", "eq=contrast=1.06:saturation=1.08,unsharp=5:5:0.5",
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-threads", "2", "-c:a", "aac", "-b:a", "192k", out_path], timeout=900)
        return [{"recipe": "Reclean/Minor Mod", "video_url": url, "confidence": 0.7,
                 "whats_changed": "Remastered: light contrast/sharpness lift + normalized loudness. Content unchanged."}]
    finally:
        try: os.remove(orig)
        except OSError: pass


async def recipe_script_rewrite(req: RunRequest) -> list:
    """Rewrite the script (Gemini) and re-voice it IN THE SPOKESPERSON'S VOICE via
    ElevenLabs clone, then lay it over the original visuals. Best for VO/B-roll ads
    (talking-head lip-sync won't match). Requires ELEVENLABS_API_KEY."""
    from ..services.elevenlabs_service import ElevenLabsService
    orig = await _download_to_temp(req.context.get("download_url", ""))
    work = tempfile.mkdtemp()
    voice_id = None
    try:
        transcript = await _transcribe_file(orig)
        hint = (req.context.get("diagnosis", {}) or {}).get("directive_hint", "")
        d = await _gemini_json(
            f'Rewrite this ad script to convert better WITHOUT losing the offer, claims, or core story. '
            f'{("Focus: " + hint) if hint else ""} Keep it the same approximate length. '
            f'Original: "{transcript[:1500]}". Return JSON {{"script":"..."}}')
        new_script = (d.get("script") or "").strip()
        if not new_script:
            raise RuntimeError("script rewrite produced nothing")

        if not ElevenLabsService.is_configured():
            # Voiced rewrite needs the clone key; return the rewritten script so it's not lost.
            return [{"recipe": "Script (rewrite)", "video_url": None, "confidence": 0.5,
                     "whats_changed": "Rewrote the script (below). Voiced version needs ELEVENLABS_API_KEY set on the engine.\n\n" + new_script[:600]}]

        # clone the spokesperson's voice from a sample of the original audio
        sample = os.path.join(work, "sample.mp3")
        await asyncio.to_thread(_ffmpeg, ["-i", orig, "-t", "45", "-vn", "-ac", "1", "-ar", "22050", "-b:a", "96k", sample])
        vo = os.path.join(work, "vo.mp3")
        cloned_ok = False
        try:
            voice_id = await asyncio.to_thread(ElevenLabsService.clone_voice, sample, f"regen-{req.request_id[:8]}")
            await asyncio.to_thread(ElevenLabsService.tts, voice_id, new_script, vo)
            cloned_ok = True
        except Exception as ce:
            # Cloning must NEVER kill the generation (401 Unauthorized / 402 quota / network /
            # any error). Fall back to a gender/age-matched preset voice — the same brain-casting
            # used everywhere else — and keep the job going. Log a warning for visibility.
            logger.warning(f"voice clone failed ({ce}) — falling back to a matched preset voice")
            from ..services import voice_studio as _vs
            ctx = req.context or {}
            char = ctx.get("character") or {}
            try:
                picked = _vs.pick_voice(gender=ctx.get("gender") or char.get("gender"),
                                        age_band=ctx.get("age_band") or char.get("age_band"),
                                        tone=(req.context.get("diagnosis", {}) or {}).get("directive_hint"))
            except ValueError as _ve:
                # unknown character gender / no eligible voice — don't guess a preset; fail closed.
                raise RuntimeError(f"voice not cast: {_ve}")
            await asyncio.to_thread(_vs.synthesize, new_script, voice_id=picked.get("id"), out_path=vo)

        name, out_path, url = _out_url(req, "script")
        # lay the new VO over the original visuals; length = the new VO
        await asyncio.to_thread(_ffmpeg,
            ["-i", orig, "-i", vo, "-map", "0:v:0", "-map", "1:a:0", "-shortest",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-threads", "2", "-c:a", "aac", "-b:a", "192k", out_path], timeout=900)
        return [{"recipe": "Script (rewrite, cloned voice)" if cloned_ok else "Script (rewrite, matched voice)",
                 "video_url": url, "confidence": 0.65 if cloned_ok else 0.6,
                 "whats_changed": ("Rewrote the script + re-voiced it in the spokesperson's cloned voice over the original visuals."
                                   if cloned_ok else
                                   "Rewrote the script + re-voiced it in a gender/age-matched voice (clone unavailable) over the original visuals.")}]
    finally:
        try:
            from ..services.elevenlabs_service import ElevenLabsService as _E
            if voice_id: await asyncio.to_thread(_E.delete_voice, voice_id)
        except Exception: pass
        try: os.remove(orig)
        except OSError: pass
        import shutil; shutil.rmtree(work, ignore_errors=True)


async def recipe_broll(req: RunRequest, label="Broll") -> list:
    """Topic-matched stock B-roll clip + on-screen caption (net-new short)."""
    orig = await _download_to_temp(req.context.get("download_url", ""))
    work = tempfile.mkdtemp()
    try:
        W, H = await asyncio.to_thread(_ffprobe_dims, orig)
        transcript = await _transcribe_file(orig)
        try:
            d = await _gemini_json(f'From this transcript give 3 stock search terms + one 5-word caption. '
                                   f'Transcript:"{transcript[:900]}". Return JSON {{"queries":[".."],"caption":".."}}')
        except Exception as e:
            # Both LLMs down → don't sink the clip; fall back to transcript-derived terms/caption.
            logger.warning(f"broll query/caption LLM failed ({e}) — using transcript-derived terms")
            d = {}
        queries = (d.get("queries") or []) + ["lifestyle", "city"]
        caption = (d.get("caption") or " ".join(transcript.split()[:6]) or "WATCH THIS")
        offer_desc = (caption + " — " + transcript[:220]).strip()

        # ── UGC-BROLL: real b-roll montage + first-person VOICEOVER + kinetic captions ─────────
        # The reference format (S2-TX-UGC-BROLL): scenic lifestyle/property footage (NO face-to-cam,
        # NO lip-sync) under a first-person VO, with bold word-by-word captions that box the numbers/
        # keywords. Taken whenever there's a real spoken script (assets.script, honoring allow_rewrite,
        # else the source transcript). Best-effort: any gap (no footage / synth / align) falls through
        # to the simple stock-clip behavior below — never a hard fail.
        # The variation route nests the caller's script under directive.assets (dispatchRun
        # forwards the directive, not the top-level assets), so fall back to it when req.assets is
        # empty — the same idiom recipe_full_ad uses. Top-level assets wins when present. Without
        # this the UGC branch never saw the script and dropped to the simple stock+original-audio path.
        _assets = req.assets or req.directive.get("assets", {}) or {}
        _assets = _assets if isinstance(_assets, dict) else {}
        script = _verbatim_user_script(_assets) or (transcript or "").strip()
        if len((script or "").split()) >= 6:
            try:
                from ..services import voice_studio as vs
                from ..services import captions as cap
                intent = {"vertical": (req.context.get("vertical") or ""),
                          "scene": (_assets.get("scene") or ""),
                          "gender": (req.context.get("gender") or ""),
                          "age_band": (req.context.get("age_band") or "")}
                # (b) full-script expressive VO — length of the ad = length of this VO
                vo = os.path.join(work, f"vo_{req.request_id[:8]}.mp3")
                _bstyle = ("first-person UGC testimonial, natural, conversational, upbeat, talking to "
                           "camera, never flat or monotone")
                _log_model_call(req.request_id, "voice", "auto", {"text": (script or "")[:400], "style": _bstyle})
                _bvo = await asyncio.to_thread(lambda: vs.synthesize(script, out_path=vo, style=_bstyle))
                T = await asyncio.to_thread(_audio_seconds, vo) if os.path.exists(vo) else 0.0
                if T <= 0:
                    raise RuntimeError("VO synthesis produced no audio")
                # (c) gather footage — tagged library b-roll FIRST, then top up with stock.
                # RELEVANCE: library b-roll is already vertical-filtered by _cast_library_broll, but
                # STOCK is keyword-matched and can drift off-topic (the classic "leaf-blower on a
                # weight-loss ad"). Vision-gate every stock clip against the offer before it enters the
                # montage, so the b-roll is actually about what the script is selling.
                srcs = []
                for u in await _cast_library_broll(intent, limit=8):
                    try:
                        srcs.append(await _download_to_temp(u, ".mp4"))
                    except Exception as de:
                        logger.warning(f"[broll] library clip download failed: {de}")
                needed = max(1, int(T // 4) + 1)
                qi = 0
                while len(srcs) < needed and qi < len(queries):
                    c = await asyncio.to_thread(StockFootageService.get_broll, queries[qi], "portrait", 30)
                    qi += 1
                    if not (c and c.get("local_path") and c["local_path"] not in srcs):
                        continue
                    # on-offer relevance gate (fails open on error) — keep b-roll on-topic
                    try:
                        _rf = await asyncio.to_thread(_extract_frames, c["local_path"], [0.5, 1.5], work)
                        if not await _asset_is_relevant(_rf, offer_desc):
                            logger.info(f"[broll] stock clip rejected as off-offer for query '{queries[qi-1]}'")
                            continue
                    except Exception as _re:
                        logger.warning(f"[broll] stock relevance check errored (allowing): {_re}")
                    srcs.append(c["local_path"])
                # (d) montage: scale/crop each clip to 1080x1920, ~4s silent cuts, until total >= T
                TW, TH, SEG = 1080, 1920, 4.0
                seg_paths, total, idx, guard = [], 0.0, 0, 0
                while total < T and srcs and guard < 200:
                    src = srcs[idx % len(srcs)]
                    pass_no = idx // len(srcs); idx += 1; guard += 1
                    sd = await asyncio.to_thread(_ffprobe_duration, src)
                    if sd <= 0.4:
                        continue
                    off = min(pass_no * SEG, max(0.0, sd - 1.0))     # different window on re-use
                    take = min(SEG, sd - off)
                    if take < 1.0:
                        off, take = 0.0, min(SEG, sd)
                    seg = os.path.join(work, f"seg_{len(seg_paths):03d}.mp4")
                    try:
                        await asyncio.to_thread(_ffmpeg,
                            ["-ss", f"{off:.2f}", "-i", src, "-t", f"{take:.2f}", "-an",
                             "-vf", f"scale={TW}:{TH}:force_original_aspect_ratio=increase,"
                                    f"crop={TW}:{TH},fps=30,setpts=PTS-STARTPTS",
                             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                             "-pix_fmt", "yuv420p", "-threads", "2", seg], 300)
                    except Exception as se:
                        logger.warning(f"[broll] segment build failed: {se}"); continue
                    seg_paths.append(seg); total += take
                if seg_paths:
                    # concat the montage and hard-trim to EXACTLY the VO length
                    listf = os.path.join(work, "broll_concat.txt")
                    with open(listf, "w") as f:
                        for s in seg_paths:
                            f.write("file '%s'\n" % s.replace("'", "'\\''"))
                    montage = os.path.join(work, "montage.mp4")
                    await asyncio.to_thread(_ffmpeg,
                        ["-f", "concat", "-safe", "0", "-i", listf, "-t", f"{T:.2f}", "-an",
                         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                         "-pix_fmt", "yuv420p", "-threads", "2", montage], 600)
                    # (e) mux the VO as the ONLY audio (b-roll clips are muted)
                    muxed = os.path.join(work, "broll_muxed.mp4")
                    await asyncio.to_thread(_ffmpeg,
                        ["-i", montage, "-i", vo, "-map", "0:v:0", "-map", "1:a:0",
                         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", muxed], 300)
                    # (f) kinetic word-by-word captions burned over the montage
                    name, out_path, url = _out_url(req, "broll")
                    ass = None
                    try:
                        words, _m = await asyncio.to_thread(lambda: cap.align(vo, script))
                        if words:
                            ass = cap.build_kinetic_ass(
                                words, os.path.join(work, f"kin_{req.request_id[:8]}.ass"),
                                play_w=TW, play_h=TH)
                    except Exception as ae:
                        logger.warning(f"[broll] kinetic captions skipped: {ae}")
                    if ass and os.path.exists(ass):
                        await asyncio.to_thread(_ffmpeg,
                            ["-i", muxed, "-vf", f"ass={ass}", "-c:v", "libx264", "-preset", "veryfast",
                             "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", out_path], 600)
                    else:
                        import shutil; shutil.move(muxed, out_path)
                    _ae_persist(out_path, name)
                    return [{"recipe": label, "video_url": url, "confidence": 0.62,
                             "whats_changed": (f'{label}: UGC b-roll montage ({len(seg_paths)} clips) with a '
                                f'first-person voiceover + kinetic word-by-word captions. Length = VO ({T:.0f}s).'),
                             "models": {"video": None, "voice": (_bvo.get("provider") if isinstance(_bvo, dict) else None),
                                        "voice_cloned": False, "lipsync": None,
                                        "captions": ("whisper+ass" if (ass and os.path.exists(ass)) else None),
                                        "recipe": label},
                             "model_calls": _drain_model_calls(req.request_id)}]
                logger.info("[broll] UGC-BROLL found no footage — falling back to simple stock b-roll")
            except Cancelled:
                raise
            except Exception as ue:
                logger.warning(f"[broll] UGC-BROLL path failed ({ue}) — falling back to simple stock b-roll")

        clip = None
        from ..services import winner_library
        _lw = winner_library.fetch_winners(req.context.get("vertical", ""), limit=1)

        # TRUE B-ROLL = NO on-camera person. The winner-clone branch below recreates a proven
        # winning ad — but our winners are TALKING-HEAD competitor ads, so cloning one reproduces a
        # talking head, which is exactly what a "b-roll" request must NOT be. So winner-clone is now
        # OPT-IN (assets.allow_winner_clone) and the DEFAULT is real scenic footage (stock → AI
        # scene, no face). This is the fix for "I asked for b-roll and got a talking head."
        _allow_winner_clone = bool((req.assets or {}).get("allow_winner_clone")) if isinstance(req.assets, dict) else False
        if _lw and not _allow_winner_clone:
            logger.info("[broll] winner-clone would reproduce a talking head — skipping it; "
                        "producing true scenic b-roll (no on-camera person)")

        # ── PRIMARY: winner-clone (conversion-first) — OPT-IN ONLY ────────────
        if _lw and _allow_winner_clone:
            ref_imgs = await _select_references(orig, work, offer_desc)
            winner_clip = await _prep_winner_clip(_lw[0]["url"], work)   # None if too long/failed
            if winner_clip:
                gen = await _generate_clip(
                    offer_desc, shot_type="b_roll", duration=12,
                    model=MultiProviderVideoService.route_capability("reference_to_video", req.model),
                    reference_video_urls=[winner_clip],
                    reference_image_urls=(ref_imgs or None),
                    winner_hook=_lw[0].get("hook"), vertical=req.context.get("vertical"),
                    request_type=(req.variation_type or "ugc"))
                if gen:
                    clip = {"local_path": gen, "id": "winner-clone (Seedance)"}
                else:
                    logger.error(f"winner-clone gen failed: {getattr(_generate_clip,'last_error','')}")

        # ── else: relevant stock (last resort) ────────────────────────────────
        if not clip:
            for q in queries:
                c = await asyncio.to_thread(StockFootageService.get_broll, q, ("portrait" if H >= W else "landscape"), 30)
                if not (c and c.get("local_path")):
                    continue
                sframes = await asyncio.to_thread(_extract_frames, c["local_path"], [0.5, 1.5], work)
                if not await _asset_is_relevant(sframes, offer_desc):
                    continue
                clip = c; break

        # ── else: plain AI generation (no winner) ─────────────────────────────
        if not clip:
            gen = await _generate_clip(offer_desc, shot_type="b_roll", duration=6, model=req.model,
                                       request_type="broll")
            if gen:
                clip = {"local_path": gen, "id": "ai-generated"}
        if not clip:
            raise RuntimeError("no on-offer footage; generation failed: "
                               + (getattr(_generate_clip, "last_error", "") or "no provider configured (set HIGGSFIELD_API_KEY[:secret] on the engine)"))
        name, out_path, url = _out_url(req, "broll")
        is_clone = str(clip.get("id", "")).startswith("winner-clone")

        if is_clone:
            # SELF-CONTAINED Seedance ad: keep ITS OWN synced voice/audio; caption is derived
            # from ITS OWN speech so voice+caption+audio all match (coherent). No original-audio
            # overlay, no pre-decided caption — that's what made the earlier output incoherent.
            cpath = clip["local_path"]
            cw, ch = await asyncio.to_thread(_ffprobe_dims, cpath)
            ccap = ""
            # only add OUR caption if the clone is text-free (avoid doubling Seedance's own text)
            cframes = await asyncio.to_thread(_extract_frames, cpath, [0.6, 2.0, 4.0], work)
            clone_has_text = _boxes_area(await _detect_caption_boxes(cframes)) > 0.03
            if not clone_has_text:
                clone_tx = ""
                try:
                    clone_tx = await _transcribe_file(cpath)
                except Exception as e:
                    logger.warning(f"clone transcribe failed: {e}")
                # Filter Whisper SOUND artifacts ("[music]", "sad music plays", "(applause)") and
                # no-real-speech clips — those must NOT become the caption.
                words = re.findall(r"[a-zA-Z']{3,}", clone_tx or "")
                artifact = (not clone_tx.strip()
                            or re.search(r"music|applause|silence|laughter|\[|\]|\(|\)", clone_tx, re.I)
                            or len(words) < 4)
                if not artifact:
                    try:
                        d2 = await _gemini_json(
                            'From this ad voiceover, write ONE short on-screen caption (3-6 words) that '
                            f'MATCHES what is actually being said. Voiceover: "{clone_tx[:300]}". '
                            'Return JSON {"caption":"..."}')
                        ccap = (d2.get("caption") or "").strip()
                    except Exception as e:
                        logger.warning(f"clone caption failed: {e}")
                else:
                    ccap = caption   # no clear speech (music/ambient) → use the on-offer CTA
            if ccap:
                cc_png = os.path.join(work, "cc.png")
                await asyncio.to_thread(_make_caption_png, ccap, cw, ch, cc_png)
                await asyncio.to_thread(_ffmpeg,
                    ["-i", cpath, "-i", cc_png, "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
                     "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast",
                     "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "2", "-c:a", "aac", "-b:a", "192k",
                     out_path], timeout=600)
            else:
                await asyncio.to_thread(_ffmpeg,
                    ["-i", cpath, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out_path], timeout=600)
            return [{"recipe": "Winner Clone (Seedance)", "video_url": url, "confidence": 0.7,
                     "whats_changed": (f'Winner-clone of a top {req.context.get("vertical","")} winner using your '
                        f'creative as references — self-contained (its OWN synced voice/audio)'
                        + (f', caption matches its speech: "{ccap}"' if ccap else '') + '.')}]

        # ── stock / silent b-roll: overlay ORIGINAL audio + CTA caption (coherent for silent assets) ──
        cap_png = os.path.join(work, "cap.png")
        await asyncio.to_thread(_make_caption_png, caption, W, H, cap_png)
        await asyncio.to_thread(_ffmpeg,
            ["-i", clip["local_path"], "-i", orig, "-i", cap_png, "-filter_complex",
             f"[0:v]trim=0:8,setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30[v0];"
             f"[v0][2:v]overlay=0:0[v];[1:a]atrim=0:8,asetpts=PTS-STARTPTS[a]",
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-threads", "2", "-c:a", "aac", "-b:a", "192k", out_path], timeout=600)
        return [{"recipe": label, "video_url": url, "confidence": 0.55,
                 "whats_changed": f'{label}: topic-matched stock ("{clip.get("id","")}") + caption "{caption}" + original audio.'}]
    finally:
        try: os.remove(orig)
        except OSError: pass
        import shutil; shutil.rmtree(work, ignore_errors=True)


async def recipe_special(req: RunRequest) -> list:
    """Special Request: route the interpreter's chosen recipe, else surface clarifications."""
    chosen = (req.directive.get("chosen_variation_type") or "").strip()
    clar = req.directive.get("conflicts_or_clarifications") or []
    if chosen and chosen in _RECIPES and chosen != "Special Request":
        return await _RECIPES[chosen](req)
    return [{"recipe": "Special Request", "video_url": None, "confidence": 0.4,
             "whats_changed": ("Needs clarification: " + "; ".join(clar)) if clar
                              else f"Could not map to a recipe. Parsed: {req.directive.get('recipe_steps')}"}]


def _record_qc(request_id: str, beat: dict, ev: dict, unverified: bool = False,
               stage: str = "clip") -> None:
    """PERSIST every critic verdict to creative_decisions so the loop has a REAL scored history.
    Previously evaluate_clip's score was used for in-flight retries and then THROWN AWAY — nothing
    was written, so /learn/decisions returned [] and nothing accumulated across runs. Append-only,
    best-effort: a logging failure must never break a generation."""
    try:
        from ..models.creative_team import CreativeDecision
        from ..database import SessionLocal
        issues = [str(i) for i in (ev.get("issues") or [])][:6]
        reasons = {"stage": stage, "beat": beat.get("i"), "shot_type": beat.get("shot_type"),
                   "overall": ev.get("overall"), "realism": ev.get("realism"),
                   "lipsync": ev.get("lipsync"), "captions": ev.get("captions"),
                   "verified": not unverified, "issues": issues,
                   "fault_personas": ev.get("fault_personas") or []}
        db = SessionLocal()
        try:
            db.add(CreativeDecision(
                request_id=request_id,
                qc_passed=(False if unverified else bool(_team_eval_passed(ev))),
                qc_reasons=json.dumps(reasons)[:4000],
                blamed_brains=json.dumps(ev.get("fault_personas") or [])[:1000],
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        # LOUD on purpose: this silently returned decisions:[] for every job, so the learning loop
        # recorded nothing and nobody knew. Log the type + message so the next run names the cause.
        logger.error(f"[critic] FAILED to persist QC verdict for {request_id}: "
                     f"{type(e).__name__}: {e}", exc_info=True)

    # CLOSE THE LOOP. Writing the verdict to creative_decisions only builds a history nothing reads;
    # the lessons table is the one store that actually reaches the next generation's prompt
    # (lessons_for_prompt / learned_engine_avoid). So a FAILED verdict becomes a lesson right here —
    # that is the difference between recording mistakes and not repeating them. Separate try: a QC
    # persist failure must not stop the learning write, and vice versa.
    try:
        if unverified or not _team_eval_passed(ev):
            from ..services import creative_learning as learn
            for issue in [str(i) for i in (ev.get("issues") or [])][:3]:
                if not issue.strip():
                    continue
                learn.record_lesson(
                    "clip", trigger=f"{stage} QA failed ({beat.get('shot_type') or 'clip'})",
                    reason=issue[:500], rule=f"Avoid: {issue[:400]}",
                    job_id=request_id)
    except Exception as e:
        logger.warning(f"[critic] lesson write failed for {request_id}: {e}")


async def _shrink_for_lipsync(char_url: str, request_id: str, max_mb: float = 18.0) -> Optional[str]:
    """Re-encode an avatar clip small enough for the cheap lip-sync endpoints' input limits.
    Returns a new public URL, or None to keep the original (never raises — this must not break a job)."""
    from ..services.storage import StorageService
    try:
        src = await _download_to_temp(char_url, ".mp4")
        if not src or not os.path.exists(src):
            return None
        if os.path.getsize(src) <= max_mb * 1024 * 1024:
            return None                                   # already small enough — don't re-encode
        small = os.path.join(UPLOAD_DIR, f"ls_{request_id[:8]}.mp4")
        await asyncio.to_thread(_ffmpeg,
            ["-i", src, "-vf", "scale='min(720,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "28", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-y", small], 300)
        if not os.path.exists(small):
            return None
        up = StorageService.upload_file(small, f"lipsrc/{os.path.basename(small)}")
        url = (StorageService.presign_url(up) or up) if up else None
        if url:
            logger.info(f"[avatar-lipsync] source shrunk "
                        f"{os.path.getsize(src)/1e6:.1f}MB → {os.path.getsize(small)/1e6:.1f}MB for the cheap lane")
        return url
    except Exception as e:
        logger.warning(f"[avatar-lipsync] source shrink skipped ({e}) — submitting the original")
        return None


async def _final_video_qa(request_id: str, out_path: str, script: str, work: str) -> dict:
    """HOLISTIC QA on the FINAL assembled video — the only stage that sees what the user receives.

    The clip-level critic grades each clip in isolation BEFORE stitching and BEFORE any post pass,
    so it is structurally blind to exactly the defects that shipped: (a) clip 2 repeating clip 1's
    lines (each clip looks fine alone), (b) an incomplete script (tail never spoken), and
    (c) artifacts introduced after grading. This transcribes the FINAL audio and vision-checks the
    FINAL frames. Best-effort: never blocks delivery, but always records an honest verdict."""
    issues, dup_ratio, spoken = [], 0.0, ""
    try:
        from ..services import captions as cap
        _wav = os.path.join(work, "finalqa.wav")
        await asyncio.to_thread(_ffmpeg, ["-i", out_path, "-vn", "-ac", "1", "-ar", "16000", "-y", _wav], 120)
        words, _m = await asyncio.to_thread(lambda: cap.align(_wav, script or ""))
        spoken = " ".join([str(w.get("word") or w.get("text") or "") for w in (words or [])]).strip()
        if spoken:
            # DUPLICATION: does the opening line reappear later? (the "same video twice" defect)
            _toks = spoken.lower().split()
            if len(_toks) >= 16:
                _head = " ".join(_toks[:8])
                if spoken.lower().count(_head) > 1:
                    issues.append(f"DUPLICATE SPEECH — the opening line is spoken "
                                  f"{spoken.lower().count(_head)}× (clips repeat instead of advancing)")
            # COMPLETENESS: did the tail of the script actually get said?
            _s = (script or "").lower().split()
            if len(_s) >= 12:
                _tail = " ".join(_s[-6:])
                import difflib as _dl
                if not _dl.SequenceMatcher(None, _tail, spoken.lower()[-160:]).ratio() > 0.35 \
                        and _tail.split()[-1] not in spoken.lower():
                    issues.append("INCOMPLETE — the end of the script (CTA) was never spoken")
            # SCRIPT FIDELITY: does the video speak the script it was GIVEN at all? Completeness only
            # checks the tail, so a video that speaks a totally different script still passed.
            if _s:
                import difflib as _dl2
                _ratio = _dl2.SequenceMatcher(None, _s, _toks).ratio()
                if _ratio < 0.55:
                    issues.append("SCRIPT MISMATCH - the video does not speak the script it was "
                                  f"given (similarity {_ratio:.0%})")
    except Exception as e:
        logger.warning(f"[final-qa] transcript check skipped: {e}")
    # VISION on the final frames (catches post-stitch artifacts: blown-out eyes, morphing, warping)
    ev = {}
    try:
        from ..services import creative_team as team
        _dur = await asyncio.to_thread(_ffprobe_duration, out_path)
        _ts = [t for t in (1.0, (_dur or 12) / 2.0, max(1.0, (_dur or 12) - 1.5))]
        _frames = await asyncio.to_thread(_extract_frames, out_path, _ts, work)
        if _frames:
            ev = await team.evaluate_clip(_frames, {"i": "final", "shot_type": "talking_head"}) or {}
            issues += [str(i) for i in (ev.get("issues") or [])]
    except Exception as e:
        logger.warning(f"[final-qa] vision check skipped: {e}")
    verdict = {**ev, "issues": issues, "final_qa": True}
    # A FINAL defect (duplicate speech / incomplete / script-mismatch / a post-stitch artifact) must
    # count as a FAILED verdict so _record_qc flags the creative_decisions row AND turns each issue
    # into a lesson — even when the vision frames scored clean, because eval_passed only reads
    # `overall` and is structurally blind to the transcript checks above. Pin the score below the bar
    # (7) so the failure and its lessons actually land where the Learning tab reads them.
    if issues and _team_eval_passed(verdict):
        verdict["overall"] = min(float(ev.get("overall") or 0), 3.0)
    _record_qc(request_id, {"i": "final"}, verdict,
               unverified=(ev.get("overall") is None and not spoken), stage="final_video")
    if issues:
        logger.warning(f"[final-qa] request {request_id} FINAL defects: {issues}")
    else:
        logger.info(f"[final-qa] request {request_id} clean")
    return verdict


def _team_eval_passed(ev: dict) -> bool:
    try:
        from ..services import creative_team as _t
        return _t.eval_passed(ev)
    except Exception:
        return False


async def _openai_vision_json(frame_paths: list, prompt: str) -> dict:
    """CROSS-FAMILY vision judge for the EVAL GATE: base64 frames → OpenAI gpt-4o → strict JSON.
    Deliberately NOT Gemini so the final examiner does not self-grade the family that graded in-flight.
    Raises if the key is missing (caller falls back to the in-house Gemini vision)."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    def _call() -> str:
        from openai import OpenAI
        oai = OpenAI(api_key=settings.openai_api_key)
        content: list = [{"type": "text", "text": prompt}]
        for fp in frame_paths:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        resp = oai.chat.completions.create(
            model=EVAL_JUDGE_MODEL, temperature=0.1,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": content}])
        return resp.choices[0].message.content or "{}"
    return json.loads(await asyncio.to_thread(_call))


async def _cross_family_vision(frame_paths: list, prompt: str):
    """Prefer the CROSS-FAMILY OpenAI judge; fall back to the in-house Gemini vision (and NOTE it).
    Returns (json_dict, engine) where engine ∈ {'openai','gemini','none'}."""
    if settings.openai_api_key:
        try:
            return await _openai_vision_json(frame_paths, prompt), "openai"
        except Exception as e:
            logger.warning(f"[eval-gate] OpenAI judge failed ({e}) — falling back to Gemini vision")
    try:
        return await _gemini_vision(frame_paths, prompt), "gemini"
    except Exception as e:
        logger.warning(f"[eval-gate] Gemini vision fallback also failed ({e})")
        return {}, "none"


async def _eval_gate(request_id: str, final_path: str, script: str, assets: dict, work: str) -> dict:
    """GLOBAL EVAL GATE — the examiner. Measures the DELIVERED file against the brief and turns every
    verdict into an action, then auto-delivers ONLY when it passes.

    A video can LOOK done yet fail FAITHFULNESS (wrong/garbled script, residual burned-in captions from
    the source footage, an abrupt end that clips the last word, the wrong cast). The clip-level critic
    grades each clip BEFORE stitch/post, so it is structurally blind to those. This runs on the FINAL
    file: cheap OBJECTIVE code checks + a CROSS-FAMILY OpenAI semantic judge. It NEVER rewards shape
    (length/keywords) — only the observable outcome — writes each dimension to creative_decisions
    (_record_qc) + creative_lessons (record_lesson 'eval'), and returns a deliver decision.

    Best-effort: any internal error DEFAULTS TO DELIVER (never blocks the pipeline) but is logged.
    Returns {faithful, quality, confidence, deliver, reasons, issues, overall, ...}."""
    try:
        assets = assets if isinstance(assets, dict) else {}
        reasons: list = []
        checks: list = []   # (name, passed) — passed True/False, or None when the check could not run

        # ── did-it-render (baseline) + per-stream durations (reused by the abrupt check) ──────────
        try:
            rendered = bool(final_path and os.path.isfile(final_path)
                            and os.path.getsize(final_path) > 1000)
        except Exception:
            rendered = False
        vdur = adur = 0.0
        try:
            vdur = await asyncio.to_thread(_stream_duration, final_path, "v")
            adur = await asyncio.to_thread(_stream_duration, final_path, "a")
        except Exception as e:
            logger.warning(f"[eval-gate] stream-duration probe failed: {e}")

        # AUGMENT the existing holistic final-video QA — run it ONCE here (transcript duplication /
        # incompleteness / script-mismatch + the in-house Gemini vision grade + its own
        # creative_decisions row). Both recipes now call _eval_gate instead of _final_video_qa, so it
        # still runs exactly once — no double work.
        fqa = {}
        try:
            fqa = await _final_video_qa(request_id, final_path, script, work) or {}
        except Exception as e:
            logger.warning(f"[eval-gate] final_video_qa skipped: {e}")
        fqa_issues = [str(i) for i in (fqa.get("issues") or [])]

        # 3 FINAL frames — shared by the residual-caption, cast, and semantic checks (extract once).
        frames = []
        try:
            _d = vdur or await asyncio.to_thread(_ffprobe_duration, final_path) or 12.0
            frames = await asyncio.to_thread(_extract_frames, final_path,
                                             [1.0, _d / 2.0, max(1.0, _d - 1.5)], work)
        except Exception as e:
            logger.warning(f"[eval-gate] frame extract failed: {e}")

        # ── 1a. FAITHFULNESS — final audio transcript vs the script (overlap + $/number survival) ──
        faithful = None
        try:
            ok, why = await _audio_matches_script(final_path, script or "")
            faithful = bool(ok)
            checks.append(("faithful", faithful))
            if not faithful:
                reasons.append(f"faithfulness: {why}")
        except Exception as e:
            logger.warning(f"[eval-gate] faithfulness check errored: {e}")

        # ── 1b. NEVER-ABRUPT — video must not end before the audio (a clipped last word) ──────────
        not_abrupt = None
        try:
            if vdur and adur:
                not_abrupt = (adur - vdur) <= 0.15
                checks.append(("not_abrupt", not_abrupt))
                if not not_abrupt:
                    reasons.append(f"abrupt end: video {vdur:.1f}s < audio {adur:.1f}s (last word cut)")
        except Exception as e:
            logger.warning(f"[eval-gate] abrupt check errored: {e}")

        # ── 1b′. NO TRAILING DEAD-AIR — video must not HANG on a frozen tail after speech ends ──────
        # The MIRROR of never-abrupt: a fixed-length t2v clip whose narration finishes early leaves a
        # frozen frame + dead silence that "hangs". The t2v lane trims this upstream; this is the safety
        # net so it never ships unnoticed when the trim could not run. Detect where the final trailing
        # silence begins (silencedetect); flag as a spec/quality issue if the dead-air exceeds ~1.5s.
        no_dead_air = None
        try:
            if vdur:
                _spk_end = await asyncio.to_thread(_speech_end_ts, final_path, vdur)
                if _spk_end is not None:
                    _dead = vdur - _spk_end
                    no_dead_air = _dead <= 1.5
                    checks.append(("no_dead_air", no_dead_air))
                    if not no_dead_air:
                        reasons.append(f"trailing dead-air / frozen tail: {_dead:.1f}s of silence after "
                                       f"the last word (video {vdur:.1f}s, speech ends ~{_spk_end:.1f}s)")
        except Exception as e:
            logger.warning(f"[eval-gate] trailing dead-air check errored: {e}")

        # ── 1c. NO RESIDUAL CAPTIONS — only when OUR captions are OFF ──────────────────────────────
        # The caller passes the RESOLVED captions flag (whether we actually burned any). If ours are
        # OFF but the detector still finds burned-in text, it is the source footage's captions → fail.
        # If ours are ON, on-screen text is expected → skip.
        no_residual = None
        try:
            our_caps = bool(assets.get("captions", False))
            if not our_caps and frames:
                boxes = await _detect_caption_boxes(frames[:3])
                no_residual = not boxes
                checks.append(("no_residual", no_residual))
                if not no_residual:
                    reasons.append("residual source captions: burned-in text on screen but "
                                   "OUR captions are OFF")
        except Exception as e:
            logger.warning(f"[eval-gate] residual-caption check errored: {e}")

        # ── 1d. SPECS — duration within the requested budget (±25%); resolution matches request ────
        spec_ok = None
        try:
            _req_secs = assets.get("seconds")
            if _req_secs and str(_req_secs).lower() != "auto" and vdur:
                _want = float(_req_secs)
                if _want > 0 and abs(vdur - _want) > _want * 0.25:
                    spec_ok = False
                    reasons.append(f"spec: duration {vdur:.1f}s off the {_want:.0f}s request (>25%)")
                else:
                    spec_ok = spec_ok if spec_ok is False else True
            _req_res = str(assets.get("resolution") or "").lower()
            if _req_res and frames:
                _short_want = {"480p": 480, "540p": 540, "720p": 720, "1080p": 1080}.get(_req_res)
                if _short_want:
                    _w, _h = await asyncio.to_thread(_video_dims, final_path)
                    if abs(min(_w, _h) - _short_want) > 0.15 * _short_want:
                        spec_ok = False
                        reasons.append(f"spec: resolution {_w}x{_h} ≠ requested {_req_res}")
                    else:
                        spec_ok = spec_ok if spec_ok is False else True
            if spec_ok is not None:
                checks.append(("spec", spec_ok))
        except Exception as e:
            logger.warning(f"[eval-gate] spec check errored: {e}")

        # ── 1e. CAST (best-effort) — on-camera gender vs the requested cast ───────────────────────
        cast_ok = None
        try:
            _want_g = str(assets.get("gender") or "").strip().lower()
            if _want_g in ("man", "male", "woman", "female") and frames:
                _norm = "man" if _want_g in ("man", "male") else "woman"
                jr, _eng = await _cross_family_vision(frames[:2],
                    'Look at the on-camera person in these video frames. Return STRICT JSON '
                    '{"person":"man|woman|unclear"} — the apparent gender presentation only.')
                seen = str((jr or {}).get("person") or "").lower()
                if seen in ("man", "woman"):
                    cast_ok = (seen == _norm)
                    checks.append(("cast", cast_ok))
                    if not cast_ok:
                        reasons.append(f"cast: requested {_norm} but the on-camera person looks {seen}")
        except Exception as e:
            logger.warning(f"[eval-gate] cast check errored: {e}")

        # ── 1f. B-ROLL PRESENCE — a UGC+B-Roll ask MUST ship with real b-roll, not a silent plain
        # talking-head. The composite lane falls back to plain on ANY shortfall (empty library, compose
        # failure), and that fallback is invisible to every pixel/audio check above. So the CALLER passes
        # _ugc_broll_requested (was it a UGC+B-Roll job) + _broll_applied (did the composite actually
        # swap in b-roll); a requested-but-not-applied job is a hard fault. STRICT NO-OP when the key is
        # absent/falsey → plain Avatar Lipsync and every other caller are never penalized.
        broll_present = None
        try:
            if assets.get("_ugc_broll_requested"):
                broll_present = bool(assets.get("_broll_applied"))
                checks.append(("broll_present", broll_present))
                if not broll_present:
                    reasons.append("b-roll missing: UGC+B-Roll was requested but the final shipped a "
                                   "plain talking-head")
        except Exception as e:
            logger.warning(f"[eval-gate] b-roll presence check errored: {e}")

        # ── 2. SEMANTIC JUDGE — CROSS-FAMILY (OpenAI gpt-4o), one-line rubrics, booleans only ─────
        real_ok = arti_ok = lip_ok = None
        judge_engine = "none"
        hard_artifact = False
        if frames:
            try:
                jr, judge_engine = await _cross_family_vision(frames[:3],
                    'You are a strict ad-QA examiner looking at frames from a FINAL delivered video ad. '
                    'Judge ONLY what is OBSERVABLE in the pixels (ignore length, keywords, intent). '
                    'Return STRICT JSON {"real_not_plastic": true|false, "no_visible_artifacts": '
                    'true|false, "lipsync_natural": true|false, "why": "<=8 words"}. Set '
                    'no_visible_artifacts=false ONLY for a HARD defect: laser/blown-out eyes, warped or '
                    'extra fingers/hands, melting faces, mirrored or gibberish on-screen text.')
                if judge_engine != "none" and jr:
                    real_ok = bool(jr.get("real_not_plastic", True))
                    arti_ok = bool(jr.get("no_visible_artifacts", True))
                    lip_ok = bool(jr.get("lipsync_natural", True))
                    _why = str(jr.get("why") or "").strip()
                    if not real_ok:
                        reasons.append(f"semantic: looks plastic/AI ({_why})".strip())
                    if not lip_ok:
                        reasons.append(f"semantic: lip-sync unnatural ({_why})".strip())
                    if not arti_ok:
                        reasons.append(f"semantic: visible artifact ({_why})".strip())
                        # A HARD artifact only BLOCKS delivery when the CROSS-FAMILY (OpenAI) judge saw
                        # it — the Gemini fallback already fed _final_video_qa, so don't double-block.
                        hard_artifact = (judge_engine == "openai")
                    if judge_engine == "gemini":
                        logger.info(f"[eval-gate] {request_id} semantic graded by Gemini fallback "
                                    f"(OpenAI key missing/failed)")
            except Exception as e:
                logger.warning(f"[eval-gate] semantic judge errored: {e}")

        # ── 3. CONFIDENCE + DELIVER ───────────────────────────────────────────────────────────────
        _obj = [p for (_n, p) in checks if p is not None]
        obj_frac = (sum(1 for p in _obj if p) / len(_obj)) if _obj else 1.0
        _sem = [p for p in (real_ok, arti_ok, lip_ok) if p is not None]
        sem_frac = (sum(1 for p in _sem if p) / len(_sem)) if _sem else 1.0
        confidence = round(0.20 * (1.0 if rendered else 0.0) + 0.50 * obj_frac + 0.30 * sem_frac, 2)
        # deliver ONLY if faithfulness, never-abrupt, no-residual and b-roll-presence all pass AND no
        # hard artifact. A check that could not run (None) is treated as non-blocking (best-effort,
        # never over-block) — so broll_present stays None (→ pass) for non-UGC+B-Roll callers.
        deliver = bool((faithful is not False) and (not_abrupt is not False)
                       and (no_residual is not False) and (broll_present is not False)
                       and (not hard_artifact))

        verdict = {
            "faithful": (faithful is not False),
            "quality": bool(obj_frac >= 0.999 and sem_frac >= 0.999),
            "confidence": confidence,
            "deliver": deliver,
            "reasons": reasons,
            "semantic_engine": judge_engine,
            # compat with the existing generate/avatar surfacing (reads .issues / .overall):
            "issues": (fqa_issues + reasons),
            "overall": fqa.get("overall"),
            "eval_gate": True,
        }

        # ── 4/5. RECORD → creative_decisions (_record_qc) + creative_lessons (record_lesson 'eval') ─
        # Passes record a qc_passed=True row so ROI can attach later; fails record a failing row.
        try:
            _ev = {"overall": (8.0 if deliver else 3.0),
                   "issues": (reasons if reasons else (["eval clean"] if deliver else [])),
                   "final_qa": True, "eval_gate": True}
            _record_qc(request_id, {"i": "eval"}, _ev, unverified=(not rendered), stage="eval")
        except Exception as e:
            logger.warning(f"[eval-gate] QC persist skipped: {e}")
        # Every FAIL dimension → a permanent EVAL-scoped lesson (Learning tab + next-run signal).
        try:
            from ..services import creative_learning as learn
            _fails = []
            if faithful is False:    _fails.append(("faithfulness", "spoken audio does not match the script"))
            if not_abrupt is False:  _fails.append(("abrupt-end", "video ends before the narration (last word cut)"))
            if no_dead_air is False: _fails.append(("trailing-dead-air", "video hangs on a frozen tail after the narration ends"))
            if no_residual is False: _fails.append(("residual-captions", "source footage's burned-in captions on screen"))
            if hard_artifact:        _fails.append(("visible-artifact", "hard visual artifact (eyes/hands/warp/text)"))
            if cast_ok is False:     _fails.append(("cast-mismatch", "on-camera person is the wrong gender"))
            if spec_ok is False:     _fails.append(("spec-mismatch", "duration/resolution off the request"))
            for _dim, _detail in _fails:
                learn.record_lesson("eval", trigger=_dim, reason=_detail[:500],
                                    rule=f"Avoid: {_dim}", job_id=request_id)
        except Exception as e:
            logger.warning(f"[eval-gate] lesson write skipped: {e}")

        if deliver:
            logger.info(f"[eval-gate] {request_id} PASS (confidence {confidence})")
        else:
            logger.warning(f"[eval-gate] {request_id} NEEDS REVIEW (confidence {confidence}): {reasons}")
        return verdict
    except Exception as e:
        # An eval-internal error must NEVER block a real render — default to deliver, but log loudly.
        logger.error(f"[eval-gate] {request_id} internal error → defaulting to DELIVER: {e}",
                     exc_info=True)
        return {"faithful": True, "quality": True, "confidence": 0.5, "deliver": True,
                "reasons": [f"eval-gate error: {e}"], "semantic_engine": "error",
                "issues": [], "overall": None, "eval_gate": True}


async def _gen_beat_with_eval(job_id: str, beat: dict, work: str, gen_attempt) -> Optional[str]:
    """Generate ONE beat, then run the eval self-learning loop: vision-QA the result, and if it
    scores below the bar, coach the faulted persona(s) + fold the correction into the beat prompt
    and regenerate — bounded by MAX_BEAT_RETRIES to protect credits. Returns the best clip path."""
    from ..services import creative_team as team
    from ..services import creative_team_activity as act
    clip = None
    attempts = 0
    while attempts <= team.MAX_BEAT_RETRIES:
        clip = await gen_attempt(beat)          # reads beat['prompt'] each time (coaching mutates it)
        if not clip:
            return None
        frames = []
        try:
            frames = await asyncio.to_thread(_extract_frames, clip, [1.0], work)
        except Exception:
            pass
        ts = act.start("critic", job_id, f"visual QA beat {beat.get('i')}")
        ev = await team.evaluate_clip(frames, beat)
        ok = team.eval_passed(ev)
        _unver = team.eval_unverified(ev)
        _ovr = ev.get("overall")
        act.finish("critic", job_id, ts, ok=(not _unver), revised=(not ok and not _unver),
                   detail=(f"beat {beat.get('i')} UNVERIFIED — vision QA unavailable (NOT graded)"
                           if _unver else f"beat {beat.get('i')} scored {_ovr}/10"),
                   helpfulness=(None if _unver else float(_ovr) / 10.0))
        # Record EVERY evaluation (pass, fail, or unverified) so there is a real scored history.
        _record_qc(job_id, beat, ev, unverified=_unver)
        if _unver:
            # Vision is down — retrying cannot improve a score we cannot read, and burning paid
            # retries here is pure waste. Ship the clip but it stays flagged UNVERIFIED (never a pass).
            logger.warning(f"[critic] beat {beat.get('i')} UNVERIFIED (vision QA unavailable) — "
                           f"delivering ungraded; flagged for human review")
            return clip
        if ok:
            for p in ("prompt", "character", "shots"):
                act.reward(p, job_id=job_id)
            return clip
        if attempts >= team.MAX_BEAT_RETRIES:
            break
        team.coach_from_eval(beat, ev, job_id=job_id)   # one-on-one + rewrite the beat prompt for the retry
        attempts += 1
    return clip                                  # bounded: return the last (best-effort) attempt


def _rewrite_allowed(assets: dict) -> bool:
    """Whether the creative office may REWRITE the caller's script (improve the hook). Default True
    (the 'Improve my hook' toggle ships ON). Turned OFF explicitly via allow_rewrite=false OR the
    legacy script_mode='verbatim'. One decision, read identically by every lane."""
    if not isinstance(assets, dict):
        return True
    if "allow_rewrite" in assets:
        return bool(assets.get("allow_rewrite"))
    sm = str(assets.get("script_mode") or "").lower()
    if sm == "verbatim":
        return False
    if sm in ("rewrite", "modify"):
        return True
    return True


def _verbatim_user_script(assets: dict) -> str:
    """The caller's OWN words to speak verbatim, or '' to let the office write. An explicit `script`
    field always wins; when rewrite is disabled the `prompt` itself IS the user's script (some lanes
    send the approved script only as the prompt). When rewrite is allowed we return '' so the office
    writes normally (now WITHOUT the fabrication clauses removed from vertical_dna)."""
    if not isinstance(assets, dict):
        return ""
    s = (assets.get("script") or "").strip()
    if s:
        return s
    if not _rewrite_allowed(assets):
        return (assets.get("prompt") or "").strip()
    return ""


async def recipe_full_ad(req: RunRequest) -> list:
    """Regeneration Composer — a full-length (~30-45s) UGC ad, composed the way editors do:
      script (enhanced loser + winner's hook angle) -> split into ONE-ACTION clips ->
      generate each clip with the REALISM PROMPT ENGINE (anti-slop) anchored to the loser's
      REAL spokesperson frame (@Image1) so the SAME person carries every clip (consistency) ->
      stitch -> OUR clean captions per clip (from the script) -> save.
    Multi-clip stitch is how we get real duration (each model clip caps ~12s)."""
    from ..services import realism_prompt_engine as rpe
    orig = await _download_to_temp(req.context.get("download_url", ""))
    work = tempfile.mkdtemp()
    try:
        W, H = await asyncio.to_thread(_ffprobe_dims, orig)
        dur = await asyncio.to_thread(_ffprobe_duration, orig)
        transcript = await _transcribe_file(orig)
        vertical = req.context.get("vertical", "")
        hint = (req.context.get("diagnosis", {}) or {}).get("directive_hint", "")

        from ..services import winner_library
        lw = winner_library.fetch_winners(vertical, limit=1)
        winner_hook = lw[0].get("hook", "") if lw else ""

        # "Use as reference": creatives the user hand-picked in the library (proxied URLs). Prepped
        # like a winner clip (scrubbed/trimmed) and passed as a reference video to generation.
        user_refs = req.context.get("reference_urls") or []
        ref_video = None
        if user_refs:
            ref_video = await _prep_winner_clip(user_refs[0], work)

        # ENTITY ANCHOR = the loser's REAL spokesperson frame (real identity, reused every clip)
        anchor_url = _frame_to_public_url(orig, min(1.5, (dur or 3) * 0.3))
        entity_desc = ""
        try:
            fr = await asyncio.to_thread(_extract_frames, orig, [min(1.5, (dur or 3) * 0.3)], work)
            if fr:
                ed = await _gemini_vision(fr, 'Describe this person as a consistent character reference '
                    '(age, gender, hair, clothing, look) in <=25 words. JSON {"desc":"..."}')
                entity_desc = ed.get("desc", "")
        except Exception as e:
            logger.warning(f"entity describe failed: {e}")

        # THE CREATIVE TEAM runs the plan (leader → strategist → script → director → shots →
        # prompts → critic). This lights up the office live-feed under this job's request_id, and
        # returns per-beat anti-slop prompts composed from the Prompt Reference Library.
        from ..services import creative_team as team
        _ra = req.assets if isinstance(req.assets, dict) else {}
        plan = await team.run_creative_team(
            offer_desc=(hint or transcript[:300] or "the offer in this ad"),
            job_id=req.request_id, vertical=vertical,
            request_type=(req.variation_type or "ugc"), model=req.model or "seedance-2",
            loser_transcript=transcript, winner_hook=winner_hook,
            loser_metrics=(req.context.get("metrics") if isinstance(req.context, dict) else None),
            entity_desc=entity_desc,
            has_real_character=bool(anchor_url), has_winner_video=bool(lw),
            n_reference_images=1 if anchor_url else 0,
            user_script=_verbatim_user_script(_ra),
            allow_rewrite=_rewrite_allowed(_ra),
            # SINGLE SOURCE OF TRUTH: requested cast/setting → office PLAN matches the render.
            # #5/#6 free-text age/scene win over the enum (same contract as the t2v lane).
            cast_gender=(_ra.get("gender") or ""), cast_age_band=(_ra.get("age_band") or ""),
            cast_age=(_ra.get("age") or ""),
            scene=(_ra.get("scene") or ""), scene_detail=(_ra.get("scene_detail") or ""),
            geo=(_ra.get("state") or ""))
        beats = (plan.get("beats") or [])[:4]   # cap 4 clips (~48s) to bound cost/time
        script = plan.get("script", transcript)
        if not beats:
            raise RuntimeError("creative team produced no beats to compose from")
        from ..services import creative_team_activity as act
        act.set_expected_sec(req.request_id, 60 + len(beats) * 90)   # refine ETA now beats are known

        shots, caps = [], []
        for i, b in enumerate(beats):
            await _abort_if_cancelled(req, f"clip {i+1}/{len(beats)}")
            act.tick(req.request_id, f"generating clip {i+1}/{len(beats)}")
            line = b.get("line", "")
            b["prompt"] = b.get("prompt") or rpe.build_prompt(
                model=b.get("model") or "seedance-2", action=b.get("action", "talks to camera"),
                request_type=b.get("request_type", "ugc"), entity_desc=entity_desc,
                environment=b.get("environment", ""), line=line, vertical=vertical,
                emotion=b.get("emotion", ""), gesture=b.get("gesture", ""),
                n_reference_images=1 if anchor_url else 0)
            beat_model = b.get("model") or MultiProviderVideoService.route_capability("reference_to_video", req.model)

            async def _attempt(bt, _line=line, _model=beat_model):
                try:
                    res = await asyncio.to_thread(
                        MultiProviderVideoService.generate, prompt=bt.get("prompt"), shot_type="b_roll",
                        duration=min(12, max(6, len(_line.split()) // 2 + 4)), preferred_model=_model,
                        reference_image_urls=([anchor_url] if anchor_url else None),
                        reference_video_urls=([ref_video] if ref_video else None), s3_prefix="regen")
                    vp = res.get("video_path")
                    return vp if (vp and os.path.exists(vp)) else None
                except Exception as e:
                    logger.warning(f"full_ad clip gen failed: {e}"); return None

            clip = await _gen_beat_with_eval(req.request_id, b, work, _attempt)
            if clip:
                shots.append(clip); caps.append(line)

        if not shots:
            raise RuntimeError("full_ad: no clips generated (check generation provider/credits)")

        # normalize + burn OUR clean caption per clip, then concat
        norm = []
        for i, (sp, line) in enumerate(zip(shots, caps)):
            cap = " ".join(line.split()[:8])  # short on-screen line from the script
            cpng = os.path.join(work, f"c{i}.png")
            await asyncio.to_thread(_make_caption_png, cap, W, H, cpng)
            npath = os.path.join(work, f"n{i}.mp4")
            await asyncio.to_thread(_ffmpeg,
                ["-i", sp, "-i", cpng, "-filter_complex",
                 f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30[v0];[v0][1:v]overlay=0:0[v]",
                 "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                 "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-shortest", npath], timeout=300)
            norm.append(npath)

        name, out_path, url = _out_url(req, "fullad")
        if len(norm) == 1:
            import shutil; shutil.copy(norm[0], out_path)
        else:
            lst = os.path.join(work, "list.txt")
            with open(lst, "w") as f:
                for n in norm:
                    f.write(f"file '{n}'\n")
            await asyncio.to_thread(_ffmpeg,
                ["-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out_path], timeout=600)

        return [{"recipe": "Full Ad (composed)", "video_url": url, "confidence": 0.7,
                 "whats_changed": (f"Composed {len(norm)}-clip UGC ad (~{len(norm)*10}s): enhanced script"
                    + (f" w/ winning hook angle" if winner_hook else "")
                    + ", same spokesperson across clips (anchored to your real frame), anti-slop realism prompts, clean captions.")}]
    finally:
        try: os.remove(orig)
        except OSError: pass
        import shutil; shutil.rmtree(work, ignore_errors=True)


async def recipe_from_assets(req: RunRequest) -> list:
    """CREATE FROM ASSETS — the user brings their OWN scenic images + a script and we produce a
    finished, narrated, captioned video end-to-end (no losing creative involved).
      script -> creative team beats + anti-slop prompts -> per beat image-to-video from the
      matching scenic image -> stitch -> voiceover (TTS of the script) -> clean captions -> save.
    This runs through the creative team so the office lights up + the eval loop grades it."""
    assets = req.assets or req.directive.get("assets", {}) or {}
    image_urls = [u for u in (assets.get("image_urls") or []) if u]
    script = (assets.get("script") or "").strip()
    do_vo = assets.get("do_voiceover", True)
    vertical = req.context.get("vertical", "")
    if not image_urls:
        raise RuntimeError("from_assets: no scenic images provided")
    if not script:
        raise RuntimeError("from_assets: no script provided")

    work = tempfile.mkdtemp()
    W, H = 1080, 1920
    try:
        from ..services import creative_team as team
        # scenic images → 'broll' request type (no talking head); the team composes anti-slop prompts
        plan = await team.run_creative_team(
            offer_desc=script[:300], job_id=req.request_id, vertical=vertical,
            request_type=(req.variation_type if req.variation_type in ("broll", "Broll") else "broll"),
            model=req.model or "seedance-2", loser_transcript=script,
            loser_metrics=(req.context.get("metrics") if isinstance(req.context, dict) else None),
            has_real_character=False, has_winner_video=False, n_reference_images=1,
            # from_assets ALWAYS has a user-provided script — honor it verbatim unless rewrite is on.
            user_script=script,
            allow_rewrite=_rewrite_allowed(req.assets if isinstance(req.assets, dict) else {}),
            # SINGLE SOURCE OF TRUTH: requested cast/setting → office PLAN matches the render.
            # #5/#6 free-text age/scene win over the enum (same contract as the t2v lane).
            cast_gender=(assets.get("gender") or ""), cast_age_band=(assets.get("age_band") or ""),
            cast_age=(assets.get("age") or ""),
            scene=(assets.get("scene") or ""), scene_detail=(assets.get("scene_detail") or ""),
            geo=(assets.get("state") or ""))
        beats = plan.get("beats") or []
        if not beats:
            beats = [{"i": i, "line": s, "prompt": "", "request_type": "broll"}
                     for i, s in enumerate(rpe.split_into_clips(script))]
        beats = beats[:6]  # bound cost/time
        from ..services import creative_team_activity as act
        act.set_expected_sec(req.request_id, 40 + len(beats) * 80)

        i2v_model = MultiProviderVideoService.route_capability("image_to_video", req.model)
        shots, caps = [], []
        for i, b in enumerate(beats):
            await _abort_if_cancelled(req, f"asset clip {i+1}/{len(beats)}")
            act.tick(req.request_id, f"animating scene {i+1}/{len(beats)}")
            img = image_urls[i % len(image_urls)]      # cycle images across beats
            line = b.get("line", "")
            b["prompt"] = b.get("prompt") or rpe.build_prompt(
                model=i2v_model,
                # use the beat's REAL directed action (so walking/entering actually renders); only
                # fall back to a neutral motion when the director gave this beat none.
                action=(b.get("action") or "the scene comes alive with subtle natural motion"),
                request_type="broll", environment="the scene in the provided image",
                vertical=vertical, n_reference_images=1)

            async def _attempt(bt, _line=line, _img=img):
                try:
                    res = await asyncio.to_thread(
                        MultiProviderVideoService.generate, prompt=bt.get("prompt"), shot_type="b_roll",
                        duration=min(10, max(4, len(_line.split()) // 2 + 4)), preferred_model=i2v_model,
                        reference_image_urls=[_img], s3_prefix="regen")
                    vp = res.get("video_path")
                    return vp if (vp and os.path.exists(vp)) else None
                except Exception as e:
                    logger.warning(f"from_assets clip gen failed: {e}"); return None

            clip = await _gen_beat_with_eval(req.request_id, b, work, _attempt)
            if clip:
                shots.append(clip); caps.append(line)

        if not shots:
            raise RuntimeError("from_assets: no clips generated (check image-to-video provider/credits)")

        # normalize + burn OUR clean caption per clip
        norm = []
        for i, (sp, line) in enumerate(zip(shots, caps)):
            cap = " ".join(line.split()[:8])
            cpng = os.path.join(work, f"c{i}.png")
            await asyncio.to_thread(_make_caption_png, cap, W, H, cpng)
            npath = os.path.join(work, f"n{i}.mp4")
            await asyncio.to_thread(_ffmpeg,
                ["-i", sp, "-i", cpng, "-filter_complex",
                 f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30[v0];[v0][1:v]overlay=0:0[v]",
                 "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                 "-pix_fmt", "yuv420p", "-r", "30", npath], timeout=300)
            norm.append(npath)

        stitched = os.path.join(work, "stitched.mp4")
        if len(norm) == 1:
            import shutil; shutil.copy(norm[0], stitched)
        else:
            lst = os.path.join(work, "list.txt")
            with open(lst, "w") as f:
                for n in norm:
                    f.write(f"file '{n}'\n")
            await asyncio.to_thread(_ffmpeg,
                ["-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "22", "-pix_fmt", "yuv420p", stitched], timeout=600)

        # VOICEOVER: narrate the script over the stitched scenic clips
        name, out_path, url = _out_url(req, "assets")
        vo_path = None
        if do_vo:
            try:
                from ..services.speech_generator import SpeechGeneratorService
                sp = await SpeechGeneratorService().generate_speech(script)
                vo_path = os.path.join(work, "vo.mp3")
                with open(vo_path, "wb") as f:
                    f.write(sp["audio_data"])
            except Exception as e:
                logger.warning(f"from_assets voiceover failed (continuing silent): {e}")
        if vo_path and os.path.exists(vo_path):
            # loop/trim video to the voiceover length so narration is never cut off
            await asyncio.to_thread(_ffmpeg,
                ["-stream_loop", "-1", "-i", stitched, "-i", vo_path, "-map", "0:v", "-map", "1:a",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k", "-shortest", out_path], timeout=600)
        else:
            import shutil; shutil.copy(stitched, out_path)

        return [{"recipe": "Create from Assets", "video_url": url, "confidence": 0.7,
                 "whats_changed": (f"Built a {len(norm)}-clip video from your {len(image_urls)} scenic "
                    f"image(s) + script: each scene animated (image-to-video), anti-slop prompts, "
                    f"{'voiceover narration, ' if vo_path else ''}clean captions.")}]
    finally:
        import shutil; shutil.rmtree(work, ignore_errors=True)


async def _veo_wait(op_name: str, timeout: int = 1200):
    """Poll a Veo 3.1 operation until done (returns the completed status with video_path)."""
    from ..services.video_creator import VideoCreatorService as VC
    import time as _t
    started = _t.time()
    while _t.time() - started < timeout:
        st = await asyncio.to_thread(VC.check_status, op_name)
        if st.get("done"):
            if st.get("status") == "failed" or not st.get("video_path"):
                raise RuntimeError(f"Veo operation failed: {st.get('error')}")
            return st
        await asyncio.sleep(15)
    raise RuntimeError("Veo operation timed out")


# ── Video-provider fallback ───────────────────────────────────────────────────────────────────
# A single provider running out of credits (e.g. Kie.ai Seedance → {'code':500,'msg':'Credits
# insufficient … Please top up'}) must NOT dead-end the whole request. On a credits/quota/billing/5xx
# error we advance to the next CONFIGURED provider; when every paid text-to-video provider is down we
# fall back to the AVATAR-LIPSYNC lane on existing library footage, then to a curated best-match clip.
_VIDEO_UNAVAILABLE_RE = re.compile(
    r"credit|insufficient|top[\s-]?up|balance|quota|out of|exhaust|payment required|billing|"
    r"not enough|no fal key|not configured|\b40[123]\b|\b429\b|\b50[023]\b",
    re.I)


def _is_provider_unavailable(exc: Exception) -> bool:
    """True when a provider error reads like credits/quota/billing/5xx — i.e. 'try the next provider',
    not a genuine content/logic failure. Defensive: any keyword/status match in the message counts."""
    return bool(_VIDEO_UNAVAILABLE_RE.search(str(exc) or ""))


class _AllVideoProvidersDown(RuntimeError):
    """Every configured text-to-video provider is unavailable (credits/quota/billing/5xx)."""


def _t2v_providers() -> list:
    """Ordered, CONFIGURED text-to-video providers for the generate lane. Kie-Seedance is primary
    (full reference set: image+video+audio); fal lanes (seedance→kling→wan) are the credits-out
    fallback and share FAL_KEY. Only providers whose key is set are included."""
    prov = []
    if settings.kie_api_key:
        prov.append("kie-seedance")
    if settings.fal_key:
        prov += ["fal-seedance", "fal-kling", "fal-wan"]
    return prov


# FIX B: provider-down cache — a t2v provider that just failed on credits/quota/billing/5xx is
# flagged down for a TTL. This lets the preflight decide, BEFORE any paid attempt, whether the
# doomed Kie attempt is worth making. No cheap balance API exists (confirmed) — the cached flag is
# the mechanism; the TTL self-heals on top-up (a provider re-enters _t2v_available once it expires).
_PROVIDER_DOWN: dict = {}   # provider -> expiry unix ts


def _t2v_available() -> list:
    """Configured t2v providers NOT currently flagged down (cache TTL expired = back in)."""
    now = time.time()
    return [p for p in _t2v_providers() if _PROVIDER_DOWN.get(p, 0) < now]


async def _generate_t2v_clip(*, prompt, image_urls, video_urls, audio_urls, seconds, resolution,
                             aspect_ratio, generate_audio, first, produced,
                             is_continuation: bool = False) -> Optional[str]:
    """Render ONE text-to-video clip, trying each configured provider in order. On a
    credits/quota/billing/5xx (or any) error from one provider, log the reason and advance to the
    next. Returns a local mp4 path (recording the winning provider in `produced['provider']`), or
    raises _AllVideoProvidersDown listing each provider's reason when every one is unavailable."""
    from ..services.kieai_service import KieAIService
    from ..services import fal_video as fv
    from ..services import capabilities as caps
    reasons = []
    _base = _t2v_providers()
    # STALE-MATRIX GUARD: warn (don't block) if a configured provider isn't declared in VIDEO_CAPS —
    # an undeclared provider would otherwise fail-open through every requirement check.
    for _p in _base:
        if not caps.known(_p):
            logger.warning(f"[generate] provider {_p} not in VIDEO_CAPS — capability UNVERIFIED; "
                           f"add it to capabilities.py (routing currently treats it as fully capable)")
    # REQUIREMENT-DRIVEN routing: when audio is needed, try the NATIVE-AUDIO providers first —
    # Kie-Seedance, then Veo 3.1 (also native audio, via the same Kie key) as a second real-audio
    # option — and only then the silent fal lanes as a last resort (recipe_generate muxes a TTS
    # voiceover onto a silent clip so nothing ships mute). Capability is an input to the decision,
    # not a post-hoc surprise. Non-audio jobs never pull in the pricier Veo lane.
    if generate_audio:
        _order = caps.audio_capable(_base)
        if settings.kie_api_key and "kie-veo" not in _order:
            _order.append("kie-veo")
        _order += [p for p in _base if p not in _order]
    else:
        _order = _base
    # CONTINUITY vs AUDIO. The fal lanes do genuine first-frame image-to-video (a continuation clip
    # begins exactly on the reference frame) — BUT fal is SILENT. Routing a TALKING continuation clip
    # to fal is exactly what left clip 2 mute (clip 1 ran on Kie with audio; clip 2 fell to fal and had
    # none). Now that the CHARACTER LOCK passes a clean identity reference image to Kie too (with an
    # "identical person" instruction), Kie holds identity while keeping its NATIVE AUDIO — so a talking
    # continuation clip STAYS on Kie. Only prefer fal's true i2v for a SILENT continuation (b-roll), where
    # there is no audio to lose. Kie's identity anchor is a soft hint, but it now has one (it had none
    # before), which beats a mute clip.
    if is_continuation and (image_urls or [None])[0] and not generate_audio:
        _ff = [p for p in _order if p.startswith("fal-")]
        _rest = [p for p in _order if not p.startswith("fal-")]
        if _ff:
            _order = _ff + _rest
            logger.info("[generate] SILENT continuation clip → first-frame image-to-video (fal) so it "
                        "continues from the previous clip's last frame, not a re-synthesized lookalike")
    for prov in _order:
        try:
            if prov == "kie-seedance":
                res = await asyncio.to_thread(
                    KieAIService.generate_video_seedance,
                    prompt=prompt,
                    reference_image_urls=(image_urls or None),
                    reference_video_urls=(video_urls or None) if first else None,
                    reference_audio_urls=(audio_urls or None) if first else None,
                    duration=int(seconds), resolution=resolution, aspect_ratio=aspect_ratio,
                    generate_audio=bool(generate_audio))
                cp = res.get("local_path") or res.get("video_path")
            elif prov == "kie-veo":
                # Veo 3.1 — NATIVE audio (48kHz + dialogue). t2v only via this path; caps at 8s, so a
                # longer request degrades to 8 narrated seconds (better than a silent fallback).
                res = await asyncio.to_thread(
                    KieAIService.generate_video_veo, prompt=prompt,
                    duration=min(8, int(seconds)), ratio=aspect_ratio,
                    fast=(str(resolution).lower() in ("480p", "540p")))
                cp = res.get("video_path") or res.get("local_path")
            else:
                # fal lanes take a single first-frame image ref only (no video/audio refs)
                img = (image_urls or [None])[0]
                res = await asyncio.to_thread(
                    fv.generate_video, prov, prompt,
                    image_url=img, seconds=int(seconds), aspect_ratio=aspect_ratio,
                    resolution=resolution)
                cp = res.get("local_path")
            if cp and os.path.exists(cp):
                produced["provider"] = prov
                if reasons:
                    logger.warning(f"[generate] {prov} produced the clip after fallbacks: {reasons}")
                return cp
            reasons.append(f"{prov}: no output")
        except Cancelled:
            raise
        except Exception as e:
            tag = "unavailable" if _is_provider_unavailable(e) else "error"
            if tag == "unavailable":
                _PROVIDER_DOWN[prov] = time.time() + 600   # FIX B: flag down 10min (self-heals on top-up)
            reasons.append(f"{prov}: {tag} ({str(e)[:120]})")
            logger.warning(f"[generate] {prov} {tag} ({str(e)[:160]}) — trying next provider")
            continue
    raise _AllVideoProvidersDown(
        "all text-to-video providers unavailable — " + "; ".join(reasons or ["none configured"]))


async def _cast_library_avatar(intent: dict):
    """Scan the tagged asset library for the best clip matching the parsed intent (gender/age/scene/
    vertical). Read-only DB scan; never raises. Returns (avatar_pick_url, avatar_tags, any_pick_url,
    any_tags): the best avatar-lipsync-ready talker AND the best clip of any kind (curated last-resort)."""
    want_g = (intent.get("gender") or "").lower()
    want_a = (intent.get("age_band") or "").lower()
    want_scene = (intent.get("scene") or "").lower()
    want_vert = (intent.get("vertical") or "").lower()
    try:
        from ..database import SessionLocal
        from ..models.asset_tag import AssetTag
        db = SessionLocal()
        try:
            rows = db.query(AssetTag).all()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[generate] library scan failed: {e}")
        return None, None, None, None

    def _score(t: dict, lip: bool) -> float:
        s = 5.0 if lip else 0.0
        s += 2 * float(t.get("face_score") or 0)
        g = (t.get("gender") or "").lower()
        if want_g and g == want_g:
            s += 3
        elif want_g and g:
            s -= 1
        if want_a and (t.get("age_band") or "").lower() == want_a:
            s += 2
        # FIX 3: STRONGLY prefer same-vertical clips (dominates gender/age) so a talking-head fallback
        # doesn't cast an off-topic-vertical face. Soft (additive) — never a hard filter, so when no
        # vertical-tagged clip exists the full ranked set still stands (relaxes automatically).
        if want_vert and (t.get("vertical") or "").lower() == want_vert:
            s += 6
        if want_scene and want_scene in (t.get("scene") or "").lower():
            s += 1
        return s

    best_lip = best_lip_s = best_any = best_any_s = None
    best_lip_s = -1e9
    best_any_s = -1e9
    for row in rows:
        try:
            t = json.loads(row.tags_json)
        except Exception:
            continue
        if not t.get("url"):
            continue
        lip = (t.get("usable_as") == "avatar_lipsync") and bool(t.get("max_talk_sec"))
        s = _score(t, lip)
        if s > best_any_s:
            best_any_s, best_any = s, t
        if lip and s > best_lip_s:
            best_lip_s, best_lip = s, t
    return ((best_lip.get("url") if best_lip else None), best_lip,
            (best_any.get("url") if best_any else None), best_any)


async def _cl_cast_broll(vertical: str = "", scene: str = "") -> dict:
    """SINGLE SOURCE OF TRUTH for library b-roll: ask Creative-Library (which owns asset_library AND
    its S3 bucket) to cast + FRESH-PRESIGN the clips. Returns {'hooks': [...], 'interiors': [...]},
    empty on any error. This is why AE never needs its own asset_tags copy: CL — the only side that
    can presign its bucket — mints server-fetchable URLs on demand. Best-effort; never raises."""
    base = (getattr(settings, "creative_library_url", "") or "").rstrip("/")
    if not base:
        return {"hooks": [], "interiors": []}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{base}/api/regen/cast-assets",
                             headers={"x-regen-secret": CALLBACK_SECRET},
                             json={"kind": "broll", "vertical": (vertical or ""), "scene": (scene or "")})
            r.raise_for_status()
            d = r.json() or {}
            return {"hooks": list(d.get("hook_urls") or []), "interiors": list(d.get("interior_urls") or [])}
    except Exception as e:
        logger.warning(f"[cast-assets] CL resolver failed ({e}); falling back to local asset_tags")
        return {"hooks": [], "interiors": []}


# Strong refs to fire-and-forget avatar-save tasks so the loop doesn't GC them mid-flight.
_t2v_avatar_tasks: set = set()


def _age_band_from(age: str) -> str:
    """Bucket a raw age ('38', 'late 30s', '35-40') into under35|35-44|45-55|55plus (best-effort).
    Returns '' when nothing usable is present. Already-bucketed input passes through unchanged."""
    import re as _re
    s = str(age or "").lower().strip()
    if not s:
        return ""
    if s in ("under35", "35-44", "45-55", "55plus"):
        return s
    nums = [int(n) for n in _re.findall(r"\d{1,3}", s) if int(n) < 120]
    n = (sum(nums) // len(nums)) if nums else None
    if n is None:
        if any(w in s for w in ("teen", "20s", "young", "college")): return "under35"
        if "30s" in s: return "35-44"
        if "40s" in s: return "45-55"
        if any(w in s for w in ("50s", "60s", "senior", "elder", "older")): return "55plus"
        return ""
    if n < 35: return "under35"
    if n < 45: return "35-44"
    if n < 55: return "45-55"
    return "55plus"


async def _save_t2v_avatar_to_cl(local_path: str, meta: dict) -> None:
    """Best-effort: register a from-scratch T2V talking-head clip as a REUSABLE library avatar in
    Creative-Library (which owns asset_library + its S3). Stages the FULL stitched clip in TWO fetchable
    forms and hands CL whichever it can pull: (1) a PRESIGNED durable-S3 URL — AE's bucket is PRIVATE, so
    a RAW object URL 403s when CL fetches it (this was silently killing every save); (2) the public
    /uploads HTTP endpoint as a fallback. We POST with the presigned URL first and, on ANY failure,
    retry with /uploads — so a fetch-back 403/404 no longer drops the avatar. Same shared secret as
    /cast-assets + /callback. Non-fatal — never raises, never blocks (detached task). Logs LOUDLY on
    every outcome so a miss is diagnosable instead of silent."""
    base = (getattr(settings, "creative_library_url", "") or "").rstrip("/")
    if not base:
        logger.error("[t2v-avatar] ❌ no creative_library_url configured — cannot save avatar"); return
    if not (local_path and os.path.exists(local_path)):
        logger.error(f"[t2v-avatar] ❌ avatar source missing: {local_path}"); return
    # Stage candidate fetch URLs in preference order: presigned durable S3 first, public /uploads second.
    candidates = []   # list of (label, url)
    try:
        from ..services.storage import StorageService
        import uuid as _uuid
        _key = f"t2v-avatars/{_uuid.uuid4().hex[:12]}.mp4"
        if await asyncio.to_thread(StorageService.upload_file, local_path, _key):
            _ps = await asyncio.to_thread(StorageService.presign_url, _key, 21600)  # 6h, plenty for CL to fetch
            if _ps:
                candidates.append(("s3-presigned", _ps)); logger.info(f"[t2v-avatar] staged durable S3 (presigned) → {_key}")
    except Exception as e:
        logger.warning(f"[t2v-avatar] S3 stage failed ({e})")
    try:
        import uuid as _uuid, shutil as _sh
        nm = f"t2v_avatar_{_uuid.uuid4().hex[:10]}.mp4"
        _sh.copy(local_path, os.path.join(UPLOAD_DIR, nm))
        candidates.append(("uploads", f"{AE_PUBLIC_URL}/api/v1/uploads/{nm}"))
    except Exception as e:
        logger.warning(f"[t2v-avatar] /uploads stage failed ({e})")
    if not candidates:
        logger.error("[t2v-avatar] ❌ could not stage avatar for save (no S3, no /uploads)"); return
    last_err = None
    for label, url in candidates:
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{base}/api/regen/save-t2v-avatar",
                                 headers={"x-regen-secret": CALLBACK_SECRET},
                                 json={**meta, "url": url})
                r.raise_for_status()
                _body = r.json() or {}
                logger.info(f"[t2v-avatar] ✅ saved '{meta.get('name')}' via {label} "
                            f"(gender={meta.get('gender')} age_band={meta.get('age_band')} "
                            f"state={meta.get('state')}) → s3_key={_body.get('s3_key')} id={_body.get('id')}")
                return
        except Exception as e:
            last_err = e
            logger.warning(f"[t2v-avatar] save via {label} failed ({e}); trying next source")
    logger.error(f"[t2v-avatar] ❌ save POST failed for '{meta.get('name')}' — all sources exhausted: {last_err}")


async def _cast_library_broll(intent: dict, limit: int = 8, prefer_kind: str = None) -> list:
    """Cast scenic B-ROLL clips for the parsed intent. PRIMARY source is CL's asset-resolver (the one
    store that holds these clips + can presign its bucket); the legacy asset_tags scan below is only a
    fallback for when the resolver is unreachable. Read-only, never raises. Returns up to `limit` URLs.

    prefer_kind='hook' → the oddly-satisfying openers (leaf-blow, hedge-trim); else interiors."""
    # SINGLE SOURCE OF TRUTH first — kills the recurring "AE's store is empty / URL is stale" class of
    # bug: CL casts from asset_library and hands back fresh, server-fetchable presigned URLs.
    try:
        _r = await _cl_cast_broll(intent.get("vertical") or "", intent.get("scene") or "")
        _pool = _r["hooks"] if (prefer_kind == "hook") else (_r["interiors"] or _r["hooks"])
        if _pool:
            return _pool[:max(1, int(limit))]
    except Exception as e:
        logger.warning(f"[broll] resolver cast errored, using local asset_tags: {e}")

    # ── LEGACY FALLBACK: AE's own asset_tags store (mirrors _cast_library_avatar's DB scan; collects
    #    clips tagged usable_as/kind=='broll'. Usually EMPTY in prod — the resolver above is primary). ──
    want_scene = (intent.get("scene") or "").lower()
    want_vert = (intent.get("vertical") or "").lower()
    prefer_kind = (prefer_kind or "").lower()
    # The stored `url` in each tag was presigned at INGEST time with a 1-hour expiry, so days later it
    # is dead (403). AssetTag's primary key IS the normalized s3_key, so re-sign a FRESH presigned URL
    # per returned clip — otherwise every b-roll download 403s and callers (recipe_broll, the UGC-BROLL
    # assembler) silently get no footage. Falls back to the stored url if presign is unavailable.
    from ..services.storage import StorageService
    def _fresh(pairs):   # pairs: [(s3_key, stored_url), ...] → [fresh_url, ...]
        return [StorageService.presign_url(k) or u for k, u in pairs]
    try:
        from ..database import SessionLocal
        from ..models.asset_tag import AssetTag
        db = SessionLocal()
        try:
            rows = db.query(AssetTag).all()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[broll] library scan failed: {e}")
        return []

    scored = []
    for row in rows:
        try:
            t = json.loads(row.tags_json)
        except Exception:
            continue
        url = t.get("url")
        if not url:
            continue
        if (t.get("usable_as") or "").lower() != "broll" and (t.get("kind") or "").lower() != "broll":
            continue
        _cv = (t.get("vertical") or "").lower()
        _kind = (t.get("kind") or "").lower()
        s = 0.0
        _same_vert = bool(want_vert and _cv == want_vert)
        if _same_vert:
            s += 6                                   # STRONGLY prefer same-vertical footage
        if prefer_kind and _kind == prefer_kind:
            s += 5                                   # bias the asked-for kind (e.g. satisfaction 'hook')
        if want_scene and want_scene in (t.get("scene") or "").lower():
            s += 2
        s -= 1.5 * float(t.get("face_score") or 0)   # b-roll is scenic → LOW face_score wins
        scored.append((s, url, (row.s3_key or url), _cv, _same_vert, _kind))
    scored.sort(key=lambda x: x[0], reverse=True)
    # PREFERRED KIND wins first, ACROSS verticals: the satisfaction 'hook' openers are the scroll-
    # stopper and are tagged vertical=None, so honor them before the same-vertical filter below (which
    # would otherwise strip them). Falls through to the normal ranking when we have none of that kind.
    if prefer_kind:
        _pk = [(k, u) for s, u, k, cv, sv, kd in scored if kd == prefer_kind]
        if _pk:
            return _fresh(_pk[:max(1, int(limit))])
    # RELEVANCE FILTER: when we know the vertical AND we have clips tagged for it, return ONLY those —
    # never pad a home-insurance ad with off-vertical footage (e.g. an auto clip) just to fill time.
    # If NOTHING matches the vertical, fall back to generic-tagged clips (untagged vertical), and only
    # then to the full ranked set — so it still produces something when the library has no exact match.
    if want_vert:
        _match = [(k, u) for s, u, k, cv, sv, kd in scored if sv]
        if _match:
            return _fresh(_match[:max(1, int(limit))])
        _generic = [(k, u) for s, u, k, cv, sv, kd in scored if not cv]
        if _generic:
            return _fresh(_generic[:max(1, int(limit))])
    return _fresh([(k, u) for s, u, k, cv, sv, kd in scored[:max(1, int(limit))]])


def _voice_clone_get(character_key: str):
    """Return a character's SAVED voice-clone reference {sample_key, ref_text, provider}, or None.
    Read-only, never raises — a cache miss just means we clone fresh."""
    if not character_key:
        return None
    try:
        from sqlalchemy import text
        from ..database import SessionLocal
        db = SessionLocal()
        try:
            row = db.execute(text("SELECT sample_key, ref_text, provider FROM voice_clones "
                                  "WHERE character_key=:k"), {"k": character_key}).first()
        finally:
            db.close()
        # Only reuse clean-era ('v2') references; a stale mid-word ref (old key) is ignored so it
        # re-extracts cleanly and re-caches — never serve a reference that causes the boundary echo.
        if row and row[0] and "clonev2" in str(row[0]):
            return {"sample_key": row[0], "ref_text": row[1], "provider": row[2]}
    except Exception as e:
        logger.warning(f"[voice-clone] cache read failed: {e}")
    return None


def _voice_clone_put(character_key: str, sample_key: str, ref_text: str = None, provider: str = "f5") -> None:
    """SAVE/refresh a character's voice-clone reference so the next generation REUSES it. Portable
    upsert (delete-then-insert). Best-effort, never raises."""
    if not (character_key and sample_key):
        return
    try:
        from sqlalchemy import text
        from ..database import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM voice_clones WHERE character_key=:k"), {"k": character_key})
            db.execute(text("INSERT INTO voice_clones (character_key, sample_key, ref_text, provider) "
                            "VALUES (:k,:s,:r,:p)"),
                       {"k": character_key, "s": sample_key, "r": (ref_text or None), "p": provider})
            db.commit()
        finally:
            db.close()
        logger.info(f"[voice-clone] saved clone for {character_key}")
    except Exception as e:
        logger.warning(f"[voice-clone] cache write failed: {e}")


async def _generate_library_fallback(req: "RunRequest", prompt: str, aspect_ratio: str,
                                      seconds: int, reasons: list) -> list:
    """Last-resort tiers when every paid text-to-video provider is out of credits/quota:
       (1) re-route into the AVATAR-LIPSYNC recipe on a cast library clip (lipsync + cheap TTS — no
           text-to-video credits), then
       (2) return the single best-match library clip as a curated suggestion.
    The user ALWAYS gets something usable — never a bare 'credits insufficient' error."""
    # Build the human note FRESH at each use from the CURRENT reasons list — never snapshot it here.
    # TIER1 (avatar-lipsync) appends its own failure reason AFTER this point, so a snapshot taken now
    # would silently drop the real cause and make an avatar-lipsync failure look like a bare t2v outage.
    def _note() -> str:
        return "Text-to-video providers unavailable (" + "; ".join(reasons[:6]) + ")."
    intent = await _parse_intent_text(prompt)
    avatar_url, _atags, any_url, _anytags = await _cast_library_avatar(intent)
    # PREFER a clip cast from the REAL curated avatar library (creative-library's asset_library,
    # usable_as='avatar_lipsync', cast by gender/age/scene/face_score — the SAME library the normal
    # avatar-lipsync path uses). The caller (CL) hands it off in assets.fallback_avatar_url. The
    # AssetTag scan above is only a per-generation result cache and is usually empty/sparse, so it
    # must not be the primary source for the fallback clip.
    _cl = req.assets if isinstance(req.assets, dict) else {}
    _lib_url = _cl.get("fallback_avatar_url") or _cl.get("library_avatar_url")
    if _lib_url:
        avatar_url = _lib_url
        any_url = any_url or _lib_url

    # TIER 1 — avatar-lipsync on the cast library clip (reuses recipe_avatar_lipsync end-to-end)
    if avatar_url:
        try:
            _vert = intent.get("vertical") or (req.context.get("vertical")
                    if isinstance(req.context, dict) else "") or ""
            req.assets = {**(req.assets or {}),
                          "character_video_url": avatar_url,
                          "script": prompt,
                          # propagate verbatim so the fallback lip-sync honors allow_rewrite:false too
                          **({"script_mode": "verbatim"} if not _rewrite_allowed(req.assets if isinstance(req.assets, dict) else {}) else {}),
                          "seconds": int(seconds),
                          "vertical": _vert}
            logger.warning(f"[generate] all t2v providers down — re-routing to avatar-lipsync on "
                           f"library clip {avatar_url}")
            out = await recipe_avatar_lipsync(req)
            for r in (out or []):
                r["recipe"] = "Generate — Library Avatar Lip-sync (t2v fallback)"
                r["whats_changed"] = ("Built from your library footage — " + _note() + " Cast a matching "
                    "avatar clip and lip-synced your script to it (no text-to-video credits used). "
                    + (r.get("whats_changed") or ""))[:600]
            if out:
                return out
        except Cancelled:
            raise
        except Exception as e:
            logger.error(f"[generate] avatar-lipsync fallback failed: {e}")
            reasons.append(f"avatar-lipsync: {str(e)[:120]}")

    # TIER 2 — curated best-match library clip (no generation at all).
    # FIX 2: topic-gate the raw clip before shipping. When we CAN vision-check it and it's clearly
    # OFF-TOPIC for this offer, do NOT ship it — raise the clean, actionable failure instead of
    # surfacing an unrelated clip as "the answer". GUARD: if the relevance check itself is
    # unavailable/errors (no vision key, download/ffmpeg fail, no frames), log and ALLOW — a
    # vision-less env must never be bricked. (_asset_is_relevant already fails-open on its own.)
    pick = avatar_url or any_url
    if pick:
        _on_topic = True
        try:
            import tempfile as _tf, shutil as _sh
            _wd = _tf.mkdtemp()
            try:
                _clip = await _download_to_temp(pick, suffix=".mp4")
                _frames = await asyncio.to_thread(_extract_frames, _clip, [0.5, 1.5], _wd)
                if _frames:
                    _on_topic = await _asset_is_relevant(_frames, prompt)
                # no frames → cannot verify → treat as unverifiable (allow)
            finally:
                _sh.rmtree(_wd, ignore_errors=True)
        except Exception as _e:
            logger.warning(f"[generate] TIER2 relevance check unavailable, allowing clip: {_e}")
            _on_topic = True
        if not _on_topic:
            logger.warning("[generate] TIER2 library clip is OFF-TOPIC for the offer — refusing to ship it")
            raise _AllVideoProvidersDown(
                "Text-to-video providers are unavailable and the closest library clip is off-topic for "
                "this offer, so nothing on-topic can be produced. " + _note() + " Top up Kie.ai or fal "
                "credits, or add relevant tagged library clips.")
        return [{"recipe": "Generate — Curated library match (providers unavailable)",
                 "video_url": pick, "confidence": 0.3,
                 "whats_changed": ("Closest match from your library — " + _note() + " Generation providers "
                    "are unavailable, so we surfaced your best existing clip instead of failing. "
                    "Top up Kie.ai or fal credits to generate net-new video.")[:600]}]

    # nothing at all — clean, actionable message (never a raw provider error)
    raise _AllVideoProvidersDown(
        "All video providers are unavailable and no library footage exists to fall back on. "
        + _note() + " Top up Kie.ai or fal credits, or add tagged library clips.")


async def _mux_tts_voiceover(req: "RunRequest", video_path: str, vo_script: str, work: str) -> bool:
    """Capability-honest recovery: when audio was requested but the clip came from a SILENT provider
    (fal fallback), speak the VO script with TTS and mux it on — so a credits-out fallback still ships
    a NARRATED ad, not a silent one. Only runs when the prompt is an actual spoken script (≥12 words),
    never on a bare visual prompt ('a sunset') where synthesized narration would be nonsense. Modifies
    video_path in place. Best-effort — returns True iff a voiceover was added; never raises."""
    try:
        words = [w for w in re.split(r"\s+", (vo_script or "").strip()) if w]
        if len(words) < 12:
            return False
        from ..services import voice_studio as vs
        vo = os.path.join(work, f"vo_{req.request_id[:8]}.mp3")
        # pass a delivery direction so the recovery VO is expressive, not the flat default read.
        res = await asyncio.to_thread(lambda: vs.synthesize(
            vo_script, out_path=vo,
            style="natural, expressive, conversational, talking to camera, never flat or monotone"))
        if not (res and os.path.exists(vo)):
            return False
        _track_cost(req.request_id, "voice", res.get("provider") or "openai", model=str(res.get("voice")),
                    units=len(vo_script), unit_type="chars", cost_usd=res.get("cost_usd") or 0,
                    note="TTS voiceover — silent-provider recovery")
        muxed = os.path.join(work, "muxed_vo.mp4")
        await asyncio.to_thread(_ffmpeg, ["-i", video_path, "-i", vo, "-map", "0:v:0", "-map", "1:a:0",
                                          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", muxed])
        import shutil
        shutil.move(muxed, video_path)
        return True
    except Cancelled:
        raise
    except Exception as e:
        logger.warning(f"[generate] TTS voiceover mux failed: {e}")
        return False


async def recipe_generate(req: RunRequest) -> list:
    """DIRECT generation from a PROMPT + optional REFERENCE IMAGE(S), engine of the user's choice:
      • 'seedance' (Kie): reference-image-conditioned clip(s) — Seedance keeps subject/scene/voice
        consistent within a clip; stitched if a longer duration is asked.
      • 'veo-extend' (Google Veo 3.1): a base clip (from the image if given, else text) then NATIVE
        +7s extends for seamless longer video.
    Reads req.assets = {engine, prompt, image_urls[], seconds}."""
    _CURRENT_RID.set(req.request_id)   # so Gemini reasoning/vision tokens bill to this job
    assets = req.assets or req.directive.get("assets", {}) or {}
    engine = (assets.get("engine") or "seedance").lower()
    prompt = (assets.get("prompt") or "").strip()
    _vo_script = prompt   # the CLEAN spoken script (before the team appends visual refinement) — used
                          # only to narrate a silent-fallback clip via TTS, never the visual prompt.
    image_urls = [u for u in (assets.get("image_urls") or []) if u]
    video_urls = [u for u in (assets.get("video_urls") or []) if u]
    audio_urls = [u for u in (assets.get("audio_urls") or []) if u]
    aspect_ratio = assets.get("aspect_ratio") or "9:16"
    resolution = assets.get("resolution") or "480p"   # DEFAULT 480p (cheaper/faster); explicit override wins
    generate_audio = assets.get("generate_audio", True)
    # USER-SELECTED GENERATION PATH: auto (default) | scratch (force text-to-video, never reuse a real
    # clip) | avatar (prefer real-library lip-sync). Gates the avatar reroute below.
    _gen_path = str(assets.get("gen_path") or "auto").lower()
    # AUTO duration: when the caller didn't pick a specific length, the SCRIPT drives runtime (a 40s
    # script renders ~40s, not a crammed 15s). An explicit number is honored as a cap below.
    _dur_raw = assets.get("seconds")
    _auto_dur = not _dur_raw or str(_dur_raw).lower() == "auto"
    seconds = int(_dur_raw) if (not _auto_dur) else (16 if engine == "veo-extend" else 15)
    if not prompt:
        raise RuntimeError("generate: prompt required")

    work = tempfile.mkdtemp()
    W, H = 1080, 1920
    NO_TEXT = (" ABSOLUTELY NO on-screen text, captions, subtitles, burned-in words, logos or "
               "watermarks anywhere in the frame — clean footage only.")
    HOOK = (" The subject is ALREADY speaking energetically from the very first frame — hook in the "
            "first 2 seconds, no silent lead-in, no dead air, no slow intro.")
    try:
        name, out_path, url = _out_url(req, "genvideo")
        _avatar_plan = False   # FIX 1: set when the brain's plan routes this request to avatar-lipsync
        _pscript = ""          # the office/user spoken script (set in the team pass below); ANY real
                               # script forces the talking-head path so every clip gets its SPOKEN LINE

        # EVERYTHING goes through the creative office (nothing bypassed): the team refines the
        # prompt (anti-slop + no-on-screen-text) and the desks light up under this job_id.
        try:
            from ..services import creative_team as team
            vertical = req.context.get("vertical", "") if isinstance(req.context, dict) else ""
            plan = await team.run_creative_team(
                offer_desc=prompt, job_id=req.request_id, vertical=vertical,
                # RESPECT what was asked for. This used to be derived purely from whether reference
                # media was attached, so a Studio request that explicitly said "broll" always came
                # out "ugc" and the b-roll lane was unreachable.
                request_type=(str(assets.get("request_type") or "").strip().lower()
                              or ("broll" if (video_urls or image_urls) else "ugc")),
                model=engine, loser_transcript=prompt,
                loser_metrics=(req.context.get("metrics") if isinstance(req.context, dict) else None),
                has_winner_video=bool(video_urls), n_reference_images=len(image_urls),
                # VERBATIM: if the caller supplied a script and did NOT allow a rewrite, the office
                # speaks it word-for-word. This is what makes the t2v lane (the one that spoke a
                # rewritten script with no CTA) finally honor the user's words — same signal the
                # avatar reroute already used, now applied at the office so ALL lanes agree.
                user_script=_verbatim_user_script(assets),
                allow_rewrite=_rewrite_allowed(assets),
                # SINGLE SOURCE OF TRUTH: thread the requested cast/setting so the office PLAN matches
                # the render (a man on a porch, not a defaulted woman 45+).
                cast_gender=(assets.get("gender") or ""), cast_age_band=(assets.get("age_band") or ""),
                # #5/#6 free-text age/scene win over the enum ("38"/"35-40", "walking her dog") so the
                # office PLAN + character honor the exact ask, not a bucket. #9 from_scratch drops the
                # "regenerate a losing ad" framing when there's no source clip/metrics.
                cast_age=(assets.get("age") or ""),
                scene=(assets.get("scene") or ""), scene_detail=(assets.get("scene_detail") or ""),
                geo=(assets.get("state") or ""),
                from_scratch=(bool(assets.get("from_scratch")) or _gen_path == "scratch"
                              or not bool(req.context.get("metrics") if isinstance(req.context, dict) else None)),
                # T2V PER-CLIP OWNS THE SPEECH. On this lane each clip appends its OWN authoritative
                # `SPOKEN LINE FOR THIS CLIP`, so the composed beat prompt must NOT also render
                # `They say exactly: "…"` — two speech instructions in one prompt fight each other.
                # Harmless on the avatar lane (which speaks plan["script"], not the visual prompt).
                omit_spoken_line=True,
                run_critic=True)
            refined = (plan.get("beats") or [{}])[0].get("prompt")
            if refined:
                # VISUAL vs SPOKEN separation. Keeping the whole ad script inside the VISUAL prompt
                # made Seedance literally STAGE the ad copy — that is where the wrong/exaggerated
                # facial expressions and off-model characters came from. When the office produced a
                # real visual direction AND the words are carried separately (per-clip SPOKEN LINE),
                # the visual prompt is the beat direction ONLY. Fall back to the old concat when
                # there is no spoken script to carry the words (b-roll/scenic), so nothing regresses.
                if len((_vo_script or "").split()) >= 20:
                    prompt = refined
                    logger.info("[generate] visual prompt = team beat direction; the script is spoken "
                                "per-clip (not staged as visual instructions)")
                else:
                    prompt = f"{prompt}. {refined}"
            # HOOK FIX: the spoken lines must come from the team's HOOK-optimized script (hook in the
            # first sentence), NOT the raw user prompt. Previously _vo_script stayed = prompt on the
            # t2v lane, so the writer's rewrite drove only the visuals while the character spoke the
            # unhooked raw text. Use plan["script"] when the office produced one.
            _pscript = (plan.get("script") or "").strip()
            try:
                _pscript = team.scrub_placeholders(_pscript)   # never speak "[Website/App Name]"
            except Exception:
                pass
            if _pscript:
                _vo_script = _pscript
            # FIX A: drive avatar-lipsync off the PLAN'S ROUTE regardless of the explicit engine. CL
            # sends engine="seedance", so the engine-gated block below never fires — but a talking-head
            # plan (route=avatar_lipsync) must still run the FUNDED lip-sync recipe (TTS+LatentSync — no
            # t2v credits), not collapse to Seedance which dies on credits. GUARD: this only FLAGS the
            # plan; the reroute below has a castable-avatar guard — a SCENIC/non-talking-head plan (its
            # route is seedance/veo_extend/image_to_video, never avatar_lipsync) never trips this, and
            # even an avatar plan with no castable avatar falls through to t2v. Scenic stays t2v.
            plan_route = ((plan.get("plan") or {}).get("route") or {}).get("engine")
            if plan_route == "avatar_lipsync":
                _avatar_plan = True
            # AUTO: let the brain's Playbook route pick the engine (ChatGPT-style — user needn't choose)
            if engine in ("", "auto"):
                routed = ((plan.get("plan") or {}).get("route") or {}).get("engine") or "seedance"
                # FIX 1: a talking-head/UGC plan (route=avatar_lipsync) must run the FUNDED avatar-
                # lipsync recipe (TTS + LatentSync — NO t2v credits), not collapse to Seedance which
                # dies on credits. Flag it here; the reroute (with a castable-avatar guard) runs below,
                # OUTSIDE this try so a recipe failure/Cancelled isn't swallowed. Scenic/b-roll routes
                # (seedance / veo_extend / image_to_video) are UNCHANGED — genuine text-to-video.
                if routed == "avatar_lipsync":
                    _avatar_plan = True
                engine = "veo-extend" if routed == "veo_extend" else ("seedance" if routed in ("seedance", "avatar_lipsync", "image_to_video") else "seedance")
                logger.info(f"[generate] brain routed engine → {engine} (from {routed}"
                            + ("; talking-head plan → will try funded avatar-lipsync" if _avatar_plan else "") + ")")
        except Exception as e:
            logger.warning(f"generate: team pass skipped ({e})")

        # A spoken AD is "talking" even when the script never literally contains the word "speak" — the
        # old keyword-only gate missed real scripts ("my home insurance bill just came in…") → they fell
        # to the seconds-default (15s) and got crammed. Treat it as talking when: a reference video, OR a
        # spokesperson keyword, OR the office wrote a real script, OR the spoken text is prose (>=20 words).
        # Computed HERE (before the reroute) because the avatar-lipsync preference below depends on it.
        _spoken = (_vo_script or "").strip()
        is_talk = (bool(video_urls)
                   or bool(_pscript)                       # a real office/user script → ALWAYS a talking head,
                   or bool((assets.get("script") or "").strip())   # even if it's short (<20 words), so its
                   or bool(re.search(r"\b(talk|say|speak|character|spokesperson|person|host|ugc|voiceover|narrat)\b", prompt, re.I))
                   or len(_spoken.split()) >= 20)          # SPOKEN LINE is guaranteed into every clip's prompt

        # TALKING-HEAD UGC PREFERS AVATAR-LIPSYNC. The plan's route=avatar_lipsync is the only signal
        # today, and the brain often routes a plainly-talking-head UGC ask to seedance — which then
        # renders a synthetic person whose lips don't match, at t2v prices. Widen the preference to any
        # talking-head ask that ALSO has a castable avatar and NO reference video to imitate. Scenic /
        # b-roll (is_talk False) and winner-reference jobs (video_urls) are untouched → still t2v, and
        # the existing castable-avatar guard below still decides the final fall-through.
        # An EXPLICIT b-roll ask outranks both signals below. is_talk is only a heuristic
        # (len(script) >= 20 words), and every ad script — including a b-roll VOICEOVER script —
        # clears that bar, so this gate used to hijack every b-roll request into a talking head no
        # matter what the user asked for. request_type is a stated intent, not a guess: it wins.
        _asked_broll = str(assets.get("request_type") or "").lower() == "broll"
        if _asked_broll and _avatar_plan:
            _avatar_plan = False
            logger.info("[generate] request_type=broll → overriding talking-head plan, staying t2v")
        if not _avatar_plan and is_talk and not video_urls and not _asked_broll and _gen_path != "scratch":
            _cl0 = req.assets if isinstance(req.assets, dict) else {}
            if _cl0.get("fallback_avatar_url") or _cl0.get("library_avatar_url"):
                _avatar_plan = True
                logger.info("[generate] talking-head UGC + castable avatar + no reference video → "
                            "preferring funded avatar-lipsync over text-to-video")
        # USER FORCED SCRATCH: never reuse a real library clip — text-to-video only, no matter what the
        # brain's plan routed. (The match-gate below still applies in 'auto'.)
        if _avatar_plan and _gen_path == "scratch":
            _avatar_plan = False
            logger.info("[generate] user chose scratch → t2v (avatar-lipsync reroute disabled)")
        # #7 HONOR THE USER'S EXPLICIT ENGINE. If they picked a t2v engine (seedance / veo / …, anything
        # that is NOT 'auto'/''), do NOT silently reroute to avatar-lipsync — that is exactly the
        # "director/plan said avatar_lipsync but it ran t2v" mismatch, and it also spends t2v credits on
        # a path the user didn't ask for. Only 'auto'/'' lets the brain pick the engine.
        _user_engine = str(assets.get("engine") or "").strip().lower()
        if _avatar_plan and _user_engine and _user_engine not in ("auto", "", "avatar", "avatar_lipsync", "avatar-lipsync"):
            _avatar_plan = False
            logger.info(f"[generate] user explicitly chose engine={_user_engine} → honoring t2v (avatar-lipsync reroute disabled)")

        # FIX C (Finance) + FIX B (preflight): before ANY paid attempt, the Finance seat records the
        # provider/credit decision. Talking-head plan → avatar-lipsync (funded, cheaper); if every t2v
        # provider is known-down (cached) this also spares the doomed Kie attempt. Scenic/non-avatar
        # plan → t2v (seedance/veo). Best-effort — never blocks generation.
        try:
            from ..services import creative_team_activity as _fin
            _fin_ts = _fin.start("finance", req.request_id, "provider/credit preflight")
            if _avatar_plan:
                _decision = ("t2v unavailable → routing avatar-lipsync (funded)"
                             if not _t2v_available() else "plan → avatar-lipsync (funded, cheaper than t2v)")
            else:
                _decision = f"t2v {'funded' if _t2v_available() else 'down (cache) — will attempt then fall back'} → {engine}"
            _fin.finish("finance", req.request_id, _fin_ts, detail=_decision)
            logger.info(f"[finance] preflight: {_decision}")
        except Exception as _e:
            logger.warning(f"[generate] finance preflight skipped ({_e})")

        # FIX 1 (reroute): plan chose avatar_lipsync → run the funded lip-sync recipe instead of a
        # credit-hungry t2v. GUARDS: only when a suitable avatar clip is castable (CL-supplied
        # fallback_avatar_url, else a library cast); if NONE is castable we KEEP t2v (fall through) —
        # never hard-fail. If the recipe itself errors (non-cancellation), also fall back to t2v.
        if _avatar_plan:
            _cl = req.assets if isinstance(req.assets, dict) else {}
            _cast_url = _cl.get("fallback_avatar_url") or _cl.get("library_avatar_url")
            # MATCH-GATED REROUTE (Feature 2). In 'auto' with a stated gender, the reused clip MUST match
            # the brief — gender at minimum, age/scene strongly preferred. Score a library cast against the
            # brief traits from assets (not a re-parse of the prompt, which drops the requested scene); if
            # the best castable clip is the wrong gender (or nothing casts), DO NOT reuse it — fall through
            # to t2v scratch. 'avatar' mode skips the gate (best real match wins, even if imperfect).
            _want_g = str(assets.get("gender") or "").lower()
            _want_a = str(assets.get("age_band") or "").lower()
            _want_scene = str(assets.get("scene") or "").lower()
            if _gen_path == "auto" and _want_g:
                try:
                    _intent = await _parse_intent_text(prompt)
                    for _k, _v in (("gender", _want_g), ("age_band", _want_a), ("scene", _want_scene)):
                        if _v:
                            _intent[_k] = _v   # brief traits are authoritative over the prompt parse
                    _cu, _ct, _au, _at = await _cast_library_avatar(_intent)
                except Exception as _e:
                    logger.warning(f"[generate] auto match-cast probe failed: {_e}")
                    _cu, _ct = None, {}
                _ct = _ct or {}
                _g_ok = (_ct.get("gender") or "").lower() == _want_g
                _a_ok = bool(_want_a) and (_ct.get("age_band") or "").lower() == _want_a
                _s_ok = bool(_want_scene) and _want_scene in (_ct.get("scene") or "").lower()
                # HARD requirements: gender must match; when a SCENE was asked for, it must match too
                # (a specific brief — man/45+/porch — must NOT reuse a man-in-a-CAR clip). Age is a
                # strong preference, logged but not a hard gate (bands are fuzzy). No match → t2v scratch.
                _match_ok = bool(_cu) and _g_ok and (_s_ok or not _want_scene)
                if _match_ok:
                    _cast_url = _cu   # matched pick, scored against the full brief
                    logger.info("[generate] library clip matches brief (gender ✓"
                                + (" age ✓" if _a_ok else "") + (" scene ✓" if _s_ok else "")
                                + f") → avatar-lipsync on {_cu}")
                else:
                    logger.info(f"[generate] no library clip matches brief (gender={_want_g} "
                                f"age={_want_a or '—'} scene={_want_scene or '—'}; best clip "
                                f"gender={(_ct.get('gender') or '—')} scene={(_ct.get('scene') or '—')}) "
                                f"→ t2v scratch")
                    _cast_url = None
            elif not _cast_url:
                # 'avatar' mode, or 'auto' with no stated gender → today's behavior: best library talker.
                try:
                    _cu, _ct, _au, _at = await _cast_library_avatar(await _parse_intent_text(prompt))
                    _cast_url = _cu   # only the avatar-lipsync-ready pick (never the any-clip pick)
                except Exception as _e:
                    logger.warning(f"[generate] avatar cast probe failed: {_e}")
                    _cast_url = None
            if _cast_url:
                _vert = (req.context.get("vertical", "") if isinstance(req.context, dict) else "") or ""
                # FIX: the avatar must SPEAK the Creative Director's WRITTEN ad script (strategist/
                # scriptwriter output), NOT the raw scene-description prompt (which the avatar would
                # otherwise read aloud). Fallback chain: written ad script → concatenated talking-head
                # beat lines → raw prompt (last resort). Never empty.
                # …EXCEPT when the user supplied the script themselves. A Studio script the user
                # read and approved is verbatim intent, not a brief — the office rewriting it is a
                # defect, not an improvement. This is why an approved CAR-insurance script came out
                # of the avatar's mouth as a HOME-insurance story with a neighbour and a state that
                # nobody wrote: the vertical DNA rewrite always outranked the user's own words.
                _spoken_script = ""
                # UNIVERSAL RULE (every path — Studio, Avatar Studio, loser regeneration, API):
                # if a script was PROVIDED, the office never rewrites it. Verbatim is the DEFAULT
                # whenever assets.script exists; only an explicit rewrite/modify mode opts out. Not
                # keyed on a per-caller flag on purpose — a new caller that forgets the flag must
                # still get the user's words, because forgetting it silently ships a rewrite.
                _user_script = _verbatim_user_script(assets)
                if _user_script and not _rewrite_allowed(assets):
                    _spoken_script = _user_script
                    logger.info("[generate] script provided by caller — speaking it VERBATIM, "
                                "office rewrite not used")
                try:
                    _spoken_script = _spoken_script or (plan.get("script") or "").strip()
                    if not _spoken_script:
                        _lines = [str(b.get("line") or "").strip()
                                  for b in (plan.get("beats") or [])
                                  if b.get("shot_type") == "talking_head" and str(b.get("line") or "").strip()]
                        _spoken_script = " ".join(_lines).strip()
                except Exception as _e:
                    logger.warning(f"[generate] written-script lookup failed: {_e}")
                    _spoken_script = ""
                _spoken_script = _spoken_script or (assets.get("prompt") or prompt)
                # CARRY THE CAST THROUGH. Rebuilding assets without gender/age_band made
                # pick_voice raise UnknownGenderError → the whole avatar lane silently fell back
                # to synthetic t2v (which is exactly why characters looked AI-generated).
                # House default when the caller sends nothing: woman.
                req.assets = {**(req.assets or {}),
                              "character_video_url": _cast_url,
                              "script": _spoken_script,
                              "gender": (assets.get("gender") or "female"),
                              "age_band": assets.get("age_band"),
                              # PROPAGATE the verbatim decision so recipe_avatar_lipsync (which reads
                              # script_mode) honors an allow_rewrite:false that arrived flag-only.
                              **({"script_mode": "verbatim"} if not _rewrite_allowed(assets) else {}),
                              "allow_rewrite": _rewrite_allowed(assets),
                              "seconds": int(seconds), "vertical": _vert}
                logger.info(f"[generate] plan → avatar_lipsync; running funded lip-sync on {_cast_url}")
                try:
                    out = await recipe_avatar_lipsync(req)
                except Cancelled:
                    raise
                except Exception as _e:
                    logger.error(f"[generate] plan avatar-lipsync failed ({_e}) — falling back to t2v")
                    out = None
                if out:
                    for r in out:
                        r["recipe"] = "Generate — Avatar Lip-sync (talking-head plan)"
                        r["whats_changed"] = ("Talking-head plan — cast a matching library avatar and "
                            "lip-synced your script to it (no text-to-video credits used). "
                            + (r.get("whats_changed") or ""))[:600]
                    return out
            else:
                logger.info("[generate] plan → avatar_lipsync but no castable avatar — keeping text-to-video")

        # Slice the BODY, then append the directives — never the other way round. Concatenating
        # first and slicing after silently cut HOOK and NO_TEXT off whenever the script was long,
        # so the model was never told "no on-screen text" (→ gibberish AI text burned in the frame,
        # colliding with our own captions).
        # A talking-head ad opens ALREADY speaking (the HOOK); a b-roll beat has NO face/speaker, so it
        # must NEVER be told "already speaking from the first frame" — that contradiction is exactly
        # what rendered a faceless clip that then failed lip-sync QA. NO_TEXT applies to both.
        _talkhook = HOOK if is_talk else ""
        prompt = prompt[:max(200, 1900 - len(_talkhook) - len(NO_TEXT))] + _talkhook + NO_TEXT

        if engine in ("veo-extend", "veo", "veo3-google"):
          # Veo (Google) can 401/402/429/5xx or time out. On any non-cancellation failure,
          # fall through to the Seedance (Kie) lane below so the job still produces a video.
          try:
            from ..services.video_creator import VideoCreatorService as VC
            from ..services import creative_team_activity as act
            # MULTI-SCENE: one scene per line → base is scene 0, each extension advances to the next
            # scene (cycles if fewer lines than segments). Single-line prompts reuse the same prompt.
            scenes = [s.strip() for s in prompt.splitlines() if s.strip()] or [prompt]
            # base 8s + (segs-1)×7s. Cap 21 segments (Veo ceiling) → up to ~148s.
            segs = max(len(scenes), max(1, round((seconds - 8) / 7) + 1))
            segs = max(1, min(21, segs))
            act.set_expected_sec(req.request_id, segs * 240)   # Veo ~2-4 min/segment
            def _scene(i): return scenes[i % len(scenes)]
            if image_urls:
                imgp = await _download_to_temp(image_urls[0], suffix=".png")
                base = await asyncio.to_thread(VC.generate_from_image, imgp, _scene(0), aspect_ratio, 8)
            else:
                base = await asyncio.to_thread(VC.generate_video, _scene(0), aspect_ratio, "720p", "8")
            act.tick(req.request_id, f"Veo base clip (scene 1/{segs})")
            st = await _veo_wait(base["operation_name"])
            paths = [st["video_path"]]; prev = base["operation_name"]
            for k in range(1, segs):
                await _abort_if_cancelled(req, f"veo extend {k}")
                act.tick(req.request_id, f"Veo extend (scene {k+1}/{segs})")
                ext = await asyncio.to_thread(VC.extend_video, prev, _scene(k))
                st = await _veo_wait(ext["operation_name"])
                paths.append(st["video_path"]); prev = ext["operation_name"]
            if len(paths) == 1:
                import shutil; shutil.copy(paths[0], out_path)
            else:
                lst = os.path.join(work, "l.txt")
                with open(lst, "w") as f:
                    for p in paths:
                        f.write(f"file '{p}'\n")
                await asyncio.to_thread(_ffmpeg,
                    ["-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out_path], timeout=600)
            _ae_persist(out_path, name)   # durable AE S3 copy (both buckets)
            approx = 8 + 7 * (len(paths) - 1)
            return [{"recipe": "Generate — Veo 3.1 extend", "video_url": url, "confidence": 0.7,
                     "whats_changed": (f"Veo 3.1 {'image-to-video + ' if image_urls else ''}native extend — "
                        f"{len(paths)} segment(s) (~{approx}s) from your prompt.")}]
          except Cancelled:
            raise
          except Exception as e:
            logger.warning(f"Veo generate/extend failed ({e}) — falling back to Seedance (Kie)")
            # fall through to the Seedance lane below

        # ── Seedance 2.0 (Kie) — native single clip up to 15s, full reference set ──
        # (Kie call now goes through _generate_t2v_clip, which adds fal fallback on credits-out.)
        from ..services import creative_team_activity as act
        dur = max(4, min(15, seconds))   # Seedance range 4-15s
        act.set_expected_sec(req.request_id, 180)   # Seedance ~2-4 min per clip
        # PREP reference videos (library/scraper clips): trim to ≤12s + scrub captions + re-host to
        # our /uploads so Kie gets a clean, non-expiring ref under its 15s cap. Skip non-video refs
        # (e.g. an image winner) — those go through reference_image_urls instead. Keep up to 3.
        prepped_vids = []
        for vu in (video_urls or [])[:3]:
            if re.search(r"\.(jpg|jpeg|png|webp|gif)(\?|$)", vu, re.I):
                if vu not in (image_urls or []):
                    image_urls = (image_urls or []) + [vu]   # treat image refs as image references
                continue
            act.tick(req.request_id, "preparing reference clip")
            pv = await _prep_winner_clip(vu, work)
            if pv:
                prepped_vids.append(pv)
        # Seedance caps ~15s/clip. For longer requests, STITCH multiple clips: each clip after the
        # first is anchored to the previous clip's LAST FRAME (+ the original refs) so the character/
        # scene stays consistent across the cut. e.g. 45s → 3 × 15s clips.
        import math as _math
        n_clips = max(1, _math.ceil(seconds / 15))
        per = max(4, min(15, _math.ceil(seconds / n_clips)))
        act.set_expected_sec(req.request_id, 180 * n_clips)
        W2, H2 = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
        # A spoken AD is "talking" even when the script never literally contains the word "speak" — the
        # old keyword-only gate missed real scripts ("my home insurance bill just came in…") → they fell
        # to the seconds-default (15s) and got crammed. Treat it as talking when: a reference video, OR a
        # spokesperson keyword, OR the office wrote a real script, OR the spoken text is prose (>=20 words).
        # (is_talk is computed BEFORE the avatar reroute above — it also drives that decision.)
        # SPLIT the spoken script into ONE chunk per clip so each clip speaks its OWN part in sequence
        # (kills the "same opening rendered twice" bug — _attempt uses bt.prompt, so the chunk MUST go
        # into the per-clip prompt). Let the script's natural beats drive clip count + pacing instead of
        # a fixed seconds/15 that repeats. Non-talking (broll) keeps the seconds-based split.
        from ..services import realism_prompt_engine as _rpe
        _vo_chunks = _rpe.split_into_clips(_vo_script or prompt, max_words=28) if is_talk else []
        # MULTI-CLIP TALKING-HEAD KEEPS ITS FULL SPLIT (reverted 2026-08-03). A prior "identity guard"
        # (commit 15292317, 2026-07-29) capped talking-head t2v fallback to ONE clip on the theory that
        # multi-clip Seedance drifts the face. In practice the proven 7/27-7/28 renders (2-4 clips,
        # ~23-43s, full scripts, "stitched with frame-continuity") show the last-frame → next-clip
        # reference_image handoff below (5114-5122) holds identity fine — and that cap silently dropped
        # the back HALF of every ad (offer + CTA), e.g. a 20s script rendered 9.4s with the $/CTA cut.
        # So we do NOT truncate here: render every script chunk as its own frame-continuity-stitched
        # clip so the WHOLE script is spoken. Length is bounded by the seconds budget below (which keeps
        # the leading chunks that fit), never by throwing the tail away.
        _per_list = None
        if _vo_chunks:
            # Size clips off the SCRIPT, not the requested `seconds`: render EVERY chunk (so the whole
            # script gets spoken — the old min(...,6) cap silently dropped the tail and cut the ad
            # short), and give each clip enough seconds for its own words (~2.5 words/sec + 1s breathing
            # room), clamped to the model's ~15s/clip cap. 8-clip safety ceiling against a runaway split.
            n_clips = max(1, min(len(_vo_chunks), 8))
            def _clip_secs(_txt):
                # Size the clip to Seedance's ACTUAL speaking pace. 2.2 w/s (+1s pad) sized clips far
                # LONGER than the model's real delivery (~3.4 w/s), so a ~28-word chunk that Seedance
                # speaks in ~7s got a 13s clip — and Seedance filled the ~6s gap with IMPROVISED GARBAGE
                # speech (the "garbage after 6-7s" + audio drifting off the script). Match the real pace,
                # no pad, so the clip ends when the words do and there's no room to improvise.
                _w = len((_txt or "").split())
                return max(4, min(15, _math.ceil(_w / 3.4)))
            _per_list = [_clip_secs(c) for c in _vo_chunks[:n_clips]]
            # DURATION PRIORITY: Auto (no explicit length) → the whole script renders. An EXPLICIT length
            # is a CAP — keep only as many leading chunks as fit the budget (never cram the full script
            # into a short window; drop the tail instead, which reads far better than rushed speech).
            if not _auto_dur and seconds > 0:
                # An explicit length is a TARGET, not a hard truncation point. Dropping a chunk the
                # moment we crossed `seconds` under-delivered the ad (the CTA fell off a 20s request
                # by 2s). Allow up to 25% overrun so the script finishes; only drop beyond that.
                _budget = seconds * 1.25
                _acc, _keep = 0, 0
                for _s in _per_list:
                    if _acc + _s > _budget and _keep >= 1:
                        break
                    _acc += _s; _keep += 1
                n_clips = _keep
                _per_list = _per_list[:_keep]
                # Captions/TTS must describe ONLY what actually got rendered. Leaving _vo_script as
                # the FULL script made the aligner diff ~200 unmatched tokens into a single word's
                # <0.4s window — the back half of the script flashed as nonsense.
                _vo_script = " ".join(_vo_chunks[:_keep])
                logger.info(f"[generate] explicit {seconds}s target (+25% = {_budget:.0f}s) → {n_clips} "
                            f"clip(s) (~{sum(_per_list)}s) of {len(_vo_chunks)} script chunk(s)")
            else:
                logger.info(f"[generate] AUTO duration → full script: {n_clips} clip(s), ~{sum(_per_list)}s")
            logger.info(f"[generate] duration: requested "
                        f"{'auto' if _auto_dur else str(seconds) + 's'} → planned {sum(_per_list)}s "
                        f"across {n_clips} clip(s)")
        # ── HARD COST GATE ────────────────────────────────────────────────────────────────────
        # t2v bills per rendered second and we may render up to 8 clips, so a long script at a high
        # resolution can run into many dollars. Project the whole stitch BEFORE the first paid clip.
        _planned_sec = sum(_per_list) if _per_list else n_clips * per
        _gate_job_cost(req.request_id,
                       f"text-to-video {n_clips} clip(s) / {_planned_sec}s @ {resolution}",
                       _t2v_projected_usd(resolution, bool(video_urls or image_urls), _planned_sec),
                       assets)
        clip_paths = []
        produced = {}                    # which t2v provider actually rendered (Kie / fal fallback)
        _identity_ref = None             # #1 char-lock: ONE stable identity frame from clip 0, reused as
                                         # @Image1 on every later clip so the face can't drift down a chain
        try:
          for ci in range(n_clips):
            per_ci = _per_list[ci] if _per_list else per   # this clip's own duration (script-sized)
            await _abort_if_cancelled(req, f"seedance clip {ci+1}/{n_clips}")
            act.tick(req.request_id, f"Seedance clip {ci+1}/{n_clips} · {per_ci}s · {aspect_ratio}")
            imgs = list(image_urls or [])
            cprompt = prompt
            if ci > 0:
                # #1 CHARACTER LOCK. Anchor EVERY continuation clip to the SAME stable identity frame
                # captured from clip 0 (a clean early/mid talking frame — see below). The OLD code grabbed
                # clip 0's LAST frame ((_pd-0.05)s) and served it as the next clip's first-frame — but that
                # end-of-file extraction fails silently, so in practice clip 2 got NO reference_image at
                # all (verified in the live Kie input) → Seedance generated a FRESH face. One shared
                # @Image1 anchor, reused on every clip, stops the face/scene drifting down a chain.
                # NOTE: no [:1900] cap here (it chopped 'Continue seamlessly' mid-word); the whole prompt
                # is bounded to 6000 after the SPOKEN LINE is appended below.
                if _identity_ref:
                    imgs = [_identity_ref] + imgs
                cprompt = (prompt +
                           " @Image1 is the EXACT SAME PERSON who must appear in this clip — identical"
                           " face, hair, skin, age and wardrobe as @Image1; do NOT generate a different"
                           " person. Continue seamlessly from the previous shot — same character, setting"
                           " and lighting; one continuous action, match-cut.")
            # THIS clip speaks ONLY its own chunk of the script, in sequence — never restart or repeat
            # earlier lines. First clip must speak from the very first frame (no silent hook lead-in).
            _chunk = _vo_chunks[ci] if ci < len(_vo_chunks) else ""
            if _chunk:
                # A talking beat has a SPOKEN LINE → it MUST be a talking head: the speaker's face
                # visible, mouth moving, talking directly to camera. A b-roll "no faces to camera"
                # style must never leak into a talking clip — it rendered a FACELESS frame that then
                # failed lip-sync QA ("not a talking head") and burned a retry. Strip that
                # contradiction and state the face requirement positively (b-roll never reaches here:
                # _vo_chunks is only built when is_talk, so _chunk is empty for a scenic beat).
                cprompt = _strip_no_face(cprompt) + (
                    " The speaker's face is clearly visible, talking DIRECTLY to camera with natural "
                    "mouth movement — this is a talking head, not b-roll.")
                _hookrule = (" The person is ALREADY speaking from the very first frame — no silent "
                             "lead-in, no dead air in the opening." if ci == 0 else "")
                cprompt = (cprompt + f' SPOKEN LINE FOR THIS CLIP — say ONLY this, word for word, and do '
                           f'NOT repeat any earlier line: "{_chunk}".' + _hookrule)[:6000]
            # Route EACH clip through the vision eval loop: the Critic grades the rendered clip,
            # coaches the faulted persona + folds the fix into the prompt, and retries (bounded).
            beat = {"i": ci, "prompt": cprompt, "shot_type": ("talking_head" if is_talk else "broll"), "line": _chunk}
            # LOG + PERSIST exactly what this t2v clip is being asked to render (prompt + params).
            _log_model_call(req.request_id, f"video/seedance clip {ci+1}/{n_clips}", f"seedance-{resolution}",
                            {"prompt": cprompt, "seconds": per_ci, "resolution": resolution,
                             "aspect_ratio": aspect_ratio, "shot_type": beat["shot_type"],
                             "images": len(imgs), "videos": len(prepped_vids), "audios": len(audio_urls)})

            # Provider fallback: Kie-Seedance → fal-seedance → fal-kling → fal-wan. A credits/quota/5xx
            # error on one advances to the next; _AllVideoProvidersDown only if every configured one is down.
            async def _attempt(bt, _imgs=imgs, _first=(ci == 0), _cont=(ci > 0)):
                return await _generate_t2v_clip(
                    prompt=bt.get("prompt"),
                    image_urls=_imgs, video_urls=prepped_vids, audio_urls=audio_urls,
                    seconds=per_ci, resolution=resolution, aspect_ratio=aspect_ratio,
                    generate_audio=generate_audio, first=_first, produced=produced,
                    is_continuation=_cont)

            cp = await _gen_beat_with_eval(req.request_id, beat, work, _attempt)
            if cp and os.path.exists(cp):
                clip_paths.append(cp)
                # #1 Lock identity from a CLEAN early/mid frame of clip 0 (a stable talking frame — NOT
                # the fragile last frame) → served as @Image1 for every subsequent clip.
                if ci == 0 and _identity_ref is None:
                    _identity_ref = _frame_to_public_url(cp, min(2.0, max(0.5, (per_ci or 8) * 0.4)))
                    logger.info(f"[generate] character-lock ref {'captured' if _identity_ref else 'FAILED'} from clip 0")
        except _AllVideoProvidersDown as _pd_exc:
            if clip_paths:
                logger.warning(f"[generate] t2v ran out mid-stitch ({_pd_exc}) — stitching the "
                               f"{len(clip_paths)} clip(s) already rendered")
            else:
                logger.warning(f"[generate] {_pd_exc} — routing to library fallback tiers")
                return await _generate_library_fallback(req, prompt, aspect_ratio, seconds,
                                                        reasons=[str(_pd_exc)])
        if not clip_paths:
            # every provider unavailable AND nothing rendered → library fallback (never a bare error)
            return await _generate_library_fallback(req, prompt, aspect_ratio, seconds,
                                                    reasons=["no clip produced (check Kie/fal credits)"])
        if len(clip_paths) == 1:
            import shutil; shutil.copy(clip_paths[0], out_path)
        else:
            # normalize every clip to uniform W:H:fps + aac, then concat (perfect frames + audio).
            # NO UPSCALING: we render 480p on purpose, so concat at the clips' OWN native size.
            # Scaling 480p up to 1080x1920 only faked a resolution number and softened the image.
            # HARD CUT is correct here: continuation clips start on the previous clip's real last
            # frame (true first-frame i2v), so the boundary frames already match — a crossfade would
            # only blur a seam that no longer exists.
            _nw, _nh = await asyncio.to_thread(_ffprobe_dims, clip_paths[0])
            if _nw and _nh:
                W2, H2 = int(_nw) - (int(_nw) % 2), int(_nh) - (int(_nh) % 2)
            norm = []
            for i, cp in enumerate(clip_paths):
                npath = os.path.join(work, f"sd{i}.mp4")
                # #4 Trim the frozen/silent tail off NON-final clips so they butt-join cleanly (the last
                # clip keeps its full ending). Only trims a clear trailing silence, with a 0.2s margin.
                _te = None if i == len(clip_paths) - 1 else await asyncio.to_thread(_speech_end_sec, cp)
                _trim = ["-t", str(_te)] if _te else []
                if _te:
                    logger.info(f"[generate] clip {i+1}: trimmed idle tail → {_te}s (butt-join)")
                await asyncio.to_thread(_ffmpeg,
                    ["-i", cp, *_trim, "-vf", f"scale={W2}:{H2}:force_original_aspect_ratio=increase,crop={W2}:{H2},fps=30",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "192k", "-ar", "48000", npath], timeout=300)
                norm.append(npath)
            lst = os.path.join(work, "sdlist.txt")
            with open(lst, "w") as f:
                for n2 in norm:
                    f.write(f"file '{n2}'\n")
            await asyncio.to_thread(_ffmpeg,
                ["-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out_path], timeout=900)
        # ── AUDIO BACKSTOP (deterministic) + capability-honest recovery ──────────────────────────
        # A frame critic cannot hear, so a silent fallback clip would ship undetected. ffprobe the
        # REAL output: if audio was requested but the (silent fal) provider produced none, narrate the
        # script with TTS and mux it so the ad isn't silent; if that can't run, ship + flag honestly.
        _audio_state = "native"   # native (provider produced it) | tts (we narrated) | none (silent)
        if generate_audio:
            from ..services import capabilities as _caps
            _probe = _probe_audio(out_path)                       # True | False | None(unknown)
            _prov_has_audio = _caps.provides_audio(produced.get("provider") or "")
            if _probe is True or (_probe is None and _prov_has_audio):
                # confirmed audio, OR the probe couldn't tell but the provider is DECLARED audio-capable
                # (don't let a probe error mislabel a KNOWN-silent provider's clip as 'native').
                _audio_state = "native"
            elif await _mux_tts_voiceover(req, out_path, _vo_script, work):
                _audio_state = "tts"
            else:
                _audio_state = "none"
                logger.warning(f"[generate] audio requested but provider {produced.get('provider')} "
                               f"shipped SILENT video and no narratable script — delivering without audio")
        # ── Best-effort: save the FULL stitched clip as a REUSABLE library avatar (non-fatal; never delays) ──
        # out_path is NOW the COMPLETE character video (every clip stitched) WITH audio but BEFORE the
        # caption finish pass below burns onto it — the ideal caption-free, full-length reusable avatar
        # (captions get re-added per new script when it's re-lipsynced). Snapshot a copy NOW so the
        # upcoming caption/trim passes don't alter the saved avatar, then hand it to CL with the render's
        # FULL cast/scene metadata (gender + age + derived age_band + scene + scene_detail + vertical +
        # state/geo + ethnicity + wardrobe + character_desc) so it's easy to pick/filter later. The save
        # uploads to durable S3 + POSTs in a detached task → never blocks the finish/return.
        try:
            if is_talk and os.path.exists(out_path):
                import uuid as _uuid, shutil as _avshu
                _av_src = os.path.join(work, f"avatar_full_{_uuid.uuid4().hex[:8]}.mp4")
                _avshu.copy(out_path, _av_src)   # caption-free FULL clip, frozen before the finish pass
                _age_raw = str(assets.get("age") or assets.get("age_band") or "").strip()
                _av_meta = {
                    "gender": (assets.get("gender") or ""),
                    "age": _age_raw,
                    "age_band": (assets.get("age_band") or _age_band_from(_age_raw)),
                    "scene": (assets.get("scene") or ""),
                    "scene_detail": (assets.get("scene_detail") or assets.get("scene") or ""),
                    "vertical": (vertical or assets.get("vertical") or ""),
                    "state": (assets.get("state") or assets.get("state_code") or ""),
                    "ethnicity": (assets.get("ethnicity") or ""),
                    "wardrobe": (assets.get("wardrobe") or ""),
                    "character_desc": (assets.get("character_desc")
                                       or f"{_age_raw} {assets.get('gender') or ''}".strip()),
                    "name": f"T2V avatar {req.request_id[:8]}",
                }
                _avt = asyncio.create_task(_save_t2v_avatar_to_cl(_av_src, _av_meta))
                _t2v_avatar_tasks.add(_avt); _avt.add_done_callback(_t2v_avatar_tasks.discard)
                logger.info(f"[generate] queued FULL-clip t2v avatar save '{_av_meta['name']}' "
                            f"(gender={_av_meta['gender']} age_band={_av_meta['age_band']} "
                            f"state={_av_meta['state'] or '—'} scene={_av_meta['scene_detail'][:40]})")
        except Exception as _save_e:
            logger.warning(f"[generate] t2v avatar auto-save skipped: {_save_e}")
        # ── FINISH PASS — captions (explicit user choice) + consumer-camera grade — ONE encode ──────
        # Captions: the t2v lane historically shipped clean footage (NO_TEXT). When the request asks
        # for captions, align the spoken script against the REAL output audio (whisper) and burn ASS —
        # same path the avatar-lipsync lane uses. Grade: a subtle sensor-grain + slightly faded
        # contrast/saturation so the render reads as a real phone capture, not a clean AI plate (the
        # single biggest "looks AI-generated" lever after the prompt). Both fold into one ffmpeg pass.
        _caps_burned = False
        _vf_parts = []
        _want_caps = bool(assets.get("captions", True)) and _audio_state != "none"
        if _want_caps:
            try:
                from ..services import captions as cap
                _cap_audio = os.path.join(work, "capaudio.wav")
                await asyncio.to_thread(_ffmpeg, ["-i", out_path, "-vn", "-ac", "1", "-ar", "16000", "-y", _cap_audio], 120)
                # When the provider generated its OWN speech (native audio), it never says our words
                # verbatim — forcing our script onto it made the aligner produce nonsense. Pass an
                # empty text so captions come from the REAL transcript. Only our own TTS (which does
                # speak the script) is aligned against the script text.
                _cap_text = (_vo_script or prompt) if _audio_state == "tts" else ""
                _cwords, _cmethod = await asyncio.to_thread(lambda: cap.align(_cap_audio, _cap_text))
                if _cwords:
                    _cw, _ch = await asyncio.to_thread(_video_dims, out_path)
                    _ass = cap.build_ass(_cwords, os.path.join(work, f"cap_{req.request_id[:8]}.ass"),
                                         play_w=_cw or W2, play_h=_ch or H2)
                    if _ass and os.path.exists(_ass):
                        _vf_parts.append(f"ass={_ass}"); _caps_burned = True
                        logger.info(f"[generate] captions: {len(_cwords)} words aligned ({_cmethod})")
            except Exception as _ce:
                logger.warning(f"[generate] caption burn skipped: {_ce}")
        # NOTE: a post ffmpeg grain/noise "realism" grade was tried here and REMOVED — a temporal noise
        # filter on AI faces at 480p caused shimmering / "lasered" eyes and a cartoon look. Realism must
        # come from the PROMPT (REALISM_LAYER), never a destructive post-filter. Captions-only pass now.
        if _vf_parts:
            try:
                _fin = os.path.join(work, "finish.mp4")
                await asyncio.to_thread(_ffmpeg,
                    ["-i", out_path, "-vf", ",".join(_vf_parts), "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", "-y", _fin], 900)
                import shutil as _shf; _shf.move(_fin, out_path)
            except Exception as _fe:
                logger.warning(f"[generate] finish pass skipped: {_fe}")
        # ── TRIM TRAILING DEAD-AIR / FROZEN TAIL (t2v/Seedance ONLY) ────────────────────────────────
        # Seedance renders a FIXED clip length, so when the narration ends before the clip does the tail
        # is a frozen frame + dead silence that "hangs" (user: t2v clip "stuck for the last 3 seconds").
        # This is the MIRROR of the avatar lane's freeze-hold (which EXTENDS a short video to cover the
        # voice): here we END cleanly right after the last word (+ a ~0.4s breath). Detect the real end of
        # speech via silencedetect; if the trailing dead-air is meaningful (>0.8s), re-encode with `-t`
        # (no resolution change). Never over-trim below a 3s floor. Runs before the eval gate so QA sees
        # the corrected file. Best-effort: any failure keeps the original clip.
        try:
            _vend = await asyncio.to_thread(_stream_duration, out_path, "v") \
                    or await asyncio.to_thread(_ffprobe_duration, out_path)
            _spk_end = await asyncio.to_thread(_speech_end_ts, out_path, _vend)
            if _vend and _spk_end is not None and (_vend - _spk_end) > 0.8:
                _trim_to = max(3.0, min(_vend, _spk_end + 0.4))
                if _vend - _trim_to > 0.25:   # only re-encode when it actually shortens the clip
                    _trimmed = os.path.join(work, "trimmed.mp4")
                    await asyncio.to_thread(_ffmpeg,
                        ["-i", out_path, "-t", f"{_trim_to:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                         "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-y", _trimmed], 400)
                    if os.path.exists(_trimmed):
                        import shutil as _sht; _sht.move(_trimmed, out_path)
                        logger.info(f"[generate] t2v trailing dead-air {_vend - _trim_to:.1f}s trimmed "
                                    f"→ ends at {_trim_to:.1f}s (last word ~{_spk_end:.1f}s)")
        except Exception as _te:
            logger.warning(f"[generate] trailing dead-air trim skipped: {_te}")
        # EVAL GATE — the global examiner on the assembled deliverable (faithfulness, never-abrupt,
        # residual captions, specs, cast + a cross-family semantic judge). Wraps final-video QA so it
        # runs once. Pass the RESOLVED captions flag (whether we actually burned any). Recorded to
        # creative_decisions + creative_lessons either way; returns a deliver decision.
        _final_qa = {}
        try:
            _final_qa = await _eval_gate(req.request_id, out_path, _vo_script or prompt,
                                         {**assets, "captions": _caps_burned}, work)
        except Exception as _qe:
            logger.warning(f"[generate] eval gate skipped: {_qe}")
        _ae_persist(out_path, name)   # durable AE S3 copy (both buckets)
        # Cost = the rate of the provider that ACTUALLY produced the clip (not always Kie).
        _with_input = bool(video_urls or image_urls)
        _prov = produced.get("provider") or "kie-seedance"
        if str(_prov).startswith("fal"):
            # fal lanes bill a flat per-second rate per model (fal-seedance/kling/wan) — use fal's.
            from ..services.fal_video import FAL_VIDEO_COST_PER_SEC
            _persec = FAL_VIDEO_COST_PER_SEC.get(_prov, 0.09)
        elif _prov == "kie-veo":
            from ..services.pricing import Pricing
            _persec = (Pricing.VEO31_FAST_PER_SEC if str(resolution).lower() in ("480p", "540p")
                       else Pricing.VEO31_STANDARD_PER_SEC)
        else:
            # Kie Seedance — OFFICIAL per-second rates by resolution; with-input is cheaper.
            _rr = _KIE_RATE_PER_SEC.get(str(resolution).lower(), _KIE_RATE_PER_SEC["720p"])
            _persec = _rr[0] if _with_input else _rr[1]
        _vid_sec = sum(_per_list[:len(clip_paths)]) if _per_list else len(clip_paths) * per
        _track_cost(req.request_id, "video", _prov, model=f"seedance-{resolution}",
                    units=_vid_sec, unit_type="sec", cost_usd=round(_persec * _vid_sec, 4),
                    note=("with-input" if _with_input else "text→video")
                         + ("" if _prov == "kie-seedance" else f" · fallback provider {_prov}"))
        refs = []
        if image_urls: refs.append(f"{len(image_urls)} image(s)")
        if video_urls: refs.append(f"{len(video_urls)} video(s)")
        if audio_urls: refs.append(f"{len(audio_urls)} audio")
        _prov_note = "" if _prov == "kie-seedance" else f" · via {_prov} (fallback — Kie unavailable)"
        # QA verdicts must CHANGE something, not just be recorded. A confirmed final-video defect
        # (duplicate speech / unspoken CTA / artifacts) drops the delivered confidence so a broken
        # take ranks BELOW clean output everywhere confidence is used, instead of shipping as an
        # equal peer. UNVERIFIED (QA could not run) sits between the two — never treated as clean.
        _qa_issues = _final_qa.get("issues") or []
        # The EVAL GATE already folds objective + semantic checks into one weighted confidence —
        # prefer it; fall back to the coarse issue-based scale only if the gate could not run.
        _confidence = _final_qa.get("confidence")
        if _confidence is None:
            _confidence = 0.75
            if _qa_issues:
                _confidence = 0.25
            elif _final_qa.get("overall") is None:
                _confidence = 0.55
        # deliver=False → flag the take as "needs review" with the failing reason NAMED (never hard-drop).
        _eval_flag = (" ⚠ EVAL (needs review): " + "; ".join((_final_qa.get("reasons") or [])[:2])
                      if _final_qa.get("deliver") is False else "")
        # MODELS MANIFEST — structured, stable keys, human-readable values (surfaced by the frontend).
        # Populated from what ACTUALLY ran (same signals as whats_changed).
        _video_label = ("veo-3.1" if _prov == "kie-veo"
                        else "seedance-2" if "seedance" in str(_prov) else str(_prov))
        _voice_label = ({"native": "native (model audio)", "tts": "tts (dubbed)", "none": None}
                        .get(_audio_state) if generate_audio else None)
        _models = {"video": _video_label, "voice": _voice_label, "voice_cloned": False,
                   "lipsync": None,
                   "captions": ("whisper+ass" if _caps_burned else None),
                   "recipe": "Generate — Seedance 2.0"}
        _gvar = {"recipe": "Generate — Seedance 2.0", "video_url": url, "confidence": _confidence,
                 "whats_changed": (f"Seedance 2.0 · {len(clip_paths)} clip(s) · ~{_vid_sec}s · {aspect_ratio} · {resolution}"
                    + (" · captions" if _caps_burned else "")
                    + f"{' · refs: ' + ', '.join(refs) if refs else ''}"
                    # HONEST audio label — reflects the ACTUAL output, not the request flag.
                    + ({"native": " · audio",
                        # TTS over a SILENT provider's footage = a voice on a face that isn't moving.
                        # Say so plainly instead of calling it "voiceover" and hiding the defect.
                        "tts": (" · ⚠ voiceover dubbed over non-speaking footage (silent provider — "
                                "lips will NOT match; top up Kie for real speech)" if is_talk
                                else " · voiceover (TTS — narrated the script)"),
                        "none": " · ⚠ no audio (silent fallback — top up Kie for narrated video)"}.get(_audio_state, "")
                       if generate_audio else "")
                    + (" · stitched with frame-continuity" if len(clip_paths) > 1 else "")
                    + _prov_note + "."
                    # HONEST QA label — never ship a known-defective video looking clean.
                    + (" ⚠ QA: " + "; ".join((_final_qa.get("issues") or [])[:2])
                       if (_final_qa.get("issues")) else "")
                    + _eval_flag),
                 "qc_issues": (_final_qa.get("issues") or []),
                 "qc_verified": (_final_qa.get("overall") is not None),
                 "models": _models, "model_calls": _drain_model_calls(req.request_id)}
        return [_gvar]
    finally:
        import shutil; shutil.rmtree(work, ignore_errors=True)


# ── Per-creation cost ledger (which provider cost what for each video/image) ──
# Rough per-variant estimate when a recipe produced media but never itemized its spend — so NO
# generation is invisible in the Team Room. Real per-provider rows (when logged) always win; this
# only fills the gap. Video ~cheapest-lane seconds; ffmpeg-only recipes are near-free.
_EST_COST = {
    "Avatar/UGC": 0.10, "Avatar Lipsync": 0.10, "Create from Assets": 0.12, "Full Ad": 0.20,
    "map + ugc": 0.10, "Broll": 0.06, "Stock Video": 0.02, "Generate Video": 0.10,
    "Special Request": 0.10, "Generate Image": 0.04, "Image": 0.04, "Image + Voiceover": 0.06,
    "Hook Change Only": 0.02, "Caption Change Only": 0.005, "Reclean/Minor Mod": 0.005, "Script": 0.001,
}


def _ensure_cost_logged(request_id, vtype, n_variants):
    """Safety-net: if a completed job wrote NO cost rows, log an estimate so spend is never invisible."""
    if not n_variants:
        return
    try:
        from ..database import SessionLocal
        from ..models.creative_team import CreationCost
        db = SessionLocal()
        try:
            has = db.query(CreationCost.id).filter(CreationCost.request_id == request_id).first()
            if has:
                return
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"cost safety-net check failed: {e}")
        return
    per = _EST_COST.get(vtype, 0.08)
    _track_cost(request_id, "generation", "estimated", model=vtype,
                units=n_variants, unit_type="variant", cost_usd=per * n_variants,
                note="estimated — recipe did not itemize provider spend")


def _track_cost(request_id, step, provider, *, model=None, units=None, unit_type=None, cost_usd=0.0, note=""):
    try:
        from ..database import SessionLocal
        from ..models.creative_team import CreationCost
        db = SessionLocal()
        try:
            db.add(CreationCost(request_id=request_id, step=step, provider=provider, model=model,
                                units=units, unit_type=unit_type, cost_usd=float(cost_usd or 0), note=note))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"track_cost failed ({step}/{provider}): {e}")
    logger.info(f"[cost] {request_id} {step} · {provider} · ${float(cost_usd or 0):.4f}{' · ' + note if note else ''}")
    # FIX C: Finance running-billing feed line — per-provider spend as it lands, so the office shows
    # live cost and the top-right billing pill can total it. Best-effort.
    try:
        from ..services import creative_team_activity as _fin
        _fin.bill(request_id, provider, float(cost_usd or 0), note or (model or step))
    except Exception:
        pass


# ── Per-generation MODEL-CALL LOG (the "Seedance disaster" blind spot) ────────
# The user could not see what each model actually RECEIVED. Every external model call in the
# generation lanes (Seedance/t2v, voice synth, lip-sync, captions) logs its FULL input here, tagged
# with the generation's request_id, AND accumulates a per-generation list that is attached to the
# returned variant as variant["model_calls"] so the frontend can surface it. Best-effort only.
_MODEL_CALLS: dict = {}   # request_id → [{stage, model, input_summary}]


def _log_model_call(request_id, stage: str, model, input_obj) -> None:
    """LOG + PERSIST one external model call's full input. Never raises, never breaks generation."""
    try:
        summary = input_obj if isinstance(input_obj, str) else json.dumps(input_obj, default=str, ensure_ascii=False)
    except Exception:
        summary = str(input_obj)
    summary = (summary or "")[:600]
    try:
        logger.info(f"[model-call] rid={request_id} stage={stage} model={model} input={summary}")
    except Exception:
        pass
    try:
        _MODEL_CALLS.setdefault(request_id, []).append(
            {"stage": stage, "model": str(model), "input_summary": summary})
    except Exception:
        pass


def _drain_model_calls(request_id) -> list:
    """Return + clear the accumulated model-call log for this generation (best-effort)."""
    try:
        return list(_MODEL_CALLS.pop(request_id, []))
    except Exception:
        return []


_NO_FACE_RE = re.compile(r",?\s*no faces?(?:\s+to\s+camera)?", re.I)


def _strip_no_face(text: str) -> str:
    """Remove any 'no faces to camera' style clause from a prompt. Used so a TALKING-HEAD clip never
    inherits a b-roll no-face visual style — that contradiction rendered faceless clips that then
    failed lip-sync QA. Best-effort string scrub; leaves everything else intact."""
    try:
        return _NO_FACE_RE.sub("", text or "")
    except Exception:
        return text or ""


# ── Durable lip-sync resume (long renders survive an AE restart) ──────────────
def _persist_lipsync(request_id, provider, job, audio_url, char_url, callback_url, out_name, script=""):
    try:
        from ..database import SessionLocal
        from ..models.creative_team import LipsyncJob
        db = SessionLocal()
        try:
            row = db.query(LipsyncJob).filter(LipsyncJob.id == request_id).first()
            if row:
                row.provider, row.provider_job, row.status, row.error = provider, job, "polling", None
            else:
                db.add(LipsyncJob(id=request_id, provider=provider, provider_job=job, audio_url=audio_url,
                                  char_url=char_url, callback_url=callback_url, out_name=out_name,
                                  script=script, status="polling"))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"persist lipsync job failed: {e}")


def _set_lipsync_status(request_id, status, error=None):
    try:
        from ..database import SessionLocal
        from ..models.creative_team import LipsyncJob
        db = SessionLocal()
        try:
            row = db.query(LipsyncJob).filter(LipsyncJob.id == request_id).first()
            if row:
                row.status, row.error = status, (error or None)
                db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"update lipsync status failed: {e}")


def _video_dims(path: str) -> tuple:
    """(w, h) of a video — captions must be sized to the REAL frame, not an assumed 1080x1920."""
    try:
        import subprocess
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                           capture_output=True, text=True, timeout=30)
        w, h = (p.stdout or "").strip().split("x")[:2]
        return int(w), int(h)
    except Exception:
        return 1080, 1920


class _Verbatim(Exception):
    """The user supplied the script — skip the writer/critic entirely."""


def _audio_seconds(path: str) -> float:
    import subprocess
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=30)
        return float((p.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def _trim_to_sentence(script: str, target_sec: float, wps: float = 2.6) -> str:
    """Cut a script down to ~target_sec of speech, ALWAYS ending on a complete sentence.
    A clip that stops mid-thought reads as broken; one that lands on a full stop reads as edited."""
    budget = max(6, int(target_sec * wps))
    sentences = re.split(r"(?<=[.!?])\s+", (script or "").strip())
    out, used = [], 0
    for s in sentences:
        n = len(s.split())
        if out and used + n > budget:
            break
        out.append(s); used += n
    return " ".join(out).strip() or script


# Tone words that signal a NON-NEUTRAL emotional delivery → lead with an expressive real voice
# provider (over the clone) for that synthesis. Neutral registers keep the clone for timbre.
_EMOTIONAL_TONES = ("excited", "energetic", "urgent", "passionate", "emotional", "upbeat", "bold",
                    "dramatic", "hopeful", "relief", "frustrat", "angry", "worried", "anxious",
                    "sad", "joyful", "happy", "surprised", "serious", "empath")


def _insert_break_pauses(script: str, older: bool = False) -> str:
    """Insert budgeted SSML <break> pauses BETWEEN sentences so the read breathes — without adding
    a single word. Older characters get a slightly longer beat. ElevenLabs honors these tags
    natively; other providers strip them (the sentence's own period still gives a natural pause).
    The LENGTH GUARDRAIL at the call site re-tightens so the added pauses never lengthen the video."""
    br = 0.3 if older else 0.2
    sents = [s for s in re.split(r"(?<=[.!?])\s+", (script or "").strip()) if s]
    if len(sents) <= 1:
        return script or ""
    return f' <break time="{br}s"/> '.join(sents)


def _avg_rgb(path: str) -> Optional[tuple]:
    """Average (R,G,B) 0-255 of a clip — a few sampled frames each downscaled to 1x1. Used to tone-
    match the lip-synced output back to the original character clip. Returns None on any probe failure."""
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
             "-vf", "fps=2,scale=1:1,format=rgb24", "-frames:v", "6", "-f", "rawvideo", "-"],
            capture_output=True, timeout=60)
        data = p.stdout or b""
        n = len(data) // 3
        if n < 1:
            return None
        rs = sum(data[i * 3] for i in range(n)) / n
        gs = sum(data[i * 3 + 1] for i in range(n)) / n
        bs = sum(data[i * 3 + 2] for i in range(n)) / n
        return (rs, gs, bs)
    except Exception:
        return None


async def _color_match_to_reference(synced_path: str, ref_url: str, request_id: str) -> Optional[str]:
    """POST-SYNC tone match. Lip-sync repaints the mouth region, whose tone can drift from the rest
    of the face/body and leave a visible seam. Pull mean-color stats from the ORIGINAL character clip
    and nudge the synced output's overall tone back toward it with a light per-channel gain + tiny
    brightness correction (colorchannelmixer + eq — NO grain, NO resolution change). Best-effort:
    returns a new path on success, else None so the caller keeps the un-matched clip (never breaks)."""
    try:
        ref_local = ref_url
        if isinstance(ref_url, str) and ref_url.startswith("http"):
            ref_local = await _download_to_temp(ref_url, ".mp4")
        rmean = await asyncio.to_thread(_avg_rgb, ref_local)
        smean = await asyncio.to_thread(_avg_rgb, synced_path)
        if not (rmean and smean):
            return None
        # per-channel gain toward the reference, CLAMPED to ±10% so a seam-fix never grades the clip
        gains = [max(0.9, min(1.1, (r / s) if s > 1 else 1.0)) for r, s in zip(rmean, smean)]
        rl = 0.299 * rmean[0] + 0.587 * rmean[1] + 0.114 * rmean[2]
        sl = 0.299 * smean[0] + 0.587 * smean[1] + 0.114 * smean[2]
        bri = max(-0.06, min(0.06, (rl - sl) / 255.0))     # small, clamped brightness nudge
        # skip when nothing meaningfully differs (avoid a pointless re-encode)
        if all(abs(g - 1.0) < 0.01 for g in gains) and abs(bri) < 0.004:
            return None
        vf = (f"colorchannelmixer=rr={gains[0]:.3f}:gg={gains[1]:.3f}:bb={gains[2]:.3f},"
              f"eq=brightness={bri:.3f}")
        out = synced_path.rsplit(".", 1)[0] + "_cm.mp4"
        await asyncio.to_thread(_ffmpeg, ["-i", synced_path, "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "copy", out], 300)
        return out if os.path.exists(out) else None
    except Exception as e:
        logger.warning(f"[avatar-lipsync] color match failed for {request_id}: {e}")
        return None


async def _mouth_region_composite(synced_path: str, orig_url: str, request_id: str) -> Optional[str]:
    """CONSTRAIN the lip-sync to the mouth. veed/sync re-render a WIDE face region, so the blend
    edge drags the jaw/background/objects around it (the 'wobble'). Video→video lip-sync keeps the
    head in the SAME position, so we can composite ONLY a tight lower-centre mouth box from the
    synced clip back over the ORIGINAL untouched footage — every pixel outside that box stays the
    real, un-wobbled original. The seam runs through cheek/jaw where both sources are the same face
    in the same place, so it is invisible. Best-effort: returns a new path, else None to keep the
    full synced clip. NO resolution change (output keeps the synced clip's dimensions)."""
    try:
        orig_local = orig_url
        if isinstance(orig_url, str) and orig_url.startswith("http"):
            orig_local = await _download_to_temp(orig_url, ".mp4")
        if not (orig_local and os.path.exists(orig_local) and os.path.exists(synced_path)):
            return None
        W, H = await asyncio.to_thread(_video_dims, synced_path)
        if not (W and H):
            return None
        # Tight lower-centre mouth box (fixed fraction — the head is centred in these talking-head
        # clips, so no face detector is needed). Even dims/offsets for yuv420p chroma.
        bw = (int(W * 0.42) // 2) * 2
        bh = (int(H * 0.30) // 2) * 2
        bx = (((W - bw) // 2) // 2) * 2
        by = (int(H * 0.52) // 2) * 2
        if bw < 16 or bh < 16 or by + bh > H:
            return None
        out = synced_path.rsplit(".", 1)[0] + "_mouth.mp4"
        # base = ORIGINAL scaled to the synced geometry + last-frame-held so it never ends before the
        # synced audio; overlay = the mouth box cropped from the synced clip; audio = the synced clip.
        fc = (f"[0:v]scale={W}:{H},tpad=stop_mode=clone:stop_duration=6[bg];"
              f"[1:v]crop={bw}:{bh}:{bx}:{by}[m];"
              f"[bg][m]overlay={bx}:{by}:shortest=1[v]")
        await asyncio.to_thread(_ffmpeg, [
            "-i", orig_local, "-i", synced_path, "-filter_complex", fc,
            "-map", "[v]", "-map", "1:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "copy", out], 400)
        return out if os.path.exists(out) else None
    except Exception as e:
        logger.warning(f"[avatar-lipsync] mouth-region composite skipped for {request_id}: {e}")
        return None


async def _cover_audio_with_footage(char_url: str, need_sec: float, request_id: str) -> str:
    """Guarantee the base clip is at least as long as the voice-over.

    Lip-sync is video→video: if the footage runs out before the audio does, the render simply
    STOPS — which is the abrupt, half-finished ending. We loop the character's own clip (and
    trim to length) so the person is on screen for the whole read. Returns a URL the lip-sync
    provider can fetch; on any failure we fall back to the original clip."""
    from ..services.storage import StorageService
    try:
        src = await _download_to_temp(char_url, ".mp4")
        have = await asyncio.to_thread(_audio_seconds, src)   # container duration
        if have <= 0 or have >= need_sec - 0.2:
            return char_url                                    # already long enough
        loops = int(need_sec // have) + 1
        ext = os.path.join(UPLOAD_DIR, f"base_{request_id[:8]}.mp4")
        # -stream_loop repeats the clip; -t cuts it exactly at the voice's length
        await asyncio.to_thread(_ffmpeg, ["-stream_loop", str(loops), "-i", src, "-t", f"{need_sec:.2f}",
                                          "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                                          "-pix_fmt", "yuv420p", ext], 300)
        up = StorageService.upload_file(ext, f"base/{os.path.basename(ext)}")
        url = StorageService.presign_url(up) or up if up else None
        if url:
            logger.info(f"[avatar-lipsync] footage {have:.1f}s < VO {need_sec:.1f}s → extended to cover the read")
            return url
    except Exception as e:
        logger.warning(f"footage extend failed, using the clip as-is (may truncate): {e}")
    return char_url


def _clean_script(s: str) -> str:
    """Make a script SPEAKABLE. Un-filled placeholders ([Your State], {{city}}) and stage
    directions must never reach the voice — the VO literally read '[Your State]' out loud."""
    if not s:
        return ""
    s = re.sub(r"\[[^\]\n]{0,40}\]", " ", s)        # [Your State], [pause]
    s = re.sub(r"\{\{[^}\n]{0,40}\}\}", " ", s)     # {{city}}
    s = re.sub(r"^\s*(SCENE|SHOT|VO|V\.O\.|CUT TO|B-ROLL)\s*[:.-].*$", " ", s, flags=re.I | re.M)
    s = re.sub(r"\*+", " ", s)                       # markdown emphasis
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\s*\n\s*", " ", s).strip()


async def _produce_lipsync_variant(request_id, out_name, result, script="", cap_words=None, vertical=None, kinetic=False):
    src = result.get("local_path")
    if not src and result.get("video_url"):
        src = await _download_to_temp(result["video_url"], ".mp4")
    out_path = os.path.join(UPLOAD_DIR, out_name)
    out_url = f"{AE_PUBLIC_URL}/api/v1/uploads/{out_name}"
    w, h = await asyncio.to_thread(_video_dims, src)

    # ── SCRUB THE ORIGINAL'S BURNED-IN CAPTIONS ───────────────────────────────────────────────
    # We re-use REAL editor creatives, and editors burn captions in CapCut. Lip-sync only changes
    # the mouth — those old captions survive, and they say the OLD script. Burning ours on top is
    # what produced two sets of captions, the bottom one contradicting the voice. Detect and blur
    # them first, then lay ours over the clean frame.
    delogo = ""
    removal_method = "none"   # which brain 'caption_remove' actually used: vmake | ffmpeg-blur | none
    if cap_words:
        try:
            work = os.path.join(UPLOAD_DIR, f"capscan_{request_id[:8]}")
            os.makedirs(work, exist_ok=True)
            dur = await asyncio.to_thread(_audio_seconds, src)
            frames = await asyncio.to_thread(
                _extract_frames, src, [max(0.3, (dur or 4) * f) for f in (0.15, 0.45, 0.75)], work)
            boxes = await _detect_caption_boxes(frames)
            if boxes:
                logger.info(f"[captions] source has {len(boxes)} burned-in caption region(s) → scrubbing before ours")
                # Editor-grade removal first (what our editors do in vmake.ai); ffmpeg-blur is the
                # fallback. Vmake fetches the URL itself, so only try it when the source is public.
                from ..services import vmake_service as vmake
                src_url = result.get("video_url")
                cleaned = None
                # GATED self-correction (caption_remove brain): an ADMIN-APPROVED rule preferring
                # 'ffmpeg-blur' suppresses vmake; otherwise vmake (editor-grade) stays the default.
                # No active rule → None → exact current behavior. Wrapped so it can never break.
                _rm_pref = None
                try:
                    from ..services import creative_tuner as ctun
                    from ..database import SessionLocal as _SL
                    _rdb = _SL()
                    try:
                        _rm_pref = ctun.governed_preference(_rdb, "caption_remove", vertical or None)
                    finally:
                        _rdb.close()
                except Exception:
                    _rm_pref = None
                if (_rm_pref != "ffmpeg-blur" and settings.vmake_caption_removal and vmake.is_configured()
                        and isinstance(src_url, str) and src_url.startswith("http")):
                    cleaned = await asyncio.to_thread(vmake.remove_captions_video, src_url)
                if cleaned:
                    src = await _download_to_temp(cleaned, ".mp4")
                    w, h = await asyncio.to_thread(_video_dims, src)
                    removal_method = "vmake"
                    logger.info("[captions] Vmake removed burned-in captions (clean master, no blur)")
                else:
                    delogo = _delogo_chain(boxes, w, h)   # ffmpeg-blur fallback
                    removal_method = "ffmpeg-blur"
        except Exception as e:
            logger.warning(f"[captions] burned-in caption scan failed (may double up): {e}")

    # Build the subtitle HERE — only now do we know the lip-synced video's real dimensions, and
    # caption size/margins are derived from them (a 1080x1920 assumption made them look tiny).
    ass_path = None
    if cap_words:
        try:
            from ..services import captions as cap
            # UGC-BROLL uses the reference RED-BOX kinetic captions (1-2 words, numbers/keywords boxed
            # red); everything else keeps the standard TikTok caption style. Same word timings.
            _capf = os.path.join(UPLOAD_DIR, f"cap_{request_id[:8]}.ass")
            ass_path = (cap.build_kinetic_ass(cap_words, _capf, play_w=w, play_h=h) if kinetic
                        else cap.build_ass(cap_words, _capf, play_w=w, play_h=h))
            logger.info(f"[captions] burning {len(cap_words)} words onto {w}x{h}"
                        + (" (kinetic red-box)" if kinetic else ""))
        except Exception as e:
            logger.error(f"[captions] build failed: {e}")

    args = ["-i", src]
    vf = delogo + (f"ass={ass_path}" if (ass_path and os.path.exists(ass_path)) else "")
    if vf:
        args += ["-vf", vf.rstrip(",")]     # scrub the old captions, then burn ours — one pass
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", out_path]
    await asyncio.to_thread(_ffmpeg, args, 300)
    _ae_persist(out_path, out_name)
    return {"recipe": "Avatar Lipsync", "video_url": out_url, "script": script,
            "captions_burned": bool(ass_path), "scrubbed_original_captions": bool(delogo),
            "caption_removal": removal_method,
            # expose the FINAL local file so a caller can run the QA gate on the real bytes it just
            # wrote (unknown keys are ignored by callers that don't need it).
            "_local_path": out_path}


async def _resume_one_lipsync(row):
    from ..services import lip_sync
    from ..services import creative_team_activity as act
    rid = row["id"]
    _CURRENT_RID.set(rid)   # fresh task after a restart — set the contextvar so any cost logged here bills to this job
    try:
        result = None
        for _ in range(150):   # ~10 min
            await asyncio.sleep(4)
            stt, res = await asyncio.to_thread(lambda: lip_sync.poll_relipsync(row["provider"], row["provider_job"]))
            if stt == "done":
                result = res; break
        if not result:
            logger.warning(f"[resume] lipsync {rid} still processing; will retry on next restart")
            return
        variant = await _produce_lipsync_variant(rid, row["out_name"] or f"regen_avatar_lipsync_{rid[:8]}.mp4", result, row.get("script") or "")
        await _callback(row["callback_url"], {"request_id": rid, "status": "ready", "variants": [variant]})
        act.end_job(rid, ok=True)
        _set_lipsync_status(rid, "done")
        logger.info(f"[resume] lipsync {rid} RECOVERED + delivered")
    except Exception as e:
        logger.error(f"[resume] lipsync {rid} failed: {e}")
        try:
            await _callback(row["callback_url"], {"request_id": rid, "status": "failed", "error": str(e)[:300]})
            act.end_job(rid, ok=False, error=str(e)[:300])
        except Exception:
            pass
        _set_lipsync_status(rid, "failed", str(e)[:300])


async def resume_pending_lipsync():
    """Startup hook: re-poll any lip-sync mid-flight when AE last restarted, and deliver it."""
    try:
        from ..database import SessionLocal
        from ..models.creative_team import LipsyncJob
        db = SessionLocal()
        try:
            rows = db.query(LipsyncJob).filter(LipsyncJob.status == "polling").all()
            pending = [{"id": r.id, "provider": r.provider, "provider_job": r.provider_job,
                        "callback_url": r.callback_url, "out_name": r.out_name, "script": r.script} for r in rows]
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"resume_pending_lipsync load failed: {e}")
        return
    if pending:
        logger.info(f"[resume] recovering {len(pending)} in-flight lip-sync job(s)")
    for row in pending:
        asyncio.create_task(_resume_one_lipsync(row))


def _script_axis_directive(index: int, total: int) -> str:
    """The instruction that makes the writer produce the index-th DISTINCT script — a different hook
    AND angle per index — for the SAME offer/vertical/character."""
    return (f"IMPORTANT — DIVERSIFICATION: this is script variation {index} of {total} in a set "
            f"generated for the SAME offer, vertical, and character. Make it MEANINGFULLY DIFFERENT "
            f"from the other variations: a DISTINCT opening hook AND a DISTINCT angle — not a reworded "
            f"version of the same script. Do not reuse the framing another variation would pick.")


async def _diversify_hook(script: str, index: int, total: int, offer_value: str, seconds: int) -> str:
    """HOOK axis: rewrite ONLY the opening 1-2 sentences so this variation opens differently, keeping
    every following sentence identical. Defensive — returns the ORIGINAL script on any failure so a
    diversification miss never crashes (or even alters) the render."""
    try:
        d = await _gemini_json(
            "Here is a first-person UGC ad voiceover script. Rewrite ONLY the opening hook (its first "
            "1-2 sentences) so it opens with a DIFFERENT angle. Keep EVERY following sentence EXACTLY "
            "as given — do not touch the body or the CTA. "
            f"This is hook variation {index} of {total}; make this opening meaningfully distinct from "
            f"the other variations (a different first line, not a reword)."
            + (f" Keep the offer {offer_value} intact." if offer_value else "")
            + f" Keep it spoken, ~{seconds}s, no stage directions. "
            f'Script: "{script[:1500]}". Return JSON {{"script":"..."}}.')
        new = _clean_script((d.get("script") or "").strip())
        return new or script
    except Exception as e:
        logger.warning(f"[avatar-lipsync] hook diversification skipped: {e}")
        return script


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# UGC-BROLL ASSEMBLER
# The real library UGC-BROLL format (S2-TX-UGC-BROLL-HAM / -RIT): ONE continuous first-person voice,
# kinetic red-box captions running from frame 1, and the picture alternating between a real filmed
# talking-head (lip-synced) and oddly-satisfying / transformation b-roll (leaf-blowing a drive clean,
# laying garage-floor tiles, an interior "same house" walk). Two proven layouts:
#   ham  → open COLD on satisfaction b-roll (VO+captions already going), then the character cuts in
#          and CONTINUES the same sentence in lip-sync, then a mid-roll interior insert.
#   rit  → open on the talking-head (~4s), then cut to the satisfaction/transformation b-roll that
#          carries the middle, then back to the face for the CTA.
# Built entirely by ASSEMBLY: the lip-sync step (recipe_avatar_lipsync) already gives us the face
# video AND the continuous VO; we just swap the PICTURE on the b-roll windows (audio plays straight
# through) and let the existing kinetic-caption burn run over the whole composite. Best-effort:
# any shortfall (no footage, ffmpeg error) returns None and the caller ships the plain talking-head.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def _clean_windows(windows: list, T: float, min_len: float = 1.5) -> list:
    """Clamp (start,end) b-roll windows to [0,T], drop any shorter than min_len, sort, and drop
    overlaps (keep the earlier). Pure math, no I/O."""
    out = []
    for s, e in windows:
        s = max(0.0, min(float(s), T))
        e = max(0.0, min(float(e), T))
        if e - s >= min_len:
            out.append((round(s, 2), round(e, 2)))
    out.sort()
    merged = []
    for s, e in out:
        if merged and s < merged[-1][1]:
            continue                                  # overlaps the previous window → skip
        merged.append((s, e))
    return merged


def _partition_timeline(b_windows: list, T: float) -> list:
    """Turn b-roll windows into an ordered, gap-free segment list covering [0,T]. Each item is
    (start, end, kind, pool) where kind is 'face' or 'broll'. The FIRST b-roll window uses the
    'hook' (satisfaction) pool — it is the scroll-stopper in both layouts — and later windows use
    'interior'. Always ends on a face segment (the CTA lands on the real person)."""
    segs, cur, bi = [], 0.0, 0
    for s, e in b_windows:
        if s - cur >= 0.5:
            segs.append((cur, s, "face", None))
        segs.append((s, e, "broll", "hook" if bi == 0 else "interior"))
        cur = e
        bi += 1
    if T - cur >= 0.5:
        segs.append((cur, T, "face", None))
    return segs


async def _broll_track(clip_urls: list, length: float, W: int, H: int, work: str, tag: str = "b") -> str:
    """Build ONE silent WxH/30fps b-roll track of exactly `length` seconds from a pool of clip URLs
    (mirrors recipe_broll's montage loop: download → ~4s cuts, re-window on re-use, scale/crop to
    fill, concat, hard-trim). Returns the track path, or None if no usable footage."""
    SEG = 4.0
    srcs = []
    for u in clip_urls:
        try:
            srcs.append(await _download_to_temp(u, ".mp4"))
        except Exception as de:
            logger.warning(f"[ugc-broll] {tag} clip download failed: {de}")
    if not srcs:
        return None
    seg_paths, total, idx, guard = [], 0.0, 0, 0
    while total < length and srcs and guard < 200:
        src = srcs[idx % len(srcs)]
        pass_no = idx // len(srcs); idx += 1; guard += 1
        sd = await asyncio.to_thread(_ffprobe_duration, src)
        if sd <= 0.4:
            continue
        off = min(pass_no * SEG, max(0.0, sd - 1.0))          # a different window each re-use
        take = min(SEG, sd - off, length - total)
        if take < 0.8:
            off, take = 0.0, min(SEG, sd, length - total)
        if take < 0.4:
            break
        seg = os.path.join(work, f"{tag}_{len(seg_paths):03d}.mp4")
        try:
            await asyncio.to_thread(_ffmpeg,
                ["-ss", f"{off:.2f}", "-i", src, "-t", f"{take:.2f}", "-an",
                 "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                        f"crop={W}:{H},fps=30,setpts=PTS-STARTPTS",
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                 "-pix_fmt", "yuv420p", "-threads", "2", seg], 300)
        except Exception as se:
            logger.warning(f"[ugc-broll] {tag} segment build failed: {se}"); continue
        seg_paths.append(seg); total += take
    if not seg_paths:
        return None
    listf = os.path.join(work, f"{tag}_list.txt")
    with open(listf, "w") as f:
        for s in seg_paths:
            f.write("file '%s'\n" % s.replace("'", "'\\''"))
    out = os.path.join(work, f"{tag}_track.mp4")
    try:
        await asyncio.to_thread(_ffmpeg,
            ["-f", "concat", "-safe", "0", "-i", listf, "-t", f"{length:.2f}", "-an",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-threads", "2", out], 400)
    except Exception as ce:
        logger.warning(f"[ugc-broll] {tag} track concat failed: {ce}"); return None
    return out if os.path.exists(out) else None


async def _compose_ugc_broll(face_path: str, vo_audio: str, T: float, intent: dict,
                             layout: str, work: str, req: "RunRequest",
                             hook_urls: list = None, interior_urls: list = None) -> tuple:
    """Intercut satisfaction/interior b-roll over the lip-synced talking-head, keeping ONE continuous
    VO. Returns (composited_path | None, status) — status is surfaced in the variant feedback so a live
    run REVEALS exactly what happened (cast counts / bail reason) without needing server logs. The
    caller's existing kinetic-caption burn runs over the composite, so captions play from frame 1 incl.
    the b-roll opener. LIBRARY b-roll ONLY (our own assets — never stock). `layout` ∈ {'ham','rit'}."""
    if not (face_path and os.path.exists(face_path) and vo_audio and os.path.exists(vo_audio) and T > 3):
        return None, "skipped: missing face/vo or T<=3"
    W, H = await asyncio.to_thread(_ffprobe_dims, face_path)
    if not (W and H):
        return None, "skipped: no face dims"

    # 1) b-roll windows (seconds). Opener capped so a short ad never spends half its length off-face.
    if layout == "ham":                                       # satisfaction cold-open → face → insert
        b_windows = [(0.0, min(6.0, 0.32 * T)), (0.55 * T, 0.72 * T)]
    else:                                                      # rit: face cold-open → satisfaction mid
        b_windows = [(min(4.0, 0.22 * T), 0.62 * T)]
    b_windows = _clean_windows(b_windows, T)
    if not b_windows:
        return None, "skipped: no windows"
    segs = _partition_timeline(b_windows, T)
    if not any(k == "broll" for _, _, k, _ in segs):
        return None, "skipped: no broll segment"

    # 2) footage pools — satisfaction 'hook' openers (cross-vertical) + same-vertical interiors.
    #    PREFER URLs the CL caller cast from asset_library (AE's own asset_tags store doesn't hold these
    #    clips); fall back to the AE-side cast only when none were passed. LIBRARY ONLY — never stock.
    hooks = list(hook_urls or []) or await _cast_library_broll(intent, limit=5, prefer_kind="hook")
    interiors = list(interior_urls or []) or await _cast_library_broll(intent, limit=6)
    # SHUFFLE both pools so every gen gets a DIFFERENT opener (hooks[0]) + different interior inserts —
    # the opener is always hooks[0], so without this the same first clip repeats even when CL rotated
    # the set. AE-side shuffle guarantees rotation independent of the caller's order.
    random.shuffle(hooks)
    random.shuffle(interiors)
    nh, ni = len(hooks), len(interiors)
    _src = "cl" if (hook_urls or interior_urls) else "ae"
    if not hooks:                                             # no satisfaction clips → reuse interiors
        hooks = interiors
    if not interiors:
        interiors = hooks
    if not hooks and not interiors:
        logger.info("[ugc-broll] library has no b-roll to cast — plain talking-head")
        return None, f"no b-roll cast (src={_src} hooks={nh} interiors={ni})"

    # 3) render each timeline segment at WxH/30fps, silent (face cut from the lip-sync master; b-roll
    #    montage from the right pool). Keeping each face segment at its ORIGINAL time preserves the
    #    lip-sync against the continuous VO we mux back at the end.
    seg_files = []
    nbroll = 0
    for si, (s, e, kind, pool) in enumerate(segs):
        L = e - s
        if L < 0.4:
            continue
        if kind == "face":
            fp = os.path.join(work, f"face_{si:02d}.mp4")
            try:
                await asyncio.to_thread(_ffmpeg,
                    ["-ss", f"{s:.2f}", "-i", face_path, "-t", f"{L:.2f}", "-an",
                     "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                            f"crop={W}:{H},fps=30,setpts=PTS-STARTPTS",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                     "-pix_fmt", "yuv420p", "-threads", "2", fp], 300)
            except Exception as fe:
                logger.warning(f"[ugc-broll] face segment {si} failed: {fe}")
                return None, f"face segment {si} failed"
            seg_files.append(fp)
        else:
            pool_urls = hooks if pool == "hook" else interiors
            track = await _broll_track(pool_urls, L, W, H, work, tag=f"br{si:02d}")
            if not track:                                    # a required b-roll window failed → bail
                logger.info(f"[ugc-broll] b-roll window {si} produced no footage — plain talking-head")
                return None, f"b-roll window {si} no footage (cast hooks={nh} interiors={ni}; fetch failed?)"
            nbroll += 1
            seg_files.append(track)
    if len(seg_files) < 2:                                    # need at least one face + one b-roll
        return None, "too few segments"

    # 4) concat all segments (re-encode → identical params) then mux the CONTINUOUS VO as the audio.
    listf = os.path.join(work, "compose_list.txt")
    with open(listf, "w") as f:
        for s in seg_files:
            f.write("file '%s'\n" % s.replace("'", "'\\''"))
    silent = os.path.join(work, "compose_silent.mp4")
    try:
        await asyncio.to_thread(_ffmpeg,
            ["-f", "concat", "-safe", "0", "-i", listf, "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-threads", "2", silent], 600)
    except Exception as ce:
        logger.warning(f"[ugc-broll] compose concat failed: {ce}")
        return None, "concat failed"
    out = os.path.join(work, "ugc_broll.mp4")
    try:
        await asyncio.to_thread(_ffmpeg,
            ["-i", silent, "-i", vo_audio, "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out], 300)
    except Exception as me:
        logger.warning(f"[ugc-broll] compose mux failed: {me}")
        return None, "mux failed"
    if os.path.exists(out):
        return out, f"composited {layout} · {nbroll} b-roll window(s) · src={_src} hooks={nh} interiors={ni}"
    return None, "no output file"


async def recipe_avatar_lipsync(req: RunRequest, ugc_broll: bool = False) -> list:
    """The team's real CapCut flow, automated end-to-end: take a REAL character clip from
    our own asset library, write/adapt a natural spoken script (inserting the offer value),
    generate a matching voice (optionally CLONED from the character's own footage for max
    naturalness), then re-lipsync the footage to that voice with LatentSync. No synthetic
    avatar — it's our own person, so it never looks 'AIfied'."""
    _CURRENT_RID.set(req.request_id)   # so Gemini reasoning/vision tokens bill to this job
    from ..services import voice_studio as vs
    from ..services.lip_sync import LipSyncService
    from ..services import creative_team_activity as act
    from ..services.storage import StorageService

    a = req.assets or {}
    char_url = a.get("character_video_url") or req.active_url
    if not char_url:
        raise RuntimeError("avatar-lipsync: no character video provided")
    seconds = int(a.get("seconds") or 20)
    offer_value = (a.get("offer_value") or "").strip()
    vertical = a.get("vertical") or req.context.get("vertical") or ""
    base = (a.get("script") or "").strip()
    try:   # a SPOKEN script must never contain "[Website/App Name]" — scrub before TTS/lip-sync
        from ..services.creative_team import scrub_placeholders as _scrub
        base = _scrub(base)
    except Exception:
        pass
    brief = (a.get("brief") or req.expectation or "").strip()

    # ── REUSE ALREADY-PAID WORK ON RETRY ───────────────────────────────────────────────────────
    # A retry/redispatch of THIS request must not re-burn the expensive lip-sync ($0.33 veed) a prior
    # attempt already paid for. If a checkpoint exists (LipsyncJob persisted at submit) and its provider
    # job still resolves, produce the variant straight from it — skipping script, TTS AND the paid veed
    # submit. Fail-open: a missing / expired / errored checkpoint just falls through to a full fresh run,
    # so first-time generations are completely unaffected. Opt out with assets.force_fresh=true.
    #
    # SAFETY: this shortcut only produces the RAW lip-synced talking head — it does NOT re-run the b-roll
    # composite or the caption burn, and it BYPASSES the final QA gate. So it is only safe for a plain,
    # caption-less Avatar Lipsync. For a UGC+B-Roll or captioned ask it would ship a degraded video (plain
    # talking-head / no captions) with nothing to catch it — so DON'T shortcut those; fall through to a
    # full run so the composite, captions and the QA gate all apply. (Proper step-ledger resume that
    # reuses veed AND re-applies b-roll/captions is the follow-up; until then, correctness wins.)
    # Skip-triggers = every stage that runs AFTER the veed checkpoint and would be lost by the raw-render
    # shortcut: captions (burn), b-roll (composite), AND lipsync_ab (produces a SECOND variant — the
    # shortcut returns one, so an A/B retry would silently drop an arm). The always-on tone-seam color
    # match is best-effort (keeps the un-matched video on failure), so skipping it is a minor quality
    # delta, not a broken deliverable — not worth forcing a full re-spend over.
    _reuse_ok = (not a.get("force_fresh")
                 and not a.get("captions")
                 and not a.get("lipsync_ab")
                 and not (ugc_broll or a.get("ugc_broll")))
    if _reuse_ok:
        try:
            from ..models.creative_team import LipsyncJob as _LJ
            from ..database import SessionLocal as _SL
            _cdb = _SL()
            try:
                _ck = _cdb.query(_LJ).filter(_LJ.id == req.request_id).first()
                _ckd = ({"provider": _ck.provider, "provider_job": _ck.provider_job,
                         "out_name": _ck.out_name, "script": _ck.script} if _ck else None)
            finally:
                _cdb.close()
            if _ckd and _ckd.get("provider") and _ckd.get("provider_job"):
                from ..services import lip_sync as _ls
                _st, _res = await asyncio.to_thread(lambda: _ls.poll_relipsync(_ckd["provider"], _ckd["provider_job"]))
                if _st == "done" and _res:
                    logger.info(f"[avatar-lipsync] REUSE checkpoint {req.request_id}: prior "
                                f"{_ckd['provider']} lip-sync still resolves — skipping script/TTS/veed re-spend")
                    _rn = _ckd.get("out_name") or _out_url(req, "avatar_lipsync")[0]
                    _rv = await _produce_lipsync_variant(req.request_id, _rn, _res, _ckd.get("script") or base or "")
                    _rv.setdefault("whats_changed", "Recovered from the paid lip-sync checkpoint (no re-spend)")
                    return [_rv]
        except Exception as _rue:
            logger.warning(f"[avatar-lipsync] checkpoint reuse skipped ({req.request_id}): {_rue}")

    # ── DIVERSIFICATION AXIS (shared contract with the creative-library caller) ────────────────
    # CL may ask for N GENUINELY-different variations of ONE request along one axis. Absent / total<=1
    # → exactly today's single-variation behavior, unchanged. Parsed defensively; a bad value → no-op.
    _axis = (a.get("variation_axis") or "").strip().lower()
    try:
        _vidx = int(a.get("variation_index") or 1)
    except (TypeError, ValueError):
        _vidx = 1
    try:
        _vtot = int(a.get("variation_total") or 1)
    except (TypeError, ValueError):
        _vtot = 1
    _diversify = _axis in ("script", "hook", "character", "format") and _vtot > 1 and _vidx >= 1
    # This recipe produces ONE footage FORMAT only (talking-head lip-sync on the supplied real clip),
    # so a 'format' ask has no alternate format to pick HERE → fall back to 'character' behavior (face
    # variety is delivered upstream by CL passing a distinct character_video_url per index).
    _axis_eff = "character" if (_diversify and _axis == "format") else _axis
    _axis_note = (f"format axis: only talking-head available in this recipe → treated like character"
                  if (_diversify and _axis == "format") else "")

    # 1) SCRIPT.
    # If the user HANDED US a script, that IS the script — speak it. The writer silently replacing
    # a supplied script is not a feature, it's a bug.
    t0 = act.start("scriptwriter", req.request_id, "strategizing + writing the script")
    # GATED self-correction (script_write brain): when a base script exists but the user did NOT
    # pin a script_mode, an ADMIN-APPROVED rule preferring 'verbatim' respects the supplied words
    # instead of rewriting. No active rule → unchanged (mode stays as the user/default set it).
    _script_mode_pin = (a.get("script_mode") or "").lower()
    _interpreted_mode = _script_mode_pin           # remembered for the learning loop (before we normalize)
    _modify_instruction = (a.get("modify_instruction") or "").strip()
    _clip_transcript = (a.get("character_transcript") or "").strip()
    # ATTACHMENT-SOURCED interpretation modes (from the ORBIT file-request parser). Honor them, then
    # normalize to the existing verbatim path so everything downstream is unchanged:
    #   reuse  → speak the clip's own transcript as-is.
    #   modify → a concrete corrected line (base) speaks verbatim; else apply the small edit to the
    #            transcript (a SURGICAL price/number/state swap, not a rewrite).
    # Anything missing falls back to today's behavior, so live generation is never broken.
    if _script_mode_pin == "reuse" and not base and _clip_transcript:
        base = _clip_transcript
        _script_mode_pin = "verbatim"
    elif _script_mode_pin == "modify":
        if base:
            _script_mode_pin = "verbatim"          # the parser already extracted the corrected line
        elif _modify_instruction and _clip_transcript:
            try:
                _d = await _gemini_json(
                    "Apply this SMALL edit to the ad voiceover transcript. Make ONLY the change "
                    "described (e.g. a price/number/state swap, or removing one mention). Keep every "
                    "other word identical — do NOT rewrite or restyle. "
                    f'Return JSON {{"script":"..."}}.\nEdit: "{_modify_instruction[:300]}".\n'
                    f'Transcript: "{_clip_transcript[:1500]}".')
                _edited = (_d.get("script") or "").strip()
                base = _edited or _clip_transcript
                _script_mode_pin = "verbatim"
            except Exception as e:
                logger.warning(f"[avatar-lipsync] modify edit failed, speaking transcript: {e}")
                base = _clip_transcript
                _script_mode_pin = "verbatim"
        elif _clip_transcript:
            base = _clip_transcript
            _script_mode_pin = "verbatim"
    if bool(base) and not _script_mode_pin:
        try:
            from ..services import creative_tuner as ctun
            from ..database import SessionLocal as _SL
            _sdb = _SL()
            try:
                if ctun.governed_preference(_sdb, "script_write", vertical or None) == "verbatim":
                    _script_mode_pin = "verbatim"
            finally:
                _sdb.close()
        except Exception:
            pass
    # HONOR THE REWRITE TOGGLE (not just script_mode). This lane runs its OWN writer (strategize_
    # and_write + critic) and does NOT go through run_creative_team, so the office short-circuit
    # never protects it. A job carrying allow_rewrite:false must be verbatim even if the caller
    # didn't ALSO set script_mode="verbatim" — otherwise the avatar rewrites the user's script.
    verbatim = bool(base) and (_script_mode_pin == "verbatim" or not _rewrite_allowed(a))
    # SCRIPT axis: ask the writer for the index-th DISTINCT script (a different hook AND angle). Only
    # applies when we're actually writing — a verbatim user script can't be rewritten, so the script
    # axis degrades to varying the HOOK only (handled after the script is finalized, below).
    _script_directive = (_script_axis_directive(_vidx, _vtot)
                         if (_diversify and _axis_eff == "script" and not verbatim) else "")
    script = base or brief
    offer_desc = " ".join(x for x in [
        brief,
        (f"Adapt this base script, keep its message and offer: {base[:1000]}" if base else ""),
        (f"You MUST naturally state the offer/value {offer_value}." if offer_value else ""),
        f"Spoken UGC voiceover, first person. Keep it SHORT — at most {int(seconds * 2.5)} words so it "
        f"speaks in about {seconds}s (hard ceiling {seconds}s).",
    ] if x).strip()
    try:
        if verbatim:
            raise _Verbatim()          # the user's words win — skip the writer AND the critic
        from ..services import creative_team as team
        _strategy, script = await team.strategize_and_write(
            offer_desc=offer_desc, vertical=(vertical or "home_insurance"), request_type="ugc",
            variation_directive=_script_directive)
        script = (script or base or brief).strip()
        # Critic pass — score the opening hook; rewrite only if weak (guards against slop)
        try:
            cr = await _gemini_json(
                "You are the Critic guarding against weak hooks and AI-slop. Score this UGC ad "
                "script's FIRST line 0-10 for scroll-stopping power. If under 8, rewrite ONLY to hook "
                f"harder in the first sentence while keeping the offer{(' ' + offer_value) if offer_value else ''}, "
                f"~{seconds}s, first-person, no stage directions. "
                f'Script: "{script[:1500]}". Return JSON {{"score": n, "script": "..."}}')
            if cr and cr.get("script") and int(cr.get("score", 10)) < 8:
                script = str(cr["script"]).strip()
                act.tick(req.request_id, "critic hardened the hook")
        except Exception as e:
            logger.warning(f"script critic pass skipped: {e}")
    except _Verbatim:
        script = base
        logger.info(f"[avatar-lipsync] speaking the SUPPLIED script verbatim ({len(base.split())} words)")
    except Exception as e:
        logger.warning(f"team script failed, falling back to direct generation: {e}")
        try:
            d = await _gemini_json(
                "Write a natural, first-person spoken UGC voiceover. "
                f"Vertical: {vertical or 'direct-response'}. ~{seconds}s (~{int(seconds * 2.6)} words). "
                + (f'Base: "{base[:1000]}". ' if base else "") + (f'Brief: "{brief[:500]}". ' if brief else "")
                + (f'Must say {offer_value}. ' if offer_value else "")
                + (_script_directive + " " if _script_directive else "")
                + 'Hook hard in the first line, no stage directions. Return JSON {"script":"..."}.')
            script = (d.get("script") or script).strip()
        except Exception:
            pass
    script = _clean_script(script)
    if not script:
        raise RuntimeError("avatar-lipsync: no script and could not generate one")
    # HOOK axis — keep the body, vary only the opening per index. Also the graceful degrade for a
    # SCRIPT axis on a verbatim user script (we can't rewrite their words, so we vary the hook only).
    if _diversify and (_axis_eff == "hook" or (_axis_eff == "script" and verbatim)):
        script = await _diversify_hook(script, _vidx, _vtot, offer_value, seconds)
        if _axis_eff == "script" and verbatim:
            _axis_note = "script axis on a verbatim user script → varied the opening HOOK only"
    # Surface the copywriting FORMULA the office actually used (AIDA/PAS/BAB/PPPP/AICPBSAWN), and pass
    # the FULL script — the office clips the row visually but shows all of it when you click the
    # Copywriter. Proves the framework is applied (strategize_and_write rotates COPY_FORMULAS).
    try:
        _formula = (_strategy.get("formula") if isinstance(_strategy, dict)
                    else getattr(_strategy, "formula", "")) or ""
    except Exception:
        _formula = ""
    _lead = ("used YOUR script verbatim · " if verbatim
             else (f"Copywriter · {_formula} formula · " if _formula else "Copywriter · "))
    act.finish("scriptwriter", req.request_id, t0, detail=_lead + (script or ""))
    _track_cost(req.request_id, "script", ("none" if verbatim else "gemini"),
                model=("user-supplied" if verbatim else "gemini-2.5-flash"),
                cost_usd=(0.0 if verbatim else 0.001),
                note=("user supplied the script — not rewritten" if verbatim else "strategist+critic"))

    await _abort_if_cancelled(req, "avatar-lipsync voice")

    # 2) VOICE — clone the character's own voice (most natural) else cast a catalog voice
    t1 = act.start("character", req.request_id, "casting the voice")
    sample_url = None
    _clone_wav = None            # LOCAL wav path — ElevenLabs clone needs a file, not a presigned URL
    _ref_text = None             # transcript of the reference clip → F5-TTS ref_text (kills boundary hallucination)
    # CLONE BY DEFAULT on reused real footage: a real face lip-synced to a stock TTS voice is an
    # eyes/ears mismatch. Clone the character's own voice unless the caller EXPLICITLY opts out.
    _do_clone = a.get("clone_voice") is not False and bool(char_url)
    _clone_engine = str(a.get("clone_engine") or "f5").lower()   # f5 | elevenlabs | auto
    # STABLE per-character key → SAVE the clone once and REUSE it across generations (consistent voice,
    # and skip re-extract/transcribe). Empty key (no asset id) → per-request behavior, uncached.
    _vc_key = str(a.get("character_asset_id") or a.get("source_filename") or "").strip()
    if _do_clone:
        # 2a) REUSE a saved clone for this character if one exists (re-presign the stored sample key).
        _vc_cached = _voice_clone_get(_vc_key) if _vc_key else None
        if _vc_cached and _vc_cached.get("sample_key"):
            _psu = StorageService.presign_url(_vc_cached["sample_key"])
            if _psu:
                sample_url = _psu
                _ref_text = _vc_cached.get("ref_text") or None
                logger.info(f"[avatar-lipsync] REUSING saved voice clone for {_vc_key}")
        # 2b) else extract a fresh ~15s sample, SAVE it to a stable key, and record it for next time.
        if not sample_url:
            try:
                raw = await _download_to_temp(char_url, ".mp4")
                wav = raw.rsplit(".", 1)[0] + ".wav"
                # ROOT FIX for the repeated-word echo: a CLEAN, phrase-bounded ~6-11s reference (starts
                # on the first word, ends on a natural silence) instead of a hard mid-word 15s cut. A
                # mid-word/over-long ref is what made f5 re-prime and inject a reference word at each
                # sentence boundary ("Satisfied"/"US"). ref_text below transcribes THIS exact segment.
                await asyncio.to_thread(_clean_ref_wav, raw, wav)
                _clone_wav = wav
                # REF TEXT: tell F5-TTS exactly what the reference clip SAYS (without it fal auto-ASRs
                # the ref and its errors bleed in as a spurious token at every sentence start). Best-effort.
                try:
                    _rt = await _transcribe_file(wav)
                    if _rt and len(_rt.split()) >= 3:
                        _ref_text = _rt.strip()
                except Exception as _rte:
                    logger.warning(f"ref-text transcribe failed (f5 will ASR): {_rte}")
                # SAVE to a STABLE per-character key so it can be re-presigned + REUSED; record it.
                if _vc_key:
                    # 'v2' = the clean-reference era. Bumping the prefix invalidates any clone saved
                    # with the old mid-word 15s ref (see _voice_clone_get), so it re-extracts cleanly.
                    _stable_key = "voice/clonev2_" + re.sub(r"[^A-Za-z0-9]", "", _vc_key)[:60] + ".wav"
                    if StorageService.upload_file(wav, _stable_key):
                        _voice_clone_put(_vc_key, _stable_key, _ref_text, provider="f5")
                        sample_url = StorageService.presign_url(_stable_key)
                # no stable key (or upload failed) → per-request sample, uncached (unchanged old path)
                if not sample_url:
                    _pr = StorageService.upload_file(wav, f"voice/sample_{req.request_id[:8]}.wav")
                    sample_url = StorageService.presign_url(_pr) or _pr
            except Exception as e:
                logger.warning(f"voice-clone sample extract failed, using preset: {e}")
    # ALWAYS cast a gender/age/tone-correct preset. It's the voice we speak with directly, AND the
    # fallback if the clone can't run — so a female character can never land on a male/androgynous
    # voice just because Chatterbox/Replicate was unavailable.
    # LEARNING: bias the pick toward voices that have actually earned ROI in this vertical. Empty
    # until data exists (cold start = today's behavior unchanged).
    _vscores = {}
    try:
        from ..services import learning_loop as learn
        from ..database import SessionLocal
        _ldb = SessionLocal()
        try:
            _vscores = learn.voice_scores(_ldb, vertical or None)
            # GATED self-correction: only a voice_cast brain that cleared the promotion bar may
            # ASSERT its governed picks. Below the bar / cold start this is {} → behavior unchanged.
            from ..services import creative_tuner as ctun
            _gov = ctun.governed_scores(_ldb, "voice_cast", vertical or None)
            if _gov:
                _vscores = {**_vscores, **_gov}
        finally:
            _ldb.close()
    except Exception:
        _vscores = {}
    voice_id = a.get("voice_id")
    if not voice_id:
        try:
            voice_id = vs.pick_voice(
                gender=a.get("gender"), age_band=a.get("age_band"), tone=a.get("tone"),
                roi_scores=_vscores).get("id")
        except ValueError as _ve:
            # No known character gender (or no eligible voice for it) — NEVER guess, or a man
            # ships with a woman's voice. Fail the voice cast CLOSED with a clear reason.
            _set_lipsync_status(req.request_id, "failed", str(_ve)[:250])
            raise RuntimeError(str(_ve))
    out_audio = os.path.join(UPLOAD_DIR, f"vo_{req.request_id[:8]}.mp3")
    # TELL the model who is speaking AND how. Casting a "55plus" voice is not enough on its own — the
    # delivery has to be directed too, or a 70-year-old woman on screen is read by a bright
    # 30-something. Gemini/OpenAI/ElevenLabs all steer delivery from plain English, so we add an
    # expressive per-line pacing note (never flat/monotone).
    _style = ", ".join(x for x in [
        vs.age_style(a.get("age_band"), a.get("gender")),
        (a.get("tone") or "warm"),
        "conversational, talking to camera, expressive with natural pauses between sentences, never flat or monotone",
    ] if x)
    # THE SCRIPT GIVEN IS THE SCRIPT SPOKEN — verbatim, no injected markup. SSML <break> tags were
    # being READ ALOUD by f5-tts ("break time zero point three seconds") and corrupted the delivery.
    # f5/OpenAI/Gemini do NOT parse SSML, so the text handed to them must be the plain words only.
    # Natural pauses come from the punctuation + the model's own prosody. Only the ElevenLabs branch
    # (which genuinely honors SSML) may add breaths, applied inline there — never to the f5 path.
    _older = (a.get("age_band") in ("55plus", "45-55"))
    # ALL-CAPS emphasis words ("jumped AGAIN", "save HUNDREDS") make TTS SPELL them letter-by-letter
    # ("A-G-A-I-N"). Lower-case caps runs of >=4 letters for the SPOKEN text only (keep short all-caps
    # like IRS/USA as acronyms). Captions still use `script`, so the on-screen emphasis is preserved.
    _tts_text = re.sub(r"\b[A-Z][A-Z']{3,}\b", lambda m: m.group(0).lower(), script)
    # When the register is non-neutral, lead with an expressive real voice over the clone (clone stays
    # as fallback for timbre). Neutral tone → unchanged (clone/cast voice leads).
    _emotional_delivery = any(w in (a.get("tone") or "").lower() for w in _EMOTIONAL_TONES)
    # CLONE ENGINE SELECT. Default f5 (fal F5-TTS via voice_studio). "elevenlabs"/"auto" render the
    # spoken audio with an ElevenLabs INSTANT CLONE of the character's own voice — A/B against f5. EL
    # clone needs the LOCAL wav (not the presigned sample_url); /voices/add makes a persistent voice,
    # so we DELETE it in a finally (quota + clutter). Any failure → fall through to the f5 path → preset.
    voice_res = None
    if _do_clone and _clone_wav and _clone_engine in ("elevenlabs", "auto"):
        try:
            from ..services import elevenlabs_service as el
            if el.ElevenLabsService.is_configured():
                _elvid = None
                try:
                    _elvid = await asyncio.to_thread(
                        el.ElevenLabsService.clone_voice, _clone_wav, f"char_{req.request_id[:8]}")
                    # ElevenLabs genuinely honors SSML <break>, so it MAY breathe between sentences.
                    _el_text = _insert_break_pauses(script, older=_older)
                    await asyncio.to_thread(el.ElevenLabsService.tts, _elvid, _el_text, out_audio, _style)
                    voice_res = {"path": out_audio, "provider": "elevenlabs", "voice": "clone", "cost_usd": 0.0}
                finally:
                    if _elvid:
                        await asyncio.to_thread(el.ElevenLabsService.delete_voice, _elvid)   # best-effort
        except Exception as _ele:
            logger.warning(f"[avatar-lipsync] ElevenLabs clone failed → f5/preset: {_ele}")
            voice_res = None
    if voice_res is None:
        _log_model_call(req.request_id, "voice", ("fal-clone:character" if sample_url else voice_id),
                        {"text": (_tts_text or "")[:400], "voice_id": voice_id, "style": _style,
                         "cloned": bool(sample_url), "prefer_expressive": bool(_emotional_delivery)})
        voice_res = await asyncio.to_thread(lambda: vs.synthesize(
            _tts_text, voice_id=("fal-clone:character" if sample_url else voice_id),
            sample_url=sample_url, out_path=out_audio, style=_style,
            fallback_voice_id=voice_id, prefer_expressive=_emotional_delivery,
            # what the character actually SAYS in the reference clip — improves clone fidelity
            ref_text=(_ref_text or a.get("character_transcript") or None)))
    _track_cost(req.request_id, "voice", voice_res.get("provider") or "openai", model=str(voice_res.get("voice")),
                units=len(script), unit_type="chars", cost_usd=voice_res.get("cost_usd") or 0)
    # ── CLONE AUDIO QA (Feature 3) — don't ship a garbled voice ──────────────────────────────────
    # The f5 clone can mangle the script ("$29"→"$1.29", "porch"→"poor", "savings"→"cash") or inject a
    # boundary artifact. Transcribe what was ACTUALLY synthesized and compare to the intended script;
    # on a bad match RETRY once, then fall back to a CLEAN preset voice (no clone) so corrupted audio
    # never ships. Best-effort: any error here keeps the original audio, never hard-fails.
    _clone_garbled = False
    if sample_url:   # only meaningful when a clone was actually used to synthesize
        try:
            _qa_ok, _qa_reason = await _audio_matches_script(out_audio, script)
            if not _qa_ok:
                logger.warning(f"[avatar-lipsync] clone audio garbled ({_qa_reason}) — re-synthesizing once")
                _retry = await asyncio.to_thread(lambda: vs.synthesize(
                    _tts_text, voice_id="fal-clone:character", sample_url=sample_url,
                    out_path=out_audio, style=_style, fallback_voice_id=voice_id,
                    prefer_expressive=_emotional_delivery,
                    ref_text=(_ref_text or a.get("character_transcript") or None)))
                if _retry:
                    voice_res = _retry
                _qa_ok2, _qa_reason2 = await _audio_matches_script(out_audio, script)
                if not _qa_ok2:
                    logger.warning(f"[avatar-lipsync] clone still garbled ({_qa_reason2}) — "
                                   f"falling back to a clean preset voice (no clone)")
                    voice_res = await asyncio.to_thread(lambda: vs.synthesize(
                        _tts_text, voice_id=voice_id, out_path=out_audio, style=_style,
                        fallback_voice_id=voice_id, prefer_expressive=_emotional_delivery))
                    sample_url = None   # a PRESET voice now, not a clone → labels/manifest reflect it
                    _clone_garbled = True
        except Exception as _qae:
            logger.warning(f"[avatar-lipsync] clone audio QA skipped: {_qae}")
    # ── PACING GUARDRAIL (never RUSH the read) ──────────────────────────────────────────────────
    # The script is now sized to the duration (word budget), so the natural read already ~fits. Only
    # a GENTLE nudge is allowed — a hard atempo (the old 1.15x) slurs words and mangles numbers
    # ("$29"→"$1.29"), which is what read as "garbled f5". Cap the speed-up at 1.06x so it NEVER
    # rushes; if the read is still a little long after that, let the video match the natural voice by
    # those couple of seconds — a natural pace beats a rushed one. f5 itself is fine; the rush was the
    # problem.
    _target_sec = float(seconds)
    _nar_sec = await asyncio.to_thread(_audio_seconds, out_audio)
    if _target_sec > 0 and _nar_sec > _target_sec:
        _sf = min(1.06, _nar_sec / _target_sec)
        if _sf > 1.001:
            _fitp = out_audio.rsplit(".", 1)[0] + "_sf.mp3"
            try:
                await asyncio.to_thread(_ffmpeg, ["-i", out_audio, "-filter:a", f"atempo={_sf:.3f}", _fitp], 120)
                out_audio = _fitp
                logger.info(f"[avatar-lipsync] narration {_nar_sec:.1f}s > target {_target_sec:.0f}s "
                            f"→ atempo {_sf:.3f}x to fit (no lengthening)")
            except Exception as _sfe:
                logger.warning(f"[avatar-lipsync] speed-fit skipped: {_sfe}")
    # ── DURATION POLICY ───────────────────────────────────────────────────────────────────────
    # NEVER cram the script into the asked-for seconds. The old code sped the VO up by as much as
    # 1.35x to squeeze under sync.so's old 20s free cap — that is exactly what made the delivery
    # sound rushed and the captions feel faster than the voice.
    #
    # Instead: let the read breathe at its natural pace and SPAN OUT the video to match it. Only
    # nudge the tempo if we're over a genuine hard ceiling, and even then never past 1.12x
    # (imperceptible). If we're still over, we cut on a SENTENCE boundary — never mid-word — so the
    # clip ends like a clip, not like a half-generated fragment.
    vo_sec = await asyncio.to_thread(_audio_seconds, out_audio)
    hard_cap = float(a.get("max_seconds") or 90)      # a real ceiling, not sync.so's old free tier
    fit_note = ""
    if vo_sec > hard_cap:
        factor = min(1.12, vo_sec / hard_cap)
        trimmed = _trim_to_sentence(script, hard_cap * factor)     # cut on a full stop
        if trimmed != script:
            script = trimmed
            out_audio = await asyncio.to_thread(lambda: vs.synthesize(
                script, voice_id=("fal-clone:character" if sample_url else voice_id),
                sample_url=sample_url, out_path=out_audio, style="casual, warm, conversational",
                fallback_voice_id=voice_id).get("path") or out_audio)
            vo_sec = await asyncio.to_thread(_audio_seconds, out_audio)
            fit_note = f"script trimmed to a full sentence to fit {hard_cap:.0f}s"
        if vo_sec > hard_cap:
            fit = out_audio.rsplit(".", 1)[0] + "_fit.mp3"
            await asyncio.to_thread(_ffmpeg, ["-i", out_audio, "-filter:a", f"atempo={factor:.3f}", fit], 120)
            out_audio, vo_sec = fit, await asyncio.to_thread(_audio_seconds, fit)
            fit_note = (fit_note + f"; tempo {factor:.2f}x").strip("; ")
    # TAIL PAD: f5's remove_silence trims the trailing beat, so the clip cuts on the last phoneme and
    # feels like the last word was chopped. Add ~0.45s of trailing silence so the ending breathes and
    # the final word lands fully. Best-effort — never block on it.
    try:
        _padded = out_audio.rsplit(".", 1)[0] + "_pad.mp3"
        await asyncio.to_thread(_ffmpeg, ["-i", out_audio, "-af", "apad=pad_dur=0.45", _padded], 120)
        if os.path.exists(_padded):
            out_audio = _padded
            vo_sec = await asyncio.to_thread(_audio_seconds, out_audio)
    except Exception as _pe:
        logger.warning(f"[avatar-lipsync] tail pad skipped: {_pe}")
    # THIS is the real runtime — the video follows the voice, not the other way round.
    seconds = max(1, int(round(vo_sec)))
    logger.info(f"[avatar-lipsync] VO runs {vo_sec:.1f}s at natural pace → video spans {seconds}s {fit_note}")

    audio_url = StorageService.upload_file(out_audio, f"voice/vo_{req.request_id[:8]}.mp3")
    if not audio_url:
        raise RuntimeError("avatar-lipsync: could not host the voice-over for lip-sync")
    # our bucket is private → presign so sync.so/fal/Replicate can actually fetch the audio
    audio_url = StorageService.presign_url(audio_url) or audio_url
    act.finish("character", req.request_id, t1, detail=f"voice={voice_res.get('provider')} (fallback={voice_res.get('fallback')})")

    # ── VERIFIER GATE (deterministic, no LLM) — the money is spent at lip-sync, so a slow/mismatched
    # voice must be caught HERE, not shipped. This is the loop's gate; it never edits itself.
    # Grade the voice we ACTUALLY cast: synthesize() can fall back to a different provider/voice, so
    # resolve the real cast voice's meta first, and only fall back to the requested id (e.g. when the
    # cast voice is a clone of the character, which is that character's own gender by construction).
    _cast_id = f"{voice_res.get('provider')}:{voice_res.get('voice')}"
    _vmeta = (next((v for v in vs.list_voices() if v.get("id") == _cast_id), None)
              or next((v for v in vs.list_voices() if v.get("id") == voice_id), {}))
    # ── SELF-CORRECTING PACE ─────────────────────────────────────────────────────────────────────
    # f5 can synth a read ABOVE the natural ceiling (e.g. 3.74 w/s), and the QC gate below would then
    # HARD-FAIL the whole generation. There was no path to slow a too-fast read (pacing only sped up
    # a too-slow one). STRETCH it under the ceiling instead of aborting — verbatim stays verbatim, all
    # words intact. Target 3.3 w/s (comfortably inside 1.8-3.6); atempo<1 lengthens; floor 0.75.
    try:
        _wc = len((script or "").split())
        if _wc >= 8 and vo_sec > 0 and (_wc / vo_sec) > 3.5:
            _factor = max(0.75, vo_sec / (_wc / 3.3))
            if _factor < 0.985:
                _slow = out_audio.rsplit(".", 1)[0] + "_slow.mp3"
                await asyncio.to_thread(_ffmpeg, ["-i", out_audio, "-filter:a", f"atempo={_factor:.3f}", _slow], 120)
                if os.path.exists(_slow):
                    out_audio = _slow
                    vo_sec = await asyncio.to_thread(_audio_seconds, out_audio)
                    seconds = max(1, int(round(vo_sec)))
                    logger.info(f"[avatar-lipsync] slowed a fast read ({_wc/vo_sec:.2f} w/s) → atempo {_factor:.3f} → {vo_sec:.1f}s")
                    # CRITICAL SYNC FIX: audio_url was hosted from the PRE-stretch audio (above). The
                    # lip-sync consumes audio_url; the captions align to out_audio. We just changed
                    # out_audio — so re-host it and repoint audio_url, else veed syncs the FAST original
                    # while captions time to the SLOW one (audio runs fast, captions crawl behind).
                    _reup = StorageService.upload_file(out_audio, f"voice/vo_{req.request_id[:8]}_slow.mp3")
                    if _reup:
                        audio_url = StorageService.presign_url(_reup) or _reup
    except Exception as _psle:
        logger.warning(f"[avatar-lipsync] pace slow-down skipped: {_psle}")
    from ..services import creative_qc as qc
    _qc = qc.verify_pre_lipsync(
        script=script, vo_seconds=vo_sec,
        voice_gender=_vmeta.get("gender"), voice_age=_vmeta.get("age_band"),
        char_gender=a.get("gender"), char_age=a.get("age_band"),
        offer_value=offer_value or None)
    if not _qc["ok"]:
        # NON-FATAL PACE: a pace-only pre-render miss must NOT abort the whole paid job anymore. The
        # self-correcting atempo stretch just above already slows a too-fast read, and the FINAL eval
        # gate re-checks faithfulness/pace on the delivered file — so pace has two later arbiters. Only
        # raise when a NON-pace BLOCKER remains (gender/age mismatch), exactly as before. Decision keys
        # off the block-severity blockers in _qc["checks"] (not _qc["reasons"], which also carries the
        # soft offer WARN — that must never trigger a hard fail).
        _blockers = [c for c in (_qc.get("checks") or [])
                     if not c.get("ok") and c.get("severity") == "block"]
        _pace_only = bool(_blockers) and all(str(c.get("name")).lower() == "pace" for c in _blockers)
        if _pace_only:
            logger.warning(f"[qc] pace-only pre-render miss ({req.request_id}) — NOT aborting "
                           f"(stretch ran; final gate arbitrates): {_qc['reasons']}")
            _set_lipsync_status(req.request_id, "warn", "QC pace (non-fatal): " + "; ".join(_qc["reasons"])[:230])
        else:
            logger.error(f"[qc] BLOCKED before lip-sync ({req.request_id}): {_qc['reasons']}")
            _set_lipsync_status(req.request_id, "failed", "QC: " + "; ".join(_qc["reasons"])[:250])
            raise RuntimeError("creative QC failed before render: " + "; ".join(_qc["reasons"]))
    if _qc["reasons"]:
        logger.warning(f"[qc] warnings ({req.request_id}): {_qc['reasons']}")

    # ── THE FOOTAGE MUST COVER THE VOICE ──────────────────────────────────────────────────────
    # If the character's clip is shorter than the VO, the lip-sync output gets cut off — that is
    # the "half-generated" ending. Extend the footage to cover the full read before we sync.
    char_url = await _cover_audio_with_footage(char_url, vo_sec, req.request_id)

    await _abort_if_cancelled(req, "avatar-lipsync render")

    # 3) LIP-SYNC — video→video re-sync on OUR real footage. Submit → PERSIST the provider job
    #    (so an AE restart doesn't orphan it) → poll. Free/cheapest first: sync.so → fal → Replicate.
    from ..services import lip_sync
    t2 = act.start("shots", req.request_id, "re-syncing the mouth on the real footage")
    prefer = a.get("lipsync_provider")   # optional override: sync | fal | latentsync | wav2lip
    quality = a.get("quality") or _ENGINE["default_quality"]   # bulk (cheapest) | premium
    name, out_path, out_url = _out_url(req, "avatar_lipsync")
    # SHRINK THE SOURCE before lip-sync. The cheap endpoints have input-size limits (fal-kling
    # rejected a library clip outright: "Video size is too large"), and lip-sync quality is driven by
    # the FACE CROP, not the source bitrate — so a 720p/CRF-28 re-encode costs nothing visually and
    # keeps us on the $0.17/min lane instead of failing over to $4.20/min. Best-effort: on any error
    # we submit the original, exactly as before.
    # NOTE: _shrink_for_lipsync is deliberately NOT called. It existed only to fit fal-kling's
    # input limit; kling is gone from the chain, and the re-encode cost ~81s per render plus real
    # quality loss (720p/CRF28) for zero benefit. Submit the original clip.
    # ── HARD COST GATE ────────────────────────────────────────────────────────────────────────
    # Lip-sync is the single most expensive step and it is billed per second of OUTPUT, so a long
    # VO on a pricey lane can bill many dollars. Project the spend on the lane(s) we could actually
    # land on (an explicit `prefer`, else the dearest default lane, since submit falls through the
    # chain) and refuse BEFORE the paid submit.
    _cand = [prefer] if prefer else ["veed", "sync", "falsync"]
    _proj = max(_lipsync_projected_usd(p, seconds) for p in _cand)
    _gate_job_cost(req.request_id, f"lip-sync {seconds}s via {'/'.join(_cand)}", _proj, a)
    _log_model_call(req.request_id, "lipsync", (prefer or f"auto ({quality})"),
                    {"video": char_url, "audio": audio_url, "prefer": prefer, "quality": quality,
                     "seconds": seconds})
    sub = await asyncio.to_thread(lambda: lip_sync.submit_relipsync(char_url, audio_url, prefer, quality=quality))
    _persist_lipsync(req.request_id, sub["provider"], sub["job"], audio_url, char_url, req.callback_url, name, script)
    result = None
    try:
        for _ in range(150):   # ~10 min; a restart mid-poll is recovered by resume_pending_lipsync()
            await asyncio.sleep(4)
            stt, res = await asyncio.to_thread(lambda: lip_sync.poll_relipsync(sub["provider"], sub["job"]))
            if stt == "done":
                result = res; break
    except Exception as _pe:
        # POLL-TIME FALLBACK. The provider chain only ran at SUBMIT, so a provider that ACCEPTED the
        # job and then failed mid-render (fal-kling: "Video size is too large") killed the whole
        # generation instead of trying the next lane. Retry once on the next provider — the user
        # gets a video, and we only step UP in price when the cheap lane genuinely can't do it.
        logger.warning(f"[avatar-lipsync] {sub['provider']} failed mid-render ({_pe}) — retrying on the next lane")
        _alt = "sync" if sub["provider"] != "sync" else "falsync"
        try:
            sub = await asyncio.to_thread(
                lambda: lip_sync.submit_relipsync(char_url, audio_url, _alt, quality=quality))
            _persist_lipsync(req.request_id, sub["provider"], sub["job"], audio_url, char_url,
                             req.callback_url, name, script)
            for _ in range(150):
                await asyncio.sleep(4)
                stt, res = await asyncio.to_thread(lambda: lip_sync.poll_relipsync(sub["provider"], sub["job"]))
                if stt == "done":
                    result = res; break
        except Exception as _pe2:
            _set_lipsync_status(req.request_id, "failed")
            raise RuntimeError(f"lip-sync failed on {_alt} after {sub.get('provider')} failed: {_pe2}") from _pe2
    # EITHER poll loop can exhaust its 150 polls without ever seeing "done" and fall through here with
    # result=None. Previously that raised WITHOUT marking the job failed, so the row stayed
    # 'processing' forever — a zombie the UI waits on for good. Always fail it explicitly.
    if result is None:
        _set_lipsync_status(req.request_id, "failed", f"lip-sync timed out on {sub['provider']}")
        raise RuntimeError("lip-sync timed out")
    act.finish("shots", req.request_id, t2, detail=f"lip-sync via {sub['provider']}")

    # ── POST-SYNC TONE-SEAM MATCH ───────────────────────────────────────────────────────────────
    # The synced clip's repainted mouth region can drift in tone from the rest of the face/body,
    # leaving a visible seam. Nudge the whole frame back toward the ORIGINAL character clip's color
    # (best-effort; NO grain, NO resolution change). On ANY failure keep the un-matched video.
    try:
        _synced_local = result.get("local_path") or await _download_to_temp(result["video_url"], ".mp4")
        _matched = await _color_match_to_reference(_synced_local, char_url, req.request_id)
        if _matched:
            result = {"local_path": _matched}   # downstream re-encodes from the tone-matched master
    except Exception as _cme:
        logger.warning(f"[avatar-lipsync] post-sync tone match skipped: {_cme}")

    # ── LIP-SYNC MASKING — DISABLED (fixed box drifts on a moving head) ───────────────────────────
    # _mouth_region_composite pasted a FIXED-POSITION mouth box from the synced clip over the original,
    # on the premise "the head stays in the same position." Real UGC clips move (the person turns /
    # leans / gestures), so the static box slides off the mouth and the overlay becomes VISIBLE — the
    # exact seam reported. veed's own output is a full-frame lip-sync that TRACKS the face, so deliver
    # that instead (no static seam). Re-enable only behind a real per-frame FACE-TRACKED mask.
    if False:  # keep the branch for an easy face-tracked revisit; never runs today
      try:
        _sp = result.get("local_path") or await _download_to_temp(result["video_url"], ".mp4")
        _mouthed = await _mouth_region_composite(_sp, char_url, req.request_id)
        if _mouthed:
            result = {"local_path": _mouthed}
      except Exception as _moe:
        logger.warning(f"[avatar-lipsync] mouth-region composite skipped: {_moe}")

    # ── UGC-BROLL COMPOSITE (optional) ─────────────────────────────────────────────────────────────
    # For a "UGC + B-Roll" ask, intercut satisfaction/interior b-roll over this lip-synced talking-head
    # while the VO (out_audio) plays straight through — the library format (open on oddly-satisfying
    # b-roll with captions already running, then the character cuts in and CONTINUES in lip-sync). The
    # layout VARIES per generation (ham = b-roll cold-open, rit = face cold-open) via the variation
    # index, so a batch isn't identical. Swap `result` to the composite BEFORE captions so the existing
    # kinetic-caption burn runs over the whole thing (opener included). Best-effort: on any shortfall
    # `result` is untouched and we ship the plain talking-head.
    _ugc_broll_note = ""   # surfaced on the creative's feedback so a live run reveals what the composite did
    _broll_applied = False   # True ONLY if the composite actually swapped in b-roll — fed to the QA gate
    if ugc_broll or (isinstance(a, dict) and a.get("ugc_broll")):
        try:
            _fm = result.get("local_path") or await _download_to_temp(result["video_url"], ".mp4")
            _ub_work = tempfile.mkdtemp()   # NOT cleaned here — the composite lives in it until variant reads it
            _ub_intent = {"vertical": (vertical or ""), "scene": (a.get("scene") or ""),
                          "gender": (a.get("gender") or ""), "age_band": (a.get("age_band") or "")}
            _ub_layout = "ham" if (_vidx % 2 == 1) else "rit"
            _ub_hooks = a.get("broll_hook_urls") if isinstance(a, dict) else None
            _ub_inter = a.get("broll_interior_urls") if isinstance(a, dict) else None
            _ub, _ub_status = await _compose_ugc_broll(_fm, out_audio, float(vo_sec), _ub_intent, _ub_layout,
                                                       _ub_work, req, hook_urls=_ub_hooks, interior_urls=_ub_inter)
            _ugc_broll_note = _ub_status or ""
            if _ub and os.path.exists(_ub):
                result = {"local_path": _ub}
                _broll_applied = True   # real b-roll composite shipped — the QA gate's presence check passes
                logger.info(f"[ugc-broll] {_ub_status} ({vo_sec:.0f}s)")
            else:
                logger.info(f"[ugc-broll] no composite ({_ub_status}) — delivering the plain talking-head")
        except Cancelled:
            raise
        except Exception as _ube:
            _ugc_broll_note = f"error: {str(_ube)[:80]}"
            logger.warning(f"[ugc-broll] composite failed ({_ube}) — plain talking-head")

    # Corrected 2026 rates (see _lipsync_projected_usd): VEED = $0.40 per MINUTE of output ($0.0067/s),
    # NOT $0.07/s — the old model was 10x high and made the office show ~$2.17 for a 31s clip instead of
    # ~$0.21. sync/falsync = $0.70/min; Replicate LatentSync/Wav2Lip are per-prediction; kling bills in
    # whole 5s blocks. ONE rate table feeds both the pre-submit gate and this post-render record.
    _lip_cost = _lipsync_projected_usd(sub["provider"], seconds)
    _track_cost(req.request_id, "lipsync", sub["provider"], units=seconds, unit_type="sec",
                cost_usd=_lip_cost, note=f"lip-sync via {sub['provider']}")

    # 3b) CAPTIONS (optional). Default = ffmpeg ASS (free, our exact words). style="veed" = VEED via fal.
    _cap_words, _cap_method, _cap_err = [], "", ""
    # GATED self-correction (caption_place brain): only when the user did NOT pin a caption_style
    # AND an ADMIN-APPROVED rule prefers a method do we bias veed/ffmpeg. No active rule → None →
    # exact current behavior. Wrapped so it can never break the render.
    _cap_style = (a.get("caption_style") or "").lower()
    if not _cap_style:
        try:
            from ..services import creative_tuner as ctun
            from ..database import SessionLocal as _SL
            _cdb = _SL()
            try:
                _cap_pref = ctun.governed_preference(_cdb, "caption_place", vertical or None)  # 'veed'|'ffmpeg'|None
            finally:
                _cdb.close()
            if _cap_pref:
                _cap_style = _cap_pref
        except Exception:
            pass
    _use_veed = bool(a.get("captions")) and ((_cap_style or "clean") == "veed") and bool(settings.fal_key)
    if a.get("captions"):
        try:
            from ..services import captions as cap
            _log_model_call(req.request_id, "captions", ("veed" if _use_veed else "whisper+ass"),
                            {"style": (_cap_style or "clean"), "script": (script or "")[:400]})
            # align() NEVER comes back empty: ElevenLabs FA → Whisper word-timestamps (real timings
            # off the actual voice, so the pace is right) → Deepgram → even-split.
            _cap_words, _cap_method = await asyncio.to_thread(lambda: cap.align(out_audio, script))
            if _cap_words and not _use_veed:
                _track_cost(req.request_id, "captions", f"{_cap_method}+ffmpeg", cost_usd=0.004,
                            note=f"{_cap_method} word timings + ffmpeg burn (TikTok style, CTA button)")
        except Exception as e:
            _cap_err = str(e)[:160]
            logger.error(f"captions FAILED for {req.request_id}: {e}")
    if a.get("captions") and not _cap_words:
        _cap_err = _cap_err or "every aligner returned no words"
        logger.error(f"captions requested but NOT burned for {req.request_id}: {_cap_err}")

    # 4) SAVE — normalize + persist to BOTH buckets (subtitle is built in here, sized to the real frame)
    variant = await _produce_lipsync_variant(req.request_id, name, result, script,
                                             cap_words=(None if _use_veed else _cap_words),
                                             vertical=(vertical or None),
                                             kinetic=bool(ugc_broll or (isinstance(a, dict) and a.get("ugc_broll"))))
    ass_path = variant.get("captions_burned")

    # 4b) VEED styled captions (fal) — post-process the produced video, feeding our SRT for accuracy
    if _use_veed:
        try:
            from ..services import captions as cap
            srt_path = cap.build_srt(_cap_words, os.path.join(UPLOAD_DIR, f"cap_{req.request_id[:8]}.srt")) if _cap_words else None
            srt_text = open(srt_path).read() if srt_path else None
            veed_url = await asyncio.to_thread(lambda: cap.veed_subtitles(
                variant["video_url"], preset=(a.get("caption_preset") or "glide"), srt_text=srt_text))
            capped = await _download_to_temp(veed_url, ".mp4")
            import shutil
            shutil.move(capped, os.path.join(UPLOAD_DIR, name))
            _ae_persist(os.path.join(UPLOAD_DIR, name), name)
            _track_cost(req.request_id, "captions", "veed(fal)", units=seconds, unit_type="min",
                        cost_usd=round(seconds / 60 * 0.10, 4), note="VEED styled")
        except Exception as e:
            logger.warning(f"VEED captions failed, keeping base video: {e}")
    _set_lipsync_status(req.request_id, "done")

    # ── NEVER AN ABRUPT STOP (reject-if-cut) ──────────────────────────────────────────────────────
    # The synced video should span the full padded VO (the 0.45s tail lives in the audio fed to the
    # provider), but a provider can hand back video a beat SHORTER than its audio — which chops the
    # final word. ffprobe BOTH streams of the DELIVERED file; if the video is shorter, freeze-hold the
    # last frame to cover the audio so the WHOLE narration always plays. Runs before the final QA so
    # QA sees the corrected file. Best-effort: never truncate, never hard-fail, no resolution change.
    try:
        _final = os.path.join(UPLOAD_DIR, name)
        _vdur = await asyncio.to_thread(_stream_duration, _final, "v")
        _adur = await asyncio.to_thread(_stream_duration, _final, "a")
        if _vdur and _adur and (_adur - _vdur) > 0.15:
            _hold = _final.rsplit(".", 1)[0] + "_hold.mp4"
            await asyncio.to_thread(_ffmpeg, [
                "-i", _final,
                "-vf", f"tpad=stop_mode=clone:stop_duration={_adur - _vdur + 0.1:.2f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "copy", _hold], 400)
            if os.path.exists(_hold):
                import shutil as _sh5
                _sh5.move(_hold, _final)
                _ae_persist(_final, name)
                logger.warning(f"[avatar-lipsync] {req.request_id}: video {_vdur:.1f}s < audio {_adur:.1f}s "
                               f"→ held last frame to cover the full narration (no truncation)")
    except Exception as _ce:
        logger.warning(f"[avatar-lipsync] tail-extend check skipped: {_ce}")

    # ── EVAL GATE (global examiner on the delivered file) — PERSISTED via _record_qc + lessons ───
    # This lane never ran the final examiner, so nothing was written to creative_decisions for an
    # avatar job and /learn/decisions came back []. The gate wraps final-video QA (so it runs once)
    # and adds the objective faithfulness/never-abrupt/residual-caption/spec/cast checks + a
    # cross-family semantic judge. Pass the RESOLVED captions flag (whether we actually burned any).
    # Fail-open on INTERNAL error (deliver defaults True), but a confident FAIL now BLOCKS delivery below.
    _eval = {}
    try:
        _fqwork = tempfile.mkdtemp()
        try:
            # Carry the b-roll signal so the gate can BLOCK a UGC+B-Roll job that silently degraded to a
            # plain talking-head (_broll_applied is set True only when the composite actually swapped in).
            _assets_for_gate = {**a, "captions": bool(ass_path or _use_veed),
                                "_ugc_broll_requested": bool(ugc_broll or (isinstance(a, dict) and a.get("ugc_broll"))),
                                "_broll_applied": _broll_applied}
            _eval = await _eval_gate(req.request_id, os.path.join(UPLOAD_DIR, name), script,
                                     _assets_for_gate, _fqwork) or {}
        finally:
            import shutil as _sh3
            _sh3.rmtree(_fqwork, ignore_errors=True)
    except Exception as _fqe:
        logger.warning(f"[avatar-lipsync] eval gate skipped: {_fqe}")

    # ── HONOR THE GATE — BLOCK a bad delivery instead of shipping it ─────────────────────────────
    # The gate is the examiner: a confident FAIL must FAIL the job with the REAL reason, not silently
    # ship a broken take (or a plain talking-head when UGC+B-Roll was requested — see _eval_gate's
    # b-roll-presence check). _eval_gate is fail-open (any INTERNAL error → deliver=True), so only a
    # genuine, high-confidence fault reaches here. Raise BEFORE the reward-critic + learning log below,
    # so a blocked take never rewards the personas or records qc_passed=True. _execute catches this and
    # fires the failed callback carrying this reason — the desired "fail loudly with the real cause".
    if _eval.get("deliver") is False:
        _gate_reasons = (_eval.get("reasons") or [])[:3]
        _set_lipsync_status(req.request_id, "failed", "QA: " + "; ".join(_gate_reasons)[:250])
        raise RuntimeError("QA gate blocked delivery: " + "; ".join(_gate_reasons))

    # ── POST-RENDER VISUAL QA (grade + coach, NO retry) ──────────────────────────────────────────
    # The avatar-lipsync path produced its clip but nothing ever critiqued the OUTPUT — so no persona
    # was ever faulted, accountability stayed pinned at 100%, and no 1:1 coaching was written. Run the
    # SAME vision Critic the t2v path uses on the FINAL delivered clip: reward the personas on a pass,
    # or attribute faults + write the one-on-one note (fed back into the next run via _coach_pre) on a
    # miss. Best-effort — never blocks or breaks delivery; grade-only, no regeneration.
    try:
        from ..services import creative_team as team
        _final_clip = os.path.join(UPLOAD_DIR, name)
        _qwork = tempfile.mkdtemp()
        try:
            _qframes = await asyncio.to_thread(_extract_frames, _final_clip,
                                               [1.0, max(1.5, seconds * 0.5)], _qwork)
            if _qframes:
                _tq = act.start("critic", req.request_id, "visual QA on the final avatar clip")
                _beat = {"i": 0, "shot_type": "talking_head", "prompt": (script or "")[:400]}
                _ev = await team.evaluate_clip(_qframes, _beat)
                _passed = team.eval_passed(_ev)
                act.finish("critic", req.request_id, _tq, ok=True, revised=(not _passed),
                           detail=(f"final clip scored {_ev.get('overall')}/10 · faults: "
                                   + ", ".join(_ev.get("fault_personas") or ["none"])),
                           helpfulness=float(_ev.get("overall", 10)) / 10.0)
                if _passed:
                    for _p in ("prompt", "character", "shots"):
                        act.reward(_p, job_id=req.request_id)
                else:
                    team.coach_from_eval(_beat, _ev, job_id=req.request_id)   # dock + 1:1 note + learn
        finally:
            import shutil as _sh2
            _sh2.rmtree(_qwork, ignore_errors=True)
    except Exception as _qe:
        logger.warning(f"[avatar-lipsync] post-render QA skipped: {_qe}")

    # auto-feedback statement for THIS generation (shown per video). Report what ACTUALLY happened —
    # a clone that fell back to a preset must not still claim "cloned from character".
    _cloned = (voice_res.get("provider") in ("fal-clone", "chatterbox")
               or (voice_res.get("provider") == "elevenlabs" and voice_res.get("voice") == "clone"))
    _swapped = voice_res.get("fallback") and voice_res.get("requested")
    fb = ("Reused real library footage · "
          f"voice {voice_res.get('provider')}:{voice_res.get('voice')}"
          + (" (cloned from character)" if _cloned
             else " (clone unavailable → cast)" if sample_url else "")
          # if we could not honour the voice the user PICKED, say so on the creative itself
          + (f" · ⚠ you picked {voice_res.get('requested')} but it was unavailable "
             f"({voice_res.get('fallback_reason')})" if _swapped else "")
          + f" · lip-sync {sub['provider']} · ~{seconds}s"
          + (f" · states offer {offer_value}" if offer_value else "")
          + (" · script: yours, verbatim" if verbatim else "")
          + (f" · captions {_cap_method}" if (a.get("captions") and ass_path) else "")
          + (" · captions VEED" if _use_veed else "")
          + (f" · variation {_vidx}/{_vtot} on the {_axis} axis" if _diversify else "")
          + (f" · ⚠ {_axis_note}" if _axis_note else "")
          + (f" · UGC-BROLL: {_ugc_broll_note}" if _ugc_broll_note else "")
          + (f" · ⚠ captions failed: {_cap_err}" if _cap_err else ""))
    # A deliver=False take already RAISED above (hard-blocked), so it never reaches here. A PASS that
    # still carries soft issues (semantic nits, spec drift) is annotated on the creative — same soft
    # note the multi-clip path surfaces — so a shipped take honestly shows what QA saw.
    if _eval.get("issues"):
        fb += " ⚠ QA: " + "; ".join((_eval.get("issues") or [])[:2])
    # MODELS MANIFEST — structured, stable keys, human-readable values (surfaced by the frontend);
    # populated from what ACTUALLY ran (same signals as whats_changed).
    _voice_label = ("f5-tts (clone)" if voice_res.get("provider") == "fal-clone"
                    else "elevenlabs (clone)" if (voice_res.get("provider") == "elevenlabs"
                                                  and voice_res.get("voice") == "clone")
                    else f"{voice_res.get('provider')}:{voice_res.get('voice')}")
    if _clone_garbled:   # clone failed QA and we swapped to a clean preset — say so on the manifest
        _voice_label = f"preset (clone garbled → fallback): {voice_res.get('provider')}:{voice_res.get('voice')}"
    _models = {"video": None, "voice": _voice_label, "voice_cloned": bool(_cloned),
               "lipsync": sub["provider"],
               "captions": ("veed" if _use_veed else ("whisper+ass" if ass_path else None)),
               "recipe": "Avatar Lipsync"}
    variant.update({"voice": voice_res.get("provider"), "voice_id": voice_id, "cloned": _cloned,
                    "voice_swapped": bool(_swapped), "voice_requested": voice_res.get("requested"),
                    "captions": bool(ass_path or _use_veed), "caption_method": _cap_method,
                    "models": _models, "whats_changed": fb, "feedback": fb,
                    # EVAL GATE — a needs-review take ranks BELOW clean output (same signal as t2v).
                    "confidence": _eval.get("confidence", 0.7),
                    "qc_issues": (_eval.get("issues") or [])})

    # ── STATE: log every choice so the loop can learn from ROI later ──
    try:
        from ..services import learning_loop as learn
        from ..database import SessionLocal
        _db = SessionLocal()
        try:
            # what each BRAIN actually decided (NULL when not recoverable → excluded from ranking):
            # keep the PARSER's interpreted mode (modify/reuse/verbatim) so the brains learn from the
            # attachment-sourced jobs too; fall back to the derived mode when none was supplied.
            _script_mode = _interpreted_mode or ("verbatim" if verbatim else ("rewrite" if base else "from-scratch"))
            _caption_method = ("veed" if _use_veed else ("ffmpeg" if ass_path else None))
            # RECAST: tag the character_key so the loop can later learn recast (library|generated)
            # quality from ROI/editor feedback — no new column/table needed.
            _ckey = a.get("character_asset_id") or a.get("source_filename") or char_url
            _recast_src = a.get("recast_source")
            if _recast_src and _recast_src != "fallback":
                _ckey = f"recast-{_recast_src}:{_ckey}"
            learn.log_decision(
                _db, request_id=req.request_id, vertical=(vertical or None),
                creative_ref=name,   # delivered filename → the key ROI joins back on
                character_key=_ckey,
                character_gender=a.get("gender"), character_age=a.get("age_band"),
                voice_id=voice_id, voice_provider=voice_res.get("provider"),
                voice_cloned=_cloned, lipsync_provider=sub["provider"],
                script_ref=(a.get("script_ref") or None), captions=bool(ass_path or _use_veed),
                script_mode=_script_mode, caption_method=_caption_method,
                caption_removal_method=(variant.get("caption_removal") or None),
                # the REQUESTED diversification axis (NULL for single-variation jobs) so editor
                # feedback ("wanted different scripts, not faces") can later train an axis classifier.
                variation_axis=(_axis or None),
                qc_passed=True, cost_usd=float(_lip_cost or 0))
        finally:
            _db.close()
    except Exception as e:
        logger.warning(f"[learn] decision log skipped: {e}")

    # ── LIP-SYNC A/B (opt-in via assets.lipsync_ab) ────────────────────────────────────────────────
    # Produce a SECOND variant lip-synced with the OTHER model on the SAME audio+video, so the two
    # lip-sync engines can be compared side by side. Each variant is labeled with its own model (the
    # primary's whats_changed already carries "· lip-sync <provider>"; the manifest records it too).
    # Best-effort: any failure just leaves the single primary variant. Default (no flag) = single.
    _variants = [variant]
    if a.get("lipsync_ab"):
        try:
            _ab_alt = "sync" if sub["provider"] != "sync" else "veed"
            _log_model_call(req.request_id, "lipsync-ab", _ab_alt,
                            {"video": char_url, "audio": audio_url, "prefer": _ab_alt, "seconds": seconds})
            _bsub = await asyncio.to_thread(
                lambda: lip_sync.submit_relipsync(char_url, audio_url, _ab_alt, quality=quality))
            _bres = None
            for _ in range(150):   # ~10 min
                await asyncio.sleep(4)
                _bst, _br = await asyncio.to_thread(
                    lambda: lip_sync.poll_relipsync(_bsub["provider"], _bsub["job"]))
                if _bst == "done":
                    _bres = _br
                    break
            if _bres:
                _stem, _ext = (name.rsplit(".", 1) + ["mp4"])[:2]
                _bname = f"{_stem}_ab_{_bsub['provider']}.{_ext}"
                _bvar = await _produce_lipsync_variant(
                    req.request_id, _bname, _bres, script,
                    cap_words=(None if _use_veed else _cap_words), vertical=(vertical or None))
                _bcost = _lipsync_projected_usd(_bsub["provider"], seconds)
                _track_cost(req.request_id, "lipsync", _bsub["provider"], units=seconds, unit_type="sec",
                            cost_usd=_bcost, note=f"lip-sync A/B via {_bsub['provider']}")
                _bfb = (fb.replace(f"· lip-sync {sub['provider']}", f"· lip-sync {_bsub['provider']}")
                        + " · A/B arm")[:600]
                _bmodels = dict(_models)
                _bmodels["lipsync"] = _bsub["provider"]
                _bvar.update({"voice": voice_res.get("provider"), "voice_id": voice_id,
                              "cloned": _cloned, "caption_method": _cap_method,
                              "captions": bool(_bvar.get("captions_burned") or _use_veed),
                              "models": _bmodels, "whats_changed": _bfb, "feedback": _bfb})
                _variants.append(_bvar)
                logger.info(f"[avatar-lipsync] A/B: primary lip-sync {sub['provider']} + alt {_bsub['provider']}")
        except Cancelled:
            raise
        except Exception as _abe:
            logger.warning(f"[avatar-lipsync] A/B second lip-sync skipped: {_abe}")

    # attach the per-generation model-call log to every variant (best-effort)
    _mc = _drain_model_calls(req.request_id)
    for _v in _variants:
        _v["model_calls"] = _mc
    return _variants


async def recipe_fal_video(req: RunRequest) -> list:
    """New-from-scratch video via a fal model (fal-seedance / fal-kling / fal-wan) — the cheap lane.
    Model is explicit + cost-tracked so the brain learns which model performs best."""
    from ..services import fal_video as fv
    a = req.assets or {}
    prompt = (a.get("prompt") or req.expectation or "").strip()
    if not prompt:
        raise RuntimeError("fal video: prompt required")
    model = (req.model or a.get("engine") or "fal-seedance")
    image_url = (a.get("image_urls") or [None])[0]
    seconds = int(a.get("seconds") or 5)
    try:
        res = await asyncio.to_thread(lambda: fv.generate_video(
            model, prompt, image_url=image_url, seconds=seconds,
            aspect_ratio=a.get("aspect_ratio") or "9:16", resolution=a.get("resolution") or "480p"))
    except Exception as e:
        # fal down / no credits / bad key → don't fail the job; fall back to the Kie
        # Seedance lane (recipe_generate), which produces an equivalent new-from-scratch video.
        logger.warning(f"fal video ({model}) failed ({e}) — falling back to Kie Seedance (recipe_generate)")
        return await recipe_generate(req)
    name, out_path, out_url = _out_url(req, "gen")
    await asyncio.to_thread(_ffmpeg, ["-i", res["local_path"], "-c:v", "libx264", "-preset", "veryfast",
                                      "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out_path], 300)
    _ae_persist(out_path, name)
    _track_cost(req.request_id, "video", res["model"], model=res["model"], units=seconds, unit_type="sec",
                cost_usd=res["cost_usd"], note=("image→video" if image_url else "text→video"))
    fb = f"New video · {res['model']}{' (image→video)' if image_url else ''} · {seconds}s · {a.get('resolution') or '480p'}"
    return [{"recipe": f"Generate — {res['model']}", "video_url": out_url, "whats_changed": fb, "feedback": fb, "confidence": 0.7}]


async def recipe_generate_router(req: RunRequest) -> list:
    """Route new-video by chosen model: fal-* → cheap fal lane; else Kie Seedance (recipe_generate)."""
    m = (req.model or (req.assets or {}).get("engine") or "").lower()
    if m.startswith("fal-"):
        return await recipe_fal_video(req)
    return await recipe_generate(req)


_RECIPES = {
    "Full Ad": recipe_full_ad,
    "Avatar Lipsync": recipe_avatar_lipsync,
    # UGC + B-Roll = the avatar-lipsync talking-head with satisfaction/interior b-roll intercut over
    # one continuous VO (the S2-TX-UGC-BROLL library format). Same real-clip + voice-clone + lip-sync
    # spine; the ugc_broll flag turns on the b-roll compositing tail. Also honored via assets.ugc_broll.
    "UGC + B-Roll": lambda r: recipe_avatar_lipsync(r, ugc_broll=True),
    "UGC + B-Roll Home Insurance": lambda r: recipe_avatar_lipsync(r, ugc_broll=True),
    "Create from Assets": recipe_from_assets,
    "Generate Video": recipe_generate_router,
    "Avatar/UGC": recipe_avatar,
    "map + ugc": recipe_avatar,
    "Hook Change Only": recipe_hook_change,
    "Caption Change Only": recipe_caption_change,
    "Reclean/Minor Mod": recipe_reclean,
    "Script": recipe_script_rewrite,
    "Broll": recipe_broll,
    "Stock Video": lambda r: recipe_broll(r, "Stock Video"),
    "Image": lambda r: recipe_broll(r, "Image"),
    "Image + Voiceover": lambda r: recipe_broll(r, "Image + Voiceover"),
    "Special Request": recipe_special,
}
