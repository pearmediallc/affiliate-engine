"""
Prompt Harness Engine — Zero-waste generation pipeline.

Every generation request passes through five sequential gates.
If ANY gate rejects the prompt, NO downstream API call is made.
Money is only spent when the system is confident the prompt will produce a
production-ready result.

Pipeline:
  [1] FrustrationDetector   — detects retry storms, angry rewrites, stuck users
  [2] VaguenessGate         — blocks prompts too thin to produce anything useful
  [3] MemoryHydrator        — injects user's learned style profile
  [4] VerticalContextLoader — injects vertical-level learned rules (existing LearningService)
  [5] OneShotOptimizer      — Gemini synthesizes everything into a final production prompt

Each gate either:
  - PASSES → enriches the context and hands off to the next gate
  - BLOCKS → returns structured feedback (questions / suggestions) without hitting API

After generation, OutcomeRecorder updates the UserPromptProfile so the system
gets smarter on every use.
"""
import uuid
import logging
import json
import re
import time as _time
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..config import settings
from ..models.harness import GenerationEvent, UserPromptProfile
from ..models.learning import LearningRecord, VerticalKnowledge

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# If user retried within this many seconds → frustration signal
_RETRY_WINDOW_SEC = 45
# If prompt has fewer than this many words → vagueness gate triggers
_MIN_WORDS_HARD = 4
_MIN_WORDS_SOFT = 8
# Gemini model used for all harness inference (cheap + fast)
_HARNESS_MODEL = "gemini-2.5-flash"

# Frustration keywords in raw prompt text
_FRUSTRATION_SIGNALS = [
    "fix", "again", "wrong", "bad", "not right", "redo", "retry",
    "still", "different", "change", "don't want", "terrible", "awful",
    "useless", "horrible", "wtf", "wtaf", "ugh", "please work",
]

# ── Gate return types ─────────────────────────────────────────────────────────

class GateResult:
    __slots__ = ("passed", "reason", "feedback", "suggestions", "enriched_context")

    def __init__(
        self,
        passed: bool,
        reason: str = "",
        feedback: str = "",
        suggestions: list = None,
        enriched_context: dict = None,
    ):
        self.passed = passed
        self.reason = reason
        self.feedback = feedback
        self.suggestions = suggestions or []
        self.enriched_context = enriched_context or {}


# ── Gemini helper ─────────────────────────────────────────────────────────────

def _gemini(prompt: str, expect_json: bool = True) -> str:
    """Call Gemini Flash. Returns raw text. Raises on failure."""
    from google import genai
    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=_HARNESS_MODEL,
        contents=prompt,
    )
    text = (response.text or "").strip()
    if expect_json and text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return text


# ── Gate 1: Frustration Detector ─────────────────────────────────────────────

class FrustrationDetector:
    """
    Detects when a user is retrying rapidly or expressing frustration.
    If detected → return clarifying questions instead of burning API budget.
    """

    @staticmethod
    def check(
        db: Session,
        user_id: Optional[str],
        vertical: str,
        feature: str,
        raw_prompt: str,
    ) -> GateResult:
        retry_count = 0
        is_retry = False
        prompt_lower = raw_prompt.lower()

        # Check recent events for this user/feature
        if user_id:
            cutoff = datetime.utcnow() - timedelta(seconds=_RETRY_WINDOW_SEC)
            recent = (
                db.query(GenerationEvent)
                .filter(
                    GenerationEvent.user_id == user_id,
                    GenerationEvent.feature == feature,
                    GenerationEvent.vertical == vertical,
                    GenerationEvent.created_at >= cutoff,
                )
                .order_by(GenerationEvent.created_at.desc())
                .limit(5)
                .all()
            )
            retry_count = len(recent)
            is_retry = retry_count > 0

        # Text-based frustration signals
        text_frustrated = any(sig in prompt_lower for sig in _FRUSTRATION_SIGNALS)

        # Hard block: rapid retries + frustration text
        if retry_count >= 3 and text_frustrated:
            return GateResult(
                passed=False,
                reason="frustration_storm",
                feedback=(
                    "It looks like you've retried several times quickly and the result "
                    "isn't matching what you need. Let me help you nail it before we spend "
                    "more API budget."
                ),
                suggestions=[
                    "What specifically is wrong with the last result? (wrong style, wrong person, wrong feel?)",
                    "What's the core emotion you want the viewer to feel?",
                    "Should the video feel more like a personal story or a product demo?",
                    "What's one example of a video you love that's similar to what you want?",
                ],
            )

        # Soft block: 2 retries — warn + suggest
        if retry_count >= 2 and is_retry:
            return GateResult(
                passed=True,  # still passes but enriches context with frustration flag
                reason="soft_frustration",
                enriched_context={
                    "frustration_level": "medium",
                    "retry_count": retry_count,
                    "is_retry": True,
                    "harness_note": (
                        "User has retried twice recently. Be more specific than last time. "
                        "Prioritize clarity and distinctiveness."
                    ),
                },
            )

        return GateResult(
            passed=True,
            reason="clean",
            enriched_context={"retry_count": retry_count, "is_retry": is_retry},
        )


