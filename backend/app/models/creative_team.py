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
    # Curated JSON of the ASSEMBLY assets (ugc_broll/captions flags, b-roll URLs, caption style,
    # vertical, variation index, script) so the restart resumer can re-run the FULL delivery — b-roll
    # composite + caption burn + QA gate — not just a raw talking-head. Nullable: old rows resume raw.
    assets_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RefVideoJob(Base):
    """Durable checkpoint for the REFERENCE-VIDEO (image-anchored i2v) path so a long render SURVIVES
    an AE restart. The failed job ec2d0aaa died because a mid-render restart zeroed the job ('engine
    restarted mid-generation, no creative to auto-resume') → produced NOTHING. We persist everything
    needed to reproduce the SAME locked render (durable reference image + verbatim prompt/script +
    gender + single_shot + seconds), and a startup resumer re-runs it (the reference image is durable
    and the render is deterministic w.r.t. the frozen inputs), then delivers via the stored callback —
    RESUMING the job instead of orphaning it. Fails LOUD (failed callback) if the resume itself errors."""
    __tablename__ = "refvideo_jobs"

    id = Column(String, primary_key=True)                    # = the regen request_id
    provider = Column(String, nullable=True)                 # veo | fal (the lane that ran)
    operation_name = Column(Text, nullable=True)             # latest Veo op (advisory; segments are on ephemeral disk)
    callback_url = Column(Text, nullable=True)
    out_name = Column(String, nullable=True)
    script = Column(Text, nullable=True)
    # Frozen render inputs (image_urls/prompt/gender/single_shot/seconds/aspect_ratio) so the resumer
    # can rebuild the RunRequest and reproduce the identical locked take. Never re-parsed or re-curated.
    assets_json = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="running", index=True)   # running | done | failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreationCost(Base):
    """Per-step provider spend for a single creation, so the UI can show exactly which AI
    provider cost what for each video/image (per request + in the Variation Studio)."""
    __tablename__ = "creation_costs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String, index=True)
    step = Column(String)            # script | voice | lipsync | captions | image | video
    provider = Column(String)
    model = Column(String, nullable=True)
    units = Column(Float, nullable=True)
    unit_type = Column(String, nullable=True)   # chars | sec | min | run | free
    cost_usd = Column(Float, default=0.0)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CreativeDecision(Base):
    """The learning STATE — one row per creative recording every CHOICE the engine made
    (character, voice, model, script, whether QC passed). ROI is stitched in later from the ad
    platform, keyed by creative_ref. The brain ranks future picks by the ROI these rows accrue —
    so it stops repeating what loses. Append-only; the brain reads AGGREGATES, never raw history,
    so it never bloats a prompt."""
    __tablename__ = "creative_decisions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String, index=True)
    creative_ref = Column(String, index=True, nullable=True)   # delivered filename → join to ROI
    vertical = Column(String, index=True, nullable=True)
    character_key = Column(String, index=True, nullable=True)  # source clip / asset id (not the name token)
    character_gender = Column(String, nullable=True)
    character_age = Column(String, nullable=True)
    voice_id = Column(String, index=True, nullable=True)
    voice_provider = Column(String, nullable=True)
    voice_cloned = Column(Boolean, default=False)
    lipsync_provider = Column(String, nullable=True)
    video_model = Column(String, nullable=True)
    script_ref = Column(String, nullable=True)
    captions = Column(Boolean, default=False)
    # Per-brain choices the pipeline actually made, so the loop can rank each brain on its own.
    # NULL when the value isn't recoverable at log time (NULLs are simply excluded from ranking).
    script_mode = Column(String, nullable=True)             # verbatim | rewrite | from-scratch
    caption_method = Column(String, nullable=True)          # veed | ffmpeg | (null = no captions)
    caption_removal_method = Column(String, nullable=True)  # vmake | ffmpeg-blur | none
    # Which brains a human 'regenerated'/'rejected' verdict actually blamed (JSON list, as TEXT).
    #   NULL  → no attribution (accepted / ROI-only / legacy) — penalizes NO specific brain
    #   "[]"  → verdict given but ambiguous — trains NO brain, creative-level stat only
    #   '["voice_cast"]' → ONLY the named brains take the loss; unnamed brains stay unlabeled
    blamed_brains = Column(Text, nullable=True)
    # Which diversification AXIS this creative was generated along (character|script|hook|format),
    # NULL for single-variation jobs. Lets editor feedback ("wanted different scripts, not faces")
    # later train an axis classifier — the loop knows WHAT kind of variety was asked for.
    variation_axis = Column(String, index=True, nullable=True)
    qc_passed = Column(Boolean, default=True)
    qc_reasons = Column(Text, nullable=True)
    cost_usd = Column(Float, default=0.0)
    roi = Column(Float, nullable=True)          # filled in later from the platform (best signal)
    roi_updated_at = Column(DateTime, nullable=True)
    # When no ROI is available, the human's decision IS the label: a media buyer accepting a
    # creative as-is is a win; sending it back is a loss. verdict ∈ accepted | regenerated.
    human_verdict = Column(String, nullable=True)
    human_reason = Column(Text, nullable=True)
    verdict_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
