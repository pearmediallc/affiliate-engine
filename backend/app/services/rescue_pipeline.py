"""
Rescue iteration video pipeline.

Turns raw Runway-generated shot videos into a curated UGC ad with:
  1. TTS voiceover per scene (OpenAI TTS HD)
  2. Lip-synced talking head for spokesperson shots (Kie.ai InfiniteTalk
     or Higgsfield Speak — whichever provider is configured)
  3. Audio-overlay for b-roll shots (no lip-sync needed)
  4. Per-shot upload to S3 under campaigns/<slug>/...
  5. ffmpeg concat into single timeline
  6. Whisper word-level transcription of assembled audio
  7. ASS karaoke captions burned into final video
  8. Final upload to S3, variation.final_video_url updated

Replaces AutoEditorService.render_variation in the rescue flow.

Memory-aware: every ffmpeg invocation runs in a subprocess and we throw
out temp dirs eagerly, so the parent FastAPI worker doesn't accumulate
buffers.
"""
import os
import re
import time
import base64
import logging
import asyncio
import tempfile
import subprocess
from typing import Optional
import httpx

from ..config import settings
from .storage import StorageService
from .speech_generator import SpeechGeneratorService
from .lip_sync import LipSyncService

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _slugify(name: Optional[str]) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", (name or "").strip().lower()).strip("-")
    return s or "unknown"


def _ffmpeg(*args, timeout: int = 300):
    """Run ffmpeg with capture-suppressed stdout to avoid filling Python memory.
    Raises RuntimeError on non-zero return."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if r.returncode != 0:
        msg = (r.stderr or b"").decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"ffmpeg failed: {msg}")
    return r


def _ensure_local(url: str, local_path: str) -> bool:
    """Download a file from our private S3 bucket via boto3, else from a
    public URL via httpx. Returns True on success."""
    if not url:
        return False
    s3_key = StorageService.parse_s3_key(url)
    if s3_key and StorageService.download_file(s3_key, local_path):
        return True
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with open(local_path, "wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
        return True
    except Exception as e:
        logger.warning(f"rescue_pipeline: download failed for {url}: {e}")
        return False


def _upload_to_s3(local_path: str, key: str) -> Optional[str]:
    return StorageService.upload_file(local_path, key)


# ── stage 1: TTS per scene ───────────────────────────────────────────────────

def _generate_tts_to_s3(text: str, s3_key: str, voice: str = "Kore") -> str:
    """Call SpeechGeneratorService → MP3 bytes → upload to S3 → return URL."""
    svc = SpeechGeneratorService()
    # generate_speech is async; this code path runs inside a FastAPI bg task
    # which has no event loop, so asyncio.run is safe.
    result = asyncio.run(
        svc.generate_speech(text=text, voice=voice, output_format="mp3")
    )
    audio_b64 = result.get("audio_data") or result.get("audio_base64")
    if not audio_b64:
        raise RuntimeError(f"TTS returned no audio_data: {list(result.keys())}")
    audio_bytes = base64.b64decode(audio_b64)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    try:
        tmp.write(audio_bytes)
        tmp.close()
        url = _upload_to_s3(tmp.name, s3_key)
        if not url:
            raise RuntimeError(f"TTS upload to {s3_key} failed")
        return url
    finally:
        try: os.unlink(tmp.name)
        except FileNotFoundError: pass


# ── stage 2a: lip-sync (spokesperson / hero shots) ───────────────────────────

def _extract_first_frame(video_url: str, out_jpg: str):
    """Pull frame 1 of a video into a JPG (used as the 'still image' input
    for the lip-sync provider)."""
    with tempfile.TemporaryDirectory() as td:
        v = os.path.join(td, "src.mp4")
        if not _ensure_local(video_url, v):
            raise RuntimeError(f"could not fetch video for frame extract: {video_url}")
        _ffmpeg("-i", v, "-vframes", "1", "-q:v", "2", out_jpg, timeout=60)


def _lip_sync(image_url: str, audio_url: str, timeout: int = 600) -> str:
    """Submit lip-sync, poll, return resulting video URL."""
    job = LipSyncService.start_generation(image_url, audio_url, model="auto")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(8)
        status = LipSyncService.check_status(job)
        st = (status.get("status") or "").lower()
        if st in ("completed", "succeeded", "success", "done"):
            url = status.get("video_url") or status.get("download_url") or status.get("url")
            if not url:
                raise RuntimeError(f"lip-sync completed but no URL: {status}")
            return url
        if st in ("failed", "error", "cancelled", "canceled"):
            raise RuntimeError(f"lip-sync failed: {status}")
    raise TimeoutError(f"lip-sync timed out after {timeout}s for job {job}")


# ── stage 2b: audio overlay (b-roll shots) ───────────────────────────────────

def _mux_audio_onto_video(video_url: str, audio_url: str, out_local: str):
    """Replace any existing audio track with the provided audio. Cuts at the
    shorter of video/audio so a 5s video doesn't get padded with silence."""
    with tempfile.TemporaryDirectory() as td:
        v = os.path.join(td, "v.mp4")
        a = os.path.join(td, "a.mp3")
        if not _ensure_local(video_url, v):
            raise RuntimeError(f"could not fetch video {video_url}")
        if not _ensure_local(audio_url, a):
            raise RuntimeError(f"could not fetch audio {audio_url}")
        _ffmpeg(
            "-i", v, "-i", a,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            out_local, timeout=120,
        )


