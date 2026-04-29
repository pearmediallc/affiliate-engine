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
# DDL is dialect-friendly: SQLite doesn't enforce types but accepts them.
_REQUIRED_COLUMNS = [
    # User approval workflow
    ("users", "status", "VARCHAR DEFAULT 'approved'"),
    ("users", "rejection_reason", "TEXT"),
    ("users", "approved_at", "DATETIME"),
    ("users", "approved_by", "VARCHAR"),
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
