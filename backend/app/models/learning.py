from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text, Integer, Float, LargeBinary
from datetime import datetime
import uuid
from ..database import Base


class LearningRecord(Base):
    __tablename__ = "learning_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    vertical = Column(String, nullable=False, index=True)
    feature = Column(String, nullable=False, index=True)  # image_generation, hook_analysis, etc.
    input_data = Column(JSON, nullable=False)  # prompt, settings, style, parameters
    output_data = Column(JSON, nullable=True)  # provider, model, cost, resolution, file ref
    feedback_rating = Column(String, nullable=True)  # positive/negative
    feedback_issues = Column(JSON, nullable=True)  # ["spelling", "wrong_style"]
    feedback_comment = Column(Text, nullable=True)
    quality_metrics = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class VerticalKnowledge(Base):
    __tablename__ = "vertical_knowledge"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vertical = Column(String, unique=True, nullable=False, index=True)
    learned_rules = Column(JSON, nullable=False, default=dict)
    style_preferences = Column(JSON, nullable=True)
    provider_performance = Column(JSON, nullable=True)
    total_samples = Column(Integer, default=0)
    avg_satisfaction = Column(Float, nullable=True)
    last_analyzed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AISuggestion(Base):
    __tablename__ = "ai_suggestions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    category = Column(String, nullable=False)  # prompt_improvement, style_change, pipeline_config
    vertical = Column(String, nullable=False, index=True)
    suggestion_text = Column(Text, nullable=False)
    suggested_change = Column(JSON, nullable=False)
    evidence = Column(JSON, nullable=True)  # feedback stats that triggered this
    status = Column(String, default="pending", index=True)  # pending, approved, rejected, applied
    reviewed_by = Column(String, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Asset(Base):
    __tablename__ = "assets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    asset_type = Column(String, nullable=False, index=True)  # image, audio, transcript, video
    original_filename = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    compressed_data = Column(LargeBinary, nullable=True)  # zlib compressed
    metadata_json = Column(JSON, nullable=True)  # provider, model, prompt, quality scores
    related_image_id = Column(String, ForeignKey("images.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
