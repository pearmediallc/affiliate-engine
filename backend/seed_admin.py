"""Seed script: creates the admin user on first deploy. Run once."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, init_db
from app.models.user import User, Role
from app.routes.auth import _hash_password, _ensure_default_roles
import uuid

def seed():
    init_db()
    db = SessionLocal()
    try:
        _ensure_default_roles(db)
        
        existing = db.query(User).filter(User.email == "deepanshupear@gmail.com").first()
        if existing:
            print(f"Admin user already exists (id={existing.id})")
            return
        
        role = db.query(Role).filter(Role.name == "admin").first()
        user = User(
            id=str(uuid.uuid4()),
            email="deepanshupear@gmail.com",
            password_hash=_hash_password("Peardeepanshu123@"),
            full_name="Deepanshu Pear",
            role_id=role.id,
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"Admin user created: deepanshupear@gmail.com (id={user.id})")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