# ── Gate 2: Vagueness Gate ────────────────────────────────────────────────────

class VaguenessGate:
    """
    Validates that a prompt has enough specificity to produce something useful.
    Hard blocks on critically thin prompts. Soft-flags borderline ones.

    Uses a Gemini classification call (cheap: ~$0.0001) to avoid wasting
    expensive generation API calls on prompts that will produce unusable output.
    """

    @staticmethod
    def check(raw_prompt: str, feature: str, vertical: str) -> GateResult:
        word_count = len(raw_prompt.split())

        # Hard block: critically short
        if word_count < _MIN_WORDS_HARD:
            return GateResult(
                passed=False,
                reason="too_vague_hard",
                feedback=f"Your prompt is too short ({word_count} words) to generate anything useful.",
                suggestions=[
                    f"Describe the scene or person: who's in it, where, doing what?",
                    f"What emotion or action should the {feature} capture?",
                    f"What's the core message for your {vertical} audience?",
                    "Add product name, setting, and target customer type.",
                ],
            )

        # Soft check via Gemini — only for borderline prompts (avoid calling Gemini for long clear prompts)
        if word_count >= _MIN_WORDS_SOFT * 3:
            return GateResult(passed=True, reason="sufficient_length")

        if not settings.gemini_api_key:
            return GateResult(passed=True, reason="no_gemini_key_skip_gate")

        classify_prompt = f"""You are a prompt quality classifier for AI {feature} generation in the {vertical} industry.

Evaluate this prompt: "{raw_prompt}"

Answer ONLY with valid JSON (no markdown):
{{
  "quality": "good" | "borderline" | "too_vague",
  "issues": ["issue1", "issue2"],
  "missing_elements": ["what is missing"],
  "questions": ["clarifying question 1", "clarifying question 2"],
  "confidence": 0.0-1.0
}}

"too_vague" = no scene, subject, emotion, or product details. "borderline" = has some details but needs more. "good" = specific enough to generate."""

        try:
            raw = _gemini(classify_prompt, expect_json=True)
            data = json.loads(raw)
        except Exception as e:
            logger.debug(f"VaguenessGate Gemini parse failed: {e} — passing prompt through")
            return GateResult(passed=True, reason="gate_error_passthrough")

        quality = data.get("quality", "good")

        if quality == "too_vague":
            return GateResult(
                passed=False,
                reason="too_vague_gemini",
                feedback=(
                    f"This prompt doesn't have enough detail to produce a production-ready {feature}. "
                    f"Issues: {', '.join(data.get('issues', []))}."
                ),
                suggestions=data.get("questions", []) or [
                    f"What specific product or service is this {feature} for?",
                    "Describe the main character/subject and their emotion.",
                    "What action happens in the first 3 seconds?",
                ],
            )

        context = {}
        if quality == "borderline":
            context["quality_warning"] = "borderline prompt — optimizer will fill in details"
            context["missing_elements"] = data.get("missing_elements", [])

        return GateResult(passed=True, reason=quality, enriched_context=context)


# ── Gate 3: Memory Hydrator ───────────────────────────────────────────────────

