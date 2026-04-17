"""Service for transcribing audio using OpenAI Whisper or Deepgram"""

import logging
import httpx
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class TranscriptionService:
    """Transcribes audio files to text using Whisper or Deepgram"""

    def __init__(self):
        self.openai_key = settings.openai_api_key
        self.deepgram_key = getattr(settings, 'deepgram_api_key', None)

        if OPENAI_AVAILABLE and self.openai_key:
            openai.api_key = self.openai_key
            self.openai_client = openai.OpenAI(api_key=self.openai_key)
        else:
            self.openai_client = None
            logger.warning("OpenAI not available for Whisper transcription")

    async def transcribe_audio(
        self,
        audio_file_path: str,
        provider: str = "openai",
        language: Optional[str] = None,
    ) -> dict:
        """
        Transcribe audio file to text

        Args:
            audio_file_path: Path to audio file (mp3, mp4, wav, m4a, flac, etc.)
            provider: "openai" or "deepgram" (default: openai)
            language: Optional language code (e.g., "en", "es", "fr")

        Returns:
            Dictionary with transcription, language, and metadata
        """
        if provider == "deepgram":
            return await self._transcribe_deepgram(audio_file_path, language)
        else:
            return await self._transcribe_openai(audio_file_path, language)

    async def _transcribe_openai(
        self,
        audio_file_path: str,
        language: Optional[str] = None,
    ) -> dict:
        """Transcribe using OpenAI Whisper API"""
        if not self.openai_client:
            raise ValueError("OpenAI client not configured. Please set OPENAI_API_KEY in .env")

        try:
            logger.info(f"Transcribing audio with OpenAI Whisper: {audio_file_path}")

            with open(audio_file_path, "rb") as audio_file:
                # Call OpenAI Whisper API
                params = {
                    "model": "whisper-1",
                    "language": language,
                } if language else {
                    "model": "whisper-1"
                }

                transcript = self.openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                )

            logger.info(f"Transcription completed using Whisper")

            return {
                "transcription": transcript.text,
                "provider": "openai_whisper",
                "language": language or "detected",
                "success": True,
                "model": "whisper-1",
            }

        except Exception as e:
            logger.error(f"OpenAI Whisper transcription failed: {str(e)}")
            raise

    async def _transcribe_deepgram(
        self,
        audio_file_path: str,
        language: Optional[str] = None,
    ) -> dict:
        """Transcribe using Deepgram API"""
        if not self.deepgram_key:
            raise ValueError("Deepgram API key not configured. Please set DEEPGRAM_API_KEY in .env")

        try:
            logger.info(f"Transcribing audio with Deepgram: {audio_file_path}")

            async with httpx.AsyncClient() as client:
                with open(audio_file_path, "rb") as audio_file:
                    audio_data = audio_file.read()

                # Prepare Deepgram request
                headers = {
                    "Authorization": f"Token {self.deepgram_key}",
                    "Content-Type": "application/octet-stream",
                }

                params = {
                    "model": "nova-2",
                    "smart_format": "true",
                }

                if language:
                    params["language"] = language

                response = await client.post(
                    "https://api.deepgram.com/v1/listen",
                    headers=headers,
                    params=params,
                    content=audio_data,
                )

                if response.status_code != 200:
                    raise Exception(f"Deepgram API error: {response.text}")

                result = response.json()
                transcript = result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")

                logger.info(f"Transcription completed using Deepgram")

                return {
                    "transcription": transcript,
                    "provider": "deepgram",
                    "language": language or "auto-detected",
                    "success": True,
                    "model": "nova-2",
                    "confidence": result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("confidence", None),
                }

        except Exception as e:
            logger.error(f"Deepgram transcription failed: {str(e)}")
            raise

    async def transcribe_audio_url(
        self,
        audio_url: str,
        provider: str = "openai",
        language: Optional[str] = None,
    ) -> dict:
        """
        Transcribe audio from URL

        Args:
            audio_url: URL to audio file
            provider: "openai" or "deepgram"
            language: Optional language code

        Returns:
            Transcription result
        """
        try:
            logger.info(f"Downloading audio from URL: {audio_url}")

            # Download audio file
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(audio_url)
                if response.status_code != 200:
                    raise Exception(f"Failed to download audio: {response.status_code}")

                audio_data = response.content

            # Save temporarily
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name

            try:
                # Transcribe the temporary file
                result = await self.transcribe_audio(temp_path, provider, language)
                result["audio_url"] = audio_url
                return result
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except:
                    pass

        except Exception as e:
            logger.error(f"Error transcribing audio from URL: {str(e)}")
            raise

    @staticmethod
    def get_supported_providers() -> list[str]:
        """Get list of supported transcription providers"""
        return ["openai", "deepgram"]

    @staticmethod
    def get_supported_languages() -> list[str]:
        """Get list of supported languages"""
        return [
            "en", "es", "fr", "de", "it", "pt", "nl", "ru", "ja", "ko", "zh",
            "ar", "hi", "th", "vi", "pl", "tr", "sv", "no", "da", "fi",
        ]
