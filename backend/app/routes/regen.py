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

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_MODEL = "gemini-2.5-flash"
CALLBACK_SECRET = os.getenv("REGEN_CALLBACK_SECRET", "change-me-regen-callback")
AE_PUBLIC_URL = os.getenv("AE_PUBLIC_URL", "https://affiliate-engine-pl4p.onrender.com")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── media helpers ─────────────────────────────────────────────────────────────
async def _download_to_temp(url: str, suffix: str = ".mp4") -> str:
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
        r = await c.get(url); r.raise_for_status(); data = r.content
    fd, path = tempfile.mkstemp(suffix=suffix); os.close(fd)
    with open(path, "wb") as f:
        f.write(data)
    return path

async def _transcribe_file(path: str) -> str:
    from ..services.transcription_service import TranscriptionService
    res = await TranscriptionService().transcribe_audio(path, provider="openai")
    return (res or {}).get("transcription") or (res or {}).get("text") or ""

def _ffprobe_dims(path: str):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
        capture_output=True, text=True, timeout=60).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)

def _ffmpeg(args, timeout: int = 600):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                   check=True, timeout=timeout,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
        recipe = _RECIPES.get(vtype, recipe_special)
        variants = await recipe(req)
        await _callback(req.callback_url, {"request_id": req.request_id, "status": "ready", "variants": variants})
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
    import tempfile
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as c:
        r = await c.get(download_url)
        r.raise_for_status()
        data = r.content
    fd, path = tempfile.mkstemp(suffix=".mp4"); os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(data)
        from ..services.transcription_service import TranscriptionService
        res = await TranscriptionService().transcribe_audio(path, provider="openai")
        return (res or {}).get("transcription") or (res or {}).get("text") or ""
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
    return [{
        "recipe": "Avatar/UGC (TikTok Symphony)",
        "video_url": url,
        "confidence": 0.6,
        "whats_changed": f"Net-new avatar ad. Script: {script[:140]}",
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


async def recipe_hook_change(req: RunRequest) -> list:
    """SURGICAL fix: keep the original's full voiceover + entire body, replace ONLY
    the first ~3.5s hook VISUAL with a topic-matched clip. Preserves script, voice,
    story, and all body footage — only the opening visual changes."""
    HOOK = 3.5
    FPS = 30
    download_url = req.context.get("download_url", "")
    if not download_url:
        raise RuntimeError("no original download_url in context")

    orig = await _download_to_temp(download_url)
    try:
        W, H = _ffprobe_dims(orig)
        transcript = await _transcribe_file(orig)

        # derive a topic-grounded stock-footage query from the ORIGINAL's content
        query = "broadcast news"
        try:
            d = await _gemini_json(
                f'From this ad transcript, give a 2-4 word stock-footage search query for a '
                f'relevant OPENING hook visual matching the topic. Transcript: "{transcript[:1200]}". '
                f'Return JSON {{"query":"..."}}')
            query = d.get("query") or query
        except Exception as e:
            logger.warning(f"hook query gen failed: {e}")

        orient = "portrait" if H >= W else "landscape"
        clip = StockFootageService.get_broll(query, orientation=orient, duration_max=10)
        if not clip or not clip.get("local_path"):
            raise RuntimeError(f"no stock footage found for hook query '{query}' — refusing to ship unrelated content")
        stock = clip["local_path"]

        out_name = f"regen_hook_{req.request_id[:8]}.mp4"
        out_path = os.path.join(UPLOAD_DIR, out_name)
        fc = (
            f"[0:v]trim=0:{HOOK},setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},fps={FPS}[hv];"
            f"[1:a]atrim=0:{HOOK},asetpts=PTS-STARTPTS[ha];"
            f"[1:v]trim={HOOK},setpts=PTS-STARTPTS,scale={W}:{H},fps={FPS}[bv];"
            f"[1:a]atrim={HOOK},asetpts=PTS-STARTPTS[ba];"
            f"[hv][ha][bv][ba]concat=n=2:v=1:a=1[outv][outa]"
        )
        _ffmpeg(["-i", stock, "-i", orig, "-filter_complex", fc,
                 "-map", "[outv]", "-map", "[outa]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k", out_path])

        return [{
            "recipe": "Hook Change Only (surgical)",
            "video_url": f"{AE_PUBLIC_URL}/api/v1/uploads/{out_name}",
            "confidence": 0.7,
            "whats_changed": (
                f"Replaced ONLY the first {HOOK}s hook visual with topic-matched stock "
                f"('{query}'); kept the original voiceover + entire body. Script, voice and story preserved."
            ),
        }]
    finally:
        try: os.remove(orig)
        except OSError: pass


async def recipe_passthrough(req: RunRequest, label: str) -> list:
    return [{
        "recipe": label,
        "video_url": None,
        "confidence": 0.5,
        "whats_changed": f"{label} directive prepared: {json.dumps(req.directive)[:200]}",
    }]


async def recipe_special(req: RunRequest) -> list:
    """Special Request / unmapped: surface the interpreter's clarifications."""
    clar = req.directive.get("conflicts_or_clarifications") or []
    return [{
        "recipe": "Special Request",
        "video_url": None,
        "confidence": 0.4,
        "whats_changed": ("Needs clarification: " + "; ".join(clar)) if clar
                         else f"Custom recipe: {req.directive.get('recipe_steps')}",
    }]


_RECIPES = {
    "Avatar/UGC": recipe_avatar,
    "map + ugc": recipe_avatar,
    "Hook Change Only": recipe_hook_change,
    "Caption Change Only": lambda r: recipe_passthrough(r, "Caption Change Only"),
    "Reclean/Minor Mod": lambda r: recipe_passthrough(r, "Reclean/Minor Mod"),
    "Script": lambda r: recipe_passthrough(r, "Script"),
    "Broll": lambda r: recipe_passthrough(r, "Broll"),
    "Stock Video": lambda r: recipe_passthrough(r, "Stock Video"),
    "Image": lambda r: recipe_passthrough(r, "Image"),
    "Image + Voiceover": lambda r: recipe_passthrough(r, "Image + Voiceover"),
    "Special Request": recipe_special,
}