class MemoryHydrator:
    """
    Loads the user's learned prompt profile and injects it as context.
    No API call — pure DB read.
    """

    @staticmethod
    def hydrate(
        db: Session,
        user_id: Optional[str],
        vertical: str,
        feature: str,
    ) -> GateResult:
        if not user_id:
            return GateResult(passed=True, reason="anonymous_user", enriched_context={})

        profile = (
            db.query(UserPromptProfile)
            .filter(
                UserPromptProfile.user_id == user_id,
                UserPromptProfile.vertical == vertical,
            )
            .first()
        )

        if not profile:
            return GateResult(passed=True, reason="no_profile_yet", enriched_context={})

        ctx: dict = {}

        if profile.preferred_tone:
            ctx["preferred_tone"] = profile.preferred_tone
        if profile.preferred_shot_types:
            ctx["preferred_shot_types"] = profile.preferred_shot_types
        if profile.preferred_color_grade:
            ctx["preferred_color_grade"] = profile.preferred_color_grade
        if profile.preferred_caption_style:
            ctx["preferred_caption_style"] = profile.preferred_caption_style
        if profile.preferred_music_mood:
            ctx["preferred_music_mood"] = profile.preferred_music_mood
        if profile.preferred_models and feature in profile.preferred_models:
            ctx["preferred_model"] = profile.preferred_models[feature]
        if profile.successful_prompt_patterns:
            ctx["successful_patterns"] = profile.successful_prompt_patterns[:5]
        if profile.learned_rules:
            ctx["learned_rules"] = profile.learned_rules[:5]
        if profile.failed_prompt_patterns:
            ctx["avoid_patterns"] = profile.failed_prompt_patterns[:3]
        if profile.typical_prompt_complexity:
            ctx["user_complexity_level"] = profile.typical_prompt_complexity
        if profile.satisfaction_rate is not None:
            ctx["user_satisfaction_rate"] = round(profile.satisfaction_rate, 2)

        return GateResult(passed=True, reason="hydrated", enriched_context=ctx)


# ── Gate 4: Vertical Context Loader ──────────────────────────────────────────

class VerticalContextLoader:
    """
    Loads vertical-level learned rules from the existing LearningService knowledge base.
    No API call — pure DB read.
    """

    @staticmethod
    def load(db: Session, vertical: str, feature: str) -> GateResult:
        knowledge = (
            db.query(VerticalKnowledge)
            .filter(VerticalKnowledge.vertical == vertical)
            .first()
        )

        if not knowledge or not knowledge.learned_rules:
            return GateResult(passed=True, reason="no_vertical_knowledge", enriched_context={})

        rules = knowledge.learned_rules
        prompt_rules = [
            r["rule"]
            for r in rules.get("prompt_rules", [])
            if r.get("confidence", 0) >= 0.65
        ]
        style_prefs = rules.get("style_preferences", {})

        ctx: dict = {}
        if prompt_rules:
            ctx["vertical_rules"] = prompt_rules[:6]
        if style_prefs.get("best"):
            ctx["vertical_best_style"] = style_prefs["best"]
        if style_prefs.get("worst"):
            ctx["vertical_avoid_style"] = style_prefs["worst"]
        if knowledge.avg_satisfaction is not None:
            ctx["vertical_satisfaction"] = round(knowledge.avg_satisfaction, 2)

        return GateResult(passed=True, reason="loaded", enriched_context=ctx)


# ── Gate 5: One-Shot Optimizer ────────────────────────────────────────────────

