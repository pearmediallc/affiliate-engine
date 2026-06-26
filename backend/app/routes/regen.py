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
import json
import base64
import logging
import asyncio
import tempfile
import subprocess
from typing import Optional, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Depends
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


async def _generate_clip(offer_desc: str, shot_type: str = "b_roll", duration: int = 6) -> Optional[str]:
    """Generate an ON-OFFER clip with the engine's generative stack (Veo 3.1 / Higgsfield /
    Runway Gen-4). Used when no relevant winner or stock footage exists — so we GENERATE
    on-brand footage instead of failing or shipping junk. Returns a local mp4 path or None.
    Costs real generation credits (intentional)."""
    _generate_clip.last_error = ""
    # turn the offer into a concrete, text-free, photorealistic scene prompt
    try:
        d = await _gemini_json(
            f'Write ONE vivid text-to-video prompt (a single sentence) for an on-brand opening '
            f'B-roll shot for this ad offer: "{offer_desc[:300]}". Concrete real-world scene with '
            f'subtle camera motion; NO on-screen text, NO captions, photorealistic, vertical 9:16. '
            f'Return JSON {{"prompt":"..."}}')
        prompt = (d.get("prompt") or offer_desc)[:500]
    except Exception:
        prompt = offer_desc[:500]
    try:
        # pin Higgsfield (where the user keeps generation credits); falls back to the
        # routing table if Higgsfield keys aren't configured.
        result = await asyncio.to_thread(
            MultiProviderVideoService.generate,
            prompt=prompt, shot_type=shot_type, duration=duration,
            preferred_model="higgsfield-v1", s3_prefix="regen")
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
    "Broll", "Stock Video", "Avatar/UGC", "map + ugc", "Image",
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
    callback_url: Optional[str] = None
    active_url: Optional[str] = None


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


async def _gemini_json(prompt: str) -> dict:
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


