from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text, Integer, Float, Boolean, LargeBinary
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
    promoted = Column(Boolean, default=False)  # measured: holdout agreement cleared the promotion bar
    promotion_metrics = Column(JSON, nullable=True)  # {live_agreement, holdout_labels, consecutive_high_cycles, ...}
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


class LearningEvent(Base):
    """
    Append-only changelog of every synthesize/tuning decision on a vertical's
    learned_rules. One row is written on EVERY keep-or-rollback decision so a
    rule set can never change (or be held) without an auditable, plain-language
    record. agreement_before/after are always the HOLDOUT numbers.
    """
    __tablename__ = "learning_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vertical = Column(String, nullable=False, index=True)
    brain = Column(String, nullable=True)  # optional brain/feature scope
    summary = Column(Text, nullable=False)  # plain-language: what changed
    agreement_before = Column(Float, nullable=True)  # holdout agreement of prior rules
    agreement_after = Column(Float, nullable=True)   # holdout agreement of candidate rules
    detail_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CreativeBrainRule(Base):
    """
    The GOVERNED selection rules for ONE creative brain in ONE vertical — the data the
    engine reads at decision time to bend a pick toward what has actually worked. Written
    ONLY through the holdout gate (creative_tuner). `promoted` says whether the engine may
    ASSERT these rules automatically (bar cleared) or only hold them as a SUGGESTION.
    Absent/empty rules = cold start = today's behavior unchanged.
    """
    __tablename__ = "creative_brain_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    brain = Column(String, nullable=False, index=True)          # voice_cast, script_write, ...
    vertical = Column(String, nullable=True, index=True)        # NULL = global
    rules_json = Column(JSON, nullable=False, default=dict)     # {preferred:{val:score}, avoided:[val]}
    promoted = Column(Boolean, default=False)                   # measured: cleared the promotion bar
    # ADMIN-APPROVAL GATE: `promoted` alone NEVER changes engine behavior. The engine reads a rule
    # ONLY when active=True (an admin approved a RuleProposal). Un-approved/proposed rules are inert
    # → cold start / un-approved = today's behavior exactly. Set True only by the approve endpoint.
    active = Column(Boolean, default=False)                     # admin-approved → engine may read it
    promotion_metrics = Column(JSON, nullable=True)
    last_analyzed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RuleProposal(Base):
    """
    An admin-approval gate item. When the holdout gate produces an IMPROVING candidate for a
    PROMOTED brain, the tuner writes ONE RuleProposal in status 'pending_admin' — it does NOT
    activate any CreativeBrainRule. An admin reviews the full evidence bundle (detail_json) and
    approves (→ activates the rule, status 'applied') or rejects (status 'rejected', old behavior
    kept). This is the throttle: holdout gate → promotion → admin approval → active rule → engine.
    Below-promotion brains never create a proposal (they are still 'gathering proof').
    """
    __tablename__ = "rule_proposals"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    brain = Column(String, nullable=False, index=True)          # voice_cast, script_write, ...
    vertical = Column(String, nullable=True, index=True)        # NULL = global
    status = Column(String, default="pending_admin", index=True)  # pending_admin | applied | rejected
    agreement_before = Column(Float, nullable=True)             # holdout agreement of ACTIVE rules
    agreement_after = Column(Float, nullable=True)              # holdout agreement of the candidate
    detail_json = Column(JSON, nullable=True)                  # full evidence bundle (why/what/when/how)
    reviewed_by = Column(String, nullable=True)                # admin identifier (approver/rejecter)
    reviewed_at = Column(DateTime, nullable=True)
    review_reason = Column(Text, nullable=True)                # rejection reason
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
