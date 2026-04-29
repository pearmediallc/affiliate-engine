"""
Pricing module — real per-call costs for every paid API the platform uses.

Numbers are based on each provider's published pricing as of early 2026.
Each helper returns a USD float for one API call.

Override any value at runtime via env var with prefix PRICE_ (e.g.
PRICE_VEO31_STANDARD_PER_SEC=0.40).
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning(f"Invalid float in env {key}={raw!r}; using default {default}")
        return default


class Pricing:
    """
    Per-call cost helpers. All return USD float.

    Each method picks the right rate from the (model, params) tuple it
    receives, so callers don't have to know the rate table.
    """

    # ---------------------------------------------------------------- VIDEO

    # Google Veo 3.1 (preview) — $/second of generated video, includes audio.
    # Source: Google Vertex AI / Gemini API pricing (preview rate).
    VEO31_STANDARD_PER_SEC = _env_float("PRICE_VEO31_STANDARD_PER_SEC", 0.40)
    VEO31_FAST_PER_SEC = _env_float("PRICE_VEO31_FAST_PER_SEC", 0.15)
    # Without audio is ~half the rate; we don't currently use audio_off so default to with-audio.

    @classmethod
    def veo_video(cls, duration_seconds: float, model: str = "veo-3.1-generate-preview") -> float:
        """Cost for a single Veo text-to-video or image-to-video call."""
        per_sec = cls.VEO31_FAST_PER_SEC if "fast" in (model or "") else cls.VEO31_STANDARD_PER_SEC
        return round(per_sec * max(0.0, float(duration_seconds)), 4)

    @classmethod
    def veo_extension(cls, duration_seconds: float = 7, model: str = "veo-3.1-generate-preview") -> float:
        """Cost for a Veo extension call (default 7s)."""
        return cls.veo_video(duration_seconds, model)

    # ---------------------------------------------------------------- IMAGES

    # Google Imagen / Gemini image gen — per image
    IMAGEN4_PER_IMG = _env_float("PRICE_IMAGEN4_PER_IMG", 0.040)
    IMAGEN4_FAST_PER_IMG = _env_float("PRICE_IMAGEN4_FAST_PER_IMG", 0.020)
    IMAGEN4_ULTRA_PER_IMG = _env_float("PRICE_IMAGEN4_ULTRA_PER_IMG", 0.060)
    GEMINI_FLASH_IMAGE_PER_IMG = _env_float("PRICE_GEMINI_FLASH_IMAGE_PER_IMG", 0.039)

    # OpenAI image — per image, depends on model + size + quality
    DALLE3_STD_1024 = _env_float("PRICE_DALLE3_STD_1024", 0.040)
    DALLE3_STD_1792 = _env_float("PRICE_DALLE3_STD_1792", 0.080)
    DALLE3_HD_1024 = _env_float("PRICE_DALLE3_HD_1024", 0.080)
    DALLE3_HD_1792 = _env_float("PRICE_DALLE3_HD_1792", 0.120)
    GPT_IMAGE_1_LOW = _env_float("PRICE_GPT_IMAGE_1_LOW", 0.011)
    GPT_IMAGE_1_MED = _env_float("PRICE_GPT_IMAGE_1_MED", 0.042)
    GPT_IMAGE_1_HIGH = _env_float("PRICE_GPT_IMAGE_1_HIGH", 0.167)

    # FAL FLUX — per image
    FLUX_DEV_PER_IMG = _env_float("PRICE_FLUX_DEV_PER_IMG", 0.025)
    FLUX_SCHNELL_PER_IMG = _env_float("PRICE_FLUX_SCHNELL_PER_IMG", 0.003)
    FLUX_PRO_PER_IMG = _env_float("PRICE_FLUX_PRO_PER_IMG", 0.055)

    # Ideogram
    IDEOGRAM_V3_PER_IMG = _env_float("PRICE_IDEOGRAM_V3_PER_IMG", 0.080)
    IDEOGRAM_V3_TURBO_PER_IMG = _env_float("PRICE_IDEOGRAM_V3_TURBO_PER_IMG", 0.030)

    @classmethod
    def image(cls, model: str, size: str = "1024x1024", quality: str = "standard") -> float:
        """Cost for a single image generation call."""
        m = (model or "").lower()
        # Google
        if "imagen-4" in m and "fast" in m:
            return cls.IMAGEN4_FAST_PER_IMG
        if "imagen-4" in m and "ultra" in m:
            return cls.IMAGEN4_ULTRA_PER_IMG
        if "imagen-4" in m or "imagen-3" in m or m.startswith("imagen"):
            return cls.IMAGEN4_PER_IMG
        if "gemini-2.5-flash-image" in m or "flash-image" in m:
            return cls.GEMINI_FLASH_IMAGE_PER_IMG
        # OpenAI
        if "dall-e-3" in m or "dalle-3" in m:
            wide = "1792" in (size or "") or "1024x1792" in (size or "")
            if quality == "hd":
                return cls.DALLE3_HD_1792 if wide else cls.DALLE3_HD_1024
            return cls.DALLE3_STD_1792 if wide else cls.DALLE3_STD_1024
        if "gpt-image" in m:
            if quality in ("low", "draft"):
                return cls.GPT_IMAGE_1_LOW
            if quality == "high":
                return cls.GPT_IMAGE_1_HIGH
            return cls.GPT_IMAGE_1_MED
        # FAL FLUX
        if "flux" in m and "schnell" in m:
            return cls.FLUX_SCHNELL_PER_IMG
        if "flux" in m and "pro" in m:
            return cls.FLUX_PRO_PER_IMG
        if "flux" in m:
            return cls.FLUX_DEV_PER_IMG
        # Ideogram
        if "ideogram" in m:
            return cls.IDEOGRAM_V3_TURBO_PER_IMG if "turbo" in m else cls.IDEOGRAM_V3_PER_IMG
        # Fallback (Google Imagen 4 default)
        return cls.IMAGEN4_PER_IMG

    # ---------------------------------------------------------------- TTS

    # OpenAI TTS — $/1k chars
    OPENAI_TTS1_PER_1K = _env_float("PRICE_OPENAI_TTS1_PER_1K", 0.015)
    OPENAI_TTS1_HD_PER_1K = _env_float("PRICE_OPENAI_TTS1_HD_PER_1K", 0.030)
    # Google Cloud TTS — $/1M chars (Neural2/WaveNet ~ $16, Standard ~ $4)
    GOOGLE_TTS_NEURAL_PER_1M = _env_float("PRICE_GOOGLE_TTS_NEURAL_PER_1M", 16.00)
    GOOGLE_TTS_STANDARD_PER_1M = _env_float("PRICE_GOOGLE_TTS_STANDARD_PER_1M", 4.00)

    @classmethod
    def tts(cls, char_count: int, model: str = "tts-1-hd") -> float:
        chars = max(0, int(char_count or 0))
        m = (model or "").lower()
        if m.startswith("tts-1-hd") or "openai" in m and "hd" in m:
            return round((chars / 1000.0) * cls.OPENAI_TTS1_HD_PER_1K, 6)
        if m.startswith("tts-1") or m.startswith("openai"):
            return round((chars / 1000.0) * cls.OPENAI_TTS1_PER_1K, 6)
        if "google" in m or "neural" in m or "wavenet" in m:
            return round((chars / 1_000_000.0) * cls.GOOGLE_TTS_NEURAL_PER_1M, 6)
        if "standard" in m:
            return round((chars / 1_000_000.0) * cls.GOOGLE_TTS_STANDARD_PER_1M, 6)
        # Default to OpenAI HD (matches our SpeechGenerator default)
        return round((chars / 1000.0) * cls.OPENAI_TTS1_HD_PER_1K, 6)

    # ---------------------------------------------------------------- TRANSCRIPTION

    # OpenAI Whisper — $/minute
    WHISPER_PER_MIN = _env_float("PRICE_WHISPER_PER_MIN", 0.006)
    # Deepgram Nova-2 — $/minute (batch)
    DEEPGRAM_NOVA2_PER_MIN = _env_float("PRICE_DEEPGRAM_NOVA2_PER_MIN", 0.0043)

    @classmethod
    def transcription(cls, duration_seconds: float, provider: str = "openai") -> float:
        minutes = max(0.0, float(duration_seconds or 0)) / 60.0
        if "deepgram" in (provider or "").lower():
            return round(minutes * cls.DEEPGRAM_NOVA2_PER_MIN, 6)
        return round(minutes * cls.WHISPER_PER_MIN, 6)

    # ---------------------------------------------------------------- LIP-SYNC

    # Replicate compute time — SadTalker on T4 GPU averages ~$0.0002/sec ≈ $0.012/min run.
    # Typical 30s output run takes ~120-180s on a T4. Estimate $0.025 per request as default.
    REPLICATE_PER_PREDICTION = _env_float("PRICE_REPLICATE_PER_PREDICTION", 0.025)
    REPLICATE_T4_PER_SEC = _env_float("PRICE_REPLICATE_T4_PER_SEC", 0.000225)
    REPLICATE_A100_PER_SEC = _env_float("PRICE_REPLICATE_A100_PER_SEC", 0.001400)
    REPLICATE_L40S_PER_SEC = _env_float("PRICE_REPLICATE_L40S_PER_SEC", 0.000975)

    @classmethod
    def lip_sync(cls, predict_time_sec: Optional[float] = None, hardware: str = "t4") -> float:
        """
        Cost for a Replicate lip-sync prediction.
        If predict_time_sec is provided (Replicate response includes 'metrics.predict_time'),
        we bill exactly that. Otherwise fall back to a flat per-prediction estimate.
        """
        if predict_time_sec is not None and predict_time_sec > 0:
            hw = (hardware or "t4").lower()
            per_sec = cls.REPLICATE_T4_PER_SEC
            if "a100" in hw:
                per_sec = cls.REPLICATE_A100_PER_SEC
            elif "l40" in hw:
                per_sec = cls.REPLICATE_L40S_PER_SEC
            return round(per_sec * float(predict_time_sec), 6)
        return cls.REPLICATE_PER_PREDICTION

    # ---------------------------------------------------------------- TEXT (Gemini)

    # Gemini 2.5 Flash — $/1M tokens (input/output approximations for ad-script lengths)
    GEMINI_FLASH_INPUT_PER_1M = _env_float("PRICE_GEMINI_FLASH_INPUT_PER_1M", 0.075)
    GEMINI_FLASH_OUTPUT_PER_1M = _env_float("PRICE_GEMINI_FLASH_OUTPUT_PER_1M", 0.30)
    GEMINI_PRO_INPUT_PER_1M = _env_float("PRICE_GEMINI_PRO_INPUT_PER_1M", 1.25)
    GEMINI_PRO_OUTPUT_PER_1M = _env_float("PRICE_GEMINI_PRO_OUTPUT_PER_1M", 5.00)

    @classmethod
    def text(cls, input_tokens: int = 0, output_tokens: int = 0, model: str = "gemini-2.5-flash") -> float:
        m = (model or "").lower()
        if "pro" in m:
            in_rate = cls.GEMINI_PRO_INPUT_PER_1M
            out_rate = cls.GEMINI_PRO_OUTPUT_PER_1M
        else:
            in_rate = cls.GEMINI_FLASH_INPUT_PER_1M
            out_rate = cls.GEMINI_FLASH_OUTPUT_PER_1M
        return round(
            (max(0, int(input_tokens)) / 1_000_000.0) * in_rate +
            (max(0, int(output_tokens)) / 1_000_000.0) * out_rate,
            6,
        )
