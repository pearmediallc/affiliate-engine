"""Lip-sync service - generates talking-head videos from portrait + audio using Replicate API"""
import os
import uuid
import time
import logging
import requests
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Available lip-sync models on Replicate
MODELS = {
    "sadtalker": {
        "version": "cddbe60a2c5decfd19e4d3e12c03734520eb5c9c2d0a08aeb1c7bbff0e855014",
        "name": "SadTalker",
        "description": "Audio-driven single image talking face animation",
        "supports_video_input": False,
    },
}


class LipSyncService:
    """Generates talking-head videos using Replicate API"""

    @staticmethod
    def get_available_models() -> list:
        return [{"id": k, **v} for k, v in MODELS.items()]

    @staticmethod
    def start_generation(
        image_url: str,
        audio_url: str,
        model: str = "sadtalker",
    ) -> dict:
        """Start a lip-sync generation job on Replicate. Returns prediction ID."""
        token = settings.replicate_api_token
        if not token:
            raise ValueError("REPLICATE_API_TOKEN not configured")

        model_info = MODELS.get(model)
        if not model_info:
            raise ValueError(f"Unknown model: {model}. Available: {list(MODELS.keys())}")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "version": model_info["version"],
            "input": {
                "source_image": image_url,
                "driven_audio": audio_url,
                "enhancer": "gfpgan",  # Face enhancement
            },
        }

        r = requests.post(
            "https://api.replicate.com/v1/predictions",
            headers=headers, json=payload, timeout=30,
        )

        if r.status_code not in (200, 201):
            raise Exception(f"Replicate API error: {r.status_code} - {r.text[:300]}")

        data = r.json()
        prediction_id = data.get("id")
        logger.info(f"Lip-sync job started: {prediction_id}")

        return {
            "prediction_id": prediction_id,
            "status": data.get("status", "starting"),
            "model": model,
        }

    @staticmethod
    def check_status(prediction_id: str) -> dict:
        """Check the status of a lip-sync generation job."""
        token = settings.replicate_api_token
        if not token:
            raise ValueError("REPLICATE_API_TOKEN not configured")

        headers = {"Authorization": f"Bearer {token}"}

        r = requests.get(
            f"https://api.replicate.com/v1/predictions/{prediction_id}",
            headers=headers, timeout=30,
        )

        if r.status_code != 200:
            raise Exception(f"Replicate status check failed: {r.status_code}")

        data = r.json()
        status = data.get("status")  # starting, processing, succeeded, failed, canceled
        output = data.get("output")
        error = data.get("error")

        result = {
            "prediction_id": prediction_id,
            "status": status,
            "error": error,
        }

        if status == "succeeded" and output:
            # Output is typically a URL to the generated video
            video_url = output if isinstance(output, str) else output[0] if isinstance(output, list) else None
            if video_url:
                result["video_url"] = video_url
                # Download the video
                try:
                    video_response = requests.get(video_url, timeout=60)
                    if video_response.status_code == 200:
                        filename = f"lipsync_{uuid.uuid4().hex[:8]}.mp4"
                        filepath = os.path.join(DOWNLOADS_DIR, filename)
                        with open(filepath, "wb") as f:
                            f.write(video_response.content)
                        result["local_path"] = filepath
                        result["download_filename"] = filename
                except Exception as dl_err:
                    logger.warning(f"Failed to download lip-sync result: {dl_err}")

        return result

    @staticmethod
    def upload_file_to_replicate(file_path: str) -> str:
        """Upload a local file to Replicate's file hosting and return the URL."""
        token = settings.replicate_api_token
        if not token:
            raise ValueError("REPLICATE_API_TOKEN not configured")

        headers = {"Authorization": f"Bearer {token}"}

        with open(file_path, "rb") as f:
            r = requests.post(
                "https://api.replicate.com/v1/files",
                headers=headers,
                files={"content": (os.path.basename(file_path), f)},
                timeout=60,
            )

        if r.status_code not in (200, 201):
            raise Exception(f"File upload failed: {r.status_code} - {r.text[:200]}")

        data = r.json()
        return data.get("urls", {}).get("get", "")
