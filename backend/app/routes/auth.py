"""Authentication routes — registration with admin approval workflow.

Every auth state-change emits an audit_logs row via record_for_user/record so
admins can reconstruct exactly who logged in / failed / was approved / etc.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from passlib.context import CryptContext
import hashlib
from datetime import datetime
import uuid
from ..database import get_db
from ..models.user import User, Role, USER_STATUS_PENDING, USER_STATUS_APPROVED, USER_STATUS_REJECTED
from ..models.audit_log import (
    ACTION_LOGIN_SUCCESS, ACTION_LOGIN_FAILED, ACTION_REGISTER,
    ACTION_USER_APPROVED, ACTION_USER_REJECTED, ACTION_USER_CREATED_BY_ADMIN,
    ACTION_USER_DEACTIVATED, ACTION_USER_REACTIVATED, ACTION_ROLE_CHANGED,
)
from ..services.audit_log_service import record, record_for_user
from ..schemas import APIResponse
from ..middleware.auth import get_current_user, require_admin, create_access_token

logger = logging.getLogger("auth_audit")
router = APIRouter()


def _request_meta(request: Request) -> dict:
    """Extract IP + UA for audit events."""
    return {
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)

def _hash_password(password: str) -> str:
    """Hash password, handling bcrypt's 72-byte limit by pre-hashing if needed"""
    if len(password.encode('utf-8')) > 72:
        password = hashlib.sha256(password.encode('utf-8')).hexdigest()
    return pwd_context.hash(password)

def _verify_password(password: str, hashed: str) -> bool:
    """Verify password, handling the pre-hash for long passwords"""
    if len(password.encode('utf-8')) > 72:
        password = hashlib.sha256(password.encode('utf-8')).hexdigest()
    return pwd_context.verify(password, hashed)

# Default permissions for each role
DEFAULT_PERMISSIONS = {
    "admin": {
        "image_generation": {"allowed": True, "daily_limit": None},
        "video_hook_analysis": {"allowed": True, "daily_limit": None},
        "video_download": {"allowed": True, "daily_limit": None},
        "transcript_analysis": {"allowed": True, "daily_limit": None},
        "script_generation": {"allowed": True, "daily_limit": None},
        "speech_generation": {"allowed": True, "daily_limit": None},
        "analytics_view": {"allowed": True},
        "feedback_submit": {"allowed": True},
        "admin_panel": {"allowed": True},
        "user_management": {"allowed": True},
        "ai_suggestions_view": {"allowed": True},
        "ai_suggestions_approve": {"allowed": True},
    },
    "editor": {
        "image_generation": {"allowed": True, "daily_limit": 100},
        "video_hook_analysis": {"allowed": True, "daily_limit": 50},
        "video_download": {"allowed": True, "daily_limit": 50},
        "transcript_analysis": {"allowed": True, "daily_limit": 50},
        "script_generation": {"allowed": True, "daily_limit": 50},
        "speech_generation": {"allowed": True, "daily_limit": 30},
        "analytics_view": {"allowed": True},
        "feedback_submit": {"allowed": True},
        "admin_panel": {"allowed": False},
        "user_management": {"allowed": False},
        "ai_suggestions_view": {"allowed": True},
        "ai_suggestions_approve": {"allowed": False},
    },
    "viewer": {
        "image_generation": {"allowed": True, "daily_limit": 10},
        "video_hook_analysis": {"allowed": True, "daily_limit": 10},
        "video_download": {"allowed": True, "daily_limit": 5},
        "transcript_analysis": {"allowed": True, "daily_limit": 10},
        "script_generation": {"allowed": True, "daily_limit": 10},
        "speech_generation": {"allowed": True, "daily_limit": 5},
        "analytics_view": {"allowed": True},
        "feedback_submit": {"allowed": True},
        "admin_panel": {"allowed": False},
        "user_management": {"allowed": False},
        "ai_suggestions_view": {"allowed": False},
        "ai_suggestions_approve": {"allowed": False},
    },
}


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str = None

class LoginRequest(BaseModel):
    email: str
    password: str

class UpdateProfileRequest(BaseModel):
    full_name: str = None
    email: str = None

class CreateUserRequest(BaseModel):
    email: str
    password: str
    full_name: str = None
    role: str = "viewer"

class UpdateUserRoleRequest(BaseModel):
    role: str

class RejectUserRequest(BaseModel):
    reason: str = ""