class OneShotOptimizer:
    """
    Synthesizes raw prompt + all enriched context into a final production-ready prompt.
    This is the only gate that makes a Gemini call (~$0.0001).
    Only runs if all previous gates passed.
    Returns a structured dict with final_prompt + reasoning + confidence.
    """

    @staticmethod
    def optimize(
        raw_prompt: str,
        feature: str,
        vertical: str,
        enriched_context: dict,
    ) -> dict:
        if not settings.gemini_api_key:
            return {
                "final_prompt": raw_prompt,
                "confidence": 0.5,
                "optimized": False,
                "reasoning": "Gemini not configured",
                "suggested_model": None,
                "suggested_params": {},
            }

        # Build context block from enriched data
        ctx_lines = []

        if enriched_context.get("preferred_tone"):
            ctx_lines.append(f"User prefers {enriched_context['preferred_tone']} tone.")
        if enriched_context.get("preferred_shot_types"):
            ctx_lines.append(f"Preferred shot types: {', '.join(enriched_context['preferred_shot_types'])}.")
        if enriched_context.get("preferred_color_grade"):
            ctx_lines.append(f"Preferred color grade: {enriched_context['preferred_color_grade']}.")
        if enriched_context.get("preferred_model"):
            ctx_lines.append(f"Preferred model for {feature}: {enriched_context['preferred_model']}.")
        if enriched_context.get("successful_patterns"):
            ctx_lines.append(f"Phrases that worked before: {'; '.join(enriched_context['successful_patterns'])}.")
        if enriched_context.get("avoid_patterns"):
            ctx_lines.append(f"Patterns that failed before: {'; '.join(enriched_context['avoid_patterns'])}.")
        if enriched_context.get("learned_rules"):
            ctx_lines.append("Learned rules: " + " | ".join(enriched_context["learned_rules"]) + ".")
        if enriched_context.get("vertical_rules"):
            ctx_lines.append("Vertical rules: " + " | ".join(enriched_context["vertical_rules"]) + ".")
        if enriched_context.get("missing_elements"):
            ctx_lines.append(f"Known missing elements: {', '.join(enriched_context['missing_elements'])}.")
        if enriched_context.get("harness_note"):
            ctx_lines.append(f"[System note]: {enriched_context['harness_note']}")
        if enriched_context.get("frustration_level"):
            ctx_lines.append(
                f"[Behavioral note]: User has retried {enriched_context.get('retry_count',0)} times — "
                "make the output MORE distinctive and specific than typical."
            )

        context_block = "\n".join(ctx_lines) if ctx_lines else "No prior user context available."

        # Feature-specific output instructions
        _FEATURE_INSTRUCTIONS = {
            "image": (
                "The final prompt must describe: subject, setting, lighting, camera angle, mood, "
                "color palette, and any text/CTA elements. Target professional ad creative quality."
            ),
            "video": (
                "The final prompt must describe: opening scene (first 2 seconds), main action, "
                "shot type (spokesperson/b-roll/UGC), pacing, emotion, and closing CTA. "
                "Use cinematographic language: lens, movement, lighting."
            ),
            "speech": (
                "The final prompt is the exact script text. Ensure it has a hook in the first "
                "5 words, flows naturally when spoken aloud, and ends with a clear CTA."
            ),
            "caption": (
                "The final prompt is the exact caption text. Ensure it's punchy, platform-native, "
                "uses pattern interrupts, and matches the user's brand voice."
            ),
        }
        feature_instruction = _FEATURE_INSTRUCTIONS.get(feature, "Make the prompt highly specific and production-ready.")

        optimizer_prompt = f"""You are an elite AI prompt engineer specializing in {feature} generation for the {vertical} industry.

RAW USER PROMPT:
"{raw_prompt}"

USER & VERTICAL CONTEXT:
{context_block}

YOUR TASK:
Transform the raw prompt into a single, production-ready {feature} prompt that will generate a publishable result on the FIRST attempt.

{feature_instruction}

RULES:
- Keep the user's core intent intact — do not change the subject or product
- Fill in missing cinematic/creative details using the context above
- If the user has frustration signals, be MORE specific and distinctive than usual
- Do not add elements the user never mentioned (no hallucinated products)
- Output ONLY valid JSON, no markdown fences, no explanation outside JSON

OUTPUT FORMAT:
{{
  "final_prompt": "<the complete, production-ready prompt>",
  "confidence": <0.0-1.0 — how likely this will produce a publish-ready result>,
  "reasoning": "<one sentence: what you changed and why>",
  "suggested_model": "<model_id or null — e.g. kling-v3, higgsfield-v1, veo-3.1>",
  "suggested_params": {{
    "color_grade": "<cinematic|warm|cool|vivid|none>",
    "aspect": "<9:16|16:9|1:1>",
    "music_mood": "<motivational|calm|energetic|none>",
    "style": "<optional>"
  }},
  "injected_elements": ["list", "of", "what", "was", "added"]
}}"""

        try:
            raw = _gemini(optimizer_prompt, expect_json=True)
            data = json.loads(raw)
        except Exception as e:
            logger.warning(f"OneShotOptimizer Gemini parse failed: {e}")
            return {
                "final_prompt": raw_prompt,
                "confidence": 0.5,
                "optimized": False,
                "reasoning": f"Optimizer error: {e}",
                "suggested_model": None,
                "suggested_params": {},
            }

        data["optimized"] = True
        return data


# ── Main HarnessEngine ────────────────────────────────────────────────────────

