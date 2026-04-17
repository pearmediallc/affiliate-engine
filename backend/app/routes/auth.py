"""Authentication routes"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from passlib.context import CryptContext
import hashlib
from datetime import datetime
import uuid
from ..database import get_db
from ..models.user import User, Role
from ..schemas import APIResponse
from ..middleware.auth import get_current_user, require_admin, create_access_token

router = APIRouter()
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


@router.post("/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user. First user becomes admin, subsequent users need admin approval."""
    _ensure_default_roles(db)

    # Check if email already exists
    existing = db.query(User).filter(User.email == request.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # First user gets admin role, others get viewer
    user_count = db.query(User).count()
    role_name = "admin" if user_count == 0 else "viewer"
    role = db.query(Role).filter(Role.name == role_name).first()

    user = User(
        id=str(uuid.uuid4()),
        email=request.email,
        password_hash=_hash_password(request.password),
        full_name=request.full_name,
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)

    return APIResponse(
        success=True,
        message=f"User registered as {role_name}",
        data={
            "user": {"id": user.id, "email": user.email, "full_name": user.full_name, "role": role_name},
            "access_token": token,
            "token_type": "bearer",
        },
    )


@router.post("/login")
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Login with email and password"""
    _ensure_default_roles(db)

    user = db.query(User).filter(User.email == request.email).first()
    if not user or not _verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()

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
    users = db.query(User).all()
    return APIResponse(
        success=True,
        message=f"Found {len(users)} users",
        data={
            "users": [
                {
                    "id": u.id,
                    "email": u.email,
                    "full_name": u.full_name,
                    "role": u.role.name if u.role else "none",
                    "is_active": u.is_active,
                    "last_login": str(u.last_login) if u.last_login else None,
                    "created_at": str(u.created_at),
                }
                for u in users
            ]
        },
    )


@router.post("/users")
async def create_user(request: CreateUserRequest, admin = Depends(require_admin), db: Session = Depends(get_db)):
    """Create a user (admin only)"""
    _ensure_default_roles(db)

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
    )
    db.add(user)
    db.commit()

    return APIResponse(
        success=True,
        message=f"User created with role {request.role}",
        data={"id": user.id, "email": user.email, "role": request.role},
    )


@router.put("/users/{user_id}/role")
async def update_user_role(user_id: str, request: UpdateUserRoleRequest, admin = Depends(require_admin), db: Session = Depends(get_db)):
    """Update a user's role (admin only)"""
    _ensure_default_roles(db)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    role = db.query(Role).filter(Role.name == request.role).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Role '{request.role}' not found")

    target.role_id = role.id
    db.commit()

    return APIResponse(success=True, message=f"User role updated to {request.role}", data={"user_id": user_id, "role": request.role})


@router.put("/users/{user_id}/deactivate")
async def deactivate_user(user_id: str, admin = Depends(require_admin), db: Session = Depends(get_db)):
    """Deactivate a user (admin only)"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    target.is_active = not target.is_active
    db.commit()

    status_text = "activated" if target.is_active else "deactivated"
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
