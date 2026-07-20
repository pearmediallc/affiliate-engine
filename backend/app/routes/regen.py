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
import json
import base64
import logging
import asyncio
import tempfile
import subprocess
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
CALLBACK_SECRET = os.getenv("REGEN_CALLBACK_SECRET", "change-me-regen-callback")
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


async def _gemini_vision(frame_paths: list, prompt: str) -> dict:
    """Send frames + a prompt to Gemini and get back STRICT JSON."""
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
    return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])


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
        logger.warning(f"caption-box detect failed: {e}")
        return []


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
                    'These frames are from a creative-library reference clip. Return STRICT JSON for a '
                    'reference index: {"role":"talking_head|map|broll|product|proof", '
                    '"age_band":"<one of: under35|35-44|45-55|55plus, or none>", '
                    '"gender":"<male|female|none>", "ethnicity":"<short or none>", '
                    '"wardrobe":"<short or none>", "scene":"<setting in <=8 words>", '
                    '"style":"<ugc_handheld|cinematic|animated|studio, or none>", '
                    '"face_score":<0.0-1.0 how clean/front-facing a single talking face is; 0 if no face>, '
                    '"num_faces":<int count of distinct human faces clearly visible in frame; 0 if none>, '
                    '"num_people":<int>, '
                    '"on_screen":"<key objects/proof e.g. document, phone, house, cash, or none>", '
                    '"emotion":"<energy/expression in 1-2 words>"}')
            except Exception as e:
                logger.warning(f"tag-asset vision failed: {e}")
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
                "emotion": tags.get("emotion") or ""}
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
    """The changelog: recent LearningEvents newest-first (every keep/reject of a governed rule),
    filterable by brain/vertical. This is the auditable record of every self-correction."""
    from ..database import SessionLocal
    from ..models.learning import LearningEvent
    db = SessionLocal()
    try:
        q = db.query(LearningEvent)
        if brain:
            q = q.filter(LearningEvent.brain == brain)
        if vertical:
            q = q.filter(LearningEvent.vertical == vertical)
        rows = q.order_by(LearningEvent.created_at.desc()).limit(min(max(limit, 1), 200)).all()
        items = [{"brain": r.brain, "vertical": r.vertical, "summary": r.summary,
                  "agreement_before": r.agreement_before, "agreement_after": r.agreement_after,
                  "detail": r.detail_json,
                  "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
        return {"success": True, "count": len(items), "events": items}
    finally:
        db.close()


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
        return {"success": True, "vertical": vt or "all", "brains": out}
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
        portrait_prompt = (", ".join(parts) +
            ". Authentic UGC look, natural skin texture with real pores, realistic lighting, correct "
            "anatomy; ONE single person only; NO on-screen text, no watermark, no plastic AI skin.")
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


@router.post("/studio/route")
async def studio_route(payload: dict, _auth: bool = Depends(require_service_key)):
    """ChatGPT-style Studio router. Given the recent thread history + the new message, classify into
    ONE strict-JSON action AND (for write actions) produce the content inline, so Node needs a single
    round-trip. Always degrades to a plain reply on any failure."""
    history = payload.get("history") or []
    message = (payload.get("message") or "").strip()
    vertical = payload.get("vertical") or ""
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
    ask = (
        "You are the router for a creative video Studio. Read the conversation and the NEW user message, "
        "then output ONE strict-JSON action. Prefer acting over asking — only ask when genuinely ambiguous.\n\n"
        f"CONVERSATION:\n{hist_text}\n\nNEW USER MESSAGE: \"{message}\"\n"
        f"DEFAULT VERTICAL: {vertical or 'general'}\n\n"
        "ACTIONS (pick exactly one; output JSON ONLY, no prose):\n"
        "1) write_script — user wants script(s)/variations/hooks for a video ad:\n"
        '   {"action":"write_script","vertical":"<vertical>","count":N,"scripts":[{"title":"...","text":"..."}]}\n'
        "   Each script.text = a complete spoken UGC ad script (the spoken lines only, no scene labels). Cap N at 5.\n"
        "2) write_ad_copy — user wants ad copy / primary text / captions:\n"
        '   {"action":"write_ad_copy","count":N,"ad_copies":[{"title":"...","text":"..."}]}  Cap N at 5.\n'
        "3) make_video — user wants to make/generate a video/creative/clip:\n"
        '   {"action":"make_video","source":"last_script|last_ad_copy|none","prompt":"...","seconds":15}\n'
        "   If the user references a prior script (e.g. \"make a video from that script\"), set source=\"last_script\" "
        "   and set prompt to that script's spoken content. Otherwise source=\"none\" and prompt is the video prompt.\n"
        "4) make_image — user wants a still image/poster/photo:\n"
        '   {"action":"make_image","prompt":"..."}\n'
        "5) reply — conversational, a question, or ambiguous:\n"
        '   {"action":"reply","text":"..."}\n'
    )
    try:
        out = await _gemini_json(ask)
        action = str(out.get("action") or "reply").lower()
        if action == "write_script":
            scripts = [s for s in (out.get("scripts") or []) if (s.get("text") or "").strip()][:5]
            if not scripts:
                return {"action": "reply", "text": "I couldn't draft that — name the product or vertical and I'll write the scripts."}
            return {"action": "write_script", "vertical": out.get("vertical") or vertical,
                    "count": len(scripts), "scripts": scripts}
        if action == "write_ad_copy":
            copies = [c for c in (out.get("ad_copies") or []) if (c.get("text") or "").strip()][:5]
            if not copies:
                return {"action": "reply", "text": "I couldn't draft that — tell me the product and I'll write the ad copy."}
            return {"action": "write_ad_copy", "count": len(copies), "ad_copies": copies}
        if action == "make_video":
            src = str(out.get("source") or "none").lower()
            if src not in ("last_script", "last_ad_copy", "none"):
                src = "none"
            return {"action": "make_video", "source": src,
                    "prompt": (out.get("prompt") or message).strip(), "seconds": int(out.get("seconds") or 15)}
        if action == "make_image":
            return {"action": "make_image", "prompt": (out.get("prompt") or message).strip()}
        return {"action": "reply", "text": (out.get("text") or "Tell me what you'd like to make.").strip()}
    except Exception as e:
        logger.warning(f"studio route failed: {e}")
        return {"action": "reply", "text": "I hit a snag routing that — could you rephrase?"}


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
    if not url:
        logger.warning("no callback_url; dropping result")
        return
    async with httpx.AsyncClient(timeout=30) as c:
        await c.post(url, json=payload, headers={"x-regen-secret": CALLBACK_SECRET})


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
        clip = None
        from ..services import winner_library
        _lw = winner_library.fetch_winners(req.context.get("vertical", ""), limit=1)

        # ── PRIMARY: winner-clone (conversion-first) ──────────────────────────
        if _lw:
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
        act.finish("critic", job_id, ts, ok=True, revised=(not ok),
                   detail=f"beat {beat.get('i')} scored {ev.get('overall')}/10",
                   helpfulness=float(ev.get("overall", 10)) / 10.0)
        if ok:
            for p in ("prompt", "character", "shots"):
                act.reward(p, job_id=job_id)
            return clip
        if attempts >= team.MAX_BEAT_RETRIES:
            break
        team.coach_from_eval(beat, ev, job_id=job_id)   # one-on-one + rewrite the beat prompt for the retry
        attempts += 1
    return clip                                  # bounded: return the last (best-effort) attempt


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
        plan = await team.run_creative_team(
            offer_desc=(hint or transcript[:300] or "the offer in this ad"),
            job_id=req.request_id, vertical=vertical,
            request_type=(req.variation_type or "ugc"), model=req.model or "seedance-2",
            loser_transcript=transcript, winner_hook=winner_hook,
            loser_metrics=(req.context.get("metrics") if isinstance(req.context, dict) else None),
            entity_desc=entity_desc,
            has_real_character=bool(anchor_url), has_winner_video=bool(lw),
            n_reference_images=1 if anchor_url else 0)
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
            has_real_character=False, has_winner_video=False, n_reference_images=1)
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
                model=i2v_model, action="the scene comes alive with subtle natural motion",
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


async def _generate_t2v_clip(*, prompt, image_urls, video_urls, audio_urls, seconds, resolution,
                             aspect_ratio, generate_audio, first, produced) -> Optional[str]:
    """Render ONE text-to-video clip, trying each configured provider in order. On a
    credits/quota/billing/5xx (or any) error from one provider, log the reason and advance to the
    next. Returns a local mp4 path (recording the winning provider in `produced['provider']`), or
    raises _AllVideoProvidersDown listing each provider's reason when every one is unavailable."""
    from ..services.kieai_service import KieAIService
    from ..services import fal_video as fv
    reasons = []
    for prov in _t2v_providers():
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
        if want_vert and (t.get("vertical") or "").lower() == want_vert:
            s += 1
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


async def _generate_library_fallback(req: "RunRequest", prompt: str, aspect_ratio: str,
                                      seconds: int, reasons: list) -> list:
    """Last-resort tiers when every paid text-to-video provider is out of credits/quota:
       (1) re-route into the AVATAR-LIPSYNC recipe on a cast library clip (lipsync + cheap TTS — no
           text-to-video credits), then
       (2) return the single best-match library clip as a curated suggestion.
    The user ALWAYS gets something usable — never a bare 'credits insufficient' error."""
    note = "Text-to-video providers unavailable (" + "; ".join(reasons[:3]) + ")."
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
                          "seconds": int(seconds),
                          "vertical": _vert}
            logger.warning(f"[generate] all t2v providers down — re-routing to avatar-lipsync on "
                           f"library clip {avatar_url}")
            out = await recipe_avatar_lipsync(req)
            for r in (out or []):
                r["recipe"] = "Generate — Library Avatar Lip-sync (t2v fallback)"
                r["whats_changed"] = ("Built from your library footage — " + note + " Cast a matching "
                    "avatar clip and lip-synced your script to it (no text-to-video credits used). "
                    + (r.get("whats_changed") or ""))[:600]
            if out:
                return out
        except Cancelled:
            raise
        except Exception as e:
            logger.error(f"[generate] avatar-lipsync fallback failed: {e}")
            reasons.append(f"avatar-lipsync: {str(e)[:120]}")

    # TIER 2 — curated best-match library clip (no generation at all)
    pick = avatar_url or any_url
    if pick:
        return [{"recipe": "Generate — Curated library match (providers unavailable)",
                 "video_url": pick, "confidence": 0.3,
                 "whats_changed": ("Closest match from your library — " + note + " Generation providers "
                    "are unavailable, so we surfaced your best existing clip instead of failing. "
                    "Top up Kie.ai or fal credits to generate net-new video.")[:600]}]

    # nothing at all — clean, actionable message (never a raw provider error)
    raise _AllVideoProvidersDown(
        "All video providers are unavailable and no library footage exists to fall back on. "
        + note + " Top up Kie.ai or fal credits, or add tagged library clips.")


