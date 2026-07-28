"""
ElevenLabs voice cloning + TTS.

Wired per the ElevenLabs API (https://elevenlabs.io/docs/api-reference):
  - Instant Voice Cloning:  POST /v1/voices/add   (multipart: name + sample audio files)
                            -> { "voice_id": "..." }
  - Text-to-Speech:         POST /v1/text-to-speech/{voice_id}
                            body { text, model_id, voice_settings } -> audio/mpeg bytes
  - Auth header: "xi-api-key: <ELEVENLABS_API_KEY>"

Set ELEVENLABS_API_KEY to enable. Until then, is_configured() is False and callers
fall back (e.g. to Gemini TTS) or skip voiced rewrites — no key is hard-coded here.
"""
import logging
from typing import Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.elevenlabs.io/v1"
# Multilingual v2 is the standard high-quality cloning model.
_TTS_MODEL = "eleven_multilingual_v2"
# Read pace applied at SYNTH time (mirrors voice_studio.VOICE_SPEED). EL's voice_settings.speed
# range is 0.7–1.2, so 1.1 is safely in-range — a punchier DR read without going chipmunk.
VOICE_SPEED = 1.1


class ElevenLabsService:
    @staticmethod
    def is_configured() -> bool:
        return bool(settings.elevenlabs_api_key)

    @staticmethod
    def _headers(json_ct: bool = False) -> dict:
        h = {"xi-api-key": settings.elevenlabs_api_key or ""}
        if json_ct:
            h["Content-Type"] = "application/json"
        return h

    @staticmethod
    def clone_voice(audio_path: str, name: str) -> str:
        """Instant Voice Clone from a sample audio file. Returns voice_id."""
        if not ElevenLabsService.is_configured():
            raise RuntimeError("ELEVENLABS_API_KEY not configured")
        with open(audio_path, "rb") as f:
            files = {"files": (f"{name}.mp3", f, "audio/mpeg")}
            data = {
                "name": name[:64],
                "description": "Auto-cloned spokesperson voice (Variation Studio)",
            }
            r = httpx.post(f"{_BASE}/voices/add", headers=ElevenLabsService._headers(),
                           data=data, files=files, timeout=120)
        r.raise_for_status()
        voice_id = r.json().get("voice_id")
        if not voice_id:
            raise RuntimeError(f"voice clone returned no voice_id: {r.text[:200]}")
        return voice_id

    @staticmethod
    def tts(voice_id: str, text: str, out_path: str, delivery: Optional[str] = None) -> str:
        """Synthesize `text` in the given voice -> write mp3 to out_path.

        `delivery` is the emotion/pacing direction. A non-empty direction makes the read EXPRESSIVE:
        voice_settings.style is raised above 0 and stability lowered, so the voice ACTS instead of
        reading flat. SSML <break .../> tags in `text` are passed through untouched — eleven_
        multilingual_v2 honors them natively — so budgeted pauses land where the caller put them."""
        if not ElevenLabsService.is_configured():
            raise RuntimeError("ELEVENLABS_API_KEY not configured")
        expressive = bool((delivery or "").strip())
        body = {
            "text": text,
            "model_id": _TTS_MODEL,
            "voice_settings": {
                "stability": 0.35 if expressive else 0.5,   # lower = more emotive/varied
                "similarity_boost": 0.8,
                "style": 0.45 if expressive else 0.0,        # >0 = expressive delivery (was always flat)
                "speed": VOICE_SPEED,
            },
        }
        with httpx.stream("POST", f"{_BASE}/text-to-speech/{voice_id}",
                          headers=ElevenLabsService._headers(json_ct=True),
                          json=body, timeout=180) as r:
            r.raise_for_status()
            with open(out_path, "wb") as out:
                for chunk in r.iter_bytes():
                    out.write(chunk)
        return out_path

    @staticmethod
    def delete_voice(voice_id: str) -> None:
        """Best-effort cleanup of a temporary cloned voice (clones count against quota)."""
        if not ElevenLabsService.is_configured() or not voice_id:
            return
        try:
            httpx.delete(f"{_BASE}/voices/{voice_id}", headers=ElevenLabsService._headers(), timeout=30)
        except Exception as e:
            logger.warning(f"elevenlabs delete_voice failed: {e}")
