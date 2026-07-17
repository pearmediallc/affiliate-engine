"""
Voice Studio — one voice layer that gives the team MORE options than ElevenLabs,
cheapest-first with automatic fallback, all on creds we ALREADY have.

This replaces the manual "open ElevenLabs → pick a voice → generate → CapCut" loop:
the team (or the brain) picks a voice from a big catalog, we synthesize the timed
script, and the avatar's own footage is re-lipsynced (LatentSync) to the new voice.

Providers, in cost order (fallback chain flows down this list):
  kokoro     — Replicate (jaaari/kokoro-82m), ~50 preset voices, ~$0.0003/run   (cheapest)
  openai     — tts-1-hd, 6 steerable voices                                     (already wired)
  deepgram   — Aura-2, natural US-English voices                                (already wired)
  chatterbox — Replicate (resemble-ai/chatterbox), clone ANY voice from ~10s    (unlimited custom)
  elevenlabs — premium                                                          (LAST RESORT only)

Public API:
  list_voices()                                   -> [{id,name,provider,gender,age_band,style,cloned}]
  pick_voice(gender=, age_band=, style=)          -> voice dict   (brain casting; gender is a HARD filter, unknown gender raises UnknownGenderError)
  synthesize(text, voice_id=, out_path=, style=)  -> {path, provider, voice, cost_usd}
  clone_voice(sample_url, name)                   -> {voice_id, provider}   (chatterbox; 11labs fallback)
"""
import logging
import os
import subprocess
import uuid
import base64
import time
from typing import Optional

import requests

from ..config import settings
from .pricing import Pricing

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Default fallback order — keep it OFF Replicate (openai/deepgram/elevenlabs are plain HTTP);
# Kokoro (Replicate) is last so the Replicate rate-limit/credit is reserved for lip-sync.
FALLBACK_ORDER = ["openai", "gemini", "deepgram", "elevenlabs", "kokoro"]

