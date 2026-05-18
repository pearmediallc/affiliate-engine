"""
Reference analyzer — extracts a structured creative brief from a reference
video or image using Gemini 2.5 Flash (multimodal, already in stack).

For video: extracts up to 8 evenly-spaced frames, sends as inline images to Gemini.
For image: single Gemini call with inline image.

No Replicate. No Pixtral. No extra API key required.
"""
import os
import subprocess
import logging
import json
import tempfile
import base64
from typing import Optional

logger = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-2.5-flash"


def _image_to_b64(path: str) -> tuple[str, str]:
    """Return (base64_string, mime_type) for a local image file."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode(), mime


def _extract_frames(video_path: str, max_frames: int = 8) -> list[str]:
    """Extract up to max_frames evenly-spaced frames. Returns list of temp jpeg paths."""
    tmpdir = tempfile.mkdtemp(prefix="ref_frames_")

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

    interval = max(1, int(duration / max_frames))
    pattern = os.path.join(tmpdir, "frame_%03d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps=1/{interval},scale=640:-1",
        "-frames:v", str(max_frames),
        "-q:v", "5", pattern,
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)

    frames = sorted(
        os.path.join(tmpdir, f)
        for f in os.listdir(tmpdir)
        if f.endswith(".jpg")
    )
    return frames[:max_frames]


def _gemini_vision(parts: list, prompt: str) -> str:
    """Send image parts + prompt to Gemini Flash. Returns raw text."""
    from google import genai
    from google.genai import types
    from ..config import settings

    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY not configured")

    client = genai.Client(api_key=settings.gemini_api_key)

    contents = []
    for b64, mime in parts:
        contents.append(
            types.Part.from_bytes(data=base64.b64decode(b64), mime_type=mime)
        )
    contents.append(types.Part.from_text(text=prompt))

    response = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=contents,
    )
    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return text


def _analyze_frames_with_gemini(frames: list[str], context: str = "") -> str:
    """Send up to 8 key frames to Gemini Flash for ad analysis."""
    selected = frames[::max(1, len(frames) // 8)][:8]
    parts = [_image_to_b64(f) for f in selected]

    prompt = f"""Analyze these frames from a video advertisement{' (' + context + ')' if context else ''}.

Return a JSON object with these exact keys:
{{
  "hook_style": "opening hook type — direct|urgency|curiosity|social_proof|transformation|fear_of_loss",
  "visual_rhythm": "fast-cut|slow-build|talking-head|demo|montage|mixed",
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

Return ONLY the JSON, no markdown fences, no explanation."""
    return _gemini_vision(parts, prompt)


def _analyze_image_with_gemini(image_path: str, context: str = "") -> str:
    """Analyze a single reference image (character portrait or setting)."""
    b64, mime = _image_to_b64(image_path)
    parts = [(b64, mime)]

    prompt = f"""Analyze this reference image{' (' + context + ')' if context else ''} for use as a character or setting reference in ad creative.

Return a JSON object:
{{
  "type": "character|setting|product|other",
  "description": "detailed visual description",
  "character": {{
    "appearance": "hair, eyes, skin tone, build, clothing style",
    "estimated_age": "25-35",
    "expression": "confident|friendly|serious|warm",
    "consistency_prompt": "photo-realistic [detailed appearance], professional ad creative, high quality"
  }},
  "setting": {{
    "description": "location and environment details",
    "type": "interior|exterior|studio",
    "lighting": "natural|studio|dramatic|soft",
    "style_tags": ["modern", "bright", "professional"]
  }},
  "color_palette": "dominant colors and mood",
  "recommended_use": "how to use this as a generation reference"
}}

Return ONLY the JSON, no markdown."""
    return _gemini_vision(parts, prompt)


def _parse_json_response(raw: str) -> dict:
    """Best-effort JSON parse from LLM output."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end])
            except Exception:
                pass
    return {"raw_response": raw, "parse_error": True}


class ReferenceAnalyzerService:
    """Analyze reference videos/images to extract structured creative briefs using Gemini Flash."""

    @staticmethod
    def analyze_video(video_path: str, context: str = "") -> dict:
        """Analyze a reference video — extract frames, send to Gemini, return brief dict."""
        logger.info(f"Analyzing reference video with Gemini: {video_path}")

        frames = _extract_frames(video_path, max_frames=8)
        if not frames:
            raise ValueError("Could not extract frames from video")

        try:
            raw = _analyze_frames_with_gemini(frames, context)
            brief = _parse_json_response(raw)
        except Exception as e:
            logger.error(f"Gemini video analysis failed: {e}")
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
        finally:
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
        """Analyze a reference image (character portrait or setting)."""
        logger.info(f"Analyzing reference image with Gemini: {image_path}")

        try:
            raw = _analyze_image_with_gemini(image_path, context)
            result = _parse_json_response(raw)
        except Exception as e:
            logger.error(f"Gemini image analysis failed: {e}")
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
        """Convert a Gemini analysis into a campaign brief dict for script + storyboard generation."""
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
