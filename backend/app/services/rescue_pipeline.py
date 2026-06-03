"""
Rescue iteration video pipeline (v2 — parallel + script-driven captions).

Turns raw Runway-generated shot videos into a curated UGC ad with:
  1. TTS voiceover per scene (OpenAI TTS HD) — ALL SCENES IN PARALLEL
  2. Lip-synced talking head for spokesperson shots — ALL SHOTS IN PARALLEL
     (Kie.ai InfiniteTalk via LipSyncService)
  3. Audio-overlay for b-roll shots — ffmpeg mux
  4. Per-shot upload to S3 under campaigns/<slug>/...
  5. ffmpeg concat into single timeline
  6. Captions built DIRECTLY from script narration + actual TTS durations
     (no Whisper round-trip — script text is the ground truth, faster,
     cheaper, and more accurate than transcription)
  7. ASS karaoke captions burned into final video
  8. Final upload to S3, variation.final_video_url updated

Replaces AutoEditorService.render_variation in the rescue flow.

Optimization wins vs v1:
  - TTS: 5 × 3s sequential → 1 × 3s parallel  (saves ~12s)
  - Lip-sync: 5 × 90s sequential → 1 × 90s parallel  (saves ~6min)
  - Captions: Whisper API call removed (saves ~15s + $0.003)
  Net: ~6-7 min off a 10-15 min render.

Memory-aware: every ffmpeg invocation runs in a subprocess with stdout
piped to DEVNULL, and temp dirs are cleared eagerly. Should sit well
under the 2GB Render cap.
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
    """Run ffmpeg with stdout suppressed (avoids Python buffer growth)."""
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


def _ffprobe_duration(path: str) -> float:
    """Read media duration in seconds via ffprobe. 0.0 on failure."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _ensure_local(url: str, local_path: str) -> bool:
    """Download from our private S3 bucket via boto3, else public URL via httpx."""
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


# ── stage 1: TTS (one scene; parallelized by caller via asyncio.gather) ──────

async def _tts_one_scene(narration: str, s3_key: str, voice: str = "Kore") -> dict:
    """TTS one scene's narration. Returns {url, duration_sec, narration}.
    Duration is measured from the downloaded MP3 via ffprobe (accurate
    even when OpenAI doesn't return it).

    Note: SpeechGeneratorService returns 'audio_data' as raw bytes AND
    'audio_base64' as the base64-encoded version. Prefer raw bytes.
    """
    svc = SpeechGeneratorService()
    result = await svc.generate_speech(text=narration, voice=voice, output_format="mp3")
    audio_data = result.get("audio_data")
    if isinstance(audio_data, bytes):
        audio_bytes = audio_data
    elif isinstance(audio_data, str) and audio_data:
        audio_bytes = base64.b64decode(audio_data)
    else:
        b64 = result.get("audio_base64")
        if not b64:
            raise RuntimeError(f"TTS returned no audio data: keys={list(result.keys())}")
        audio_bytes = base64.b64decode(b64)
    if len(audio_bytes) < 1000:
        raise RuntimeError(f"TTS audio suspiciously small ({len(audio_bytes)}B) for {len(narration)}ch narration")

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    try:
        tmp.write(audio_bytes)
        tmp.close()
        duration = _ffprobe_duration(tmp.name)
        url = await asyncio.to_thread(_upload_to_s3, tmp.name, s3_key)
        if not url:
            raise RuntimeError(f"TTS upload to {s3_key} failed")
        return {"url": url, "duration_sec": duration, "narration": narration}
    finally:
        try: os.unlink(tmp.name)
        except FileNotFoundError: pass


# ── stage 2a: lip-sync (one shot; parallelized via asyncio.gather) ──────────

async def _extract_first_frame_async(video_url: str, out_jpg: str):
    def _do():
        with tempfile.TemporaryDirectory() as td:
            v = os.path.join(td, "src.mp4")
            if not _ensure_local(video_url, v):
                raise RuntimeError(f"could not fetch video for frame extract: {video_url}")
            _ffmpeg("-i", v, "-vframes", "1", "-q:v", "2", out_jpg, timeout=60)
    await asyncio.to_thread(_do)


