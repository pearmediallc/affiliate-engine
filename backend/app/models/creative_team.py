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
