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
    # Learning loop — holdout-gated promotion state on vertical_knowledge
    ("vertical_knowledge", "promoted", "BOOLEAN DEFAULT FALSE"),
    ("vertical_knowledge", "promotion_metrics", "TEXT"),
    # Creative learning loop — per-brain choices + attribution on creative_decisions
    # The human verdict/reason the learning loop reads AND that SQLAlchemy names on every INSERT.
    # These were missing in prod, so EVERY creative_decisions insert failed with UndefinedColumn --
    # silently, inside a broad except -- which is why /learn/decisions returned [] for every job and
    # the learning loop recorded nothing at all.
    ("creative_decisions", "human_verdict", "VARCHAR"),
    ("creative_decisions", "human_reason", "TEXT"),
    # Same failure, missed in the earlier fix: verdict_at is on the model but was never migrated,
    # so it alone kept killing every INSERT. THIS is why creative_decisions still had 0 rows.
    ("creative_decisions", "verdict_at", "TIMESTAMP"),
    ("creative_decisions", "script_mode", "VARCHAR"),
    ("creative_decisions", "caption_method", "VARCHAR"),
    ("creative_decisions", "caption_removal_method", "VARCHAR"),
    ("creative_decisions", "blamed_brains", "TEXT"),
    # Diversification axis the creative was generated along (character|script|hook|format)
    ("creative_decisions", "variation_axis", "VARCHAR"),
    # Admin-approval gate — engine reads a governed rule ONLY when an admin approved it (active).
    ("creative_brain_rules", "active", "BOOLEAN DEFAULT FALSE"),
    # FULL PARITY with app/models/creative_team.py::CreativeDecision. SQLAlchemy names EVERY mapped
    # column on INSERT, so a single un-migrated column kills 100% of QA writes (that is what happened
    # twice: human_verdict/human_reason, then verdict_at). These are all no-ops where the column
    # already exists; listing them means the next added column can only ever be missed once.
    ("creative_decisions", "creative_ref", "VARCHAR"),
    ("creative_decisions", "vertical", "VARCHAR"),
    ("creative_decisions", "character_key", "VARCHAR"),
    ("creative_decisions", "character_gender", "VARCHAR"),
    ("creative_decisions", "character_age", "VARCHAR"),
    ("creative_decisions", "voice_id", "VARCHAR"),
    ("creative_decisions", "voice_provider", "VARCHAR"),
    ("creative_decisions", "voice_cloned", "BOOLEAN"),
    ("creative_decisions", "lipsync_provider", "VARCHAR"),
    ("creative_decisions", "video_model", "VARCHAR"),
    ("creative_decisions", "script_ref", "TEXT"),
    ("creative_decisions", "captions", "BOOLEAN"),
    ("creative_decisions", "qc_passed", "BOOLEAN"),
    ("creative_decisions", "qc_reasons", "TEXT"),
    ("creative_decisions", "cost_usd", "DOUBLE PRECISION"),
    ("creative_decisions", "roi", "DOUBLE PRECISION"),
    ("creative_decisions", "roi_updated_at", "TIMESTAMP"),
    # LipsyncJob — persisted assembly assets so a restart resumes the COMPLETE delivery (b-roll
    # composite + caption burn + QA gate), not a raw talking-head. Nullable so old 'polling' rows work.
    ("lipsync_jobs", "assets_json", "TEXT"),
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

    # Per-user long-term agentic memory table. Created here (not from a SQLAlchemy model) because it
    # picks its embedding column type at runtime — vector(1536) when pgvector is available, else a
    # JSON-text fallback — which a static model can't express.
    _ensure_user_memory_table()

    # Per-character voice-clone cache (SAVE + REUSE the character's cloned voice across generations).
    _ensure_voice_clones_table()

    # Reconcile historical lip-sync costs to the REAL rate (veed was logged at ~7x). Recomputes from
    # `units` (seconds), so it is idempotent and safe on every boot — fixes the inflated office totals.
    _backfill_lipsync_costs()