# ── Curated preset catalog (casting-tagged so the brain can pick the right voice) ──
# age_band ∈ {under35,35-44,45-55,55plus}; gender ∈ {female,male}
VOICE_CATALOG = [
    # Kokoro (Replicate) — cheapest, natural, our default pool
    {"id": "kokoro:af_bella",   "name": "Bella",   "provider": "kokoro", "gender": "female", "age_band": "35-44", "style": "warm, friendly"},
    {"id": "kokoro:af_sarah",   "name": "Sarah",   "provider": "kokoro", "gender": "female", "age_band": "45-55", "style": "mature, trustworthy"},
    {"id": "kokoro:af_nicole",  "name": "Nicole",  "provider": "kokoro", "gender": "female", "age_band": "35-44", "style": "soft, calm"},
    {"id": "kokoro:af_sky",     "name": "Sky",     "provider": "kokoro", "gender": "female", "age_band": "under35", "style": "bright, upbeat"},
    {"id": "kokoro:am_adam",    "name": "Adam",    "provider": "kokoro", "gender": "male",   "age_band": "35-44", "style": "confident, clear"},
    {"id": "kokoro:am_michael", "name": "Michael", "provider": "kokoro", "gender": "male",   "age_band": "45-55", "style": "mature, authoritative"},
    {"id": "kokoro:bf_emma",    "name": "Emma",    "provider": "kokoro", "gender": "female", "age_band": "45-55", "style": "mature British, composed"},
    # OpenAI — steerable
    {"id": "openai:nova",    "name": "Nova",    "provider": "openai", "gender": "female", "age_band": "35-44", "style": "confident, bold"},
    {"id": "openai:shimmer", "name": "Shimmer", "provider": "openai", "gender": "female", "age_band": "under35", "style": "bright, cheerful"},
    # Alloy reads androgynous — selectable by hand, but NEVER auto-cast (it lands as "male" on a woman)
    {"id": "openai:alloy",   "name": "Alloy",   "provider": "openai", "gender": "female", "age_band": "45-55", "style": "calm, neutral", "auto_cast": False},
    {"id": "openai:fable",   "name": "Fable",   "provider": "openai", "gender": "female", "age_band": "35-44", "style": "expressive, storytelling"},
    {"id": "openai:onyx",    "name": "Onyx",    "provider": "openai", "gender": "male",   "age_band": "45-55", "style": "deep, authoritative"},
    {"id": "openai:echo",    "name": "Echo",    "provider": "openai", "gender": "male",   "age_band": "35-44", "style": "clear, informative"},
    # Deepgram Aura-2 — very natural US English
    {"id": "deepgram:aura-2-hera-en",    "name": "Hera",    "provider": "deepgram", "gender": "female", "age_band": "45-55", "style": "mature, grounded"},
    {"id": "deepgram:aura-2-luna-en",    "name": "Luna",    "provider": "deepgram", "gender": "female", "age_band": "under35", "style": "friendly, casual"},
    {"id": "deepgram:aura-2-asteria-en", "name": "Asteria", "provider": "deepgram", "gender": "female", "age_band": "35-44", "style": "clear, upbeat"},
    {"id": "deepgram:aura-2-orion-en",   "name": "Orion",   "provider": "deepgram", "gender": "male",   "age_band": "45-55", "style": "warm, mature"},
    {"id": "deepgram:aura-2-arcas-en",   "name": "Arcas",   "provider": "deepgram", "gender": "male",   "age_band": "35-44", "style": "natural, conversational"},
    # Gemini TTS — prebuilt voices, delivery steerable in plain English (no cloning)
    {"id": "gemini:Kore",       "name": "Kore",       "provider": "gemini", "gender": "female", "age_band": "35-44", "style": "firm, confident"},
    {"id": "gemini:Aoede",      "name": "Aoede",      "provider": "gemini", "gender": "female", "age_band": "under35", "style": "breezy, natural"},
    {"id": "gemini:Leda",       "name": "Leda",       "provider": "gemini", "gender": "female", "age_band": "under35", "style": "youthful, bright"},
    {"id": "gemini:Gacrux",     "name": "Gacrux",     "provider": "gemini", "gender": "female", "age_band": "45-55", "style": "mature, warm"},
    {"id": "gemini:Vindemiatrix","name": "Vindemiatrix","provider": "gemini","gender": "female", "age_band": "45-55", "style": "gentle, reassuring"},
    {"id": "gemini:Charon",     "name": "Charon",     "provider": "gemini", "gender": "male",   "age_band": "45-55", "style": "informative, steady"},
    {"id": "gemini:Puck",       "name": "Puck",       "provider": "gemini", "gender": "male",   "age_band": "35-44", "style": "upbeat, engaging"},
    {"id": "gemini:Orus",       "name": "Orus",       "provider": "gemini", "gender": "male",   "age_band": "45-55", "style": "firm, authoritative"},
    # 55plus — there were NO elderly voices at all, so an "OLD LADY" clip could never be cast and
    # fell through to a bright 35-44 voice. Gemini takes the delivery direction in plain English,
    # so an elder read is steered at synth time (see _age_style).
    {"id": "gemini:Sulafat",    "name": "Sulafat",    "provider": "gemini", "gender": "female", "age_band": "55plus", "style": "elderly, gentle, unhurried"},
    {"id": "gemini:Achernar",   "name": "Achernar",   "provider": "gemini", "gender": "female", "age_band": "55plus", "style": "elderly, soft, grandmotherly"},
    {"id": "gemini:Iapetus",    "name": "Iapetus",    "provider": "gemini", "gender": "male",   "age_band": "55plus", "style": "elderly, weathered, calm"},
    {"id": "gemini:Rasalgethi", "name": "Rasalgethi", "provider": "gemini", "gender": "male",   "age_band": "55plus", "style": "elderly, measured, warm"},
    # ElevenLabs voices are NOT hardcoded — see _eleven_voices(). Hardcoding public Voice-Library
    # ids is what caused the 402s: "Free users cannot use library voices via the API". We now ask
    # the account which voices it can actually use.
]


