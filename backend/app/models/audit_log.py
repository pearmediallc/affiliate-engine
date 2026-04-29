"""AuditLog model — every user-visible action recorded for admin review."""
from sqlalchemy import Column, String, DateTime, JSON, Integer, Text, Index
from datetime import datetime
import uuid
from ..database import Base


# Categorical action codes. Keep this list short and stable; specifics go in
# `metadata_json`. Values are strings so SQLite stays compatible.
ACTION_LOGIN_SUCCESS = "login_success"
ACTION_LOGIN_FAILED = "login_failed"
ACTION_LOGOUT = "logout"
ACTION_REGISTER = "register"
ACTION_USER_APPROVED = "user_approved"
ACTION_USER_REJECTED = "user_rejected"
ACTION_USER_CREATED_BY_ADMIN = "user_created_by_admin"
ACTION_USER_DEACTIVATED = "user_deactivated"
ACTION_USER_REACTIVATED = "user_reactivated"
ACTION_ROLE_CHANGED = "role_changed"
ACTION_API_REQUEST = "api_request"          # auto-recorded by middleware
ACTION_PAGE_VIEW = "page_view"              # frontend hook posts this
ACTION_GENERATION_STARTED = "generation_started"
ACTION_GENERATION_COMPLETED = "generation_completed"
ACTION_GENERATION_FAILED = "generation_failed"
ACTION_DOWNLOAD = "download"
ACTION_FEEDBACK_GIVEN = "feedback_given"


class AuditLog(Base):
    """Immutable timeline of every meaningful action across the platform.

    One row per event. Keep payload small — never log full request bodies
    (avoid stuffing PII / API keys / image bytes here). Metadata is a JSON
    grab-bag of small contextual fields.
    """
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Actor — nullable for unauthenticated requests.
    user_id = Column(String, nullable=True, index=True)
    user_email = Column(String, nullable=True, index=True)  # snapshot — survives user deletion
    role = Column(String, nullable=True)                     # snapshot of role at time of action

    action = Column(String, nullable=False, index=True)      # see ACTION_* above
    category = Column(String, nullable=True, index=True)     # auth | admin | generation | navigation | api

    # What was acted upon.
    resource_type = Column(String, nullable=True)            # "user", "job", "image", "video", ...
    resource_id = Column(String, nullable=True)

    # Frontend context — which screen/page the user was on (URL path).
    screen = Column(String, nullable=True, index=True)

    # Backend HTTP context (for ACTION_API_REQUEST and others).
    method = Column(String, nullable=True)                   # GET, POST, PUT, DELETE
    path = Column(String, nullable=True)                     # /api/v1/...
    status_code = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    # Network forensics.
    ip = Column(String, nullable=True, index=True)
    user_agent = Column(String, nullable=True)

    # Free-form structured details. Keep small (< 4KB). NEVER store bodies.
    metadata_json = Column(JSON, nullable=True)

    # Composite index for common admin filter combinations.
    __table_args__ = (
        Index("ix_audit_user_ts", "user_id", "timestamp"),
        Index("ix_audit_action_ts", "action", "timestamp"),
    )