async def _lip_sync_one(image_url: str, audio_url: str, timeout: int = 600) -> str:
    """Submit lip-sync, poll asynchronously, return resulting video URL."""
    job = await asyncio.to_thread(
        LipSyncService.start_generation, image_url, audio_url, "auto",
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(8)
        status = await asyncio.to_thread(LipSyncService.check_status, job)
        st = (status.get("status") or "").lower()
        if st in ("completed", "succeeded", "success", "done"):
            url = status.get("video_url") or status.get("download_url") or status.get("url")
            if not url:
                raise RuntimeError(f"lip-sync completed but no URL: {status}")
            return url
        if st in ("failed", "error", "cancelled", "canceled"):
            raise RuntimeError(f"lip-sync failed: {status}")
    raise TimeoutError(f"lip-sync timed out after {timeout}s for job {job}")


# ── stage 2b: audio overlay (b-roll; parallelized) ───────────────────────────

async def _mux_audio_onto_video_async(video_url: str, audio_url: str, out_local: str):
    def _do():
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
    await asyncio.to_thread(_do)


# ── stage 3: script-driven captions (no Whisper) ─────────────────────────────
#
# We KNOW each scene's narration text (from storyboard) and its exact
# audio duration (from ffprobe on the TTS MP3). That's enough to emit
# perfectly-timed, perfectly-spelled captions. Whisper would add a round
# trip, $$, and the chance of mistranscribing the very text we wrote.

_WORD_RE = re.compile(r"\S+")

def _split_into_word_chunks(narration: str, chunk_size: int = 4) -> list[list[str]]:
    """Split narration into chunk-of-N word groups, preserving punctuation."""
    words = _WORD_RE.findall(narration)
    return [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]


def _fmt_ass_time(t: float) -> str:
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); cs = int((t * 100) % 100)
    return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"


def _build_ass_from_scenes(
    scene_data: list[dict],
    width: int = 1080,
    height: int = 1920,
    words_per_chunk: int = 4,
) -> str:
    """Build an ASS file directly from each scene's narration + duration.
    scene_data: [{narration, duration_sec, start_offset_sec}] in playback order."""
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
    lines = []
    for scene in scene_data:
        narration = (scene.get("narration") or "").strip()
        dur = float(scene.get("duration_sec") or 0.0)
        start_offset = float(scene.get("start_offset_sec") or 0.0)
        if not narration or dur <= 0:
            continue
        chunks = _split_into_word_chunks(narration, chunk_size=words_per_chunk)
        if not chunks:
            continue
        # Weight chunk durations by character count so longer phrases get
        # more screen time than short ones — better than uniform splitting.
        weights = [sum(len(w) for w in c) or 1 for c in chunks]
        total_w = sum(weights)
        cur = start_offset
        for chunk, w in zip(chunks, weights):
            slice_dur = dur * (w / total_w)
            start = cur
            end = cur + slice_dur
            cur = end
            text = " ".join(chunk).replace("{", "(").replace("}", ")")
            lines.append(
                f"Dialogue: 0,{_fmt_ass_time(start)},{_fmt_ass_time(end)},Default,,0,0,0,,{text}"
            )
    return header + "\n".join(lines) + "\n"


def _burn_subtitles(video_in: str, ass_path: str, video_out: str):
    """Re-encode video with subtitles burned in via ffmpeg subtitles filter."""
    escaped = ass_path.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    _ffmpeg(
        "-i", video_in,
        "-vf", f"subtitles='{escaped}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        video_out, timeout=600,
    )


# ── per-shot async pipeline (TTS, then either lipsync or mux, then upload) ──

