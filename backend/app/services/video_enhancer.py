"""Video enhancer - post-processing for generated videos using ffmpeg"""
import os
import uuid
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)

ENHANCED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "generated_videos")
os.makedirs(ENHANCED_DIR, exist_ok=True)


class VideoEnhancerService:
    """Post-processes videos using ffmpeg"""

    @staticmethod
    def _run_ffmpeg(cmd: list, timeout: int = 120) -> bool:
        """Run an ffmpeg command. Returns True on success."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode != 0:
                logger.error(f"ffmpeg error: {result.stderr[:500]}")
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg timed out")
            return False
        except FileNotFoundError:
            logger.error("ffmpeg not found")
            return False

    @staticmethod
    def add_background_music(
        video_path: str,
        audio_path: str,
        music_volume: float = 0.15,
        output_path: str = None,
    ) -> Optional[str]:
        """Mix background music into a video at specified volume"""
        output = output_path or os.path.join(ENHANCED_DIR, f"music_{uuid.uuid4().hex[:8]}.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", f"[1:a]volume={music_volume}[bg];[0:a][bg]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", output,
        ]
        if VideoEnhancerService._run_ffmpeg(cmd):
            return output
        return None

    @staticmethod
    def add_text_overlay(
        video_path: str,
        text: str,
        position: str = "bottom",
        font_size: int = 36,
        font_color: str = "white",
        bg_opacity: float = 0.5,
        output_path: str = None,
    ) -> Optional[str]:
        """Burn text overlay onto video using ffmpeg drawtext filter"""
        output = output_path or os.path.join(ENHANCED_DIR, f"text_{uuid.uuid4().hex[:8]}.mp4")

        # Position mapping
        pos_map = {
            "top": "x=(w-text_w)/2:y=40",
            "center": "x=(w-text_w)/2:y=(h-text_h)/2",
            "bottom": "x=(w-text_w)/2:y=h-text_h-40",
        }
        pos_str = pos_map.get(position, pos_map["bottom"])

        # Escape text for ffmpeg
        escaped = text.replace("'", "'\\''").replace(":", "\\:")

        filter_str = (
            f"drawbox=x=0:y={'h-80' if position == 'bottom' else '0' if position == 'top' else '(h-80)/2'}:w=iw:h=80:"
            f"color=black@{bg_opacity}:t=fill,"
            f"drawtext=text='{escaped}':{pos_str}:fontsize={font_size}:"
            f"fontcolor={font_color}:borderw=2:bordercolor=black@0.5"
        )

        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", filter_str,
            "-c:a", "copy", output,
        ]
        if VideoEnhancerService._run_ffmpeg(cmd):
            return output
        return None

    @staticmethod
    def resize_for_platform(
        video_path: str,
        platform: str = "tiktok",
        output_path: str = None,
    ) -> Optional[str]:
        """Resize/crop video for specific social media platform"""
        output = output_path or os.path.join(ENHANCED_DIR, f"{platform}_{uuid.uuid4().hex[:8]}.mp4")

        platform_specs = {
            "tiktok": {"ratio": "9:16", "filter": "crop=ih*9/16:ih,scale=1080:1920"},
            "reels": {"ratio": "9:16", "filter": "crop=ih*9/16:ih,scale=1080:1920"},
            "youtube": {"ratio": "16:9", "filter": "crop=iw:iw*9/16,scale=1920:1080"},
            "instagram": {"ratio": "1:1", "filter": "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080"},
            "facebook": {"ratio": "1:1", "filter": "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080"},
        }

        spec = platform_specs.get(platform, platform_specs["tiktok"])

        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", spec["filter"],
            "-c:a", "copy", output,
        ]
        if VideoEnhancerService._run_ffmpeg(cmd):
            return output
        return None

    @staticmethod
    def apply_color_grade(
        video_path: str,
        preset: str = "warm",
        output_path: str = None,
    ) -> Optional[str]:
        """Apply color grading to video using ffmpeg eq/colorbalance filters"""
        output = output_path or os.path.join(ENHANCED_DIR, f"graded_{uuid.uuid4().hex[:8]}.mp4")

        presets = {
            "warm": "colorbalance=rs=0.05:gs=0:bs=-0.05:rm=0.05:gm=0:bm=-0.03",
            "cool": "colorbalance=rs=-0.05:gs=0:bs=0.08:rm=-0.03:gm=0:bm=0.05",
            "cinematic": "eq=contrast=1.1:brightness=0.02:saturation=0.85,colorbalance=rs=0.02:gs=-0.02:bs=0.05",
            "vintage": "eq=contrast=1.05:brightness=-0.02:saturation=0.7,colorbalance=rs=0.08:gs=0.03:bs=-0.05",
            "vivid": "eq=contrast=1.15:brightness=0.03:saturation=1.3",
        }

        filter_str = presets.get(preset, presets["warm"])

        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", filter_str,
            "-c:a", "copy", output,
        ]
        if VideoEnhancerService._run_ffmpeg(cmd):
            return output
        return None

    @staticmethod
    def enhance_full(
        video_path: str,
        color_grade: str = "cinematic",
        text: str = None,
        text_position: str = "bottom",
        platform: str = None,
        music_path: str = None,
        music_volume: float = 0.15,
    ) -> dict:
        """Apply full enhancement pipeline to a video"""
        current = video_path
        steps = []

        # Step 1: Color grade
        if color_grade and color_grade != "none":
            result = VideoEnhancerService.apply_color_grade(current, color_grade)
            if result:
                current = result
                steps.append(f"color_grade:{color_grade}")

        # Step 2: Text overlay
        if text:
            result = VideoEnhancerService.add_text_overlay(current, text, text_position)
            if result:
                current = result
                steps.append(f"text_overlay:{text_position}")

        # Step 3: Background music
        if music_path and os.path.isfile(music_path):
            result = VideoEnhancerService.add_background_music(current, music_path, music_volume)
            if result:
                current = result
                steps.append("background_music")

        # Step 4: Platform resize
        if platform:
            result = VideoEnhancerService.resize_for_platform(current, platform)
            if result:
                current = result
                steps.append(f"resize:{platform}")

        return {
            "enhanced_path": current,
            "enhanced_filename": os.path.basename(current),
            "steps_applied": steps,
            "download_url": f"/api/v1/video/download/{os.path.basename(current)}",
        }

    @staticmethod
    def get_options() -> dict:
        return {
            "color_grades": ["none", "warm", "cool", "cinematic", "vintage", "vivid"],
            "platforms": ["tiktok", "reels", "youtube", "instagram", "facebook"],
            "text_positions": ["top", "center", "bottom"],
        }
