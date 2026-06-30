"""
Winning Reference Library consumer — reads the adforge scraper Postgres DIRECTLY.

Winners are NOT a separate table: they are `ads` JOIN `winning_ad_scores` where
is_winner = TRUE, ranked by profitability_score. Schema (verified from the scraper ORM):
  winning_ad_scores(ad_id FK->ads.id, is_winner bool, profitability_score float, hook text)
  ads(id pk, vertical, video_url, image_url, s3_video_key)

Set WINNER_DB_URL to activate. Fully graceful: unconfigured / unreachable / empty -> [],
and the caller falls back to its own winners, then stock, then generation. Read-only.
"""
import logging
from ..config import settings

logger = logging.getLogger(__name__)

_SQL = """
    SELECT a.video_url, a.image_url, a.s3_video_key, a.s3_image_key,
           a.vertical, w.profitability_score AS score, w.hook
      FROM winning_ad_scores w
      JOIN ads a ON a.id = w.ad_id
     WHERE w.is_winner = TRUE
       AND a.vertical IS NOT NULL
       AND LOWER(a.vertical) = LOWER(%(vertical)s)
     ORDER BY w.profitability_score DESC NULLS LAST
     LIMIT %(limit)s
"""


def _durable_url(s3_key, fallback_url):
    """Prefer the durable S3 copy ({winner_media_base}/{key}); else the scraped CDN url."""
    base = (settings.winner_media_base or "").rstrip("/")
    if base and s3_key:
        return f"{base}/{s3_key.lstrip('/')}"
    return fallback_url


def is_configured() -> bool:
    return bool(settings.winner_db_url)


def health(verticals: list = None) -> dict:
    """Prove the connection live: returns {configured, connected, total_winners, by_vertical, error}."""
    if not is_configured():
        return {"configured": False, "connected": False, "error": "WINNER_DB_URL not set"}
    verticals = verticals or ["home_insurance", "auto_insurance", "bizop", "refinance", "medicare"]
    import psycopg2
    conn = None
    try:
        conn = psycopg2.connect(settings.winner_db_url, connect_timeout=6)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM winning_ad_scores WHERE is_winner = TRUE")
            total = cur.fetchone()[0]
        by_v = {v: len(fetch_winners(v, limit=50)) for v in verticals}
        return {"configured": True, "connected": True, "total_winners": total, "by_vertical": by_v}
    except Exception as e:
        return {"configured": True, "connected": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def fetch_winners(vertical: str, limit: int = 10, media: str = "video") -> list:
    """Return ranked winner reference dicts for a vertical (best profitability first).
    Each: {url, hook, vertical, score, media_type}. [] if unconfigured/empty/error."""
    if not is_configured() or not vertical or vertical == "unknown":
        return []
    import psycopg2
    import psycopg2.extras
    conn = None
    try:
        conn = psycopg2.connect(settings.winner_db_url, connect_timeout=6)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_SQL, {"vertical": vertical, "limit": int(limit)})
            rows = cur.fetchall()
    except Exception as e:
        logger.warning(f"winner_library DB query failed (vertical={vertical}): {e}")
        return []
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    out = []
    for r in rows:
        # prefer durable S3 video, else durable S3 image, else scraped CDN urls
        vid = _durable_url(r.get("s3_video_key"), r.get("video_url"))
        img = _durable_url(r.get("s3_image_key"), r.get("image_url"))
        url = (vid if media == "video" else img) or vid or img
        if not url:
            continue
        out.append({
            "url": url,
            "hook": r.get("hook") or "",
            "vertical": r.get("vertical") or vertical,
            "score": r.get("score") or 0,
            "media_type": "video" if (r.get("s3_video_key") or r.get("video_url")) else "image",
        })
    logger.info(f"winner_library: {len(out)} winners for vertical={vertical}")
    return out
