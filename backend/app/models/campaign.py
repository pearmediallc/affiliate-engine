"""Campaign pipeline models: Character, Setting, Campaign, Shot, Variation"""
from sqlalchemy import Column, String, DateTime, JSON, Text, Float, Integer, ForeignKey
from datetime import datetime
import uuid
from ..database import Base


class Character(Base):
    __tablename__ = "characters"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)          # physical appearance, style, personality notes
    portrait_url = Column(String, nullable=True)       # generated reference portrait image
    portrait_path = Column(String, nullable=True)      # local file path
    consistency_prompt = Column(Text, nullable=True)   # locked prompt fragment for image consistency
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SceneSetting(Base):
    __tablename__ = "scene_settings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)          # location, lighting, atmosphere
    reference_image_url = Column(String, nullable=True)
    reference_image_path = Column(String, nullable=True)
    location_type = Column(String, nullable=True)      # interior, exterior, studio, etc.
    style_tags = Column(JSON, nullable=True)           # ["modern", "bright", "professional"]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    vertical = Column(String, nullable=True, index=True)

    # Input: idea text or reference
    brief_text = Column(Text, nullable=True)           # raw idea or brief from user
    reference_video_url = Column(String, nullable=True)
    reference_video_path = Column(String, nullable=True)
    reference_image_url = Column(String, nullable=True)
    reference_image_path = Column(String, nullable=True)

    # Analyzed output from reference
    analyzed_brief = Column(JSON, nullable=True)       # structured brief from vision analysis

    # Generated
    script = Column(Text, nullable=True)
    storyboard = Column(JSON, nullable=True)           # list of shot dicts

    # Status
    status = Column(String, default="draft", index=True)
    # draft → briefing → scripting → storyboarding → generating → editing → review → completed

    total_cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Shot(Base):
    __tablename__ = "shots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id = Column(String, ForeignKey("campaigns.id"), nullable=False, index=True)
    variation_id = Column(String, nullable=True, index=True)  # null = base; set for variants
    sequence_num = Column(Integer, nullable=False)

    shot_type = Column(String, nullable=True)          # hero, spokesperson, b_roll, transition
    character_id = Column(String, nullable=True)       # FK to characters.id
    setting_id = Column(String, nullable=True)         # FK to scene_settings.id
    prompt = Column(Text, nullable=True)               # final generation prompt
    model_id = Column(String, nullable=True)           # which model to use
    duration = Column(Integer, default=6)              # seconds

    # Generation result
    video_url = Column(String, nullable=True)
    video_path = Column(String, nullable=True)
    job_id = Column(String, nullable=True)             # FK to jobs.id
    status = Column(String, default="pending", index=True)  # pending, generating, completed, failed
    cost_usd = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Variation(Base):
    __tablename__ = "variations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id = Column(String, ForeignKey("campaigns.id"), nullable=False, index=True)

    variation_type = Column(String, nullable=True)
    # hook | character | style | setting | vertical_port

    label = Column(String, nullable=True)              # human-readable: "Hook A – urgency"
    shots_config = Column(JSON, nullable=True)         # which shots differ from base + their overrides

    # Output videos — one per aspect ratio
    final_video_url = Column(String, nullable=True)    # 16:9 (default)
    final_video_9_16 = Column(String, nullable=True)   # TikTok/Reels
    final_video_1_1 = Column(String, nullable=True)    # Instagram square

    # Music added
    music_track_id = Column(String, nullable=True)
    music_url = Column(String, nullable=True)

    status = Column(String, default="pending", index=True)
    # pending | generating | editing | completed | failed

    review_status = Column(String, default="pending")
    # pending | approved | rejected | regenerate_requested

    total_cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