# ── ElevenLabs: ask the ACCOUNT what it can actually use (never assume) ───────────────
_ELEVEN_CACHE: dict = {"at": 0.0, "voices": []}
_ELEVEN_TTL = 600.0


def _eleven_voices() -> list:
    """The voices THIS ElevenLabs account can actually synthesize with.

    Free tier cannot call public Voice-Library voices via the API (402 Payment Required) — so a
    hardcoded id list is worse than useless, it silently swaps the user's voice. GET /v1/voices
    returns exactly what the key is entitled to; we offer only those."""
    if not settings.elevenlabs_api_key:
        return []
    now = time.time()
    if _ELEVEN_CACHE["voices"] and now - _ELEVEN_CACHE["at"] < _ELEVEN_TTL:
        return _ELEVEN_CACHE["voices"]
    out = []
    try:
        r = requests.get("https://api.elevenlabs.io/v1/voices",
                         headers={"xi-api-key": settings.elevenlabs_api_key}, timeout=30)
        if r.status_code == 200:
            for v in (r.json() or {}).get("voices", []):
                vid, name = v.get("voice_id"), v.get("name")
                if not vid or not name:
                    continue
                labels = v.get("labels") or {}
                g = (labels.get("gender") or "").lower()
                age = (labels.get("age") or "").lower()
                band = ("under35" if "young" in age else
                        "55plus" if "old" in age else
                        "45-55" if "middle" in age else "35-44")
                out.append({"id": f"elevenlabs:{vid}", "name": name, "provider": "elevenlabs",
                            "gender": "male" if g.startswith("m") else "female",
                            "age_band": band,
                            "style": (labels.get("description") or labels.get("use_case") or "natural")})
            logger.info(f"elevenlabs: {len(out)} voices available to this account")
        else:
            logger.warning(f"elevenlabs /voices {r.status_code}: {r.text[:160]} — disabling ElevenLabs voices")
    except Exception as e:
        logger.warning(f"elevenlabs voice list failed: {e}")
    _ELEVEN_CACHE.update({"at": now, "voices": out})
    return out

# ElevenLabs default public voice ids (used only when 11labs is the chosen/last provider)
_ELEVEN_DEFAULTS = {"female": "21m00Tcm4TlvDq8ikWAM", "male": "TxGEqnHWrfWFTfGW9XjX"}


def available_providers() -> set:
    """Voice providers we can ACTUALLY synthesize with — so we never offer (or auto-cast) a voice
    that will fail. Kokoro/Chatterbox run on Replicate: a token alone isn't enough, the account has
    to be funded (REPLICATE_ENABLED), or every call 402s and we silently swap the user's voice."""
    p = set()
    if settings.openai_api_key:     p.add("openai")
    if settings.gemini_api_key:     p.add("gemini")
    if settings.deepgram_api_key:   p.add("deepgram")
    if settings.elevenlabs_api_key and _eleven_voices(): p.add("elevenlabs")
    if settings.fal_key or settings.fal_api_key: p.add("fal-clone")   # F5-TTS zero-shot cloning
    if settings.replicate_usable:   p.add("kokoro")
    if settings.chatterbox_api_url or settings.replicate_usable: p.add("chatterbox")
    return p


def clone_available() -> bool:
    """Can we actually clone the character's voice? fal (F5-TTS) does this on the key we already
    have — so cloning does NOT require Replicate. sync.so can't clone at all; it's lip-sync only."""
    return bool(settings.fal_key or settings.fal_api_key
                or settings.chatterbox_api_url or settings.replicate_usable)


def _by_id(voice_id: str) -> Optional[dict]:
    for v in VOICE_CATALOG + _eleven_voices():
        if v["id"] == voice_id:
            return v
    return None