def _ensure_default_roles(db: Session):
    """Create default roles if they don't exist"""
    for role_name, perms in DEFAULT_PERMISSIONS.items():
        existing = db.query(Role).filter(Role.name == role_name).first()
        if not existing:
            role = Role(
                id=str(uuid.uuid4()),
                name=role_name,
                description=f"{role_name.title()} role",
                permissions=perms,
                rate_limits={},
            )
            db.add(role)
    db.commit()


def _serialize_user(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role.name if u.role else "none",
        "is_active": u.is_active,
        "status": u.status or USER_STATUS_APPROVED,
        "rejection_reason": u.rejection_reason,
        "approved_at": str(u.approved_at) if u.approved_at else None,
        "approved_by": u.approved_by,
        "last_login": str(u.last_login) if u.last_login else None,
        "created_at": str(u.created_at),
    }


@router.post("/register")
async def register(request: RegisterRequest, http_request: Request, db: Session = Depends(get_db)):
    """Register a new user.

    First user becomes admin (auto-approved). All other registrations go
    into the admin approval queue with status='pending' and is_active=False.
    No access token is returned — the user must wait for approval.
    """
    _ensure_default_roles(db)
    meta = _request_meta(http_request)

    # Check if email already exists
    existing = db.query(User).filter(User.email == request.email).first()
    if existing:
        logger.warning(f"register_blocked_duplicate email={request.email} ip={meta['ip']}")
        record(db, action=ACTION_REGISTER, category="auth",
               user_email=request.email, ip=meta["ip"], user_agent=meta["user_agent"],
               status_code=400,
               metadata={"outcome": "duplicate_email"})
        raise HTTPException(status_code=400, detail="Email already registered")

    # First user gets admin role + auto-approval; others go viewer + pending
    user_count = db.query(User).count()
    is_first_user = user_count == 0
    role_name = "admin" if is_first_user else "viewer"
    role = db.query(Role).filter(Role.name == role_name).first()

    now = datetime.utcnow()
    user = User(
        id=str(uuid.uuid4()),
        email=request.email,
        password_hash=_hash_password(request.password),
        full_name=request.full_name,
        role_id=role.id,
        is_active=is_first_user,
        status=USER_STATUS_APPROVED if is_first_user else USER_STATUS_PENDING,
        approved_at=now if is_first_user else None,
        approved_by="self-bootstrap" if is_first_user else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(
        f"register email={user.email} role={role_name} status={user.status} "
        f"first_user={is_first_user} ip={meta['ip']}"
    )
    record(
        db, action=ACTION_REGISTER, category="auth",
        user_id=user.id, user_email=user.email, role=role_name,
        ip=meta["ip"], user_agent=meta["user_agent"],
        status_code=200,
        metadata={"first_user": is_first_user, "approval_required": not is_first_user},
    )

    if is_first_user:
        token = create_access_token(user.id)
        return APIResponse(
            success=True,
            message=f"User registered as {role_name} (first user, auto-approved)",
            data={
                "user": {"id": user.id, "email": user.email, "full_name": user.full_name,
                          "role": role_name, "status": USER_STATUS_APPROVED,
                          "permissions": role.permissions},
                "access_token": token,
                "token_type": "bearer",
                "status": USER_STATUS_APPROVED,
                "approval_required": False,
            },
        )

    # Pending: do not issue a token. Frontend should show "awaiting approval".
    return APIResponse(
        success=True,
        message="Registration received — your account is pending admin approval.",
        data={
            "user": {"id": user.id, "email": user.email, "status": USER_STATUS_PENDING},
            "status": USER_STATUS_PENDING,
            "approval_required": True,
        },
    )


@router.post("/login")
async def login(request: LoginRequest, http_request: Request, db: Session = Depends(get_db)):
    """Login with email and password. Blocks unapproved or rejected users."""
    _ensure_default_roles(db)
    meta = _request_meta(http_request)

    user = db.query(User).filter(User.email == request.email).first()
    if not user or not _verify_password(request.password, user.password_hash):
        logger.warning(f"login_failed email={request.email} ip={meta['ip']} reason=invalid_credentials")
        record(db, action=ACTION_LOGIN_FAILED, category="auth",
               user_id=user.id if user else None,
               user_email=request.email,
               ip=meta["ip"], user_agent=meta["user_agent"],
               status_code=401,
               metadata={"reason": "invalid_credentials"})
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Approval gate
    user_status = user.status or USER_STATUS_APPROVED
    if user_status == USER_STATUS_PENDING:
        logger.info(f"login_blocked_pending email={user.email} ip={meta['ip']}")
        record_for_user(db, user, action=ACTION_LOGIN_FAILED, category="auth",
                        ip=meta["ip"], user_agent=meta["user_agent"], status_code=403,
                        metadata={"reason": "pending_approval"})
        raise HTTPException(
            status_code=403,
            detail="Your account is pending admin approval. You'll be able to sign in once an admin approves it.",
        )
    if user_status == USER_STATUS_REJECTED:
        reason = user.rejection_reason or "Contact support for more information."
        logger.info(f"login_blocked_rejected email={user.email} ip={meta['ip']}")
        record_for_user(db, user, action=ACTION_LOGIN_FAILED, category="auth",
                        ip=meta["ip"], user_agent=meta["user_agent"], status_code=403,
                        metadata={"reason": "rejected", "rejection_reason": reason})
        raise HTTPException(
            status_code=403,
            detail=f"Your registration was not approved. Reason: {reason}",
        )

    if not user.is_active:
        logger.info(f"login_blocked_inactive email={user.email} ip={meta['ip']}")
        record_for_user(db, user, action=ACTION_LOGIN_FAILED, category="auth",
                        ip=meta["ip"], user_agent=meta["user_agent"], status_code=403,
                        metadata={"reason": "deactivated"})
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()

    logger.info(f"login_success email={user.email} ip={meta['ip']}")
    record_for_user(db, user, action=ACTION_LOGIN_SUCCESS, category="auth",
                    ip=meta["ip"], user_agent=meta["user_agent"], status_code=200)

    token = create_access_token(user.id)

    return APIResponse(
        success=True,
        message="Login successful",
        data={
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role.name,
                "status": user_status,
                "permissions": user.role.permissions,
            },
            "access_token": token,
            "token_type": "bearer",
        },
    )


