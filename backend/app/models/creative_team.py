"""
Durable audit log for the creative team — one row per persona step / eval / coaching, so every
task is permanently recorded (survives restarts/deploys) and drillable per job. Because it lives
in the shared Postgres, reports + coaching are also consistent across workers.
"""
from sqlalchemy import Column, String, DateTime, Text, Integer, Float, Boolean, Index
from datetime import datetime
import uuid
from ..database import Base


class CreativeTeamEvent(Base):
    __tablename__ = "creative_team_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, nullable=True, index=True)       # = the regen request_id
    creative_id = Column(String, nullable=True)
    persona = Column(String, nullable=False, index=True)     # director, strategist, ...
    role = Column(String, nullable=True)                     # human-readable role name
    event = Column(String, nullable=False, index=True)       # done | fail | revise | coached | reward
    task = Column(Text, nullable=True)
    detail = Column(Text, nullable=True)
    ms = Column(Integer, nullable=True)
    ok = Column(Boolean, nullable=True)
    revised = Column(Boolean, nullable=True)
    helpfulness = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("ix_cte_job_persona", "job_id", "persona"),)


class CreativeLesson(Base):
    """Self-learning failure memory: every mistake the team makes is recorded here with WHY it
    happened and the corrective RULE, deduped by a signature so repeats increment `hits` instead of
    duplicating. The brain reads applicable lessons before every job so a failure never recurs."""
    __tablename__ = "creative_lessons"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sig = Column(String, unique=True, index=True)   # dedup signature (scope+trigger+rule)
    scope = Column(String, index=True)              # routing | quality | engine | asset | cost | job
    style = Column(String, nullable=True, index=True)
    engine = Column(String, nullable=True)
    vertical = Column(String, nullable=True, index=True)
    trigger = Column(Text, nullable=True)           # what happened / what was asked
    reason = Column(Text, nullable=True)            # WHY it failed
    rule = Column(Text, nullable=True)              # HOW to avoid it next time (the corrective)
    job_id = Column(String, nullable=True)
    hits = Column(Integer, default=1)               # how many times this failure recurred
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LipsyncJob(Base):
    """Durable handle for an in-flight video→video lip-sync so a long render SURVIVES an AE
    restart: we persist the provider + provider job id + everything needed to finalize, and a
    startup resumer re-polls and delivers it (no more orphaned 'running' jobs)."""
    __tablename__ = "lipsync_jobs"

    id = Column(String, primary_key=True)                    # = the regen request_id
    provider = Column(String, nullable=False)                # sync | fal | latentsync | wav2lip
    provider_job = Column(String, nullable=False)            # the provider's generation/prediction id
    audio_url = Column(Text, nullable=True)
    char_url = Column(Text, nullable=True)
    callback_url = Column(Text, nullable=True)
    out_name = Column(String, nullable=True)
    script = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="polling", index=True)   # polling | done | failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
