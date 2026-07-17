"""Persistent cache for tag-asset (ffprobe + transcribe + vision) results.

Keyed by the STABLE S3 object key (no presign query string), so the expensive
download/Whisper/Gemini pass runs ONCE per clip and every later call is a DB read.
The clip content behind a key never changes, so there is no TTL.
"""
from sqlalchemy import Column, String, Text, DateTime
from datetime import datetime
from ..database import Base


class AssetTag(Base):
    __tablename__ = "asset_tags"

    s3_key = Column(String, primary_key=True)       # normalized S3 object key (query string stripped)
    tags_json = Column(Text, nullable=False)        # full tag-asset result, JSON-encoded
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
