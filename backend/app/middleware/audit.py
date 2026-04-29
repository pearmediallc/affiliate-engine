"""HTTP middleware — auto-records every API request to audit_logs.

Recorded fields are method/path/status/duration + actor (when token is valid).
Body bytes are NEVER stored — that would leak prompts, passwords, image data.

Designed to be cheap: a single INSERT per request via background DB session,
so a failure to log never breaks the originating request.
"""
import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from jose import JWTError, jwt
from ..config import settings
from ..database import SessionLocal
from ..services.audit_log_service import record
from ..models.audit_log import ACTION_API_REQUEST

logger = logging.getLogger(__name__)


# Paths whose audit-log noise outweighs their value. Never recorded.
_SKIP_PATHS = (
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
)
# Image / video / thumbnail serving — high-volume, low-signal. Skip.
_SKIP_SUBSTRINGS = (
    "/serve/",
    "/thumb/",
    "/download/",
)


def _should_skip(path: str) -> bool:
    if path in _SKIP_PATHS:
        return True
    return any(s in path for s in _SKIP_SUBSTRINGS)


def _resolve_user_from_token(token: str):
    """Decode the bearer token to a (user_id, email, role) tuple. Returns
    (None, None, None) on failure — middleware tolerates anonymous traffic."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        if not user_id:
            return None, None, None
    except JWTError:
        return None, None, None

    # Look up email/role for richer audit context
    db = SessionLocal()
    try:
        from ..models.user import User
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            return user_id, None, None
        role_name = u.role.name if u.role else None
        return u.id, u.email, role_name
    except Exception:
        return user_id, None, None
    finally:
        try:
            db.close()
        except Exception:
            pass


def _category_for_path(path: str) -> str:
    if path.startswith("/api/v1/auth"):
        return "auth"
    if path.startswith("/api/v1/admin"):
        return "admin"
    if path.startswith("/api/v1/jobs"):
        return "jobs"
    if "/video" in path or "/image" in path or "/speech" in path or "/transcription" in path or "/lip-sync" in path:
        return "generation"
    return "api"


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Capture request metadata BEFORE handler runs (in case body is consumed)
        path = request.url.path
        if _should_skip(path):
            return await call_next(request)

        method = request.method
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
        auth_header = request.headers.get("authorization") or ""
        token = auth_header.split(" ", 1)[1] if auth_header.lower().startswith("bearer ") else None

        start = time.time()
        response: Response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)

        # Resolve user (best-effort — never block the response)
        user_id, user_email, role = (None, None, None)
        if token:
            try:
                user_id, user_email, role = _resolve_user_from_token(token)
            except Exception:
                pass

        # Write audit row in a fresh DB session to avoid cross-thread issues
        try:
            db = SessionLocal()
            try:
                record(
                    db,
                    action=ACTION_API_REQUEST,
                    category=_category_for_path(path),
                    user_id=user_id, user_email=user_email, role=role,
                    method=method, path=path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    ip=ip, user_agent=ua,
                )
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"audit middleware swallow: {e}")

        return response