def list_voices(cloned: Optional[list] = None, only_available: bool = False) -> list:
    """Full pickable catalog: presets + any cloned voices passed in (from DB).
    only_available=True hides voices whose provider key isn't configured (so the picker
    never offers a voice that would silently fall back to a different one)."""
    avail = available_providers() if only_available else None
    pool = VOICE_CATALOG + _eleven_voices()     # ElevenLabs comes from the account, not a hardcoded list
    out = [{**v, "cloned": False} for v in pool
           if not avail or v.get("provider") in avail]
    for c in (cloned or []):
        out.append({"id": c.get("id") or f"chatterbox:{c.get('voice_id')}", "name": c.get("name", "Cloned"),
                    "provider": c.get("provider", "chatterbox"), "gender": c.get("gender"),
                    "age_band": c.get("age_band"), "style": c.get("style", "cloned voice"),
                    "cloned": True, "sample_url": c.get("sample_url")})
    return out


def age_style(age_band: str | None, gender: str | None = None) -> str:
    """Delivery direction for the age we're casting. A voice model can only sound 70 if we ASK
    it to — Gemini/OpenAI steer delivery from plain English, so we always tell them who's talking."""
    who = "woman" if (gender or "female") == "female" else "man"
    return {
        "55plus":  f"an elderly {who} in her seventies, warm and unhurried, softer and a little frail"
                   if who == "woman" else
                   f"an elderly man in his seventies, warm and unhurried, weathered",
        "45-55":   f"a mature {who} in her fifties, grounded and trustworthy"
                   if who == "woman" else f"a mature man in his fifties, grounded and trustworthy",
        "35-44":   f"a {who} in her late thirties, natural and conversational"
                   if who == "woman" else f"a man in his late thirties, natural and conversational",
        "under35": f"a young {who} in her late twenties, casual and upbeat"
                   if who == "woman" else f"a young man in his late twenties, casual and upbeat",
    }.get(age_band or "", f"a {who} speaking naturally to camera")


class UnknownGenderError(ValueError):
    """pick_voice was asked to cast without a known character gender. We refuse to guess — a man
    must never receive a woman's voice — so the caller must fail the voice cast CLOSED (surface
    "character gender unknown — voice not cast") rather than ship a guessed voice. It subclasses
    ValueError so a plain `except ValueError` still catches it."""
    pass


def pick_voice(*, gender: Optional[str] = None, age_band: Optional[str] = None,
               style: Optional[str] = None, cloned: Optional[list] = None,
               tone: Optional[str] = None, roi_scores: Optional[dict] = None) -> dict:
    """Brain casting: best catalog match among voices we can ACTUALLY synthesize.
    Gender is a HARD filter — only voices of the character's gender are eligible; there is NO
    default gender, an unknown gender raises UnknownGenderError so the pipeline fails closed
    instead of guessing. `tone` is the script's register (e.g. "serious, informational" /
    "upbeat") so the voice matches the writing."""
    g = (gender or "").strip().lower()
    if g not in ("male", "female"):
        # NEVER guess gender — a wrong guess ships a man with a woman's voice. Fail closed and let
        # the caller abort the voice cast with a clear reason.
        raise UnknownGenderError(
            f"character gender unknown — voice not cast (got {gender!r}; expected 'male' or 'female')")
    age_band = age_band or "45-55"
    # HARD gender filter: only voices of THIS gender are eligible — the other gender is excluded
    # entirely (never a soft weight), and we never auto-cast an androgynous voice.
    pool = [v for v in list_voices(cloned, only_available=True)
            if v.get("auto_cast") is not False and (v.get("gender") or "").lower() == g]
    if not pool:
        # this gender has NO eligible voice in ANY configured provider — surface it clearly;
        # do NOT fall back to the other gender.
        raise ValueError(f"no {g} voice available in any configured provider")
    want = " ".join(x for x in [style, tone] if x).lower()
    scored = []
    for v in pool:
        s = 0
        # gender already guaranteed to match (hard-filtered above) — rank within by age/tone/roi
        if v.get("age_band") == age_band: s += 3
        vstyle = (v.get("style") or "").lower()
        if want and vstyle:                            # tone/style overlap on any word
            s += 2 * sum(1 for w in set(want.replace(",", " ").split()) if len(w) > 3 and w in vstyle)
        if v.get("provider") in ("elevenlabs", "openai", "deepgram"): s += 1   # avoid Replicate for auto-cast
        if v.get("cloned"): s += 2                     # prefer our own cloned voices when present
        # LEARNED bias: a voice that has earned ROI gets up to +2. Bounded so it TIE-BREAKS among
        # age-correct voices of the SAME gender. Zero at cold start.
        s += 2 * float((roi_scores or {}).get(v.get("id"), 0) or 0)
        scored.append((s, v))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


