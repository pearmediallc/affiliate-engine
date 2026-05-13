"""Music library routes — search and download CC0 background music from Pixabay."""
import logging
from fastapi import APIRouter, Depends, Query
from ..schemas import APIResponse
from ..middleware.auth import get_current_user
from ..services.music_library import MusicLibraryService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/search")
async def search_music(
    mood: str = Query(default="motivational"),
    duration_min: int = Query(default=20),
    duration_max: int = Query(default=120),
    per_page: int = Query(default=10, le=20),
    page: int = Query(default=1),
    user=Depends(get_current_user),
):
    """Search CC0 music tracks by mood. Returns track list with download URLs."""
    tracks = MusicLibraryService.search(
        mood=mood,
        duration_min=duration_min,
        duration_max=duration_max,
        page=page,
        per_page=per_page,
    )
    return APIResponse(
        success=True,
        message=f"Found {len(tracks)} tracks",
        data={"tracks": tracks, "mood": mood},
    )


@router.get("/moods")
async def list_moods(user=Depends(get_current_user)):
    """List available mood categories."""
    from ..services.music_library import _MOOD_GENRE_MAP
    return APIResponse(
        success=True,
        message="Available moods",
        data={"moods": list(_MOOD_GENRE_MAP.keys())},
    )
