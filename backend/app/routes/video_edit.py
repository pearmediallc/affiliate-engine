"""
Standalone video editor — upload a video, apply edits, download result.
Works independently of campaigns/shots.
"""
import asyncio
import os
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from ..schemas import APIResponse
from ..middleware.auth import get_current_user
from ..services.auto_editor import (
    AutoEditorService, OUTPUT_DIR,
    _single_pass_edit, _single_pass_caption,
    _segments_to_captions, _captions_to_srt, _run,
    # Professional UGC caption engine
    _words_from_whisper_result, _group_words_into_lines,
    _build_ass, _burn_ass, _fmt_srt_time, _ASS_STYLES,
)
from ..services.storage import StorageService

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_TMP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "upload_tmp",
)
os.makedirs(UPLOAD_TMP, exist_ok=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def _sync_edit(tmp_input: str, uid: str, color_grade: str, caption_text: str,
               caption_style: str, music_mood: str, aspects: list[str]) -> dict:
    """Single-pass ffmpeg edit pipeline (called from thread pool)."""
    music_path = None
    if music_mood.strip():
        try:
            from ..services.music_library import MusicLibraryService
            music_path = MusicLibraryService.get_track_for_ad(music_mood.strip())
        except Exception as me:
            logger.warning(f"Music lookup failed (non-fatal): {me}")

    urls: dict[str, str] = {}
    for aspect in aspects:
        out = os.path.join(OUTPUT_DIR, f"edit_{aspect.replace(':', '_')}_{uid}.mp4")
        ok = _single_pass_edit(
            tmp_input, out,
            color_grade=color_grade,
            caption_text=caption_text,
            caption_style=caption_style,
            aspect=aspect,
            music_path=music_path,
        )
        if ok and os.path.isfile(out):
            filename = os.path.basename(out)
            s3_url = StorageService.upload_file(out, f"videos/{filename}")
            urls[aspect] = s3_url if s3_url else f"/api/v1/video-edit/download/{filename}"
    return urls


def _sync_caption_pro(
    tmp_input: str,
    tmp_audio: str,
    tmp_srt: str,
    tmp_ass: str,
    words_per_line: int,
    caption_style: str,
    aspects: list[str],
    openai_key: str,
    uid: str,
) -> dict:
    """
    Professional UGC auto-caption pipeline:
    1. Extract audio (16kHz mono WAV)
    2. Transcribe with Whisper — word-level timestamps
    3. Group words into short lines → ASS karaoke file
    4. Burn ASS captions + aspect crop in one ffmpeg pass per aspect

    Returns urls, srt, ass, transcript, word_count, segments.
    """
    # 1. Extract audio
    ok = _run([
        "ffmpeg", "-y", "-i", tmp_input,
        "-vn", "-ar", "16000", "-ac", "1", "-f", "wav", tmp_audio,
    ])
    if not ok or not os.path.isfile(tmp_audio):
        raise RuntimeError("Audio extraction failed — check ffmpeg is installed")

    # 2. Transcribe with Whisper — request BOTH segment AND word timestamps
    import openai as _oai
    client = _oai.OpenAI(api_key=openai_key)
    with open(tmp_audio, "rb") as af:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=af,
            response_format="verbose_json",
            timestamp_granularities=["segment", "word"],
        )

    # Extract word-level timing (falls back to proportional split if unavailable)
    words = _words_from_whisper_result(result)
    if not words:
        raise ValueError("No speech detected in the video")

    # 3. Group words into caption lines
    style_cfg = _ASS_STYLES.get(caption_style, _ASS_STYLES["tiktok"])
    wpl = min(words_per_line, style_cfg["words_per_line"])  # respect style max
    lines = _group_words_into_lines(words, max(1, wpl))

    # 4. Write ASS file (karaoke word highlighting)
    ass_content = _build_ass(lines, style_name=caption_style)
    with open(tmp_ass, "w", encoding="utf-8") as f:
        f.write(ass_content)

    # Also write SRT for download / portability
    simple_caps = [{"start": ln["start"], "end": ln["end"], "text": ln["text"]} for ln in lines]
    srt_content = _captions_to_srt(simple_caps)
    with open(tmp_srt, "w", encoding="utf-8") as f:
        f.write(srt_content)

    # 5. Burn captions per aspect — one ffmpeg pass each
    urls: dict[str, str] = {}
    for aspect in aspects:
        out = os.path.join(OUTPUT_DIR, f"ugccap_{aspect.replace(':', '_')}_{uid}.mp4")

        # First: aspect-crop the video (no captions yet)
        tmp_cropped = os.path.join(OUTPUT_DIR, f"crop_{aspect.replace(':', '_')}_{uid}.mp4")
        ok_crop = _single_pass_caption(tmp_input, tmp_cropped, tmp_srt,
                                       caption_style="none", aspect=aspect)

        if ok_crop and os.path.isfile(tmp_cropped):
            # Then burn ASS onto the cropped video
            ok_burn = _burn_ass(tmp_cropped, out, tmp_ass)
            try:
                os.remove(tmp_cropped)
            except Exception:
                pass
        else:
            # Fallback: burn ASS directly on original (aspect not cropped)
            ok_burn = _burn_ass(tmp_input, out, tmp_ass)

        if ok_burn and os.path.isfile(out):
            fname = os.path.basename(out)
            s3 = StorageService.upload_file(out, f"videos/{fname}")
            urls[aspect] = s3 if s3 else f"/api/v1/video-edit/download/{fname}"

    if not urls:
        raise RuntimeError("All aspect exports failed — check ffmpeg logs")

    full_text = " ".join(w["word"] for w in words)
    segments = []
    segs = getattr(result, "segments", None) or []
    for seg in segs:
        segments.append({
            "start": float(getattr(seg, "start", 0)),
            "end": float(getattr(seg, "end", 0)),
            "text": (getattr(seg, "text", "") or "").strip(),
        })

    return {
        "urls": urls,
        "srt": srt_content,
        "ass": ass_content,
        "transcript": full_text,
        "word_count": len(words),
        "caption_count": len(lines),
        "segments": segments,
    }