class HarnessEngine:
    """
    Public interface. Call before_generate() for every generation request.
    Call after_generate() once the user takes an action (download/reject/retry).
    """

    @staticmethod
    def before_generate(
        db: Session,
        user_id: Optional[str],
        vertical: str,
        feature: str,
        raw_prompt: str,
        params: dict = None,
    ) -> dict:
        """
        Run the full 5-gate pipeline.

        Returns:
          {
            "approved": bool,          — False = do NOT call generation API
            "event_id": str,           — store this, pass to after_generate
            "final_prompt": str,       — use this prompt (enriched), not raw
            "confidence": float,       — 0.0-1.0 readiness score
            "suggested_model": str,    — model to use
            "suggested_params": dict,  — color_grade, aspect, etc.
            "gate_stopped": str,       — which gate blocked (if approved=False)
            "feedback": str,           — message to show user (if blocked)
            "suggestions": list,       — clarifying questions (if blocked)
            "injected_elements": list, — what the optimizer added
          }
        """
        params = params or {}
        merged_context: dict = {}

        # ── Gate 1: Frustration Detector ──────────────────────────────────
        g1 = FrustrationDetector.check(db, user_id, vertical, feature, raw_prompt)
        if not g1.passed:
            _record_blocked(db, user_id, vertical, feature, raw_prompt, "frustration", params)
            return _blocked_response("frustration", g1.feedback, g1.suggestions)
        merged_context.update(g1.enriched_context)

        # ── Gate 2: Vagueness Gate ─────────────────────────────────────────
        g2 = VaguenessGate.check(raw_prompt, feature, vertical)
        if not g2.passed:
            _record_blocked(db, user_id, vertical, feature, raw_prompt, "vagueness", params)
            return _blocked_response("vagueness", g2.feedback, g2.suggestions)
        merged_context.update(g2.enriched_context)

        # ── Gate 3: Memory Hydrator ────────────────────────────────────────
        g3 = MemoryHydrator.hydrate(db, user_id, vertical, feature)
        merged_context.update(g3.enriched_context)

        # ── Gate 4: Vertical Context ───────────────────────────────────────
        g4 = VerticalContextLoader.load(db, vertical, feature)
        merged_context.update(g4.enriched_context)

        # ── Gate 5: One-Shot Optimizer ─────────────────────────────────────
        opt = OneShotOptimizer.optimize(raw_prompt, feature, vertical, merged_context)

        final_prompt = opt.get("final_prompt") or raw_prompt
        confidence = float(opt.get("confidence", 0.5))
        suggested_model = opt.get("suggested_model") or params.get("model_id")
        suggested_params = {**params, **(opt.get("suggested_params") or {})}

        # Record the approved event
        event_id = _record_event(
            db, user_id, vertical, feature, raw_prompt, final_prompt,
            merged_context.get("retry_count", 0), merged_context.get("is_retry", False),
            suggested_model, params,
        )

        return {
            "approved": True,
            "event_id": event_id,
            "final_prompt": final_prompt,
            "raw_prompt": raw_prompt,
            "confidence": confidence,
            "suggested_model": suggested_model,
            "suggested_params": suggested_params,
            "gate_stopped": None,
            "feedback": None,
            "suggestions": [],
            "injected_elements": opt.get("injected_elements", []),
            "reasoning": opt.get("reasoning", ""),
        }

    @staticmethod
    def after_generate(
        db: Session,
        event_id: str,
        outcome: str,  # "downloaded" | "rejected" | "regenerated" | "approved"
        time_to_action_sec: float = None,
        cost_usd: float = None,
        generation_time_sec: float = None,
        error: str = None,
    ) -> None:
        """Record what happened after generation. Updates the event + profile."""
        event = db.query(GenerationEvent).filter(GenerationEvent.id == event_id).first()
        if not event:
            logger.warning(f"HarnessEngine.after_generate: event {event_id} not found")
            return

        event.downloaded = outcome == "downloaded"
        event.approved = outcome in ("downloaded", "approved")
        event.rejected = outcome == "rejected"
        event.regenerated = outcome == "regenerated"
        event.time_to_action_sec = time_to_action_sec
        event.outcome_recorded_at = datetime.utcnow()
        if cost_usd is not None:
            event.cost_usd = cost_usd
        if generation_time_sec is not None:
            event.generation_time_sec = generation_time_sec
        if error:
            event.error = error

        db.commit()

        # Async-style profile update (only if user is known)
        if event.user_id:
            try:
                _update_profile(db, event.user_id, event.vertical)
            except Exception as e:
                logger.warning(f"Profile update failed (non-fatal): {e}")

    @staticmethod
    def get_profile(db: Session, user_id: str, vertical: str) -> dict:
        profile = (
            db.query(UserPromptProfile)
            .filter(
                UserPromptProfile.user_id == user_id,
                UserPromptProfile.vertical == vertical,
            )
            .first()
        )
        if not profile:
            return {"user_id": user_id, "vertical": vertical, "status": "no_data_yet"}

        return {
            "user_id": user_id,
            "vertical": vertical,
            "preferred_tone": profile.preferred_tone,
            "preferred_shot_types": profile.preferred_shot_types,
            "preferred_color_grade": profile.preferred_color_grade,
            "preferred_music_mood": profile.preferred_music_mood,
            "preferred_models": profile.preferred_models,
            "learned_rules": profile.learned_rules,
            "total_generations": profile.total_generations,
            "satisfaction_rate": profile.satisfaction_rate,
            "total_spend_usd": profile.total_spend_usd,
            "last_synthesized_at": str(profile.last_synthesized_at) if profile.last_synthesized_at else None,
        }

    @staticmethod
    def synthesize_profile(db: Session, user_id: str, vertical: str) -> dict:
        """
        Force a profile re-synthesis from all GenerationEvents for this user/vertical.
        Called automatically by after_generate every 10 events, or manually by admin.
        """
        return _synthesize_profile_gemini(db, user_id, vertical)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _blocked_response(gate: str, feedback: str, suggestions: list) -> dict:
    return {
        "approved": False,
        "event_id": None,
        "final_prompt": None,
        "raw_prompt": None,
        "confidence": 0.0,
        "suggested_model": None,
        "suggested_params": {},
        "gate_stopped": gate,
        "feedback": feedback,
        "suggestions": suggestions,
        "injected_elements": [],
        "reasoning": f"Blocked at gate: {gate}",
    }


