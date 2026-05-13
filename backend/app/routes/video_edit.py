"""
Standalone video editor — upload a video, apply edits, download result.
Works independently of campaigns/shots.
"""
import os
import uuid
import logging
import shutil
import tempfile
from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from ..schemas import APIResponse
from ..middleware.auth import get_current_user
from ..services.auto_editor import AutoEditorService, OUTPUT_DIR, _color_grade, _burn_captions, _mix_audio, _export_aspect
from ..services.storage import StorageService

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_TMP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "upload_tmp",
)
os.makedirs(UPLOAD_TMP, exist_ok=True)


@router.post("/edit")
async def edit_video(
    video: UploadFile = File(...),
    color_grade: str = Form(default="none"),
    caption_text: str = Form(default=""),
    caption_style: str = Form(default="subtitle"),   # subtitle | bold_center
    music_mood: str = Form(default=""),              # empty = no music
    output_aspects: str = Form(default="16:9,9:16,1:1"),
    user=Depends(get_current_user),
):
    """
    Upload a video file, apply color grade / captions / music,
    and get back download links in up to 3 aspect ratios.
    """
    uid = uuid.uuid4().hex[:8]
    tmp_input = os.path.join(UPLOAD_TMP, f"input_{uid}.mp4")

    try:
        # Save upload
        with open(tmp_input, "wb") as f:
            content = await video.read()
            f.write(content)

        working = tmp_input
        next_path = lambda suffix: os.path.join(UPLOAD_TMP, f"work_{uid}_{suffix}.mp4")

        # Step 1: color grade
        if color_grade and color_grade != "none":
            graded = next_path("graded")
            _color_grade(working, graded, color_grade)
            working = graded

        # Step 2: burn caption (static full-video overlay)
        if caption_text.strip():
            from ..services.auto_editor import _get_duration
            dur = _get_duration(working)
            captions = [{"text": caption_text.strip(), "start": 0, "end": dur, "style": caption_style}]
            captioned = next_path("captioned")
            _burn_captions(working, captioned, captions)
            working = captioned

        # Step 3: add background music
        if music_mood.strip():
            try:
                from ..services.music_library import MusicLibraryService
                music_path = MusicLibraryService.get_track_for_ad(music_mood.strip())
                if music_path:
                    mixed = next_path("mixed")
                    _mix_audio(working, mixed, music_path=music_path)
                    working = mixed
            except Exception as me:
                logger.warning(f"Music step failed (non-fatal): {me}")

        # Step 4: export requested aspects
        aspects = [a.strip() for a in output_aspects.split(",") if a.strip()]
        outputs: dict[str, str] = {}
        urls: dict[str, str] = {}

        for aspect in aspects:
            out_path = _export_aspect(working, aspect)
            if out_path and os.path.isfile(out_path):
                filename = os.path.basename(out_path)
                s3_url = StorageService.upload_file(out_path, f"videos/{filename}")
                url = s3_url if s3_url else f"/api/v1/video-edit/download/{filename}"
                outputs[aspect] = out_path
                urls[aspect] = url

        return APIResponse(
            success=True,
            message="Video edited successfully",
            data={"urls": urls, "aspects": list(urls.keys())},
        )

    except Exception as e:
        logger.error(f"Video edit failed: {e}", exc_info=True)
        raise
    finally:
        # Clean up temp input and working files (outputs stay for download)
        for f in os.listdir(UPLOAD_TMP):
            p = os.path.join(UPLOAD_TMP, f)
            if uid in f and "work_" in f:
                try:
                    os.remove(p)
                except Exception:
                    pass
        try:
            os.remove(tmp_input)
        except Exception:
            pass


@router.get("/download/{filename}")
async def download_edited(filename: str, user=Depends(get_current_user)):
    filename = os.path.basename(filename)
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        from fastapi import HTTPException
        raise HTTPException(404, detail="File not found or expired")
    return FileResponse(path, media_type="video/mp4",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
