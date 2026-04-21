"""Video creation engine using Google Veo 3.1"""
import os
import uuid
import time
import logging
import base64
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)

VIDEOS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "generated_videos")
os.makedirs(VIDEOS_DIR, exist_ok=True)


class VideoCreatorService:
    """Creates videos using Google Veo 3.1 via the Gemini API"""

    @staticmethod
    def generate_video(
        prompt: str,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        duration: str = "8",
    ) -> dict:
        """
        Generate a video from text prompt using Veo 3.1.
        Returns operation info for polling.
        """
        from google import genai
        from google.genai import types

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        client = genai.Client(api_key=settings.gemini_api_key)

        # Normalize duration: accept "8", "8s", 8 -> int
        try:
            duration_int = int(str(duration).rstrip("s").strip())
        except (ValueError, AttributeError):
            duration_int = 8

        config = types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            resolution=resolution or "720p",
            duration_seconds=duration_int,
        )

        logger.info(f"Starting Veo 3.1: aspect={aspect_ratio} res={resolution} dur={duration_int}s prompt={prompt[:80]}")

        operation = client.models.generate_videos(
            model="veo-3.1-generate-preview",
            prompt=prompt,
            config=config,
        )

        return {
            "operation_name": operation.name,
            "status": "generating",
            "prompt": prompt[:200],
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "duration_seconds": duration_int,
        }

    @staticmethod
    def generate_from_image(
        image_path: str,
        prompt: str = "",
        aspect_ratio: str = "16:9",
    ) -> dict:
        """Generate video using an image as the starting frame."""
        from google import genai
        from google.genai import types

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        client = genai.Client(api_key=settings.gemini_api_key)

        # Read image and create genai Image
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        # Infer mime type from extension
        ext = (os.path.splitext(image_path)[1] or ".png").lower().lstrip(".")
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
        image = types.Image(image_bytes=image_bytes, mime_type=mime)

        logger.info(f"Starting Veo 3.1 image-to-video: {prompt[:100]}...")

        operation = client.models.generate_videos(
            model="veo-3.1-generate-preview",
            prompt=prompt or "Animate this image with natural, cinematic motion",
            image=image,
            config=types.GenerateVideosConfig(aspect_ratio=aspect_ratio),
        )

        return {
            "operation_name": operation.name,
            "status": "generating",
            "prompt": prompt[:200],
            "type": "image_to_video",
        }

    @staticmethod
    def check_status(operation_name: str) -> dict:
        """Poll the status of a video generation operation."""
        from google import genai
        from google.genai import types

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        client = genai.Client(api_key=settings.gemini_api_key)

        operation = types.GenerateVideosOperation(name=operation_name)
        operation = client.operations.get(operation)

        result = {
            "operation_name": operation_name,
            "done": operation.done,
            "status": "completed" if operation.done else "generating",
        }

        if operation.done and operation.response:
            try:
                generated_video = operation.response.generated_videos[0]

                # Download the video
                client.files.download(file=generated_video.video)

                filename = f"veo_{uuid.uuid4().hex[:8]}.mp4"
                filepath = os.path.join(VIDEOS_DIR, filename)
                generated_video.video.save(filepath)

                result["video_path"] = filepath
                result["video_filename"] = filename
                result["download_url"] = f"/api/v1/video/download/{filename}"

                logger.info(f"Veo video saved: {filepath}")
            except Exception as e:
                logger.error(f"Failed to save Veo video: {e}")
                result["error"] = str(e)
                result["status"] = "failed"

        return result

    @staticmethod
    def get_capabilities() -> dict:
        """Return Veo 3.1 capabilities for the frontend"""
        return {
            "models": [
                {"id": "veo-3.1-generate-preview", "name": "Veo 3.1", "tier": "standard", "audio": True},
                {"id": "veo-3.1-fast-generate-preview", "name": "Veo 3.1 Fast", "tier": "fast", "audio": True},
            ],
            "aspect_ratios": ["16:9", "9:16"],
            "resolutions": ["720p", "1080p"],
            "durations": ["4", "6", "8"],
            "features": ["text_to_video", "image_to_video", "native_audio", "dialogue", "sound_effects"],
        }