def _backfill_lipsync_costs() -> None:
    """Recompute every stored lip-sync cost from its `units` (seconds) × the REAL per-minute rate.
    Historical veed rows were written at $0.07/s (~7x high), which inflated the office 'spent this
    month' and per-gen totals (they're SUMs of creation_costs.cost_usd). Recomputing from units is
    idempotent — a correct row recomputes to itself — so this runs safely on every startup."""
    import math
    try:
        from .services.lip_sync import FAL_LIPSYNC_PER_MIN as PM
    except Exception:
        PM = {"kling": 0.168, "falsync": 0.70, "veed": 0.60}
    per_min = {"sync": PM.get("falsync", 0.70), "fal": PM.get("veed", 0.60), **PM}
    try:
        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT id, provider, units FROM creation_costs "
                "WHERE step='lipsync' AND unit_type='sec' AND units IS NOT NULL AND units > 0")).fetchall()
            n = 0
            for _id, prov, units in rows:
                p = (prov or "").lower()
                if p in ("latentsync", "wav2lip"):            # flat per-render — leave as-is
                    continue
                if p == "kling":                              # billed in whole 5s blocks
                    new = round(math.ceil(float(units) / 5.0) * (PM.get("kling", 0.168) * 5.0 / 60.0), 4)
                else:
                    new = round(float(units) / 60.0 * per_min.get(p, 0.70), 4)
                conn.execute(text("UPDATE creation_costs SET cost_usd=:c WHERE id=:i"),
                             {"c": new, "i": _id})
                n += 1
        logger.info(f"migrations: reconciled {n} lip-sync cost rows to real rates")
    except Exception as e:
        logger.warning(f"migrations: lip-sync cost backfill skipped: {e}")


def _ensure_voice_clones_table() -> None:
    """Create the `voice_clones` cache (idempotent). One row per character: the SAVED clone reference
    (a stable S3 key for the ~15s voice sample + its transcript) so subsequent generations REUSE the
    same cloned voice instead of re-extracting/re-transcribing — consistent voice, less cost."""
    dialect = engine.dialect.name
    is_pg = dialect.startswith("postgres")
    ts_ddl = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    ddl = f"""
        CREATE TABLE IF NOT EXISTS voice_clones (
            character_key TEXT PRIMARY KEY,   -- stable per-character id (asset id / source filename)
            sample_key    TEXT,               -- stable S3 key of the saved voice sample (re-presign on use)
            ref_text      TEXT,               -- transcript of the sample → F5-TTS ref_text
            provider      TEXT,               -- f5 | elevenlabs (which engine the clone is for)
            created_at    {ts_ddl},
            updated_at    {ts_ddl}
        )
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(ddl))
        logger.info("migrations: voice_clones table ready")
    except Exception as e:
        logger.error(f"migrations: failed to create voice_clones: {e}")


def _ensure_user_memory_table() -> None:
    """Create the pgvector-optional `user_memory` table (idempotent).

    Detects pgvector at runtime: on Postgres we try `CREATE EXTENSION IF NOT EXISTS vector` (the DB
    user may lack permission — we log and continue), then check pg_type. If `vector` is available the
    embedding column is vector(1536) and search uses the `<=>` operator; otherwise embedding is TEXT
    holding a JSON float array and cosine similarity is computed in Python (per-user rows are few).
    """
    dialect = engine.dialect.name
    is_pg = dialect.startswith("postgres")

    use_vector = False
    if is_pg:
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as e:
            logger.warning(f"migrations: pgvector extension unavailable ({e}); "
                           f"user_memory will use the JSON-text embedding fallback")
        try:
            with engine.connect() as conn:
                use_vector = bool(conn.execute(
                    text("SELECT 1 FROM pg_type WHERE typname = 'vector'")).first())
        except Exception:
            use_vector = False

    id_ddl = "BIGSERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    emb_ddl = "vector(1536)" if use_vector else "TEXT"   # TEXT = JSON float array (fallback)
    ts_ddl = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"        # portable across SQLite + Postgres

    ddl = f"""
        CREATE TABLE IF NOT EXISTS user_memory (
            id          {id_ddl},
            user_id     TEXT NOT NULL,
            kind        TEXT NOT NULL DEFAULT 'factual',   -- factual | episodic | semantic
            mem_key     TEXT,                              -- set for factual overrides; NULL for episodic
            content     TEXT,
            embedding   {emb_ddl},
            source_ref  TEXT,                              -- provenance: the message/turn it came from
            created_at  {ts_ddl},
            updated_at  {ts_ddl}
        )
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(ddl))
        logger.info(f"migrations: user_memory table ready (embedding={emb_ddl})")
    except Exception as e:
        logger.error(f"migrations: failed to create user_memory: {e}")
        return

    try:
        with engine.begin() as conn:
            # Every read/write filters by user_id (strict per-user scoping).
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_user_memory_user ON user_memory(user_id)"))
            # Upsert key for factual overrides: one row per (user_id, kind, mem_key). Episodic rows
            # carry mem_key=NULL, and NULLs are distinct in a unique index on BOTH SQLite and Postgres,
            # so episodic memories append freely while factual ones overwrite (no stale duplicates).
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_memory_key "
                "ON user_memory(user_id, kind, mem_key)"))
    except Exception as e:
        logger.warning(f"migrations: user_memory index skipped: {e}")