# ── Gemini TTS (prebuilt voices + natural-language style steering) ────────────
# Gemini has NO voice cloning (Google's cloning is Chirp 3, sales-gated). What it does give us is
# a cheap, very natural preset lane whose delivery we can steer in plain English — which pairs
# with the tone the brain already infers from the script.
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")


def _syn_gemini(text: str, voice: str, out_path: str, style: Optional[str] = None) -> dict:
    key = settings.gemini_api_key
    if not key:
        raise RuntimeError("no gemini key")
    # Gemini TTS takes the delivery direction inline, as prose.
    prompt = f"Say this in a {style} tone, like a real person talking to camera: {text}" if style else text
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TTS_MODEL}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseModalities": ["AUDIO"],
                                   "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}},
        timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"gemini tts {r.status_code}: {r.text[:200]}")
    parts = (((r.json() or {}).get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    b64 = next((p["inlineData"]["data"] for p in parts if p.get("inlineData", {}).get("data")), None)
    if not b64:
        raise RuntimeError("gemini tts returned no audio")
    # it hands back raw PCM (s16le, 24k, mono) — wrap it into the mp3 the pipeline expects
    raw = out_path + ".pcm"
    with open(raw, "wb") as f:
        f.write(base64.b64decode(b64))
    subprocess.run(["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", raw, out_path],
                   capture_output=True, timeout=120, check=True)
    try:
        os.remove(raw)
    except OSError:
        pass
    return {"provider": "gemini", "voice": voice, "cost_usd": 0.002}


# ── fal voice CLONE (F5-TTS) ──────────────────────────────────────────────────
# Zero-shot voice cloning from the character's OWN footage: give it a reference clip + our
# script, it speaks the script in that person's voice. Runs on the FAL key we already pay for —
# no Replicate, no Chatterbox host. sync.so cannot do this (it is lip-sync only).
FAL_CLONE_MODEL = os.getenv("FAL_CLONE_MODEL", "fal-ai/f5-tts")


def _syn_fal_clone(text: str, out_path: str, sample_url: str, ref_text: Optional[str] = None) -> dict:
    key = settings.fal_key or settings.fal_api_key
    if not key:
        raise RuntimeError("no fal key")
    if not sample_url:
        raise RuntimeError("fal clone needs a reference audio sample")
    payload = {"gen_text": text[:5000], "ref_audio_url": sample_url,
               "model_type": "F5-TTS", "remove_silence": True}
    if ref_text:
        payload["ref_text"] = ref_text[:2000]   # else fal ASRs the reference itself
    r = requests.post(f"https://fal.run/{FAL_CLONE_MODEL}",
                      headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
                      json=payload, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"fal clone {r.status_code}: {r.text[:200]}")
    url = ((r.json() or {}).get("audio_url") or {}).get("url")
    if not url:
        raise RuntimeError("fal clone returned no audio")
    _dl(url, out_path)
    return {"provider": "fal-clone", "voice": "cloned from character", "cost_usd": 0.02}


# ── Replicate helper (synchronous via Prefer: wait) ───────────────────────────
def _replicate_run(owner: str, name: str, payload: dict, timeout: int = 120) -> Optional[str]:
    token = settings.replicate_api_token
    if not token:
        raise RuntimeError("no replicate token")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "wait"}
    r = requests.post(f"https://api.replicate.com/v1/models/{owner}/{name}/predictions",
                      headers=headers, json={"input": payload}, timeout=timeout)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"replicate {name} error {r.status_code}: {r.text[:200]}")
    data = r.json()
    # if Prefer:wait didn't finish, poll briefly
    for _ in range(30):
        status = data.get("status")
        if status == "succeeded":
            out = data.get("output")
            return out if isinstance(out, str) else (out[0] if isinstance(out, list) and out else None)
        if status in ("failed", "canceled"):
            raise RuntimeError(f"replicate {name} {status}: {data.get('error')}")
        time.sleep(2)
        pr = requests.get(data.get("urls", {}).get("get", ""), headers={"Authorization": f"Bearer {token}"}, timeout=30)
        data = pr.json()
    raise RuntimeError(f"replicate {name} timed out")