async def _execute(req: RunRequest):
    """Pick recipe by variation_type → produce variants → POST back to callback."""
    vtype = (req.variation_type or req.directive.get("chosen_variation_type") or "Hook Change Only")
    try:
        await _abort_if_cancelled(req, "start")
        recipe = _RECIPES.get(vtype, recipe_special)
        variants = await recipe(req)
        await _callback(req.callback_url, {"request_id": req.request_id, "status": "ready", "variants": variants})
    except Cancelled as c:
        logger.info(f"regen run cancelled for {req.request_id}: {c}")
        await _callback(req.callback_url, {"request_id": req.request_id, "status": "cancelled", "error": str(c), "variants": []})
    except Exception as e:
        logger.exception(f"regen run failed for {req.request_id}")
        await _callback(req.callback_url, {"request_id": req.request_id, "status": "failed", "error": str(e), "variants": []})


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
    # 2) an explicit rewrite directive may refine it; otherwise keep the original message
    directive_script = req.directive.get("script_directive")
    if directive_script and directive_script != "none":
        script = directive_script
    elif original_script:
        script = original_script
    else:
        # do NOT invent unrelated content — fail loudly so the UI surfaces it
        raise RuntimeError("could not transcribe the original and no script directive given — refusing to generate unrelated content")

    avatar_id = await _pick_avatar(age="elderly", gender="female", region="namer")
    if not avatar_id:
        raise RuntimeError("no matching avatar found")

    # last credit-safety gate before the paid TikTok render
    await _abort_if_cancelled(req, "avatar generation")

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

    # Remove the TikTok "AI-generated" watermark (bottom strip) so the clip is ad-usable:
    # crop the bottom ~8% and scale back to the original frame size, then serve from our host.
    final_url = url
    try:
        raw = await _download_to_temp(url)
        try:
            W, H = await asyncio.to_thread(_ffprobe_dims, raw)
            keep_h = (int(H * 0.92) // 2) * 2  # even height for yuv420p
            name, out_path, out_url = _out_url(req, "avatar")
            await asyncio.to_thread(_ffmpeg,
                ["-i", raw, "-vf", f"crop={W}:{keep_h}:0:0,scale={W}:{H}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                 "-threads", "2", "-c:a", "aac", "-b:a", "192k", out_path], timeout=300)
            final_url = out_url
        finally:
            try: os.remove(raw)
            except OSError: pass
    except Exception as e:
        logger.warning(f"avatar watermark crop failed, serving raw: {e}")

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

        # else: format-matched PROVEN WINNER — must be ON-OFFER and reasonably caption-clean
        # (reject loose-keyword mismatches AND winners too text-heavy to mask without smear).
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
            if _boxes_area(boxes) > 0.16:   # too much burned text → masking would smear
                logger.info("skipping winner: too caption-heavy to mask cleanly")
                continue
            src_path, src_label, is_winner, cover_boxes = cand, \
                f"your winner '{(wh.get('filename') or '')[:30]}' (roas {wh.get('roas')})", True, boxes
            break

        # else: stock footage — also gated on relevance
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
            gen = await _generate_clip(offer_desc, shot_type="b_roll", duration=max(4, int(hook_end) + 1))
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
        voice_id = await asyncio.to_thread(ElevenLabsService.clone_voice, sample, f"regen-{req.request_id[:8]}")
        vo = os.path.join(work, "vo.mp3")
        await asyncio.to_thread(ElevenLabsService.tts, voice_id, new_script, vo)

        name, out_path, url = _out_url(req, "script")
        # lay the new VO over the original visuals; length = the new VO
        await asyncio.to_thread(_ffmpeg,
            ["-i", orig, "-i", vo, "-map", "0:v:0", "-map", "1:a:0", "-shortest",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-threads", "2", "-c:a", "aac", "-b:a", "192k", out_path], timeout=900)
        return [{"recipe": "Script (rewrite, cloned voice)", "video_url": url, "confidence": 0.65,
                 "whats_changed": "Rewrote the script + re-voiced it in the spokesperson's cloned voice over the original visuals."}]
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
        d = await _gemini_json(f'From this transcript give 3 stock search terms + one 5-word caption. '
                               f'Transcript:"{transcript[:900]}". Return JSON {{"queries":[".."],"caption":".."}}')
        queries = (d.get("queries") or []) + ["lifestyle", "city"]
        caption = (d.get("caption") or " ".join(transcript.split()[:6]) or "WATCH THIS")
        offer_desc = (caption + " — " + transcript[:220]).strip()
        # force_generate skips stock and goes straight to AI generation (Higgsfield/Veo)
        force_gen = bool((req.directive or {}).get("force_generate"))
        clip = None
        if not force_gen:
            for q in queries:
                c = await asyncio.to_thread(StockFootageService.get_broll, q, ("portrait" if H >= W else "landscape"), 30)
                if not (c and c.get("local_path")):
                    continue
                sframes = await asyncio.to_thread(_extract_frames, c["local_path"], [0.5, 1.5], work)
                if not await _asset_is_relevant(sframes, offer_desc):   # reject off-offer stock
                    continue
                clip = c; break
        # else: GENERATE an on-offer b-roll clip (Veo / Higgsfield / Runway)
        if not clip:
            gen = await _generate_clip(offer_desc, shot_type="b_roll", duration=5)
            if gen:
                clip = {"local_path": gen, "id": "ai-generated (Veo/Higgsfield)"}
        if not clip:
            raise RuntimeError("no on-offer footage; generation failed: "
                               + (getattr(_generate_clip, "last_error", "") or "no provider configured (set HIGGSFIELD_API_KEY[:secret] on the engine)"))
        cap_png = os.path.join(work, "cap.png")
        await asyncio.to_thread(_make_caption_png, caption, W, H, cap_png)
        name, out_path, url = _out_url(req, "broll")
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


_RECIPES = {
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
