"""
Harness Engine API — prompt quality gates + outcome tracking + profile management.

Frontend calls /harness/optimize BEFORE every generation.
If approved=True → use final_prompt + suggested_model + suggested_params for the API call.
If approved=False → show feedback + suggestions to user. Do NOT generate.

After generation, frontend calls /harness/outcome to record what happened.
This is how the system learns and gets smarter over every iteration.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from ..schemas import APIResponse
from ..middleware.auth import get_current_user
from ..database import SessionLocal
from ..services.harness_engine import HarnessEngine

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    raw_prompt: str = Field(..., min_length=1)
    feature: str = Field(..., description="image | video | speech | caption")
    vertical: str = Field(default="home_insurance")
    params: dict = Field(default_factory=dict, description="Any extra generation params")


class OutcomeRequest(BaseModel):
    event_id: str
    outcome: str = Field(..., description="downloaded | rejected | regenerated | approved")
    time_to_action_sec: Optional[float] = None
    cost_usd: Optional[float] = None
    generation_time_sec: Optional[float] = None
    error: Optional[str] = None


class SynthesizeRequest(BaseModel):
    vertical: str = Field(default="home_insurance")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/optimize")
async def optimize_prompt(
    body: OptimizeRequest,
    user=Depends(get_current_user),
):
    """
    Run the 5-gate harness pipeline on a raw prompt.

    Returns:
      approved=True  → generation is safe. Use final_prompt + suggested params.
      approved=False → blocked. Show feedback + suggestions to user. Do not generate.

    This is the ONLY endpoint that needs to be called before every generation.
    """
    db = SessionLocal()
    try:
        result = HarnessEngine.before_generate(
            db=db,
            user_id=str(user.id),
            vertical=body.vertical,
            feature=body.feature,
            raw_prompt=body.raw_prompt,
            params=body.params,
        )
        return APIResponse(
            success=True,
            message="approved" if result["approved"] else f"blocked:{result['gate_stopped']}",
            data=result,
        )
    finally:
        db.close()


@router.post("/outcome")
async def record_outcome(
    body: OutcomeRequest,
    user=Depends(get_current_user),
):
    """
    Record what happened after a generation (download, reject, retry).
    Must be called after every generation — this is how the harness learns.
    """
    db = SessionLocal()
    try:
        HarnessEngine.after_generate(
            db=db,
            event_id=body.event_id,
            outcome=body.outcome,
            time_to_action_sec=body.time_to_action_sec,
            cost_usd=body.cost_usd,
            generation_time_sec=body.generation_time_sec,
            error=body.error,
        )
        return APIResponse(success=True, message="Outcome recorded", data={})
    finally:
        db.close()


@router.get("/profile/{vertical}")
async def get_profile(
    vertical: str,
    user=Depends(get_current_user),
):
    """Return the user's learned prompt profile for a vertical."""
    db = SessionLocal()
    try:
        profile = HarnessEngine.get_profile(db, str(user.id), vertical)
        return APIResponse(success=True, message="Profile loaded", data=profile)
    finally:
        db.close()


@router.post("/synthesize")
async def synthesize_profile(
    body: SynthesizeRequest,
    user=Depends(get_current_user),
):
    """
    Force a profile re-synthesis from scratch.
    Normally called automatically every 10 generations — use this to trigger manually.
    """
    db = SessionLocal()
    try:
        result = HarnessEngine.synthesize_profile(db, str(user.id), body.vertical)
        return APIResponse(success=True, message="Profile synthesized", data=result)
    finally:
        db.close()


@router.get("/stats/{vertical}")
async def get_harness_stats(
    vertical: str,
    user=Depends(get_current_user),
):
    """Return generation statistics for this user × vertical combination."""
    from ..models.harness import GenerationEvent
    from sqlalchemy import func

    db = SessionLocal()
    try:
        q = db.query(GenerationEvent).filter(
            GenerationEvent.user_id == str(user.id),
            GenerationEvent.vertical == vertical,
        )
        total = q.count()
        approved = q.filter(GenerationEvent.approved == True).count()  # noqa: E712
        rejected = q.filter(GenerationEvent.rejected == True).count()  # noqa: E712
        retried  = q.filter(GenerationEvent.regenerated == True).count()  # noqa: E712
        blocked  = q.filter(GenerationEvent.error.like("blocked_at%")).count()
        spend    = db.query(func.sum(GenerationEvent.cost_usd)).filter(
            GenerationEvent.user_id == str(user.id),
            GenerationEvent.vertical == vertical,
        ).scalar() or 0.0

        return APIResponse(
            success=True,
            message="Harness stats",
            data={
                "total_events": total,
                "approved": approved,
                "rejected": rejected,
                "retried": retried,
                "blocked_by_gates": blocked,
                "api_calls_saved": blocked,
                "total_spend_usd": round(float(spend), 4),
                "satisfaction_rate": round(approved / total, 2) if total else None,
            },
        )
    finally:
        db.close()


@router.get("/gates")
async def describe_gates(user=Depends(get_current_user)):
    """Describe all 5 gates and their current thresholds."""
    return APIResponse(
        success=True,
        message="Gate configuration",
        data={
            "gates": [
                {
                    "id": 1,
                    "name": "FrustrationDetector",
                    "description": "Detects retry storms and angry rewrites. Hard blocks if user retried 3+ times within 45s with frustration language.",
                    "blocks_api": True,
                    "cost": "free — DB query only",
                },
                {
                    "id": 2,
                    "name": "VaguenessGate",
                    "description": "Validates prompt has enough detail to generate something useful. Hard blocks < 4 words. Gemini-classifies borderline prompts.",
                    "blocks_api": True,
                    "cost": "~$0.0001 for borderline prompts, free for clear prompts",
                },
                {
                    "id": 3,
                    "name": "MemoryHydrator",
                    "description": "Loads user's learned style profile (tone, models, patterns). Always passes — only enriches context.",
                    "blocks_api": False,
                    "cost": "free — DB read only",
                },
                {
                    "id": 4,
                    "name": "VerticalContextLoader",
                    "description": "Injects vertical-level learned rules from past generation feedback. Always passes — only enriches context.",
                    "blocks_api": False,
                    "cost": "free — DB read only",
                },
                {
                    "id": 5,
                    "name": "OneShotOptimizer",
                    "description": "Gemini synthesizes everything into a production-ready prompt. Only runs if all gates passed.",
                    "blocks_api": False,
                    "cost": "~$0.0001 — Gemini Flash",
                },
            ],
            "total_cost_per_approved_prompt": "~$0.0001–$0.0002",
            "total_cost_per_blocked_prompt": "$0.00",
        },
    )