# ── routes ────────────────────────────────────────────────────────────────────

@router.post("/edit")
async def edit_video(
    video: UploadFile = File(...),
    color_grade: str = Form(default="none"),
    caption_text: str = Form(default=""),
    caption_style: str = Form(default="subtitle"),
    music_mood: str = Form(default=""),
    output_aspects: str = Form(default="16:9,9:16,1:1"),
    user=Depends(get_current_user),
):
    uid = uuid.uuid4().hex[:8]
    tmp_input = os.path.join(UPLOAD_TMP, f"input_{uid}.mp4")

    try:
        with open(tmp_input, "wb") as f:
            while True:
                chunk = await video.read(65536)
                if not chunk:
                    break
                f.write(chunk)

        aspects = [a.strip() for a in output_aspects.split(",") if a.strip()]
        urls = await asyncio.to_thread(
            _sync_edit, tmp_input, uid, color_grade, caption_text,
            caption_style, music_mood, aspects,
        )

        return APIResponse(
            success=True,
            message="Video edited successfully",
            data={"urls": urls, "aspects": list(urls.keys())},
        )

    except Exception as e:
        logger.error(f"Video edit failed: {e}", exc_info=True)
        raise
    finally:
        try:
            os.remove(tmp_input)
        except Exception:
            pass


@router.post("/auto-caption")
async def auto_caption_video(
    video: UploadFile = File(...),
    words_per_line: int = Form(default=2),
    caption_style: str = Form(default="tiktok"),
    output_aspects: str = Form(default="9:16"),
    user=Depends(get_current_user),
):
    """
    Professional UGC auto-caption:
    - Transcribes with Whisper (word-level timestamps)
    - Groups into 1-4 word lines for TikTok/UGC pacing
    - Burns karaoke-style ASS captions (each word highlights when spoken)
    - Exports per requested aspect ratio

    caption_style options: tiktok | bold_center | subtitle | karaoke
    """
    from ..config import settings
    if not settings.openai_api_key:
        raise HTTPException(400, detail="OPENAI_API_KEY not configured")

    uid = uuid.uuid4().hex[:8]
    tmp_input = os.path.join(UPLOAD_TMP, f"acap_in_{uid}.mp4")
    tmp_audio = os.path.join(UPLOAD_TMP, f"acap_au_{uid}.wav")
    tmp_srt   = os.path.join(UPLOAD_TMP, f"acap_{uid}.srt")
    tmp_ass   = os.path.join(UPLOAD_TMP, f"acap_{uid}.ass")

    try:
        with open(tmp_input, "wb") as f:
            while True:
                chunk = await video.read(65536)
                if not chunk:
                    break
                f.write(chunk)

        aspects = [a.strip() for a in output_aspects.split(",") if a.strip()] or ["9:16"]
        # Clamp words_per_line: 1–4 (UGC style typically 1-3 words)
        wpl = max(1, min(words_per_line, 4))

        data = await asyncio.to_thread(
            _sync_caption_pro,
            tmp_input, tmp_audio, tmp_srt, tmp_ass,
            wpl, caption_style, aspects, settings.openai_api_key, uid,
        )

        return APIResponse(
            success=True,
            message=f"Transcribed {data['word_count']} words, burned {data['caption_count']} caption lines",
            data=data,
        )

    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(500, detail=str(e))
    except Exception as e:
        logger.error(f"Auto-caption failed: {e}", exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        for p in [tmp_input, tmp_audio, tmp_srt, tmp_ass]:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass


@router.get("/styles")
async def get_caption_styles():
    """Return available caption styles with their descriptions."""
    return APIResponse(
        success=True,
        message="Caption styles",
        data={
            "styles": [
                {"id": "tiktok",      "label": "TikTok/Reels",    "description": "2 words per line, huge white text, center screen — viral UGC style"},
                {"id": "karaoke",     "label": "Karaoke highlight","description": "3 words per line, active word turns yellow when spoken"},
                {"id": "bold_center", "label": "Bold center",      "description": "3 words per line, large bold centered text"},
                {"id": "subtitle",    "label": "Subtitle",         "description": "5 words per line, classic bottom subtitle with background"},
            ]
        },
    )


@router.get("/download/{filename}")
async def download_edited(filename: str):
    filename = os.path.basename(filename)  # prevent path traversal
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(404, detail="File not found or expired")
    return FileResponse(path, media_type="video/mp4",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
