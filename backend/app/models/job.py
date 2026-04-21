"""Job model - persistent async job tracking"""
from sqlalchemy import Column, String, DateTime, JSON, Text, Float
from datetime import datetime
import uuid
from ..database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    job_type = Column(String, nullable=False, index=True)  # ugc_video, talking_head, veo_video, image_generation, script, ad_copy, landing_page, angle_generation
    status = Column(String, default="pending", index=True)  # pending, processing, completed, failed
    provider = Column(String, nullable=True)  # tiktok, replicate, google, gemini
    provider_job_id = Column(String, nullable=True)  # external task/prediction/operation ID
    input_data = Column(JSON, nullable=True)  # what was requested
    result_data = Column(JSON, nullable=True)  # the output (URLs, text, HTML, etc.)
    result_url = Column(String, nullable=True)  # primary result URL (video, image, etc.)
    error_message = Column(Text, nullable=True)
    cost_usd = Column(Float, default=0.0)
    vertical = Column(String, nullable=True)
    admin_feedback_rating = Column(String, nullable=True)  # admin's rating: positive/negative
    admin_feedback_comment = Column(Text, nullable=True)  # admin's comment
    admin_feedback_by = Column(String, nullable=True)  # admin user ID who gave feedback
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