def _dl(url: str, out_path: str) -> str:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)
    return out_path


# ── Per-provider synthesis (each writes mp3/wav to out_path) ───────────────────
def _syn_kokoro(text: str, voice: str, out_path: str) -> dict:
    url = _replicate_run("jaaari", "kokoro-82m", {"text": text, "voice": voice, "speed": 1.0})
    if not url:
        raise RuntimeError("kokoro no output")
    _dl(url, out_path)
    return {"provider": "kokoro", "voice": voice, "cost_usd": 0.0004}


def _syn_openai(text: str, voice: str, out_path: str, style: Optional[str] = None) -> dict:
    if not settings.openai_api_key:
        raise RuntimeError("no openai key")
    payload = {"model": "gpt-4o-mini-tts", "input": text, "voice": voice, "response_format": "mp3"}
    if style:
        payload["instructions"] = f"Speak in a {style} tone, natural and human, like a real person in a casual selfie video."
    r = requests.post("https://api.openai.com/v1/audio/speech",
                      headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
                      json=payload, timeout=120)
    if r.status_code != 200:
        # gpt-4o-mini-tts may be unavailable on some keys → fall back to tts-1-hd
        payload["model"] = "tts-1-hd"; payload.pop("instructions", None)
        r = requests.post("https://api.openai.com/v1/audio/speech",
                          headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
                          json=payload, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"openai tts {r.status_code}: {r.text[:160]}")
    with open(out_path, "wb") as f:
        f.write(r.content)
    return {"provider": "openai", "voice": voice, "cost_usd": Pricing.tts(len(text), payload["model"])}


def _syn_deepgram(text: str, model: str, out_path: str) -> dict:
    if not settings.deepgram_api_key:
        raise RuntimeError("no deepgram key")
    r = requests.post(f"https://api.deepgram.com/v1/speak?model={model}",
                      headers={"Authorization": f"Token {settings.deepgram_api_key}", "Content-Type": "application/json"},
                      json={"text": text}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"deepgram tts {r.status_code}: {r.text[:160]}")
    with open(out_path, "wb") as f:
        f.write(r.content)
    return {"provider": "deepgram", "voice": model, "cost_usd": len(text) / 1000 * 0.030}


def _syn_chatterbox(text: str, out_path: str, *, voice_name: Optional[str] = None,
                    sample_url: Optional[str] = None, style: Optional[str] = None) -> dict:
    """
    Clone/preset synthesis via Chatterbox. Prefers a self-hosted OpenAI-compatible
    server (settings.chatterbox_api_url → POST /v1/audio/speech, voice = library name);
    else uses Replicate (resemble-ai/chatterbox) with an audio_prompt sample.
    """
    base = (settings.chatterbox_api_url or "").rstrip("/")
    if base:
        # more expressive for casual UGC delivery
        exaggeration = 0.7 if (style and any(w in style.lower() for w in ("excited", "energetic", "upbeat"))) else 0.5
        headers = {"Content-Type": "application/json"}
        if settings.chatterbox_api_key:
            headers["Authorization"] = f"Bearer {settings.chatterbox_api_key}"
        r = requests.post(f"{base}/v1/audio/speech", headers=headers, timeout=180, json={
            "input": text, "voice": voice_name or "alloy",
            "exaggeration": exaggeration, "cfg_weight": 0.5, "temperature": 0.8,
        })
        if r.status_code != 200:
            raise RuntimeError(f"chatterbox server {r.status_code}: {r.text[:160]}")
        with open(out_path, "wb") as f:
            f.write(r.content)   # server returns WAV
        return {"provider": "chatterbox", "voice": voice_name or "default", "cost_usd": 0.0005}
    # Replicate fallback needs a reference sample to clone from
    if not sample_url:
        raise RuntimeError("chatterbox: no self-hosted url and no sample_url for Replicate")
    url = _replicate_run("resemble-ai", "chatterbox", {"prompt": text, "audio_prompt": sample_url})
    if not url:
        raise RuntimeError("chatterbox no output")
    _dl(url, out_path)
    return {"provider": "chatterbox", "voice": "cloned", "cost_usd": 0.002}


