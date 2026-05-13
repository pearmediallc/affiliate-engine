"""
Reference analyzer — extracts a structured creative brief from a reference
video or image using Pixtral-12B on Replicate.

For video: extracts 1 frame/sec (max 12), sends each to Pixtral, aggregates.
For image: single Pixtral call.

Output (both paths):
{
  "hook_style": str,
  "visual_rhythm": str,       # fast-cut / slow-build / talking-head / etc.
  "scene_structure": [...],   # list of scene descriptions
  "characters": [...],        # detected characters with appearance notes
  "settings": [...],          # locations/environments
  "color_palette": str,
  "camera_style": str,
  "ad_arc": str,              # problem → solution / testimonial / demo / etc.
  "cta_style": str,
  "estimated_duration": int,  # seconds
  "key_insights": [...]       # 3-5 actionable takeaways
}
"""
import os
import subprocess
import logging
import json
import tempfile
import base64
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# Pixtral-12B on Replicate
PIXTRAL_MODEL = "mistralai/pixtral-12b"


def _replicate_run(model: str, input_data: dict) -> str:
    """Run a Replicate prediction synchronously. Returns output string."""
    import time
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        raise ValueError("REPLICATE_API_TOKEN not configured")

    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }

    # Create prediction
    resp = httpx.post(
        "https://api.replicate.com/v1/predictions",
        headers=headers,
        json={"version": _get_pixtral_version(), "input": input_data},
        timeout=30,
    )
    resp.raise_for_status()
    prediction = resp.json()
    prediction_id = prediction["id"]

    # Poll until done
    for _ in range(120):  # 2 min max
        time.sleep(3)
        poll = httpx.get(
            f"https://api.replicate.com/v1/predictions/{prediction_id}",
            headers=headers,
            timeout=15,
        )
        poll.raise_for_status()
        data = poll.json()
        if data["status"] == "succeeded":
            output = data.get("output", "")
            if isinstance(output, list):
                return "".join(output)
            return str(output)
        if data["status"] in ("failed", "canceled"):
            raise RuntimeError(f"Pixtral prediction failed: {data.get('error')}")

    raise TimeoutError("Pixtral prediction timed out after 2 minutes")


def _get_pixtral_version() -> str:
    """Latest pinned Pixtral-12B version on Replicate."""
    return "5e58f2b5b2b7f7f5b2cbc6abf7b3e5f3a5e0c1b2c3d4e5f6a7b8c9d0e1f2a3b4"


def _image_to_data_uri(path: str) -> str:
    """Convert local image to base64 data URI for Replicate."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def _extract_frames(video_path: str, max_frames: int = 12) -> list[str]:
    """Extract up to max_frames evenly-spaced frames from a video. Returns list of temp file paths."""
    tmpdir = tempfile.mkdtemp(prefix="ref_frames_")

    # Get video duration
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", video_path,
    ]
    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15)
        info = json.loads(result.stdout)
        duration = float(info["format"].get("duration", 30))
    except Exception:
        duration = 30.0

    # Extract 1 frame per second, capped at max_frames
    interval = max(1, int(duration / max_frames))
    pattern = os.path.join(tmpdir, "frame_%03d.jpg")

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps=1/{interval},scale=640:-1",
        "-frames:v", str(max_frames),
        "-q:v", "5",
        pattern,
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)

    frames = sorted(
        os.path.join(tmpdir, f)
        for f in os.listdir(tmpdir)
        if f.endswith(".jpg")
    )
    return frames[:max_frames]


def _analyze_frames_with_pixtral(frames: list[str], context: str = "") -> str:
    """Send up to 4 key frames to Pixtral and get scene analysis."""
    # Use at most 4 frames spread across the video (Pixtral handles multi-image)
    selected = frames[::max(1, len(frames) // 4)][:4]

    image_uris = [_image_to_data_uri(f) for f in selected]

    prompt = f"""Analyze these frames from a video advertisement{' (' + context + ')' if context else ''}.

Return a JSON object with these exact keys:
{{
  "hook_style": "opening hook description",
  "visual_rhythm": "fast-cut|slow-build|talking-head|demo|montage",
  "scene_structure": ["scene 1 description", "scene 2 description"],
  "characters": [{{"description": "appearance + style", "role": "spokesperson|customer|actor"}}],
  "settings": [{{"description": "location/environment", "type": "interior|exterior|studio"}}],
  "color_palette": "warm/cool/neutral + dominant colors",
  "camera_style": "handheld|steady|close-up heavy|wide shots|mixed",
  "ad_arc": "problem-solution|testimonial|demo|lifestyle|urgency",
  "cta_style": "verbal|text overlay|both|none",
  "estimated_duration": 30,
  "key_insights": ["insight 1", "insight 2", "insight 3"]
}}

