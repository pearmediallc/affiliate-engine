"""
Prompt Harness Engine — DB models.

GenerationEvent: one row per generation attempt, capturing full input context,
  outcome signals, and behavioral markers (retry speed, sentiment shifts).

UserPromptProfile: synthesized per-user, per-vertical prompt profile.
  Updated automatically by the harness after N events.
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text, Integer, Float, Boolean
from datetime import datetime
import uuid
from ..database import Base


class GenerationEvent(Base):
    __tablename__ = "generation_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    vertical = Column(String, nullable=False, index=True)
    feature = Column(String, nullable=False, index=True)  # image | video | speech | caption

    # Raw input from user
    raw_prompt = Column(Text, nullable=False)
    # Harness-enriched prompt that was actually sent to the API
    enriched_prompt = Column(Text, nullable=True)

    # Generation parameters
    model_id = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    params = Column(JSON, nullable=True)  # color_grade, aspect, style, etc.

    # Outcome signals (filled in by after_generate)
    downloaded = Column(Boolean, nullable=True)      # user clicked download
    regenerated = Column(Boolean, nullable=True)     # user immediately re-ran
    approved = Column(Boolean, nullable=True)        # user explicitly approved
    rejected = Column(Boolean, nullable=True)        # user explicitly rejected
    time_to_action_sec = Column(Float, nullable=True) # seconds from result to next action

    # Behavioral / sentiment signals
    is_retry = Column(Boolean, default=False)        # this was a retry of a previous prompt
    retry_count = Column(Integer, default=0)         # how many times user retried this session
    prompt_sentiment = Column(String, nullable=True)  # positive | neutral | frustrated
    prompt_complexity = Column(String, nullable=True) # simple | moderate | complex

    # Cost and metadata
    cost_usd = Column(Float, nullable=True)
    generation_time_sec = Column(Float, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    outcome_recorded_at = Column(DateTime, nullable=True)


class UserPromptProfile(Base):
    """
    Synthesized profile for a user × vertical combination.
    Built by analyzing their GenerationEvent history.
    Acts as injected context before every new generation.
    """
    __tablename__ = "user_prompt_profiles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    vertical = Column(String, nullable=False, index=True)

    # Synthesized prompt style traits
    preferred_tone = Column(String, nullable=True)          # urgent | warm | professional | playful
    preferred_shot_types = Column(JSON, nullable=True)      # ["spokesperson", "b_roll"]
    preferred_color_grade = Column(String, nullable=True)
    preferred_caption_style = Column(String, nullable=True)
    preferred_music_mood = Column(String, nullable=True)
    preferred_models = Column(JSON, nullable=True)          # {feature: model_id}

    # What works / what doesn't
    successful_prompt_patterns = Column(JSON, nullable=True) # phrases/structures that got downloads
    failed_prompt_patterns = Column(JSON, nullable=True)     # patterns that led to rejection/retry
    learned_rules = Column(JSON, nullable=True)              # Gemini-synthesized rules list

    # Behavioral profile
    avg_retry_count = Column(Float, nullable=True)
    frustration_triggers = Column(JSON, nullable=True)       # ["vague prompts", "wrong aspect"]
    typical_prompt_complexity = Column(String, nullable=True)

    # Stats
    total_generations = Column(Integer, default=0)
    successful_generations = Column(Integer, default=0)
    satisfaction_rate = Column(Float, nullable=True)
    total_spend_usd = Column(Float, default=0.0)

    last_synthesized_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