# ── stage 3: Whisper word-level transcription ────────────────────────────────

def _whisper_words(audio_local: str) -> list[dict]:
    """OpenAI Whisper API with word-level timestamps. Returns [{word,start,end}]."""
    # Lazy import — the openai SDK is heavy and Phase A deferred it.
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    with open(audio_local, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )
    words = []
    for w in (getattr(result, "words", None) or []):
        words.append({
            "word": getattr(w, "word", str(w)),
            "start": float(getattr(w, "start", 0.0)),
            "end": float(getattr(w, "end", 0.0)),
        })
    return words


# ── stage 4: ASS karaoke captions ────────────────────────────────────────────

def _fmt_ass_time(t: float) -> str:
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); cs = int((t * 100) % 100)
    return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"


def _words_to_ass(
    words: list[dict],
    width: int = 1080,
    height: int = 1920,
    words_per_line: int = 4,
) -> str:
    """Group word timestamps into N-word phrases and emit an ASS subtitle
    file. Bottom-center, large bold white text with black outline — the
    short-form vertical ad style most editors use."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,80,80,240,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if not words:
        return header
    lines = []
    for i in range(0, len(words), words_per_line):
        chunk = words[i:i + words_per_line]
        start = chunk[0]["start"]
        end = chunk[-1]["end"]
        text = " ".join((w["word"] or "").strip() for w in chunk).strip()
        # ASS doesn't like { or } in text — escape
        text = text.replace("{", "(").replace("}", ")")
        lines.append(
            f"Dialogue: 0,{_fmt_ass_time(start)},{_fmt_ass_time(end)},Default,,0,0,0,,{text}"
        )
    return header + "\n".join(lines) + "\n"


def _burn_subtitles(video_in: str, ass_path: str, video_out: str):
    """Re-encode video with subtitles burned in via ffmpeg subtitles filter."""
    # ffmpeg subtitles filter path escaping: backslash colons.
    escaped = ass_path.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    _ffmpeg(
        "-i", video_in,
        "-vf", f"subtitles='{escaped}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        video_out, timeout=600,
    )


# ── main entry point ─────────────────────────────────────────────────────────

def render_full_video(
    campaign_id: str,
    variation_id: str,
    lip_sync_spokesperson: bool = True,
) -> dict:
    """End-to-end rescue video assembly. Returns {final_url, ...}.

    Side effects:
      - uploads per-scene TTS to campaigns/<slug>/audio/scene_N.mp3
      - uploads stills + lip-synced clips to campaigns/<slug>/...
      - uploads final video to campaigns/<slug>/final.mp4
      - sets variation.final_video_url, variation.status='completed'
    """
    from ..database import SessionLocal
    from ..models.campaign import Campaign, Shot, Variation

    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"campaign {campaign_id} not found")
        variation = db.query(Variation).filter(Variation.id == variation_id).first()
        if not variation:
            raise ValueError(f"variation {variation_id} not found")

        shots = (
            db.query(Shot)
            .filter(Shot.variation_id == variation_id, Shot.status == "completed")
            .order_by(Shot.sequence_num)
            .all()
        )
        if not shots:
            raise ValueError("no completed shots in variation")

        storyboard = campaign.storyboard or []
        slug = _slugify(campaign.name or campaign_id)

        logger.info(
            f"rescue_pipeline: starting variation={variation_id[:8]} "
            f"slug={slug} shots={len(shots)} lipsync={lip_sync_spokesperson}"
        )

        with tempfile.TemporaryDirectory(prefix="rescue_") as workdir:
            processed_urls: list[str] = []

            # Phase 1 — per-shot TTS + (lipsync OR audio overlay)
            for i, shot in enumerate(shots):
                scene = storyboard[i] if i < len(storyboard) else {}
                narration = (scene.get("narration_text") or "").strip()

                if not narration:
                    logger.info(f"rescue_pipeline: scene {i+1} no narration, using raw shot")
                    processed_urls.append(shot.video_url)
                    continue

                # TTS
                tts_key = f"campaigns/{slug}/audio/scene_{i+1:02d}.mp3"
                logger.info(f"rescue_pipeline: TTS scene {i+1} ({len(narration)} chars)")
                audio_url = _generate_tts_to_s3(narration, tts_key)

                shot_type = (shot.shot_type or "").lower()
                use_lipsync = lip_sync_spokesperson and shot_type in ("spokesperson", "hero")

                if use_lipsync:
                    logger.info(f"rescue_pipeline: lip-sync scene {i+1} (shot_type={shot_type})")
                    still_local = os.path.join(workdir, f"still_{i+1:02d}.jpg")
                    _extract_first_frame(shot.video_url, still_local)
                    still_key = f"campaigns/{slug}/stills/scene_{i+1:02d}.jpg"
                    still_url = _upload_to_s3(still_local, still_key)
                    if not still_url:
                        raise RuntimeError(f"failed to upload still for scene {i+1}")
                    synced_url = _lip_sync(still_url, audio_url)
                    processed_urls.append(synced_url)
                else:
                    logger.info(f"rescue_pipeline: audio overlay scene {i+1} (shot_type={shot_type})")
                    muxed_local = os.path.join(workdir, f"muxed_{i+1:02d}.mp4")
                    _mux_audio_onto_video(shot.video_url, audio_url, muxed_local)
                    muxed_key = f"campaigns/{slug}/shots-with-audio/scene_{i+1:02d}.mp4"
                    muxed_url = _upload_to_s3(muxed_local, muxed_key)
                    if not muxed_url:
                        raise RuntimeError(f"failed to upload muxed scene {i+1}")
                    processed_urls.append(muxed_url)

            # Phase 2 — pull every processed clip back to disk + concat
            logger.info(f"rescue_pipeline: assembling {len(processed_urls)} clips")
            local_clips: list[str] = []
            for i, url in enumerate(processed_urls):
                local = os.path.join(workdir, f"clip_{i:02d}.mp4")
                if _ensure_local(url, local):
                    local_clips.append(local)
                else:
                    logger.warning(f"rescue_pipeline: skipping clip {i+1} — fetch failed")
            if not local_clips:
                raise RuntimeError("no clips to stitch")

            concat_list = os.path.join(workdir, "concat.txt")
            with open(concat_list, "w") as fh:
                for c in local_clips:
                    fh.write(f"file '{c}'\n")
            stitched = os.path.join(workdir, "stitched.mp4")
            _ffmpeg(
                "-f", "concat", "-safe", "0", "-i", concat_list,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                stitched, timeout=300,
            )

            # Phase 3 — Whisper transcribe assembled audio
            audio_path = os.path.join(workdir, "audio.mp3")
            _ffmpeg("-i", stitched, "-vn", "-acodec", "libmp3lame", "-ab", "128k", audio_path)
            logger.info("rescue_pipeline: Whisper word-level transcription")
            try:
                words = _whisper_words(audio_path)
            except Exception as e:
                logger.warning(f"rescue_pipeline: Whisper failed, shipping without captions: {e}")
                words = []

            # Phase 4 — burn karaoke captions (skip if Whisper failed)
            if words:
                ass_path = os.path.join(workdir, "captions.ass")
                with open(ass_path, "w", encoding="utf-8") as fh:
                    fh.write(_words_to_ass(words))
                final_path = os.path.join(workdir, "final.mp4")
                logger.info(f"rescue_pipeline: burning {len(words)} words of captions")
                _burn_subtitles(stitched, ass_path, final_path)
            else:
                final_path = stitched

            # Phase 5 — upload final
            final_key = f"campaigns/{slug}/final.mp4"
            final_url = _upload_to_s3(final_path, final_key)
            if not final_url:
                raise RuntimeError("failed to upload final video")
            logger.info(f"rescue_pipeline: final uploaded to {final_url}")

            variation.final_video_url = final_url
            variation.status = "completed"
            db.commit()

            return {
                "final_url": final_url,
                "clips_assembled": len(local_clips),
                "scenes_with_lipsync": sum(
                    1 for i, s in enumerate(shots)
                    if (s.shot_type or "").lower() in ("spokesperson", "hero")
                    and (storyboard[i] if i < len(storyboard) else {}).get("narration_text", "").strip()
                ) if lip_sync_spokesperson else 0,
                "words_captioned": len(words),
            }
    finally:
        db.close()
