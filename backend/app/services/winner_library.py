"""
Winning Reference Library consumer.

Two ways to read competitor winners by vertical (first configured wins):

  Option 2 (preferred): token-authed HTTPS API on the scraper's Cloud Run app.
     GET {WINNER_LIBRARY_URL}/api/winning?vertical=&limit=   Authorization: Bearer {token}
     The app talks to its DB + bucket internally and returns winners with downloadable
     (presigned) media URLs. DB + bucket never exposed.

  Option B (fallback): read the adforge Postgres directly (WINNER_DB_URL) and presign the
     private S3 keys ourselves (needs IP allowlist + bucket creds).

Fully graceful: nothing configured / unreachable / empty -> [], and the caller falls back to
its own winners, then stock, then generation. Read-only.
"""
import logging
import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# ── shared helpers ────────────────────────────────────────────────────────────
def _http_configured() -> bool:
    return bool(settings.winner_library_url and settings.winner_library_token)

def _db_configured() -> bool:
    return bool(settings.winner_db_url)

def is_configured() -> bool:
    return _http_configured() or _db_configured()


def _pick_media_url(item: dict, media: str):
    """Find a downloadable media URL in an API winner item. Prefer a ready http(s) URL
    (the app already presigns); else presign an s3 key ourselves."""
    keys_v = ["video_url", "videoUrl", "s3_video_url", "media_url", "url"]
    keys_i = ["image_url", "imageUrl", "s3_image_url"]
    order = (keys_v + keys_i) if media == "video" else (keys_i + keys_v)
    for k in order:
        v = item.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    # only an s3 key was returned -> presign it ourselves (Option B helper)
    sk = item.get("s3_video_key") or item.get("s3_image_key")
    return _presign(sk) if sk else None


# ── Option 2: HTTP API ────────────────────────────────────────────────────────
def _fetch_http(vertical: str, limit: int) -> list:
    base = settings.winner_library_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.winner_library_token}"}
    params = {"vertical": vertical, "limit": limit}
    ads = None
    for path in ("/api/winning", "/api/winning/top"):
        try:
            r = httpx.get(f"{base}{path}", params=params, headers=headers, timeout=20)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            body = r.json() or {}
            ads = body.get("winning_ads") or body.get("ads") or body.get("data") or body.get("results") or []
            break
        except Exception as e:
            logger.warning(f"winner_library HTTP {path} failed ({vertical}): {e}")
    if not ads:
        return []
    out = []
    for a in ads:
        url = _pick_media_url(a, "video")
        if not url:
            continue
        out.append({
            "url": url,
            "hook": a.get("hook") or "",
            "vertical": a.get("vertical") or vertical,
            "score": a.get("profitability_score") or a.get("score") or 0,
            "media_type": "video" if (a.get("video_url") or a.get("s3_video_key")) else "image",
        })
    logger.info(f"winner_library(HTTP): {len(out)} winners for vertical={vertical}")
    return out


# ── Option B: direct Postgres + presign ───────────────────────────────────────
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

_s3_client = None

def _get_s3():
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.winner_s3_access_key_id or settings.aws_access_key_id,
            aws_secret_access_key=settings.winner_s3_secret_access_key or settings.aws_secret_access_key,
            region_name=settings.winner_s3_region or settings.aws_region,
        )
    return _s3_client


def _presign(s3_key):
    """Presigned GET for a private winner object (1h). None on failure/no key."""
    if not s3_key:
        return None
    key = s3_key.lstrip("/")
    try:
        return _get_s3().generate_presigned_url(
            "get_object", Params={"Bucket": settings.winner_s3_bucket, "Key": key}, ExpiresIn=3600)
    except Exception as e:
        logger.warning(f"winner presign failed for {key}: {e}")
        base = (settings.winner_media_base or "").rstrip("/")
        return f"{base}/{key}" if base else None


def _fetch_db(vertical: str, limit: int) -> list:
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
        url = _presign(r.get("s3_video_key")) or r.get("video_url") \
            or _presign(r.get("s3_image_key")) or r.get("image_url")
        if not url:
            continue
        out.append({
            "url": url,
            "hook": r.get("hook") or "",
            "vertical": r.get("vertical") or vertical,
            "score": r.get("score") or 0,
            "media_type": "video" if (r.get("s3_video_key") or r.get("video_url")) else "image",
        })
    logger.info(f"winner_library(DB): {len(out)} winners for vertical={vertical}")
    return out


# ── public API ────────────────────────────────────────────────────────────────
def fetch_winners(vertical: str, limit: int = 10, media: str = "video") -> list:
    """Ranked winner reference dicts for a vertical (best first):
    {url, hook, vertical, score, media_type}. [] if unconfigured/empty/error."""
    if not vertical or vertical == "unknown":
        return []
    if _http_configured():
        return _fetch_http(vertical, limit)
    if _db_configured():
        return _fetch_db(vertical, limit)
    return []


def health(verticals: list = None) -> dict:
    """Prove the configured source live: {source, configured, connected, total/by_vertical, error}."""
    source = "http" if _http_configured() else ("db" if _db_configured() else "none")
    if source == "none":
        return {"source": source, "configured": False, "connected": False,
                "error": "set WINNER_LIBRARY_URL+TOKEN (Option 2) or WINNER_DB_URL"}
    verticals = verticals or ["home_insurance", "auto_insurance", "bizop", "refinance", "medicare"]
    try:
        by_v = {v: len(fetch_winners(v, limit=50)) for v in verticals}
        connected = any(c > 0 for c in by_v.values()) or _probe(source)
        return {"source": source, "configured": True, "connected": connected, "by_vertical": by_v}
    except Exception as e:
        return {"source": source, "configured": True, "connected": False,
                "error": f"{type(e).__name__}: {str(e)[:160]}"}


def _probe(source: str) -> bool:
    """Light reachability probe so health() reports connected even when a vertical has 0 winners."""
    try:
        if source == "http":
            r = httpx.get(f"{settings.winner_library_url.rstrip('/')}/api/winning",
                          params={"vertical": "home_insurance", "limit": 1},
                          headers={"Authorization": f"Bearer {settings.winner_library_token}"}, timeout=15)
            return r.status_code < 500
        import psycopg2
        c = psycopg2.connect(settings.winner_db_url, connect_timeout=6); c.close()
        return True
    except Exception:
        return False