@router.get("/me")
async def get_profile(user = Depends(get_current_user)):
    """Get current user profile"""
    return APIResponse(
        success=True,
        message="Profile retrieved",
        data={
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.name,
            "permissions": user.role.permissions,
            "is_active": user.is_active,
            "status": user.status or USER_STATUS_APPROVED,
            "last_login": str(user.last_login) if user.last_login else None,
            "created_at": str(user.created_at),
        },
    )


@router.put("/me")
async def update_profile(request: UpdateProfileRequest, user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update current user profile"""
    if request.full_name is not None:
        user.full_name = request.full_name
    if request.email is not None:
        existing = db.query(User).filter(User.email == request.email, User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = request.email

    db.commit()
    db.refresh(user)

    return APIResponse(
        success=True,
        message="Profile updated",
        data={"id": user.id, "email": user.email, "full_name": user.full_name},
    )


# --- Admin endpoints ---

@router.get("/users")
async def list_users(admin = Depends(require_admin), db: Session = Depends(get_db)):
    """List all users (admin only)"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return APIResponse(
        success=True,
        message=f"Found {len(users)} users",
        data={"users": [_serialize_user(u) for u in users]},
    )


@router.get("/users/pending")
async def list_pending_users(admin = Depends(require_admin), db: Session = Depends(get_db)):
    """List users awaiting approval (admin only)."""
    users = db.query(User).filter(User.status == USER_STATUS_PENDING).order_by(User.created_at.desc()).all()
    return APIResponse(
        success=True,
        message=f"{len(users)} pending users",
        data={"users": [_serialize_user(u) for u in users]},
    )