def _record_blocked(
    db: Session,
    user_id: Optional[str],
    vertical: str,
    feature: str,
    raw_prompt: str,
    gate: str,
    params: dict,
) -> None:
    event = GenerationEvent(
        id=str(uuid.uuid4()),
        user_id=user_id,
        vertical=vertical,
        feature=feature,
        raw_prompt=raw_prompt,
        enriched_prompt=None,
        model_id=None,
        provider=None,
        params=params,
        rejected=True,
        error=f"blocked_at_{gate}",
        prompt_sentiment="frustrated" if gate == "frustration" else "unclear",
    )
    db.add(event)
    try:
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to record blocked event: {e}")
        db.rollback()


def _record_event(
    db: Session,
    user_id: Optional[str],
    vertical: str,
    feature: str,
    raw_prompt: str,
    enriched_prompt: str,
    retry_count: int,
    is_retry: bool,
    model_id: Optional[str],
    params: dict,
) -> str:
    event_id = str(uuid.uuid4())
    event = GenerationEvent(
        id=event_id,
        user_id=user_id,
        vertical=vertical,
        feature=feature,
        raw_prompt=raw_prompt,
        enriched_prompt=enriched_prompt,
        model_id=model_id,
        provider=None,
        params=params,
        is_retry=is_retry,
        retry_count=retry_count,
    )
    db.add(event)
    try:
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to record generation event: {e}")
        db.rollback()
    return event_id


def _update_profile(db: Session, user_id: str, vertical: str) -> None:
    """Re-synthesize profile every 10 completed events."""
    count = (
        db.query(func.count(GenerationEvent.id))
        .filter(
            GenerationEvent.user_id == user_id,
            GenerationEvent.vertical == vertical,
            GenerationEvent.approved.isnot(None),
        )
        .scalar()
    )
    if count > 0 and count % 10 == 0:
        _synthesize_profile_gemini(db, user_id, vertical)