async def recipe_generate(req: RunRequest) -> list:
    """DIRECT generation from a PROMPT + optional REFERENCE IMAGE(S), engine of the user's choice:
      • 'seedance' (Kie): reference-image-conditioned clip(s) — Seedance keeps subject/scene/voice
        consistent within a clip; stitched if a longer duration is asked.
      • 'veo-extend' (Google Veo 3.1): a base clip (from the image if given, else text) then NATIVE
        +7s extends for seamless longer video.
    Reads req.assets = {engine, prompt, image_urls[], seconds}."""
    assets = req.assets or req.directive.get("assets", {}) or {}
    engine = (assets.get("engine") or "seedance").lower()
    prompt = (assets.get("prompt") or "").strip()
    image_urls = [u for u in (assets.get("image_urls") or []) if u]
    video_urls = [u for u in (assets.get("video_urls") or []) if u]
    audio_urls = [u for u in (assets.get("audio_urls") or []) if u]
    aspect_ratio = assets.get("aspect_ratio") or "9:16"
    resolution = assets.get("resolution") or "720p"
    generate_audio = assets.get("generate_audio", True)
    seconds = int(assets.get("seconds") or (16 if engine == "veo-extend" else 15))
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

        # EVERYTHING goes through the creative office (nothing bypassed): the team refines the
        # prompt (anti-slop + no-on-screen-text) and the desks light up under this job_id.
        try:
            from ..services import creative_team as team
            vertical = req.context.get("vertical", "") if isinstance(req.context, dict) else ""
            plan = await team.run_creative_team(
                offer_desc=prompt, job_id=req.request_id, vertical=vertical,
                request_type=("broll" if (video_urls or image_urls) else "ugc"),
                model=engine, loser_transcript=prompt,
                loser_metrics=(req.context.get("metrics") if isinstance(req.context, dict) else None),
                has_winner_video=bool(video_urls), n_reference_images=len(image_urls),
                run_critic=True)
            refined = (plan.get("beats") or [{}])[0].get("prompt")
            if refined:
                prompt = f"{prompt}. {refined}"
            # AUTO: let the brain's Playbook route pick the engine (ChatGPT-style — user needn't choose)
            if engine in ("", "auto"):
                routed = ((plan.get("plan") or {}).get("route") or {}).get("engine") or "seedance"
                engine = "veo-extend" if routed == "veo_extend" else ("seedance" if routed in ("seedance", "avatar_lipsync", "image_to_video") else "seedance")
                logger.info(f"[generate] brain routed engine → {engine} (from {routed})")
        except Exception as e:
            logger.warning(f"generate: team pass skipped ({e})")
        prompt = (prompt + HOOK + NO_TEXT)[:1900]

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
        is_talk = bool(video_urls) or bool(re.search(r"\b(talk|say|speak|character|spokesperson|person|host|ugc)\b", prompt, re.I))
        clip_paths = []
        produced = {}                    # which t2v provider actually rendered (Kie / fal fallback)
        try:
          for ci in range(n_clips):
            await _abort_if_cancelled(req, f"seedance clip {ci+1}/{n_clips}")
            act.tick(req.request_id, f"Seedance clip {ci+1}/{n_clips} · {per}s · {aspect_ratio}")
            imgs = list(image_urls or [])
            cprompt = prompt
            if ci > 0 and clip_paths:
                _pd = await asyncio.to_thread(_ffprobe_duration, clip_paths[-1])
                cont = _frame_to_public_url(clip_paths[-1], max(0.5, (_pd or per) - 0.4))   # last frame → seamless continuation
                if cont:
                    imgs = [cont] + imgs
                cprompt = (prompt + " Continue seamlessly from the previous shot — same character, "
                           "wardrobe, setting and lighting; one continuous action, match-cut.")[:1900]
            # Route EACH clip through the vision eval loop: the Critic grades the rendered clip,
            # coaches the faulted persona + folds the fix into the prompt, and retries (bounded).
            beat = {"i": ci, "prompt": cprompt, "shot_type": ("talking_head" if is_talk else "broll"), "line": ""}

            # Provider fallback: Kie-Seedance → fal-seedance → fal-kling → fal-wan. A credits/quota/5xx
            # error on one advances to the next; _AllVideoProvidersDown only if every configured one is down.
            async def _attempt(bt, _imgs=imgs, _first=(ci == 0)):
                return await _generate_t2v_clip(
                    prompt=bt.get("prompt"),
                    image_urls=_imgs, video_urls=prepped_vids, audio_urls=audio_urls,
                    seconds=per, resolution=resolution, aspect_ratio=aspect_ratio,
                    generate_audio=generate_audio, first=_first, produced=produced)

            cp = await _gen_beat_with_eval(req.request_id, beat, work, _attempt)
            if cp and os.path.exists(cp):
                clip_paths.append(cp)
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
            # normalize every clip to uniform W:H:fps + aac, then concat (perfect frames + audio)
            norm = []
            for i, cp in enumerate(clip_paths):
                npath = os.path.join(work, f"sd{i}.mp4")
                await asyncio.to_thread(_ffmpeg,
                    ["-i", cp, "-vf", f"scale={W2}:{H2}:force_original_aspect_ratio=increase,crop={W2}:{H2},fps=30",
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
        _ae_persist(out_path, name)   # durable AE S3 copy (both buckets)
        # Cost = the rate of the provider that ACTUALLY produced the clip (not always Kie).
        _with_input = bool(video_urls or image_urls)
        _prov = produced.get("provider") or "kie-seedance"
        if str(_prov).startswith("fal"):
            # fal lanes bill a flat per-second rate per model (fal-seedance/kling/wan) — use fal's.
            from ..services.fal_video import FAL_VIDEO_COST_PER_SEC
            _persec = FAL_VIDEO_COST_PER_SEC.get(_prov, 0.09)
        else:
            # Kie Seedance — OFFICIAL per-second rates by resolution; with-input is cheaper.
            _KIE_RATE = {"480p": (0.0575, 0.095), "720p": (0.125, 0.205), "1080p": (0.31, 0.51), "4k": (0.64, 1.04)}
            _rr = _KIE_RATE.get(str(resolution).lower(), _KIE_RATE["720p"])
            _persec = _rr[0] if _with_input else _rr[1]
        _vid_sec = len(clip_paths) * per
        _track_cost(req.request_id, "video", _prov, model=f"seedance-{resolution}",
                    units=_vid_sec, unit_type="sec", cost_usd=round(_persec * _vid_sec, 4),
                    note=("with-input" if _with_input else "text→video")
                         + ("" if _prov == "kie-seedance" else f" · fallback provider {_prov}"))
        refs = []
        if image_urls: refs.append(f"{len(image_urls)} image(s)")
        if video_urls: refs.append(f"{len(video_urls)} video(s)")
        if audio_urls: refs.append(f"{len(audio_urls)} audio")
        _prov_note = "" if _prov == "kie-seedance" else f" · via {_prov} (fallback — Kie unavailable)"
        return [{"recipe": "Generate — Seedance 2.0", "video_url": url, "confidence": 0.75,
                 "whats_changed": (f"Seedance 2.0 · {len(clip_paths)}×{per}s (~{len(clip_paths)*per}s) · {aspect_ratio} · {resolution}"
                    f"{' · refs: ' + ', '.join(refs) if refs else ''}"
                    f"{' · audio' if generate_audio else ''}"
                    + (" · stitched with frame-continuity" if len(clip_paths) > 1 else "")
                    + _prov_note + ".")}]
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


async def _produce_lipsync_variant(request_id, out_name, result, script="", cap_words=None, vertical=None):
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
            ass_path = cap.build_ass(cap_words, os.path.join(UPLOAD_DIR, f"cap_{request_id[:8]}.ass"),
                                     play_w=w, play_h=h)
            logger.info(f"[captions] burning {len(cap_words)} words onto {w}x{h}")
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
            "caption_removal": removal_method}


async def _resume_one_lipsync(row):
    from ..services import lip_sync
    from ..services import creative_team_activity as act
    rid = row["id"]
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


async def recipe_avatar_lipsync(req: RunRequest) -> list:
    """The team's real CapCut flow, automated end-to-end: take a REAL character clip from
    our own asset library, write/adapt a natural spoken script (inserting the offer value),
    generate a matching voice (optionally CLONED from the character's own footage for max
    naturalness), then re-lipsync the footage to that voice with LatentSync. No synthetic
    avatar — it's our own person, so it never looks 'AIfied'."""
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
    brief = (a.get("brief") or req.expectation or "").strip()

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
    verbatim = bool(base) and _script_mode_pin == "verbatim"
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
    act.finish("scriptwriter", req.request_id, t0,
               detail=("used YOUR script verbatim · " if verbatim else "") + script[:160])
    _track_cost(req.request_id, "script", ("none" if verbatim else "gemini"),
                model=("user-supplied" if verbatim else "gemini-2.5-flash"),
                cost_usd=(0.0 if verbatim else 0.001),
                note=("user supplied the script — not rewritten" if verbatim else "strategist+critic"))

    await _abort_if_cancelled(req, "avatar-lipsync voice")

    # 2) VOICE — clone the character's own voice (most natural) else cast a catalog voice
    t1 = act.start("character", req.request_id, "casting the voice")
    sample_url = None
    if a.get("clone_voice"):
        try:
            raw = await _download_to_temp(char_url, ".mp4")
            wav = raw.rsplit(".", 1)[0] + ".wav"
            # F5-TTS wants a clean ~10-15s reference of the person actually speaking
            await asyncio.to_thread(_ffmpeg, ["-i", raw, "-vn", "-ac", "1", "-ar", "24000", "-t", "15", wav], 120)
            sample_url = StorageService.upload_file(wav, f"voice/sample_{req.request_id[:8]}.wav")
            # the clone model fetches this itself — our bucket is private, so presign it
            sample_url = StorageService.presign_url(sample_url) or sample_url
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
    # TELL the model who is speaking. Casting a "55plus" voice is not enough on its own — the
    # delivery has to be directed too, or a 70-year-old woman on screen is read by a bright
    # 30-something. Gemini/OpenAI both steer delivery from plain English.
    _style = ", ".join(x for x in [
        vs.age_style(a.get("age_band"), a.get("gender")),
        (a.get("tone") or "warm"),
        "conversational, talking to camera",
    ] if x)
    voice_res = await asyncio.to_thread(lambda: vs.synthesize(
        script, voice_id=("fal-clone:character" if sample_url else voice_id),
        sample_url=sample_url, out_path=out_audio, style=_style,
        fallback_voice_id=voice_id,
        # what the character actually SAYS in the reference clip — improves clone fidelity
        ref_text=(a.get("character_transcript") or None)))
    _track_cost(req.request_id, "voice", voice_res.get("provider") or "openai", model=str(voice_res.get("voice")),
                units=len(script), unit_type="chars", cost_usd=voice_res.get("cost_usd") or 0)
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
    from ..services import creative_qc as qc
    _qc = qc.verify_pre_lipsync(
        script=script, vo_seconds=vo_sec,
        voice_gender=_vmeta.get("gender"), voice_age=_vmeta.get("age_band"),
        char_gender=a.get("gender"), char_age=a.get("age_band"),
        offer_value=offer_value or None)
    if not _qc["ok"]:
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
    sub = await asyncio.to_thread(lambda: lip_sync.submit_relipsync(char_url, audio_url, prefer, quality=quality))
    _persist_lipsync(req.request_id, sub["provider"], sub["job"], audio_url, char_url, req.callback_url, name, script)
    result = None
    try:
        for _ in range(150):   # ~10 min; a restart mid-poll is recovered by resume_pending_lipsync()
            await asyncio.sleep(4)
            stt, res = await asyncio.to_thread(lambda: lip_sync.poll_relipsync(sub["provider"], sub["job"]))
            if stt == "done":
                result = res; break
    except Exception:
        _set_lipsync_status(req.request_id, "failed")
        raise
    if not result:
        raise RuntimeError(f"lip-sync via {sub['provider']} timed out")
    act.finish("shots", req.request_id, t2, detail=f"lip-sync via {sub['provider']}")
    _lip_cost = {"fal": round(seconds / 60 * 0.10, 4), "latentsync": 0.088, "wav2lip": 0.03}.get(sub["provider"], 0.0)
    _track_cost(req.request_id, "lipsync", sub["provider"], units=seconds, unit_type="sec",
                cost_usd=_lip_cost, note=("1 free sync.so credit" if sub["provider"] == "sync" else ""))

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
                                             vertical=(vertical or None))
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
    # auto-feedback statement for THIS generation (shown per video). Report what ACTUALLY happened —
    # a clone that fell back to a preset must not still claim "cloned from character".
    _cloned = voice_res.get("provider") in ("fal-clone", "chatterbox")
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
          + (f" · ⚠ captions failed: {_cap_err}" if _cap_err else ""))
    variant.update({"voice": voice_res.get("provider"), "voice_id": voice_id, "cloned": _cloned,
                    "voice_swapped": bool(_swapped), "voice_requested": voice_res.get("requested"),
                    "captions": bool(ass_path or _use_veed), "caption_method": _cap_method,
                    "whats_changed": fb, "feedback": fb})

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
    return [variant]


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
