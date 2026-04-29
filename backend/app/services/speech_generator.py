"""Service for generating speech/audio from text using Google Cloud TTS or OpenAI"""
import logging
from typing import Optional
from ..config import settings
from .pricing import Pricing
import uuid
import base64
import requests

try:
    from google.cloud import texttospeech
    GOOGLE_TTS_AVAILABLE = True
except ImportError:
    GOOGLE_TTS_AVAILABLE = False
    logging.warning("google-cloud-texttospeech not installed - using OpenAI TTS instead")

try:
    import google.generativeai as genai
    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    GOOGLE_GENAI_AVAILABLE = False

logger = logging.getLogger(__name__)

# Available voices in Gemini TTS
AVAILABLE_VOICES = {
    "Kore": "firm, professional",
    "Puck": "upbeat, energetic",
    "Enceladus": "breathy, warm",
    "Charon": "informative, clear",
    "Ember": "passionate, expressive",
    "Lunar": "calm, soothing",
    "Nova": "confident, bold",
    "Phoenix": "bright, cheerful",
    "Sage": "wise, thoughtful",
    "Vale": "deep, authoritative",
}


class SpeechGeneratorService:
    """Generates speech/audio from text using Gemini models"""

    def __init__(self):
        if settings.gemini_api_key and GOOGLE_GENAI_AVAILABLE:
            genai.configure(api_key=settings.gemini_api_key)
            self.model = genai.GenerativeModel("gemini-2.5-flash-lite")
        else:
            self.model = None
            logger.warning("Gemini TTS not available")

    async def generate_speech(
        self,
        text: str,
        voice: str = "Kore",
        style: Optional[str] = None,
        language: str = "en",
        output_format: str = "mp3",
    ) -> dict:
        """
        Generate speech from text using OpenAI TTS API (primary) or Google Cloud TTS (fallback)

        Args:
            text: Text to convert to speech
            voice: Voice name (Alloy, Echo, Fable, Onyx, Nova, Shimmer for OpenAI)
            style: Style description (e.g., "excited", "confident") - used as system prompt
            language: Language code (e.g., "en", "es", "fr")
            output_format: Audio format (mp3, wav, ogg, pcm)

        Returns:
            Dictionary with audio data, metadata
        """
        if not text or len(text.strip()) == 0:
            raise ValueError("Cannot generate speech from empty text")

        try:
            # Try OpenAI TTS first (primary)
            if settings.openai_api_key:
                logger.info(f"Attempting OpenAI TTS with voice: {voice}")
                return await self._generate_with_openai_tts(text, voice, language, output_format)
        except Exception as openai_e:
            logger.warning(f"OpenAI TTS failed: {str(openai_e)}, trying Google Cloud TTS")

        # Fallback to Google Cloud TTS
        if GOOGLE_TTS_AVAILABLE and settings.google_api_key:
            logger.info(f"Attempting Google Cloud TTS")
            return self._generate_with_google_tts(text, voice, language, output_format)

        raise Exception("No TTS provider available - configure OpenAI or Google Cloud API keys")

    async def _generate_with_openai_tts(self, text: str, voice: str, language: str, output_format: str) -> dict:
        """Generate speech using OpenAI TTS API"""
        # Map our voices to OpenAI voices
        voice_map = {
            "Kore": "onyx",  # firm, professional
            "Puck": "nova",  # upbeat, energetic
            "Enceladus": "shimmer",  # breathy, warm
            "Charon": "echo",  # informative, clear
            "Ember": "fable",  # passionate, expressive
            "Lunar": "alloy",  # calm, soothing
            "Nova": "nova",  # confident, bold
            "Phoenix": "shimmer",  # bright, cheerful
            "Sage": "alloy",  # wise, thoughtful
            "Vale": "onyx",  # deep, authoritative
        }

        openai_voice = voice_map.get(voice, "alloy")

        url = "https://api.openai.com/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "tts-1-hd",  # High definition TTS
            "input": text,
            "voice": openai_voice,
            "response_format": "mp3",
        }

        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise Exception(f"OpenAI TTS API error: {response.text}")

        audio_data = response.content
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')

        # Estimate duration based on text length (rough estimate: 150 words per minute)
        word_count = len(text.split())
        estimated_duration_ms = int((word_count / 150) * 60 * 1000)

        logger.info(f"Speech generated successfully with OpenAI TTS ({len(audio_data)} bytes)")

        char_count = len(text or "")
        cost_usd = Pricing.tts(char_count, "tts-1-hd")

        return {
            "audio_base64": audio_base64,
            "audio_data": audio_data,
            "mime_type": "audio/mpeg",
            "duration_ms": estimated_duration_ms,
            "voice": voice,
            "language": language,
            "format": "mp3",
            "model": "tts-1-hd",
            "provider": "openai",
            "char_count": char_count,
            "cost_usd": cost_usd,
        }

    def _generate_with_google_tts(self, text: str, voice: str, language: str, output_format: str) -> dict:
        """Generate speech using Google Cloud Text-to-Speech API"""
        from google.cloud import texttospeech

        # Create client
        client = texttospeech.TextToSpeechClient()

        # Build the request
        input_text = texttospeech.SynthesisInput(text=text)

        # Map our voices to Google voices
        voice_name = "en-US-Neural2-C"  # Default female voice
        if "male" in voice.lower() or voice in ["Kore", "Charon", "Vale"]:
            voice_name = "en-US-Neural2-A"  # Male voice

        voice_config = texttospeech.VoiceSelectionParams(
            language_code=f"{language}-US",
            name=voice_name,
        )

        # Audio config
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
        )

        # Perform the text-to-speech request
        response = client.synthesize_speech(
            input=input_text,
            voice=voice_config,
            audio_config=audio_config,
        )

        audio_data = response.audio_content
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')

        # Estimate duration based on text length
        word_count = len(text.split())
        estimated_duration_ms = int((word_count / 150) * 60 * 1000)

        logger.info(f"Speech generated successfully with Google Cloud TTS ({len(audio_data)} bytes)")

        char_count = len(text or "")
        # Neural2 voices are billed at the WaveNet/Neural rate ($16 / 1M chars)
        cost_usd = Pricing.tts(char_count, "google-neural")

        return {
            "audio_base64": audio_base64,
            "audio_data": audio_data,
            "mime_type": "audio/mpeg",
            "duration_ms": estimated_duration_ms,
            "voice": voice,
            "language": language,
            "format": "mp3",
            "model": "google-cloud-tts",
            "provider": "google-cloud",
            "char_count": char_count,
            "cost_usd": cost_usd,
        }

    def get_available_voices(self) -> dict:
        """Get list of available voices"""
        return AVAILABLE_VOICES

    def get_supported_languages(self) -> list[str]:
        """Get list of supported languages"""
        return [
            "en", "es", "fr", "de", "it", "pt", "ru", "ja", "ko", "zh",
            "ar", "hi", "th", "vi", "id", "pl", "uk", "nl", "tr", "sv",
            "fi", "da", "no", "cs", "sk", "hu", "ro", "el", "he", "fa"
        ]