def _synthesize_profile_gemini(db: Session, user_id: str, vertical: str) -> dict:
    """
    Use Gemini to analyze a user's generation history and synthesize a profile.
    Writes/updates the UserPromptProfile row.
    """
    events = (
        db.query(GenerationEvent)
        .filter(
            GenerationEvent.user_id == user_id,
            GenerationEvent.vertical == vertical,
        )
        .order_by(GenerationEvent.created_at.desc())
        .limit(50)
        .all()
    )

    if len(events) < 3:
        return {"status": "insufficient_data", "count": len(events)}

    successful = [e for e in events if e.downloaded or e.approved]
    failed = [e for e in events if e.rejected]
    retried = [e for e in events if e.regenerated or e.is_retry]

    analysis_prompt = f"""Analyze this user's AI generation history for the "{vertical}" vertical and build their prompt profile.

HISTORY ({len(events)} events):

SUCCESSFUL GENERATIONS (user downloaded/approved):
{chr(10).join([f"- Prompt: {e.enriched_prompt or e.raw_prompt}" for e in successful[:15]])}

FAILED/REJECTED GENERATIONS:
{chr(10).join([f"- Prompt: {e.raw_prompt} | Error: {e.error}" for e in failed[:10]])}

RETRY PATTERNS (user regenerated without downloading):
{chr(10).join([f"- Retried {e.retry_count}x on: {e.raw_prompt[:100]}" for e in retried[:10]])}

BEHAVIORAL STATS:
- Total events: {len(events)}
- Success rate: {round(len(successful)/len(events)*100)}%
- Avg retry count: {round(sum(e.retry_count for e in events)/len(events), 1)}
- Preferred models: {list(set(e.model_id for e in successful if e.model_id))[:5]}

Synthesize this into a user profile. Output ONLY valid JSON:
{{
  "preferred_tone": "urgent|warm|professional|playful|dramatic",
  "preferred_shot_types": ["list", "of", "shot", "types"],
  "preferred_color_grade": "cinematic|warm|cool|vivid|none",
  "preferred_caption_style": "tiktok|bold_center|subtitle|karaoke|none",
  "preferred_music_mood": "motivational|calm|energetic|dramatic|none",
  "preferred_models": {{"image": "model_id", "video": "model_id"}},
  "successful_prompt_patterns": ["phrase pattern 1", "phrase pattern 2"],
  "failed_prompt_patterns": ["what didn't work 1", "what didn't work 2"],
  "learned_rules": ["rule 1", "rule 2", "rule 3"],
  "typical_prompt_complexity": "simple|moderate|complex",
  "frustration_triggers": ["trigger 1", "trigger 2"]
}}"""

    try:
        raw = _gemini(analysis_prompt, expect_json=True)
        profile_data = json.loads(raw)
    except Exception as e:
        logger.error(f"Profile synthesis Gemini call failed: {e}")
        return {"status": "synthesis_failed", "error": str(e)}

    # Update or create profile
    profile = (
        db.query(UserPromptProfile)
        .filter(
            UserPromptProfile.user_id == user_id,
            UserPromptProfile.vertical == vertical,
        )
        .first()
    )

    if not profile:
        profile = UserPromptProfile(
            id=str(uuid.uuid4()),
            user_id=user_id,
            vertical=vertical,
        )
        db.add(profile)

    profile.preferred_tone = profile_data.get("preferred_tone")
    profile.preferred_shot_types = profile_data.get("preferred_shot_types")
    profile.preferred_color_grade = profile_data.get("preferred_color_grade")
    profile.preferred_caption_style = profile_data.get("preferred_caption_style")
    profile.preferred_music_mood = profile_data.get("preferred_music_mood")
    profile.preferred_models = profile_data.get("preferred_models")
    profile.successful_prompt_patterns = profile_data.get("successful_prompt_patterns")
    profile.failed_prompt_patterns = profile_data.get("failed_prompt_patterns")
    profile.learned_rules = profile_data.get("learned_rules")
    profile.typical_prompt_complexity = profile_data.get("typical_prompt_complexity")
    profile.frustration_triggers = profile_data.get("frustration_triggers")
    profile.total_generations = len(events)
    profile.successful_generations = len(successful)
    profile.satisfaction_rate = len(successful) / len(events) if events else None
    profile.total_spend_usd = sum(e.cost_usd or 0.0 for e in events)
    profile.last_synthesized_at = datetime.utcnow()

    try:
        db.commit()
    except Exception as e:
        logger.error(f"Profile commit failed: {e}")
        db.rollback()
        return {"status": "commit_failed", "error": str(e)}

    return {
        "status": "synthesized",
        "user_id": user_id,
        "vertical": vertical,
        "total_events": len(events),
        "satisfaction_rate": profile.satisfaction_rate,
        "rules_count": len(profile_data.get("learned_rules", [])),
    }
