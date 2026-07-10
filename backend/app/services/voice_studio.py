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
  pick_voice(gender=, age_band=, style=)          -> voice dict   (brain casting, 45-55 woman default)
  synthesize(text, voice_id=, out_path=, style=)  -> {path, provider, voice, cost_usd}
  clone_voice(sample_url, name)                   -> {voice_id, provider}   (chatterbox; 11labs fallback)
"""
import logging
import os
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
FALLBACK_ORDER = ["openai", "deepgram", "elevenlabs", "kokoro"]

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
    {"id": "openai:alloy",   "name": "Alloy",   "provider": "openai", "gender": "female", "age_band": "45-55", "style": "calm, neutral"},
    {"id": "openai:fable",   "name": "Fable",   "provider": "openai", "gender": "female", "age_band": "35-44", "style": "expressive, storytelling"},
    {"id": "openai:onyx",    "name": "Onyx",    "provider": "openai", "gender": "male",   "age_band": "45-55", "style": "deep, authoritative"},
    {"id": "openai:echo",    "name": "Echo",    "provider": "openai", "gender": "male",   "age_band": "35-44", "style": "clear, informative"},
    # Deepgram Aura-2 — very natural US English
    {"id": "deepgram:aura-2-hera-en",    "name": "Hera",    "provider": "deepgram", "gender": "female", "age_band": "45-55", "style": "mature, grounded"},
    {"id": "deepgram:aura-2-luna-en",    "name": "Luna",    "provider": "deepgram", "gender": "female", "age_band": "under35", "style": "friendly, casual"},
    {"id": "deepgram:aura-2-asteria-en", "name": "Asteria", "provider": "deepgram", "gender": "female", "age_band": "35-44", "style": "clear, upbeat"},
    {"id": "deepgram:aura-2-orion-en",   "name": "Orion",   "provider": "deepgram", "gender": "male",   "age_band": "45-55", "style": "warm, mature"},
    {"id": "deepgram:aura-2-arcas-en",   "name": "Arcas",   "provider": "deepgram", "gender": "male",   "age_band": "35-44", "style": "natural, conversational"},
]

# ElevenLabs default public voice ids (used only when 11labs is the chosen/last provider)
_ELEVEN_DEFAULTS = {"female": "21m00Tcm4TlvDq8ikWAM", "male": "TxGEqnHWrfWFTfGW9XjX"}


def _by_id(voice_id: str) -> Optional[dict]:
    for v in VOICE_CATALOG:
        if v["id"] == voice_id:
            return v
    return None


def list_voices(cloned: Optional[list] = None) -> list:
    """Full pickable catalog: presets + any cloned voices passed in (from DB)."""
    out = [{**v, "cloned": False} for v in VOICE_CATALOG]
    for c in (cloned or []):
        out.append({"id": c.get("id") or f"chatterbox:{c.get('voice_id')}", "name": c.get("name", "Cloned"),
                    "provider": c.get("provider", "chatterbox"), "gender": c.get("gender"),
                    "age_band": c.get("age_band"), "style": c.get("style", "cloned voice"),
                    "cloned": True, "sample_url": c.get("sample_url")})
    return out


def pick_voice(*, gender: Optional[str] = None, age_band: Optional[str] = None,
               style: Optional[str] = None, cloned: Optional[list] = None) -> dict:
    """Brain casting: best catalog match. Default bias = 45-55 woman (house rule)."""
    gender = gender or "female"
    age_band = age_band or "45-55"
    pool = list_voices(cloned)
    scored = []
    for v in pool:
        s = 0
        if v.get("gender") == gender: s += 3
        if v.get("age_band") == age_band: s += 3
        if style and style.lower() in (v.get("style") or "").lower(): s += 2
        if v.get("provider") in ("openai", "deepgram", "elevenlabs"): s += 1   # avoid Replicate for auto-cast
        if v.get("cloned"): s += 1                  # prefer our own cloned voices when present
        scored.append((s, v))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else {"id": "kokoro:af_sarah", "provider": "kokoro"}


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
               cloned: Optional[list] = None) -> dict:
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
    # explicit clone request: voice_id 'chatterbox:*' or a raw sample → route to chatterbox
    if not provider and voice_id and voice_id.startswith("chatterbox"):
        provider = "chatterbox"
    if not provider and sample_url:
        provider = "chatterbox"
    native = (voice_id.split(":", 1)[1] if voice_id and ":" in voice_id else None)

    # build the attempt order: chosen provider first, then the cheap→premium chain
    order = ([provider] if provider else []) + [p for p in FALLBACK_ORDER if p != provider]
    errors = []
    for prov in order:
        try:
            if prov == "chatterbox":
                voice_name = native if provider == "chatterbox" and native else None
                res = _syn_chatterbox(text, out_path, voice_name=voice_name, sample_url=sample_url, style=style)
            elif prov == "kokoro":
                res = _syn_kokoro(text, native if provider == "kokoro" and native else "af_sarah", out_path)
            elif prov == "openai":
                res = _syn_openai(text, native if provider == "openai" and native else "nova", out_path, style)
            elif prov == "deepgram":
                res = _syn_deepgram(text, native if provider == "deepgram" and native else "aura-2-hera-en", out_path)
            elif prov == "elevenlabs":
                res = _syn_elevenlabs(text, native if provider == "elevenlabs" and native else _ELEVEN_DEFAULTS["female"], out_path)
            else:
                continue
            res["path"] = out_path
            res["fallback"] = (prov != provider) if provider else False
            if res["fallback"]:
                logger.warning(f"voice_studio: fell back to {prov} (chosen={provider})")
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
    if settings.chatterbox_api_url or settings.replicate_api_token:
        return {"voice_id": f"chatterbox:{name}", "provider": "chatterbox", "sample_url": sample_url, "name": name}
    # last resort — ElevenLabs instant clone (counts against 11labs quota)
    from .elevenlabs_service import ElevenLabsService
    if ElevenLabsService.is_configured():
        local = os.path.join(DOWNLOADS_DIR, f"clone_{uuid.uuid4().hex[:6]}.mp3")
        _dl(sample_url, local)
        vid = ElevenLabsService.clone_voice(local, name)
        return {"voice_id": f"elevenlabs:{vid}", "provider": "elevenlabs", "name": name}
    raise RuntimeError("no cloning provider available (need Replicate or ElevenLabs)")
