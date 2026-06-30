"""
Winning Reference Library consumer.

Queries the Meta-ad-library scraper for competitor WINNERS by vertical, so the regen
recipes can use a proven, real winning ad as a reference (highest-priority source, above
stock and pure generation).

Contract (metaadlibrary): GET {WINNER_LIBRARY_URL}/api/winning/top?vertical=&angle=&limit=
  Auth: Authorization: Bearer {WINNER_LIBRARY_TOKEN}
  -> { "winning_ads": [ { "video_url", "image_url", "hook", "angle", "vertical",
                          "profitability_score", ... } ] }

Fully graceful: if not configured or unreachable, returns [] and the caller falls back
to its existing sources. No behavior change until both env vars are set.
"""
import logging
import httpx

from ..config import settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(settings.winner_library_url and settings.winner_library_token)


def fetch_winners(vertical: str, limit: int = 10, angle: str = "", media: str = "video") -> list:
    """Return ranked winner reference dicts for a vertical (best profitability first).
    Each dict: {url, hook, angle, vertical, score, media_type}. [] if unconfigured/empty."""
    if not is_configured() or not vertical or vertical == "unknown":
        return []
    base = settings.winner_library_url.rstrip("/")
    params = {"vertical": vertical, "limit": limit}
    if angle:
        params["angle"] = angle
    try:
        r = httpx.get(f"{base}/api/winning/top", params=params,
                      headers={"Authorization": f"Bearer {settings.winner_library_token}"},
                      timeout=20)
        r.raise_for_status()
        ads = (r.json() or {}).get("winning_ads", []) or []
    except Exception as e:
        logger.warning(f"winner_library fetch failed ({vertical}): {e}")
        return []

    out = []
    for a in ads:
        url = a.get("video_url") if media == "video" else a.get("image_url")
        url = url or a.get("video_url") or a.get("image_url")
        if not url:
            continue
        out.append({
            "url": url,
            "hook": a.get("hook") or "",
            "angle": a.get("angle") or "",
            "vertical": a.get("vertical") or vertical,
            "score": a.get("profitability_score") or 0,
            "media_type": "video" if a.get("video_url") else "image",
        })
    logger.info(f"winner_library: {len(out)} winners for vertical={vertical}")
    return out