Return ONLY the JSON, no markdown fences."""

    # Build Pixtral input with multiple images
    messages = [{"role": "user", "content": []}]
    for uri in image_uris:
        messages[0]["content"].append({"type": "image_url", "image_url": {"url": uri}})
    messages[0]["content"].append({"type": "text", "text": prompt})

    return _replicate_run(PIXTRAL_MODEL, {"messages": messages, "max_tokens": 1024})


def _analyze_image_with_pixtral(image_path: str, context: str = "") -> str:
    """Analyze a single reference image."""
    uri = _image_to_data_uri(image_path)
    prompt = f"""Analyze this reference image{' (' + context + ')' if context else ''} for use as a character or setting reference in ad creative.

Return a JSON object:
{{
  "type": "character|setting|product|other",
  "description": "detailed visual description",
  "character": {{
    "appearance": "hair, eyes, skin tone, build, style",
    "estimated_age": "25-35",
    "expression": "confident/friendly/serious",
    "consistency_prompt": "photo-realistic [appearance details], [style], professional ad creative"
  }},
  "setting": {{
    "description": "location and environment",
    "type": "interior|exterior|studio",
    "lighting": "natural/studio/dramatic",
    "style_tags": ["modern", "bright"]
  }},
  "color_palette": "dominant colors",
  "recommended_use": "how to use this as a reference"
}}

Return ONLY the JSON."""

    messages = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": uri}},
        {"type": "text", "text": prompt},
    ]}]
    return _replicate_run(PIXTRAL_MODEL, {"messages": messages, "max_tokens": 800})


def _parse_json_response(raw: str) -> dict:
    """Best-effort JSON parse from LLM output."""
    raw = raw.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try extracting the first {...} block
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end])
            except Exception:
                pass
    return {"raw_response": raw, "parse_error": True}


class ReferenceAnalyzerService:
    """Analyze reference videos/images to extract structured creative briefs."""

    @staticmethod
    def analyze_video(video_path: str, context: str = "") -> dict:
        """
        Analyze a reference video and return a structured brief.
        video_path: local path to uploaded video file.
        """
        logger.info(f"Analyzing reference video: {video_path}")

        frames = _extract_frames(video_path, max_frames=12)
        if not frames:
            raise ValueError("Could not extract frames from video")

        try:
            raw = _analyze_frames_with_pixtral(frames, context)
            brief = _parse_json_response(raw)
        except Exception as e:
            logger.error(f"Pixtral video analysis failed: {e}")
            # Return minimal fallback so pipeline isn't blocked
            brief = {
                "hook_style": "unknown",
                "visual_rhythm": "unknown",
                "scene_structure": [],
                "characters": [],
                "settings": [],
                "color_palette": "unknown",
                "camera_style": "unknown",
                "ad_arc": "unknown",
                "cta_style": "unknown",
                "estimated_duration": 30,
                "key_insights": [],
                "error": str(e),
            }

        # Clean up frame files
        for f in frames:
            try:
                os.remove(f)
            except Exception:
                pass

        brief["source_type"] = "video"
        brief["source_path"] = video_path
        return brief

    @staticmethod
    def analyze_image(image_path: str, context: str = "") -> dict:
        """Analyze a reference image (character or setting)."""
        logger.info(f"Analyzing reference image: {image_path}")

        try:
            raw = _analyze_image_with_pixtral(image_path, context)
            result = _parse_json_response(raw)
        except Exception as e:
            logger.error(f"Pixtral image analysis failed: {e}")
            result = {
                "type": "unknown",
                "description": "Analysis failed",
                "error": str(e),
            }

        result["source_type"] = "image"
        result["source_path"] = image_path
        return result

    @staticmethod
    def extract_brief_for_campaign(analysis: dict, vertical: str = "", offer: str = "") -> dict:
        """
        Convert a raw Pixtral analysis into a campaign brief dict
        ready to drive script + storyboard generation.
        """
        return {
            "vertical": vertical,
            "offer": offer,
            "hook_style": analysis.get("hook_style", ""),
            "visual_rhythm": analysis.get("visual_rhythm", "mixed"),
            "ad_arc": analysis.get("ad_arc", "problem-solution"),
            "cta_style": analysis.get("cta_style", "verbal"),
            "color_palette": analysis.get("color_palette", ""),
            "camera_style": analysis.get("camera_style", "mixed"),
            "reference_characters": analysis.get("characters", []),
            "reference_settings": analysis.get("settings", []),
            "key_insights": analysis.get("key_insights", []),
            "estimated_duration": analysis.get("estimated_duration", 30),
        }