@router.post("/users")
async def create_user(request: CreateUserRequest, http_request: Request, admin = Depends(require_admin), db: Session = Depends(get_db)):
    """Create a user (admin only). Admin-created users are auto-approved."""
    _ensure_default_roles(db)
    meta = _request_meta(http_request)

    existing = db.query(User).filter(User.email == request.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    role = db.query(Role).filter(Role.name == request.role).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Role '{request.role}' not found")

    user = User(
        id=str(uuid.uuid4()),
        email=request.email,
        password_hash=_hash_password(request.password),
        full_name=request.full_name,
        role_id=role.id,
        is_active=True,
        status=USER_STATUS_APPROVED,
        approved_at=datetime.utcnow(),
        approved_by=admin.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"user_created_by_admin admin={admin.email} new_user={user.email} role={request.role}")
    record_for_user(
        db, admin, action=ACTION_USER_CREATED_BY_ADMIN, category="admin",
        resource_type="user", resource_id=user.id,
        ip=meta["ip"], user_agent=meta["user_agent"], status_code=200,
        metadata={"new_user_email": user.email, "new_user_role": request.role},
    )

    return APIResponse(
        success=True,
        message=f"User created with role {request.role} (approved)",
        data=_serialize_user(user),
    )


@router.post("/users/{user_id}/approve")
async def approve_user(user_id: str, http_request: Request, admin = Depends(require_admin), db: Session = Depends(get_db)):
    """Approve a pending registration (admin only)."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    meta = _request_meta(http_request)

    target.status = USER_STATUS_APPROVED
    target.is_active = True
    target.rejection_reason = None
    target.approved_at = datetime.utcnow()
    target.approved_by = admin.id
    db.commit()
    db.refresh(target)

    logger.info(f"user_approved admin={admin.email} target={target.email}")
    record_for_user(
        db, admin, action=ACTION_USER_APPROVED, category="admin",
        resource_type="user", resource_id=target.id,
        ip=meta["ip"], user_agent=meta["user_agent"], status_code=200,
        metadata={"target_email": target.email},
    )

    return APIResponse(success=True, message="User approved", data=_serialize_user(target))


@router.post("/users/{user_id}/reject")
async def reject_user(
    user_id: str,
    request: RejectUserRequest,
    http_request: Request,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reject a pending registration (admin only)."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot reject yourself")
    meta = _request_meta(http_request)

    target.status = USER_STATUS_REJECTED
    target.is_active = False
    target.rejection_reason = (request.reason or "").strip()[:500] or None
    target.approved_at = datetime.utcnow()
    target.approved_by = admin.id
    db.commit()
    db.refresh(target)

    logger.info(f"user_rejected admin={admin.email} target={target.email}")
    record_for_user(
        db, admin, action=ACTION_USER_REJECTED, category="admin",
        resource_type="user", resource_id=target.id,
        ip=meta["ip"], user_agent=meta["user_agent"], status_code=200,
        metadata={"target_email": target.email, "reason": target.rejection_reason},
    )

    return APIResponse(success=True, message="User rejected", data=_serialize_user(target))


@router.put("/users/{user_id}/role")
async def update_user_role(user_id: str, request: UpdateUserRoleRequest, http_request: Request, admin = Depends(require_admin), db: Session = Depends(get_db)):
    """Update a user's role (admin only)"""
    _ensure_default_roles(db)
    meta = _request_meta(http_request)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    role = db.query(Role).filter(Role.name == request.role).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Role '{request.role}' not found")

    old_role = target.role.name if target.role else None
    target.role_id = role.id
    db.commit()

    logger.info(f"role_changed admin={admin.email} target={target.email} {old_role}->{request.role}")
    record_for_user(
        db, admin, action=ACTION_ROLE_CHANGED, category="admin",
        resource_type="user", resource_id=target.id,
        ip=meta["ip"], user_agent=meta["user_agent"], status_code=200,
        metadata={"target_email": target.email, "from_role": old_role, "to_role": request.role},
    )

    return APIResponse(success=True, message=f"User role updated to {request.role}", data={"user_id": user_id, "role": request.role})


@router.put("/users/{user_id}/deactivate")
async def deactivate_user(user_id: str, http_request: Request, admin = Depends(require_admin), db: Session = Depends(get_db)):
    """Toggle a user's is_active flag (admin only). Doesn't change approval status."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    meta = _request_meta(http_request)

    target.is_active = not target.is_active
    db.commit()

    status_text = "activated" if target.is_active else "deactivated"
    logger.info(f"user_{status_text} admin={admin.email} target={target.email}")
    record_for_user(
        db, admin,
        action=ACTION_USER_REACTIVATED if target.is_active else ACTION_USER_DEACTIVATED,
        category="admin", resource_type="user", resource_id=target.id,
        ip=meta["ip"], user_agent=meta["user_agent"], status_code=200,
        metadata={"target_email": target.email},
    )
    return APIResponse(success=True, message=f"User {status_text}", data={"user_id": user_id, "is_active": target.is_active})


@router.get("/roles")
async def list_roles(admin = Depends(require_admin), db: Session = Depends(get_db)):
    """List all roles (admin only)"""
    _ensure_default_roles(db)
    roles = db.query(Role).all()
    return APIResponse(
        success=True,
        message=f"Found {len(roles)} roles",
        data={
            "roles": [
                {"id": r.id, "name": r.name, "description": r.description, "permissions": r.permissions}
                for r in roles
            ]
        },
    )
