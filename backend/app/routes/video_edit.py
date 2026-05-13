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
    """
    Single-pass ffmpeg edit pipeline (called from thread pool).
    All filters applied in one encode per aspect — no intermediate temp files.
    """
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


def _sync_caption(tmp_input: str, tmp_audio: str, tmp_srt: str, _unused: object,
                  words_per_line: int, caption_style: str, aspects: list[str],
                  openai_key: str, uid: str) -> dict:
    """Run full auto-caption pipeline synchronously (called from thread pool)."""
    # 1. Extract audio (fast — audio only, no video decode overhead)
    ok = _run([
        "ffmpeg", "-y", "-i", tmp_input,
        "-vn", "-ar", "16000", "-ac", "1", "-f", "wav", tmp_audio,
    ])
    if not ok or not os.path.isfile(tmp_audio):
        raise RuntimeError("Audio extraction failed — check ffmpeg is installed")

    # 2. Transcribe with Whisper
    import openai as _oai
    client = _oai.OpenAI(api_key=openai_key)
    with open(tmp_audio, "rb") as af:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=af,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    segments = [
        {"start": s.start, "end": s.end, "text": s.text}
        for s in (result.segments or [])
    ]
    if not segments:
        raise ValueError("No speech detected in the video")

    # 3. Chunk → SRT
    captions = _segments_to_captions(segments, words_per_line=max(1, min(words_per_line, 12)))
    srt_content = _captions_to_srt(captions)
    with open(tmp_srt, "w", encoding="utf-8") as f:
        f.write(srt_content)

    # 4. Burn captions (SRT → subtitles filter; fallback to drawtext if libass missing)
    # 4+5. Burn captions + aspect export — one ffmpeg pass per aspect
    urls: dict[str, str] = {}
    for aspect in aspects:
        out = os.path.join(OUTPUT_DIR, f"acap_{aspect.replace(':', '_')}_{uid}.mp4")
        ok = _single_pass_caption(tmp_input, out, tmp_srt,
                                  caption_style=caption_style, aspect=aspect)
        if ok and os.path.isfile(out):
            fname = os.path.basename(out)
            s3 = StorageService.upload_file(out, f"videos/{fname}")
            urls[aspect] = s3 if s3 else f"/api/v1/video-edit/download/{fname}"

    if not urls:
        raise RuntimeError("All aspect exports failed — check ffmpeg logs")

    full_text = " ".join(s["text"].strip() for s in segments)
    return {
        "urls": urls,
        "srt": srt_content,
        "transcript": full_text,
        "segments": segments,
        "caption_count": len(captions),
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
        # Stream upload to disk in chunks — never load the full video into RAM
        with open(tmp_input, "wb") as f:
            while True:
                chunk = await video.read(65536)  # 64 KB at a time
                if not chunk:
                    break
                f.write(chunk)

        aspects = [a.strip() for a in output_aspects.split(",") if a.strip()]

        # All ffmpeg work runs in a thread so the event loop stays free
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
        for fname in os.listdir(UPLOAD_TMP):
            p = os.path.join(UPLOAD_TMP, fname)
            if uid in fname and "work_" in fname:
                try:
                    os.remove(p)
                except Exception:
                    pass
        try:
            os.remove(tmp_input)
        except Exception:
            pass


@router.post("/auto-caption")
async def auto_caption_video(
    video: UploadFile = File(...),
    words_per_line: int = Form(default=5),
    caption_style: str = Form(default="subtitle"),
    output_aspects: str = Form(default="9:16"),
    user=Depends(get_current_user),
):
    from ..config import settings
    if not settings.openai_api_key:
        raise HTTPException(400, detail="OPENAI_API_KEY not configured")

    uid = uuid.uuid4().hex[:8]
    tmp_input = os.path.join(UPLOAD_TMP, f"acap_in_{uid}.mp4")
    tmp_audio = os.path.join(UPLOAD_TMP, f"acap_au_{uid}.wav")
    tmp_srt   = os.path.join(UPLOAD_TMP, f"acap_{uid}.srt")

    try:
        # Stream upload to disk in chunks — never load the full video into RAM
        with open(tmp_input, "wb") as f:
            while True:
                chunk = await video.read(65536)
                if not chunk:
                    break
                f.write(chunk)

        aspects = [a.strip() for a in output_aspects.split(",") if a.strip()] or ["9:16"]

        # All heavy work (ffmpeg + Whisper HTTP) runs in a thread
        data = await asyncio.to_thread(
            _sync_caption, tmp_input, tmp_audio, tmp_srt, None,
            words_per_line, caption_style, aspects, settings.openai_api_key, uid,
        )

        return APIResponse(
            success=True,
            message=f"Transcribed {len(data['segments'])} segments, burned {data['caption_count']} caption lines",
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
        for p in [tmp_input, tmp_audio, tmp_srt,
                  os.path.join(UPLOAD_TMP, f"acap_norm_{uid}.mp4")]:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass


@router.get("/download/{filename}")
async def download_edited(filename: str):
    filename = os.path.basename(filename)  # prevent path traversal
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(404, detail="File not found or expired")
    return FileResponse(path, media_type="video/mp4",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
