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
    """Initialize database - creates all tables, then runs additive migrations."""
    Base.metadata.create_all(bind=engine)
    # Apply additive column migrations (User.status, etc.) so existing DBs upgrade in place.
    try:
        from .migrations import run_migrations
        run_migrations()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Schema migrations failed: {e}", exc_info=True)
