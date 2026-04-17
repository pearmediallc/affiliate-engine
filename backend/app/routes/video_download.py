import json
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..middleware.auth import get_optional_user, log_usage

router = APIRouter()

DOWNLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Map download_id -> file path
_download_registry: dict[str, Path] = {}


class VideoURLRequest(BaseModel):
    url: str


class VideoDownloadRequest(BaseModel):
    url: str
    format_id: Optional[str] = None


@router.post("/info")
async def video_info(req: VideoURLRequest):
    """Fetch video metadata without downloading."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-playlist", req.url],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timed out fetching video info")

    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip() or "Failed to fetch video info")

    data = json.loads(result.stdout)

    formats = []
    for f in data.get("formats", []):
        # Only include formats that have video
        if f.get("vcodec", "none") == "none" and f.get("acodec", "none") != "none":
            continue
        formats.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution", f"{f.get('width', '?')}x{f.get('height', '?')}"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
        })

    return {
        "title": data.get("title"),
        "thumbnail": data.get("thumbnail"),
        "duration": data.get("duration"),
        "formats": formats,
    }


@router.post("/start")
async def video_download_start(
    req: VideoDownloadRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Download video and return a download_id for retrieval."""
    download_id = str(uuid.uuid4())
    output_template = str(DOWNLOADS_DIR / f"{download_id}.%(ext)s")

    cmd = ["yt-dlp", "--no-playlist", "-o", output_template]
    if req.format_id:
        cmd += ["-f", req.format_id]
    cmd.append(req.url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Download timed out")

    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip() or "Download failed")

    # Find the downloaded file (yt-dlp fills in the extension)
    downloaded = list(DOWNLOADS_DIR.glob(f"{download_id}.*"))
    if not downloaded:
        raise HTTPException(status_code=500, detail="Download completed but file not found")

    filepath = downloaded[0]
    _download_registry[download_id] = filepath

    if user:
        log_usage("video_download", user.id, db, cost_usd=0.0)

    return {
        "download_id": download_id,
        "filename": filepath.name,
    }


@router.get("/file/{download_id}")
async def video_download_file(download_id: str):
    """Serve a downloaded file."""
    filepath = _download_registry.get(download_id)

    if not filepath or not filepath.exists():
        # Try finding on disk as fallback
        matches = list(DOWNLOADS_DIR.glob(f"{download_id}.*"))
        if not matches:
            raise HTTPException(status_code=404, detail="File not found")
        filepath = matches[0]

    return FileResponse(
        path=str(filepath),
        filename=filepath.name,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filepath.name}"'},
    )