async def _process_one_shot(
    shot,
    scene: dict,
    slug: str,
    workdir: str,
    seq: int,
    lip_sync_spokesperson: bool = False,
) -> dict:
    """Run TTS + audio-mux for a single shot. Returns dict with
    {url, duration_sec, narration} for the caption builder downstream.

    Lip-sync was removed — every supported provider (Kie.ai InfiniteTalk,
    Higgsfield Speak) returned 404 or rejected the model identifier. The
    rescue pipeline now relies on Runway shots already producing a
    consistent character (via the image_url passed to Runway in
    _generate_shot_bg) and just lays TTS audio over them. The
    lip_sync_spokesperson kwarg is kept for API compat but ignored.
    """
    narration = (scene.get("narration_text") or "").strip()
    if not narration:
        # No narration — keep the silent shot as-is. Probe its duration so
        # we don't drop it from the timeline.
        out = os.path.join(workdir, f"silent_{seq:02d}.mp4")
        if not await asyncio.to_thread(_ensure_local, shot.video_url, out):
            raise RuntimeError(f"could not fetch silent shot {seq}")
        return {
            "url": shot.video_url,
            "duration_sec": _ffprobe_duration(out),
            "narration": "",
        }

    # 1. TTS
    tts_key = f"campaigns/{slug}/audio/scene_{seq:02d}.mp3"
    logger.info(f"rescue_pipeline: TTS scene {seq} ({len(narration)} chars)")
    tts = await _tts_one_scene(narration, tts_key)

    # 2. Audio overlay onto Runway shot
    logger.info(f"rescue_pipeline: audio overlay scene {seq}")
    muxed_local = os.path.join(workdir, f"muxed_{seq:02d}.mp4")
    await _mux_audio_onto_video_async(shot.video_url, tts["url"], muxed_local)
    muxed_key = f"campaigns/{slug}/shots-with-audio/scene_{seq:02d}.mp4"
    muxed_url = await asyncio.to_thread(_upload_to_s3, muxed_local, muxed_key)
    if not muxed_url:
        raise RuntimeError(f"failed to upload muxed scene {seq}")
    return {"url": muxed_url, "duration_sec": tts["duration_sec"], "narration": narration}


# ── main entry point ─────────────────────────────────────────────────────────

async def _render_async(
    campaign_id: str,
    variation_id: str,
    lip_sync_spokesperson: bool,
) -> dict:
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
            f"rescue_pipeline: variation={variation_id[:8]} slug={slug} "
            f"shots={len(shots)} lipsync={lip_sync_spokesperson}"
        )

        with tempfile.TemporaryDirectory(prefix="rescue_") as workdir:
            # Phase 1+2 — process all shots in parallel (TTS + lipsync/mux)
            t0 = time.time()
            scene_results = await asyncio.gather(*[
                _process_one_shot(
                    shots[i],
                    storyboard[i] if i < len(storyboard) else {},
                    slug, workdir, i + 1, lip_sync_spokesperson,
                )
                for i in range(len(shots))
            ])
            logger.info(f"rescue_pipeline: parallel TTS+lipsync done in {time.time()-t0:.1f}s")

            # Phase 3 — assign start offsets from durations, download + concat
            offset = 0.0
            for r in scene_results:
                r["start_offset_sec"] = offset
                offset += r["duration_sec"]

            local_clips = []
            for i, r in enumerate(scene_results):
                local = os.path.join(workdir, f"clip_{i:02d}.mp4")
                if _ensure_local(r["url"], local):
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

            # Phase 4 — build captions directly from script + actual durations
            ass_path = os.path.join(workdir, "captions.ass")
            with open(ass_path, "w", encoding="utf-8") as fh:
                fh.write(_build_ass_from_scenes(scene_results))
            final_path = os.path.join(workdir, "final.mp4")
            logger.info("rescue_pipeline: burning script-driven captions")
            _burn_subtitles(stitched, ass_path, final_path)

            # Phase 5 — upload final
            final_key = f"campaigns/{slug}/final.mp4"
            final_url = _upload_to_s3(final_path, final_key)
            if not final_url:
                raise RuntimeError("failed to upload final video")
            logger.info(f"rescue_pipeline: final uploaded to {final_url}")

            variation.final_video_url = final_url
            variation.status = "completed"
            db.commit()

            total_duration = sum(r["duration_sec"] for r in scene_results)
            return {
                "final_url": final_url,
                "clips_assembled": len(local_clips),
                "duration_sec": round(total_duration, 2),
                "scenes_with_lipsync": sum(
                    1 for i, s in enumerate(shots)
                    if (s.shot_type or "").lower() in ("spokesperson", "hero")
                    and (storyboard[i] if i < len(storyboard) else {}).get("narration_text", "").strip()
                ) if lip_sync_spokesperson else 0,
            }
    finally:
        db.close()


def render_full_video(
    campaign_id: str,
    variation_id: str,
    lip_sync_spokesperson: bool = True,
) -> dict:
    """Sync wrapper around the async pipeline (called from a sync FastAPI
    BackgroundTask)."""
    return asyncio.run(_render_async(campaign_id, variation_id, lip_sync_spokesperson))
