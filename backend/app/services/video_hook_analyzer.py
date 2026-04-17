"""Service for analyzing video hooks using Gemini model"""
import logging
import base64
import subprocess
import tempfile
import os
import time
from typing import Optional
from ..config import settings

try:
    from google import genai
    GEMMA_AVAILABLE = True
except ImportError:
    GEMMA_AVAILABLE = False

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

logger = logging.getLogger(__name__)


class VideoHookAnalyzerService:
    """Analyzes video hooks using Gemma model for conversion optimization"""

    def __init__(self):
        if GEMMA_AVAILABLE and settings.gemini_api_key:
            # Use the new google.genai client with Gemini Flash for multimodal analysis
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.gemma_model = "gemini-2.5-flash"
        else:
            self.client = None
            logger.warning("Gemini model not available")

    def _download_video_url(self, video_url: str) -> str:
        """
        Download a video from a URL using yt-dlp to a temp file.

        Args:
            video_url: URL to download (YouTube, TikTok, Instagram, or direct link)

        Returns:
            Path to the downloaded temp file (caller must clean up)

        Raises:
            FileNotFoundError: If yt-dlp is not installed
            RuntimeError: If the download fails
        """
        tmp_dir = tempfile.mkdtemp(prefix="video_hook_")
        output_path = os.path.join(tmp_dir, "video.mp4")

        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "-f", "best[filesize<50M]",
                    "--no-playlist",
                    "-o", output_path,
                    video_url,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            # Clean up the temp dir on failure
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise FileNotFoundError(
                "yt-dlp is not installed. Install it with: pip install yt-dlp"
            )
        except subprocess.TimeoutExpired:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError("Video download timed out after 120 seconds")

        if result.returncode != 0:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(f"yt-dlp download failed: {result.stderr.strip()}")

        # yt-dlp may choose a different extension; find the actual file
        if not os.path.exists(output_path):
            # Look for any file yt-dlp wrote in the temp dir
            files = os.listdir(tmp_dir)
            if files:
                output_path = os.path.join(tmp_dir, files[0])
            else:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise RuntimeError("yt-dlp did not produce an output file")

        logger.info(f"Downloaded video to {output_path}")
        return output_path

    async def analyze_video_hook(
        self,
        video_url: str,
        hook_duration_seconds: int = 5,
    ) -> dict:
        """
        Analyze the hook (first 5-10 seconds) of a video to understand conversion factors.

        Downloads the video via yt-dlp, then uploads it to Gemini for multimodal analysis.

        Args:
            video_url: URL to video (YouTube, TikTok, or direct video link)
            hook_duration_seconds: Duration of hook to analyze (typically 5-10 seconds)

        Returns:
            Dictionary with hook analysis, key elements, and effectiveness factors
        """
        if not self.client:
            raise ValueError("Gemini model not configured")

        video_path = None
        try:
            video_id, platform = self._parse_video_url(video_url)
            logger.info(f"Analyzing video hook from {platform}: {video_id}")

            # Download the video so we can send actual video content to Gemini
            video_path = self._download_video_url(video_url)

            # Reuse the file-based analysis flow
            result = await self.analyze_video_file(
                video_path=video_path,
                filename=f"{platform}_{video_id}",
                hook_duration_seconds=hook_duration_seconds,
            )

            # Override metadata to reflect the original URL source
            result["video_url"] = video_url
            result["platform"] = platform
            result["video_id"] = video_id

            return result

        except Exception as e:
            logger.error(f"Video hook analysis failed: {str(e)}", exc_info=True)
            raise
        finally:
            # Clean up downloaded temp file
            if video_path and os.path.exists(video_path):
                import shutil
                tmp_dir = os.path.dirname(video_path)
                shutil.rmtree(tmp_dir, ignore_errors=True)
                logger.info(f"Cleaned up temp video directory: {tmp_dir}")

    async def analyze_with_transcript(
        self,
        video_url: str,
        transcript_text: Optional[str] = None,
        hook_duration_seconds: int = 5,
    ) -> dict:
        """
        Analyze video hook with transcript for more detailed insights

        Args:
            video_url: URL to video
            transcript_text: Optional transcript or script of the video
            hook_duration_seconds: Duration of hook to analyze

        Returns:
            Dictionary with comprehensive hook analysis including transcript insights
        """
        if not self.client:
            raise ValueError("Gemma model not configured")

        try:
            video_id, platform = self._parse_video_url(video_url)

            transcript_context = ""
            if transcript_text:
                transcript_context = f"""
FULL TRANSCRIPT:
{transcript_text}

"""

            analysis_prompt = f"""Analyze this video transcript for affiliate marketing optimization.

PLATFORM: {platform}
{transcript_context}

Provide detailed analysis of:

1. **SCRIPT ANALYSIS**:
   - Opening hook line (what's said in first 3 seconds?)
   - Psychological triggers in script
   - Pacing and delivery style
   - Call-to-action language

2. **SPEECH PATTERNS**:
   - Tone (urgent, confident, curious, emotional)
   - Pace (slow/fast)
   - Pauses/emphasis on key words
   - Accent/delivery style

3. **VISUAL + AUDIO SYNERGY**:
   - How do visuals support the script?
   - Background music/sound effects
   - Text overlays matching voiceover

4. **CONVERSION MECHANICS**:
   - What problem does it identify?
   - What desire does it create?
   - What action does it request?
   - Urgency factors

5. **SIMILAR AD FORMULAS**:
   - What proven ad formula is this using? (PAS, AIDA, BAB, StoryBrand, etc.)
   - Which copywriting framework matches?
   - Psychological angles employed

6. **REPLICATION GUIDE**:
   - Step-by-step breakdown to create similar hook
   - Timing recommendations
   - Key phrases to copy (legally)
   - Visual style to emulate

7. **VERTICAL APPLICABILITY**:
   - Which affiliate verticals could use this approach?
   - Product/service types that match
   - Audience segments most receptive

Format as actionable insights for creating high-converting affiliate video ads."""

            response = self.client.models.generate_content(
                model=self.gemma_model,
                contents=[analysis_prompt],
            )

            detailed_analysis = response.text

            return {
                "video_url": video_url,
                "platform": platform,
                "video_id": video_id,
                "hook_duration_seconds": hook_duration_seconds,
                "has_transcript": bool(transcript_text),
                "transcript_snippet": transcript_text[:500] if transcript_text else None,
                "detailed_analysis": detailed_analysis,
                "analysis_model": self.gemma_model,
                "analysis_type": "hook_with_transcript",
            }

        except Exception as e:
            logger.error(f"Transcript analysis failed: {str(e)}", exc_info=True)
            raise

    async def analyze_video_file(
        self,
        video_path: str,
        filename: str,
        hook_duration_seconds: int = 5,
    ) -> dict:
        """
        Analyze an uploaded video file's hook using Gemini with actual video content

        Args:
            video_path: Local path to the uploaded video file
            filename: Original filename
            hook_duration_seconds: Duration of hook to analyze

        Returns:
            Dictionary with hook analysis
        """
        if not self.client:
            raise ValueError("Gemini model not configured")

        try:
            logger.info(f"Analyzing uploaded video file: {filename}")

            # Upload the video file to Gemini and wait for it to be processed
            uploaded_file = self.client.files.upload(file=video_path)

            # Poll until the file is ACTIVE (Gemini needs time to process video)
            max_wait = 60  # seconds
            waited = 0
            while uploaded_file.state.name != "ACTIVE" and waited < max_wait:
                logger.info(f"Waiting for video upload to process... state={uploaded_file.state.name}")
                time.sleep(2)
                waited += 2
                uploaded_file = self.client.files.get(name=uploaded_file.name)

            if uploaded_file.state.name != "ACTIVE":
                raise ValueError(f"Video file processing timed out (state: {uploaded_file.state.name})")

            analysis_prompt = f"""Analyze this video's hook (first {hook_duration_seconds} seconds) for affiliate marketing effectiveness.

VIDEO FILE: {filename}
HOOK DURATION: {hook_duration_seconds} seconds

Watch the first {hook_duration_seconds} seconds carefully and analyze:

1. **HOOK TYPE**: What type of hook is this? (Visual shock, Curiosity gap, Problem statement, Benefit teaser, etc.)

2. **ATTENTION GRABBERS** (0-3 seconds):
   - What makes you stop and watch?
   - Visual elements used (colors, movement, text, faces)
   - Audio/music used to capture attention

3. **CONVERSION ELEMENTS**:
   - Emotional trigger (fear, curiosity, desire, urgency, social proof, etc.)
   - Psychology used (scarcity, FOMO, aspiration, etc.)
   - How does it create viewer engagement?

4. **TEXT/CTA STRATEGY**:
   - What text overlays are used?
   - Is there a CTA? If so, what is it?
   - Text placement and readability

5. **EFFECTIVENESS SCORE**:
   - Rate the hook effectiveness: 1-10
   - Why is it effective or ineffective?
   - What makes people want to click/swipe?

6. **KEY TAKEAWAYS FOR AFFILIATE ADS**:
   - What can we learn from this hook?
   - How can we apply these techniques to affiliate product ads?
   - Similar products/verticals this approach would work for

7. **RECOMMENDATIONS**:
   - How would you improve this hook?
   - What variations would work better?
   - Multi-platform applicability (TikTok, Instagram, YouTube, Facebook)

Format the response as clear, actionable insights that can be used to create similar high-converting ads."""

            response = self.client.models.generate_content(
                model=self.gemma_model,
                contents=[uploaded_file, analysis_prompt],
            )

            hook_analysis = response.text

            logger.info(f"Hook analysis completed for uploaded file: {filename}")

            return {
                "video_url": f"uploaded:{filename}",
                "platform": "Direct Video",
                "video_id": filename,
                "hook_duration_seconds": hook_duration_seconds,
                "hook_analysis": hook_analysis,
                "analysis_model": self.gemma_model,
                "analysis_type": "hook_effectiveness",
            }

        except Exception as e:
            logger.error(f"Video file hook analysis failed: {str(e)}", exc_info=True)
            raise

    async def _extract_frames(self, video_url: str, duration: int) -> list:
        """
        Extract frames from video for analysis

        Args:
            video_url: Video URL
            duration: Duration in seconds to extract

        Returns:
            List of base64-encoded frames
        """
        if not OPENCV_AVAILABLE:
            logger.warning("OpenCV not available, skipping frame extraction")
            return []

        try:
            # This is a placeholder - in production, would actually extract frames
            logger.info(f"Extracting frames from {video_url} (first {duration}s)")
            # Frame extraction would happen here using cv2
            return []

        except Exception as e:
            logger.warning(f"Frame extraction failed: {str(e)}")
            return []

    @staticmethod
    def _parse_video_url(video_url: str) -> tuple[str, str]:
        """
        Parse video URL to extract video ID and platform

        Args:
            video_url: Video URL

        Returns:
            Tuple of (video_id, platform)
        """
        # YouTube
        if "youtube.com" in video_url or "youtu.be" in video_url:
            if "youtu.be/" in video_url:
                video_id = video_url.split("youtu.be/")[1].split("?")[0]
            else:
                video_id = video_url.split("v=")[1].split("&")[0] if "v=" in video_url else "unknown"
            return video_id, "YouTube"

        # TikTok
        elif "tiktok.com" in video_url:
            video_id = video_url.split("/video/")[1].split("?")[0] if "/video/" in video_url else "unknown"
            return video_id, "TikTok"

        # Instagram
        elif "instagram.com" in video_url:
            video_id = video_url.split("/p/")[1].split("/")[0] if "/p/" in video_url else "unknown"
            return video_id, "Instagram"

        # Generic video link
        else:
            video_id = video_url.split("/")[-1].split(".")[0]
            return video_id, "Direct Video"
