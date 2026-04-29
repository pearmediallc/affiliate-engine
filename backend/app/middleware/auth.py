"""Authentication and authorization middleware"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from ..database import get_db
from ..config import settings

security = HTTPBearer(auto_error=False)

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Extract and validate JWT token, return User object"""
    # Import here to avoid circular imports
    from ..models.user import User

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Like get_current_user but returns None instead of raising if no token"""
    from ..models.user import User

    if not credentials:
        return None

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str = payload.get("sub")
        if not user_id:
            return None
        return db.query(User).filter(User.id == user_id, User.is_active == True).first()
    except JWTError:
        return None


def require_permission(feature: str):
    """Dependency factory: checks if user's role allows this feature"""
    def checker(user = Depends(get_current_user)):
        from ..models.user import User
        if not user.role:
            raise HTTPException(status_code=403, detail="No role assigned")

        permissions = user.role.permissions or {}
        feature_perm = permissions.get(feature, {})

        if not feature_perm.get("allowed", False):
            raise HTTPException(
                status_code=403,
                detail=f"Your role '{user.role.name}' does not have access to {feature}",
            )
        return user
    return checker


def check_rate_limit(feature: str):
    """Dependency factory: checks if user has exceeded daily rate limit for feature"""
    def checker(user = Depends(get_current_user), db: Session = Depends(get_db)):
        from ..models.user import UsageLog

        permissions = user.role.permissions or {}
        feature_perm = permissions.get(feature, {})
        daily_limit = feature_perm.get("daily_limit")

        # No limit set means unlimited
        if daily_limit is None:
            return user

        # Count today's usage
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        usage_count = db.query(func.count(UsageLog.id)).filter(
            UsageLog.user_id == user.id,
            UsageLog.feature == feature,
            UsageLog.created_at >= today_start,
        ).scalar()

        if usage_count >= daily_limit:
            raise HTTPException(
                status_code=429,
                detail=f"Daily limit of {daily_limit} {feature} operations exceeded. Resets at midnight UTC.",
            )
        return user
    return checker


def require_admin(user = Depends(get_current_user)):
    """Require admin role"""
    if not user.role or user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def log_usage(feature: str, user_id: str, db: Session, cost_usd: float = 0.0, metadata: dict = None):
    """Log a usage event for rate limiting tracking + spend audit. Stores cost as float."""
    from ..models.user import UsageLog
    import uuid

    log = UsageLog(
        id=str(uuid.uuid4()),
        user_id=user_id,
        feature=feature,
        cost_usd=float(cost_usd or 0.0),
        metadata_json=metadata,
    )
    db.add(log)
    db.commit()


def create_access_token(user_id: str, expires_delta: timedelta = None) -> str:
    """Create a JWT access token"""
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expiry_minutes))
    to_encode = {"sub": user_id, "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)
