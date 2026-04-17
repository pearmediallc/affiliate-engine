from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# Support both PostgreSQL and SQLite
engine = create_engine(
    settings.database_url,
    # pool_pre_ping for PostgreSQL connection health checks
    pool_pre_ping=True if settings.database_url.startswith("postgresql") else False,
    # SQLite needs connect_args for threading
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all models
Base = declarative_base()


def get_db():
    """Dependency for database sessions in FastAPI routes"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database - creates all tables"""
    Base.metadata.create_all(bind=engine)
