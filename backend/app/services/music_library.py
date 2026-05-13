"""
Pixabay music library — free CC0 tracks, no attribution required.
API docs: https://pixabay.com/api/docs/#api_music

Searches by mood/genre/BPM and downloads MP3 to local cache.
"""
import os
import logging
import hashlib
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

MUSIC_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "music_cache",
)
os.makedirs(MUSIC_CACHE_DIR, exist_ok=True)

PIXABAY_API_BASE = "https://pixabay.com/api/music/"


def _pixabay_key() -> Optional[str]:
    from ..config import settings
    return settings.pixabay_api_key


# Mood → Pixabay genre/category mappings
_MOOD_GENRE_MAP = {
    "upbeat":      "electronic",
    "energetic":   "dance",
    "motivational": "corporate",
    "calm":        "ambient",
    "dramatic":    "cinematic",
    "emotional":   "classical",
    "corporate":   "corporate",
    "happy":       "pop",
    "sad":         "ambient",
    "tense":       "film-score",
    "inspiring":   "corporate",
}


class MusicLibraryService:
    """Search and download background music from Pixabay (CC0, free commercial use)."""

    @staticmethod
    def search(
        mood: str = "motivational",
        duration_max: int = 300,
        duration_min: int = 30,
        page: int = 1,
        per_page: int = 10,
    ) -> list[dict]:
        """
        Search Pixabay music. Returns list of track dicts:
        [{ id, title, duration, audio_url, preview_url, tags }]
        """
        api_key = _pixabay_key()
        if not api_key:
            logger.warning("PIXABAY_API_KEY not configured — returning empty music results")
            return []

        genre = _MOOD_GENRE_MAP.get(mood.lower(), "corporate")
        params = {
            "key": api_key,
            "genre": genre,
            "min_duration": duration_min,
            "max_duration": duration_max,
            "page": page,
            "per_page": per_page,
        }

        try:
            resp = httpx.get(PIXABAY_API_BASE, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            hits = data.get("hits", [])
            return [
                {
                    "id": str(h["id"]),
                    "title": h.get("tags", "Unknown"),
                    "duration": h.get("duration", 0),
                    "audio_url": h.get("audio", ""),
                    "preview_url": h.get("preview", ""),
                    "tags": h.get("tags", ""),
                    "genre": genre,
                    "mood": mood,
                    "license": "CC0",
                }
                for h in hits
                if h.get("audio")
            ]
        except Exception as e:
            logger.error(f"Pixabay music search failed: {e}")
            return []

    @staticmethod
    def download(audio_url: str, track_id: str = "") -> Optional[str]:
        """Download an MP3 from Pixabay to local cache. Returns local path."""
        cache_key = hashlib.md5(audio_url.encode()).hexdigest()[:12]
        filename = f"pixabay_{track_id or cache_key}.mp3"
        local_path = os.path.join(MUSIC_CACHE_DIR, filename)

        if os.path.isfile(local_path):
            return local_path

        try:
            with httpx.stream("GET", audio_url, follow_redirects=True, timeout=60) as r:
                r.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            return local_path
        except Exception as e:
            logger.error(f"Music download failed {audio_url}: {e}")
            return None

    @staticmethod
    def get_track_for_ad(mood: str = "motivational", ad_duration: int = 30) -> Optional[dict]:
        """
        Convenience: search + download the best matching track for an ad.
        Returns track dict with local_path included, or None.
        """
        tracks = MusicLibraryService.search(
            mood=mood,
            duration_min=max(ad_duration, 20),
            duration_max=max(ad_duration + 60, 120),
            per_page=5,
        )
        if not tracks:
            return None

        track = tracks[0]
        local_path = MusicLibraryService.download(track["audio_url"], track["id"])
        if not local_path:
            return None

        track["local_path"] = local_path
        return track