def _syn_elevenlabs(text: str, voice_id: str, out_path: str) -> dict:
    from .elevenlabs_service import ElevenLabsService
    if not ElevenLabsService.is_configured():
        raise RuntimeError("no elevenlabs key")
    ElevenLabsService.tts(voice_id, text, out_path)
    return {"provider": "elevenlabs", "voice": voice_id, "cost_usd": len(text) / 1000 * 0.05}


def synthesize(text: str, *, voice_id: Optional[str] = None, out_path: Optional[str] = None,
               style: Optional[str] = None, sample_url: Optional[str] = None,
               cloned: Optional[list] = None, fallback_voice_id: Optional[str] = None,
               ref_text: Optional[str] = None) -> dict:
    """
    Synthesize `text` in the chosen voice, cheapest-first with automatic fallback.
    - voice_id like 'kokoro:af_sarah' / 'openai:nova' / 'deepgram:aura-2-hera-en'
      / 'chatterbox:<name>' (needs sample_url) — resolved from the catalog.
    - On any provider error we drop to the next in FALLBACK_ORDER, ElevenLabs last.
    Returns {path, provider, voice, cost_usd}.
    """
    if not text or not text.strip():
        raise ValueError("empty text")
    out_path = out_path or os.path.join(DOWNLOADS_DIR, f"vo_{uuid.uuid4().hex[:8]}.mp3")

    v = _by_id(voice_id) if voice_id else None
    # resolve a cloned voice's sample from the passed-in DB list
    if not v and voice_id and cloned:
        for c in cloned:
            if (c.get("id") == voice_id) or (voice_id.endswith(str(c.get("voice_id", "\0")))):
                v = {"provider": c.get("provider", "chatterbox")}; sample_url = sample_url or c.get("sample_url")
                break

    provider = (v or {}).get("provider")
    # A clone request = "speak MY script in THIS person's voice", i.e. a reference sample.
    # Prefer fal (F5-TTS) — it clones on the key we already pay for. Chatterbox/Replicate only
    # if fal isn't configured.
    if not provider and voice_id and voice_id.startswith(("chatterbox", "fal-clone")):
        provider = "fal-clone" if (settings.fal_key or settings.fal_api_key) else "chatterbox"
    if not provider and sample_url:
        provider = "fal-clone" if (settings.fal_key or settings.fal_api_key) else "chatterbox"
    # a voice_id like 'elevenlabs:<id>' / 'deepgram:<model>' explicitly names the provider
    if not provider and voice_id and ":" in voice_id:
        pref = voice_id.split(":", 1)[0]
        if pref in ("openai", "deepgram", "elevenlabs", "kokoro", "chatterbox"):
            provider = pref
    native = (voice_id.split(":", 1)[1] if voice_id and ":" in voice_id else None)

    # If the clone can't run (no Chatterbox/Replicate), don't even try — go straight to the
    # cast voice so a female character never lands on a blind default voice.
    if provider == "chatterbox" and not clone_available():
        logger.warning("voice_studio: cloning unavailable (no Chatterbox/Replicate) → casting a preset voice")
        provider, native, sample_url = None, None, None

    # What voice did the caller actually want? If we have to leave their provider (e.g. Kokoro
    # needs Replicate and Replicate has no payment method), we must land on the CLOSEST voice —
    # same gender, same age band — not that provider's arbitrary default.
    fb = _by_id(fallback_voice_id) if fallback_voice_id else None
    want = v or fb or {}
    want_gender = want.get("gender") or "female"
    want_age = want.get("age_band")

    def _native_for(prov: str) -> Optional[str]:
        if provider == prov and native:
            return native
        best, best_s = None, -1
        for c in VOICE_CATALOG + _eleven_voices():
            if c.get("provider") != prov or c.get("auto_cast") is False:
                continue
            s = (5 if c.get("gender") == want_gender else 0) + (3 if c.get("age_band") == want_age else 0)
            if s > best_s:
                best, best_s = c, s
        return best["id"].split(":", 1)[1] if best else None

    # build the attempt order: chosen provider → the cast voice's provider → the cheap chain,
    # and skip any provider whose key isn't configured.
    avail = available_providers()
    order = ([provider] if provider else []) + ([fb["provider"]] if fb else []) + FALLBACK_ORDER
    order = [p for i, p in enumerate(order) if p in avail and p not in order[:i]]
    errors = []
    for prov in order:
        try:
            if prov == "fal-clone":
                res = _syn_fal_clone(text, out_path, sample_url=sample_url, ref_text=ref_text)
            elif prov == "chatterbox":
                res = _syn_chatterbox(text, out_path, voice_name=_native_for("chatterbox"),
                                      sample_url=sample_url, style=style)
            elif prov == "kokoro":
                res = _syn_kokoro(text, _native_for("kokoro") or "af_sarah", out_path)
            elif prov == "openai":
                res = _syn_openai(text, _native_for("openai") or "nova", out_path, style)
            elif prov == "gemini":
                res = _syn_gemini(text, _native_for("gemini") or "Kore", out_path, style)
            elif prov == "deepgram":
                res = _syn_deepgram(text, _native_for("deepgram") or "aura-2-hera-en", out_path)
            elif prov == "elevenlabs":
                ev = _native_for("elevenlabs") or ((_eleven_voices() or [{}])[0].get("id", ":").split(":", 1)[-1])
                if not ev:
                    raise RuntimeError("no ElevenLabs voice available to this account")
                res = _syn_elevenlabs(text, ev, out_path)
            else:
                continue
            res["path"] = out_path
            res["fallback"] = (prov != provider) if provider else False
            res["requested"] = voice_id
            if res["fallback"]:
                # Say EXACTLY what happened — a silent swap is how "I picked Sarah and got Nova"
                # goes unnoticed. errors[0] is why the chosen provider refused.
                res["fallback_reason"] = (errors[0] if errors else f"{provider} unavailable")[:160]
                logger.warning(f"voice_studio: requested {voice_id} ({provider}) → USED {prov}:{res.get('voice')} "
                               f"— reason: {res['fallback_reason']}")
            return res
        except Exception as e:
            errors.append(f"{prov}: {e}")
            logger.warning(f"voice_studio {prov} failed: {e}")
    raise RuntimeError("all voice providers failed → " + " | ".join(errors[-4:]))


def clone_voice(sample_url: str, name: str) -> dict:
    """
    Register a reusable cloned voice. Chatterbox clones at synth-time from the sample
    (no pre-registration needed), so we just validate + return a catalog-style ref.
    Falls back to ElevenLabs instant-clone if Chatterbox/Replicate is unavailable.
    """
    if settings.chatterbox_api_url or settings.replicate_usable:
        return {"voice_id": f"chatterbox:{name}", "provider": "chatterbox", "sample_url": sample_url, "name": name}
    # last resort — ElevenLabs instant clone (counts against 11labs quota)
    from .elevenlabs_service import ElevenLabsService
    if ElevenLabsService.is_configured():
        local = os.path.join(DOWNLOADS_DIR, f"clone_{uuid.uuid4().hex[:6]}.mp3")
        _dl(sample_url, local)
        vid = ElevenLabsService.clone_voice(local, name)
        return {"voice_id": f"elevenlabs:{vid}", "provider": "elevenlabs", "name": name}
    raise RuntimeError("no cloning provider available (need Replicate or ElevenLabs)")
