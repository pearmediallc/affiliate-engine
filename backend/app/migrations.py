"""
Idempotent additive schema migrations.

Runs on startup after Base.metadata.create_all(). Adds columns the model
declares but the existing table is missing. Safe to call repeatedly.

Why not Alembic?  This project's existing convention is auto-create on
boot (main.py calls init_db()). To avoid breaking that workflow on dev
laptops with pre-existing SQLite files, we do additive ALTERs here.
"""
import logging
from sqlalchemy import inspect, text
from .database import engine

logger = logging.getLogger(__name__)


# Each entry: (table_name, column_name, ddl_fragment_for_alter)
# DDL must be portable across SQLite + Postgres.
# - VARCHAR works on both
# - TEXT works on both
# - TIMESTAMP works on both (Postgres native; SQLite stores as TEXT but accepts it)
# - DATETIME is SQLite-only — DON'T USE IT in migrations
_REQUIRED_COLUMNS = [
    # User approval workflow
    ("users", "status", "VARCHAR DEFAULT 'approved'"),
    ("users", "rejection_reason", "TEXT"),
    ("users", "approved_at", "TIMESTAMP"),
    ("users", "approved_by", "VARCHAR"),
    # Harness engine — generation_events table columns (table created by create_all)
    ("generation_events", "is_retry", "BOOLEAN DEFAULT FALSE"),
    ("generation_events", "retry_count", "INTEGER DEFAULT 0"),
    ("generation_events", "prompt_sentiment", "VARCHAR"),
    ("generation_events", "prompt_complexity", "VARCHAR"),
    ("generation_events", "cost_usd", "DOUBLE PRECISION"),
    ("generation_events", "generation_time_sec", "DOUBLE PRECISION"),
    ("generation_events", "time_to_action_sec", "DOUBLE PRECISION"),
    ("generation_events", "outcome_recorded_at", "TIMESTAMP"),
    ("generation_events", "error", "TEXT"),
    # Harness engine — user_prompt_profiles table columns
    ("user_prompt_profiles", "frustration_triggers", "TEXT"),
    ("user_prompt_profiles", "typical_prompt_complexity", "VARCHAR"),
    ("user_prompt_profiles", "total_spend_usd", "DOUBLE PRECISION DEFAULT 0"),
    ("user_prompt_profiles", "last_synthesized_at", "TIMESTAMP"),
]


def run_migrations() -> None:
    """Run all additive schema migrations. Safe to call multiple times."""
    inspector = inspect(engine)
    dialect = engine.dialect.name

    for table, column, ddl in _REQUIRED_COLUMNS:
        try:
            existing = {c["name"] for c in inspector.get_columns(table)}
        except Exception as e:
            logger.warning(f"migrations: cannot inspect {table}: {e}")
            continue

        if column in existing:
            continue

        sql = f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
            logger.info(f"migrations: added {table}.{column}")
        except Exception as e:
            logger.error(f"migrations: failed to add {table}.{column}: {e}")

    # Backfill existing users to 'approved' so we don't lock them out on upgrade.
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE users SET status = 'approved' WHERE status IS NULL OR status = ''"
            ))
    except Exception as e:
        logger.warning(f"migrations: backfill users.status failed: {e}")

    # UsageLog.cost_usd was historically String. SQLite is flexible-typed, so
    # writing Float now works and SUM() coerces. For Postgres we'd need an
    # ALTER TYPE — gated below so non-Postgres deploys skip silently.
    if dialect.startswith("postgres"):
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE usage_logs ALTER COLUMN cost_usd "
                    "TYPE DOUBLE PRECISION USING NULLIF(cost_usd,'')::double precision"
                ))
            logger.info("migrations: usage_logs.cost_usd → double precision")
        except Exception as e:
            # Likely already migrated; not fatal.
            logger.debug(f"migrations: usage_logs.cost_usd ALTER skipped: {e}")
