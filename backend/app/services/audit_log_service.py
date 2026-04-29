"""Audit log service — single entry point for recording user-visible events.

Use `record()` from any route or service that wants to leave a breadcrumb in
the admin audit timeline. Failures are swallowed so audit logging never breaks
the originating request.

Critical design choice: every write opens its OWN DB session via SessionLocal.
The caller's `db` argument is IGNORED (kept only for API compatibility). This
guarantees that an audit-log failure can NEVER corrupt the caller's transaction.
"""
import logging
import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy.orm import Session
from ..models.audit_log import AuditLog
from ..database import SessionLocal

logger = logging.getLogger(__name__)


# Maximum length we'll store for any free-form text field. Anything longer is
# truncated. Keeps audit rows light and avoids accidentally storing huge blobs.
_MAX_FIELD_LEN = 1024


def _truncate(s: Any, n: int = _MAX_FIELD_LEN) -> Optional[str]:
    if s is None:
        return None
    s = str(s)
    return s if len(s) <= n else s[:n] + "..."


def record(
    db: Optional[Session] = None,
    *,
    action: str,
    category: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    role: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    screen: Optional[str] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    status_code: Optional[int] = None,
    duration_ms: Optional[int] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Optional[AuditLog]:
    """Best-effort write to audit_logs. Never raises.

    The `db` argument is accepted for API compatibility but IGNORED — we always
    open a private SessionLocal so a write failure can't corrupt any caller's
    transaction. If the audit_logs table is missing, the column types differ,
    or the DB is otherwise unhappy, the function logs a warning and returns
    None. The caller continues unaffected.
    """
    own_session: Optional[Session] = None
    try:
        own_session = SessionLocal()
        log = AuditLog(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            user_id=user_id,
            user_email=_truncate(user_email, 320),
            role=_truncate(role, 64),
            action=_truncate(action, 64) or "unknown",
            category=_truncate(category, 64),
            resource_type=_truncate(resource_type, 64),
            resource_id=_truncate(resource_id, 128),
            screen=_truncate(screen, 256),
            method=_truncate(method, 16),
            path=_truncate(path, 512),
            status_code=int(status_code) if status_code is not None else None,
            duration_ms=int(duration_ms) if duration_ms is not None else None,
            ip=_truncate(ip, 64),
            user_agent=_truncate(user_agent, 512),
            metadata_json=metadata or {},
        )
        own_session.add(log)
        own_session.commit()
        return log
    except Exception as e:
        logger.warning(f"audit_log record failed: {e}")
        if own_session is not None:
            try:
                own_session.rollback()
            except Exception:
                pass
        return None
    finally:
        if own_session is not None:
            try:
                own_session.close()
            except Exception:
                pass


def record_for_user(
    db: Optional[Session],
    user,
    *,
    action: str,
    **kwargs,
) -> Optional[AuditLog]:
    """Convenience: extract user_id/email/role from a User model instance.

    `db` is ignored — record() opens its own session.
    """
    if user is None:
        return record(action=action, **kwargs)
    role_name = None
    try:
        role_name = user.role.name if user.role else None
    except Exception:
        pass
    return record(
        action=action,
        user_id=getattr(user, "id", None),
        user_email=getattr(user, "email", None),
        role=role_name,
        **kwargs,
    )
