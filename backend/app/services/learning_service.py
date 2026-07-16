"""Learning service - builds institutional knowledge from generation data + feedback"""
import logging
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..models.learning import LearningRecord, VerticalKnowledge, AISuggestion, LearningEvent
from ..config import settings

logger = logging.getLogger(__name__)

# ── Holdout-gated tuning loop (Karpathy loop verifier) ────────────────────────
# The verifier below is the thing the loop is judged by. Keep it simple and
# honest: mine candidate rules from TRAIN only, then score them on a held-out
# slice the miner never saw. A change is kept ONLY if it does strictly better
# on the holdout than the rules currently in production.

_PROMOTION_AGREEMENT_BAR = 0.85   # holdout agreement required to promote a brain
_PROMOTION_MIN_HOLDOUT = 50       # min labeled holdout records required to promote
_HOLDOUT_MOD = 5                  # id-hash % 5 == 0 → holdout (~20%), deterministic


def _norm(s) -> str:
    return (s or "").strip().lower()


def is_holdout(record_id: str) -> bool:
    """
    Deterministic, reproducible train/holdout split keyed on the record id.
    NO randomness — the same record always lands in the same bucket across runs.
    ~20% of records fall into the holdout (stable md5 hash % 5 == 0).
    """
    digest = hashlib.md5((record_id or "").encode("utf-8")).hexdigest()
    return int(digest, 16) % _HOLDOUT_MOD == 0


def _rule_texts(rules) -> list:
    if not rules or not isinstance(rules, dict):
        return []
    return [_norm(r.get("rule")) for r in rules.get("prompt_rules", []) if r.get("rule")]


def agreement(rules, records) -> float:
    """
    Fraction of labeled records whose human verdict the rule set correctly predicts.

    Guess-vs-truth mapping (documented assumption):
      * TRUTH  = LearningRecord.feedback_rating ("positive" | "negative") — the human label.
      * GUESS  = the mined prompt_rules. These rules encode the issues that cause
                 negative feedback (the fallback miner literally emits "Avoid: <issue>",
                 and Gemini rules reference the same issue tags). So the rule set
                 predicts a record NEGATIVE when any of that record's feedback_issues
                 is referenced by some rule's text, otherwise POSITIVE.

    We score that prediction against the human label. This is the closest honest
    proxy available from the current signals: it measures whether the rules
    GENERALIZE to held-out negatives rather than memorizing the training issues.
    A rule set overfit to train-only issues fails to fire on holdout negatives with
    different issues → predicts them positive → wrong → lower agreement.
    Labels are normalized (lowercase/strip) on the way in.
    """
    labeled = [r for r in records if _norm(r.feedback_rating) in ("positive", "negative")]
    if not labeled:
        return 0.0
    texts = _rule_texts(rules)
    correct = 0
    for rec in labeled:
        issues = [_norm(i) for i in (rec.feedback_issues or []) if _norm(i)]
        fired = any(any(iss in t for t in texts) for iss in issues)
        predicted = "negative" if fired else "positive"
        if predicted == _norm(rec.feedback_rating):
            correct += 1
    return correct / len(labeled)


def evaluate_candidate(old_rules, candidate_rules, holdout_records) -> dict:
    """
    Pure gate decision: score both rule sets on the SAME holdout and keep the
    candidate ONLY if it is strictly better. Returns holdout numbers only.
    """
    before = agreement(old_rules, holdout_records)
    after = agreement(candidate_rules, holdout_records)
    return {"agreement_before": before, "agreement_after": after, "keep": after > before}


def _labeled_count(records) -> int:
    return len([r for r in records if _norm(r.feedback_rating) in ("positive", "negative")])


def _apply_candidate(
    db: Session,
    vertical: str,
    candidate_rules: dict,
    holdout_records: list,
    total_samples: int,
    satisfaction: float,
) -> dict:
    """
    Gate + persist + changelog. Given a candidate rule set mined from TRAIN,
    score it on the HOLDOUT against the rules currently in production and keep it
    ONLY if strictly better. Writes exactly one LearningEvent on every
    decision (keep OR rollback) and recomputes the measured promotion state.
    """
    knowledge = db.query(VerticalKnowledge).filter(
        VerticalKnowledge.vertical == vertical
    ).first()

    old_rules = knowledge.learned_rules if (knowledge and knowledge.learned_rules) else {}
    prev_metrics = (knowledge.promotion_metrics if knowledge else None) or {}
    prev_live = prev_metrics.get("live_agreement")

    ev = evaluate_candidate(old_rules, candidate_rules, holdout_records)
    keep = ev["keep"]
    before, after = ev["agreement_before"], ev["agreement_after"]

    # live_agreement = holdout agreement of whatever rules are now serving.
    live_agreement = after if keep else before
    holdout_labels = _labeled_count(holdout_records)

    # Promotion bar (measured, never hardcoded): high holdout agreement over enough
    # holdout labels AND stable across the last >= 2 cycles.
    consecutive_high = (
        live_agreement >= _PROMOTION_AGREEMENT_BAR
        and prev_live is not None
        and prev_live >= _PROMOTION_AGREEMENT_BAR
    )
    promoted = (
        live_agreement >= _PROMOTION_AGREEMENT_BAR
        and holdout_labels >= _PROMOTION_MIN_HOLDOUT
        and consecutive_high
    )
    promotion_metrics = {
        "live_agreement": live_agreement,
        "holdout_labels": holdout_labels,
        "agreement_threshold": _PROMOTION_AGREEMENT_BAR,
        "min_holdout_labels": _PROMOTION_MIN_HOLDOUT,
        "consecutive_high_cycles": consecutive_high,
        "prev_live_agreement": prev_live,
    }

    # Persist. On rollback we leave learned_rules untouched. We only create a fresh
    # VerticalKnowledge row when we actually keep rules (nothing to serve otherwise).
    if keep:
        if not knowledge:
            knowledge = VerticalKnowledge(id=str(uuid.uuid4()), vertical=vertical)
            db.add(knowledge)
        knowledge.learned_rules = candidate_rules

    if knowledge:
        knowledge.total_samples = total_samples
        knowledge.avg_satisfaction = satisfaction
        knowledge.promoted = promoted
        knowledge.promotion_metrics = promotion_metrics
        knowledge.last_analyzed_at = datetime.utcnow()

    if keep:
        summary = (
            f"Adopted new learned_rules for '{vertical}': holdout agreement "
            f"{before:.2f} → {after:.2f} over {holdout_labels} holdout labels."
        )
    else:
        summary = (
            f"Rejected candidate for '{vertical}': holdout agreement would go "
            f"{before:.2f} → {after:.2f}; kept existing rules (rollback)."
        )

    db.add(LearningEvent(
        id=str(uuid.uuid4()),
        vertical=vertical,
        summary=summary,
        agreement_before=before,
        agreement_after=after,
        detail_json={
            "kept": keep,
            "holdout_labels": holdout_labels,
            "candidate_rules_count": len((candidate_rules or {}).get("prompt_rules", [])),
            "live_agreement": live_agreement,
            "promoted": promoted,
        },
    ))
    db.commit()

    return {
        "status": "analyzed",
        "vertical": vertical,
        "total_samples": total_samples,
        "satisfaction": satisfaction,
        "kept": keep,
        "agreement_before": before,
        "agreement_after": after,
        "holdout_agreement": live_agreement,   # the number callers should trust
        "holdout_labels": holdout_labels,
        "promoted": promoted,
        "rules_count": len(
            ((candidate_rules if keep else old_rules) or {}).get("prompt_rules", [])
        ),
    }


class LearningService:
    """Service that learns from generation data and feedback to improve future outputs"""

    @staticmethod
    def record_generation(
        db: Session,
        user_id: Optional[str],
        vertical: str,
        feature: str,
        input_data: dict,
        output_data: dict = None,
    ) -> str:
        """Store every generation as a learning record. Returns record ID."""
        record = LearningRecord(
            id=str(uuid.uuid4()),
            user_id=user_id,
            vertical=vertical,
            feature=feature,
            input_data=input_data,
            output_data=output_data,
        )
        db.add(record)
        db.commit()
        return record.id

    @staticmethod
    def record_feedback(
        db: Session,
        image_id: str,
        rating: str,
        issues: list = None,
        comment: str = None,
    ):
        """Attach feedback to the most recent learning record for this image"""
        # Find learning record that references this image
        record = db.query(LearningRecord).filter(
            LearningRecord.output_data.isnot(None),
        ).order_by(LearningRecord.created_at.desc()).first()

        # Also update any record whose output_data contains this image_id
        records = db.query(LearningRecord).all()
        for r in records:
            if r.output_data and isinstance(r.output_data, dict):
                if r.output_data.get("image_id") == image_id:
                    r.feedback_rating = rating
                    r.feedback_issues = issues
                    r.feedback_comment = comment
                    db.commit()
                    return

        # If no matching record, just log it
        logger.warning(f"No learning record found for image {image_id}")

    @staticmethod
    def get_generation_context(db: Session, vertical: str, feature: str = "image_generation") -> str:
        """
        Called BEFORE every generation.
        Returns learned rules as system prompt context.
        This is how the system 'remembers' what works.
        """
        # Get vertical knowledge
        knowledge = db.query(VerticalKnowledge).filter(
            VerticalKnowledge.vertical == vertical
        ).first()

        if not knowledge or not knowledge.learned_rules:
            return ""

        rules = knowledge.learned_rules
        prompt_rules = rules.get("prompt_rules", [])

        if not prompt_rules:
            return ""

        # Build context string from high-confidence rules
        context_lines = [f"LEARNED RULES FOR {vertical.upper()} (from past generation feedback):"]
        for rule in prompt_rules:
            if rule.get("confidence", 0) >= 0.6:
                context_lines.append(f"- {rule['rule']} (confidence: {rule['confidence']:.0%})")

        style_prefs = rules.get("style_preferences", {})
        if style_prefs.get("best"):
            context_lines.append(f"- Preferred style: {style_prefs['best']}")
        if style_prefs.get("worst"):
            context_lines.append(f"- Avoid style: {style_prefs['worst']}")

        return "\n".join(context_lines) if len(context_lines) > 1 else ""

    @staticmethod
    async def analyze_vertical(db: Session, vertical: str) -> dict:
        """
        Analyze all learning records for a vertical.
        Uses Gemini to identify patterns and produce rules.
        Updates VerticalKnowledge.
        """
        # Get all records for this vertical
        records = db.query(LearningRecord).filter(
            LearningRecord.vertical == vertical,
            LearningRecord.feedback_rating.isnot(None),
        ).all()

        if len(records) < 5:
            return {"status": "insufficient_data", "count": len(records)}

        # Deterministic train/holdout split. Candidate rules are mined from TRAIN
        # ONLY; the HOLDOUT is the untouched verifier the keep-decision is judged on.
        train = [r for r in records if not is_holdout(r.id)]
        holdout = [r for r in records if is_holdout(r.id)]

        if not train:  # degenerate split (all records hashed to holdout)
            return {"status": "insufficient_data", "count": len(records)}

        # Build analysis data — TRAIN ONLY (never let the miner see the holdout)
        positive = [r for r in train if r.feedback_rating == "positive"]
        negative = [r for r in train if r.feedback_rating == "negative"]

        # Collect issue frequencies
        issue_counts = {}
        for r in negative:
            if r.feedback_issues:
                for issue in r.feedback_issues:
                    issue_counts[issue] = issue_counts.get(issue, 0) + 1

        total = len(records)
        satisfaction = len(positive) / len(train) if train else 0

        # Use Gemini to analyze patterns
        analysis_prompt = f"""Analyze these image generation results for the "{vertical}" vertical and derive rules.

STATISTICS:
- Total generations with feedback (train): {len(train)}
- Positive feedback: {len(positive)} ({satisfaction:.0%})
- Negative feedback: {len(negative)}
- Top issues: {dict(sorted(issue_counts.items(), key=lambda x: -x[1])[:5])}

POSITIVE EXAMPLES (what worked):
{chr(10).join([f"- Prompt: {r.input_data.get('prompt', 'N/A')[:200]}" for r in positive[:10]])}

NEGATIVE EXAMPLES (what failed):
{chr(10).join([f"- Prompt: {r.input_data.get('prompt', 'N/A')[:200]} | Issues: {r.feedback_issues}" for r in negative[:10]])}

Based on this data, output a JSON object with:
{{
  "prompt_rules": [
    {{"rule": "description of the rule", "confidence": 0.0-1.0, "evidence_count": N}},
    ...
  ],
  "style_preferences": {{"best": "style_name", "worst": "style_name"}},
  "provider_performance": {{"provider_name": satisfaction_rate}}
}}

Output ONLY valid JSON, no markdown, no explanation."""

        try:
            from google import genai
            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=analysis_prompt,
            )

            import json
            # Try to parse the JSON response
            text = response.text.strip()
            # Remove markdown code blocks if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            candidate_rules = json.loads(text)

        except Exception as e:
            logger.error(f"Gemini analysis failed: {e}")
            # Fallback: derive basic rules from data (TRAIN only)
            candidate_rules = {
                "prompt_rules": [
                    {"rule": f"Avoid: {issue}", "confidence": count / len(negative) if negative else 0, "evidence_count": count}
                    for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1])[:5]
                ],
                "style_preferences": {},
                "provider_performance": {},
            }

        # Holdout gate: keep the candidate ONLY if it beats the live rules on the
        # untouched holdout. Persists the decision + writes a LearningEvent either way.
        return _apply_candidate(
            db=db,
            vertical=vertical,
            candidate_rules=candidate_rules,
            holdout_records=holdout,
            total_samples=total,
            satisfaction=satisfaction,
        )

    @staticmethod
    async def generate_suggestions(db: Session, vertical: str) -> list:
        """
        Generate AI suggestions based on feedback analysis.
        These go into a queue for admin approval.
        """
        knowledge = db.query(VerticalKnowledge).filter(
            VerticalKnowledge.vertical == vertical
        ).first()

        if not knowledge or not knowledge.learned_rules:
            return []

        rules = knowledge.learned_rules
        suggestions = []

        for rule in rules.get("prompt_rules", []):
            if rule.get("confidence", 0) >= 0.7 and rule.get("evidence_count", 0) >= 3:
                # Check if suggestion already exists
                existing = db.query(AISuggestion).filter(
                    AISuggestion.vertical == vertical,
                    AISuggestion.suggestion_text == rule["rule"],
                    AISuggestion.status.in_(["pending", "approved"]),
                ).first()

                if not existing:
                    suggestion = AISuggestion(
                        id=str(uuid.uuid4()),
                        category="prompt_improvement",
                        vertical=vertical,
                        suggestion_text=rule["rule"],
                        suggested_change={"type": "add_prompt_rule", "rule": rule["rule"]},
                        evidence={"confidence": rule["confidence"], "evidence_count": rule["evidence_count"], "satisfaction": knowledge.avg_satisfaction},
                        status="pending",
                    )
                    db.add(suggestion)
                    suggestions.append(suggestion)

        # Style preference suggestion
        style_prefs = rules.get("style_preferences", {})
        if style_prefs.get("best") and style_prefs.get("worst"):
            suggestion_text = f"Switch default style from {style_prefs['worst']} to {style_prefs['best']}"
            existing = db.query(AISuggestion).filter(
                AISuggestion.vertical == vertical,
                AISuggestion.suggestion_text == suggestion_text,
                AISuggestion.status.in_(["pending", "approved"]),
            ).first()

            if not existing:
                suggestion = AISuggestion(
                    id=str(uuid.uuid4()),
                    category="style_change",
                    vertical=vertical,
                    suggestion_text=suggestion_text,
                    suggested_change={"type": "change_default_style", "from": style_prefs["worst"], "to": style_prefs["best"]},
                    evidence={"satisfaction": knowledge.avg_satisfaction},
                    status="pending",
                )
                db.add(suggestion)
                suggestions.append(suggestion)

        db.commit()
        return suggestions

    @staticmethod
    def get_vertical_stats(db: Session, vertical: str) -> dict:
        """Get learning stats for a vertical"""
        total = db.query(func.count(LearningRecord.id)).filter(
            LearningRecord.vertical == vertical
        ).scalar()

        with_feedback = db.query(func.count(LearningRecord.id)).filter(
            LearningRecord.vertical == vertical,
            LearningRecord.feedback_rating.isnot(None),
        ).scalar()

        positive = db.query(func.count(LearningRecord.id)).filter(
            LearningRecord.vertical == vertical,
            LearningRecord.feedback_rating == "positive",
        ).scalar()

        knowledge = db.query(VerticalKnowledge).filter(
            VerticalKnowledge.vertical == vertical
        ).first()

        return {
            "vertical": vertical,
            "total_records": total,
            "with_feedback": with_feedback,
            "positive": positive,
            "negative": with_feedback - positive,
            "satisfaction": positive / with_feedback if with_feedback > 0 else None,
            "learned_rules_count": len(knowledge.learned_rules.get("prompt_rules", [])) if knowledge and knowledge.learned_rules else 0,
            "last_analyzed": str(knowledge.last_analyzed_at) if knowledge and knowledge.last_analyzed_at else None,
            # Measured promotion state: lets callers tell "suggest" (guess) from "assert".
            "promoted": bool(knowledge.promoted) if knowledge else False,
            "promotion_metrics": knowledge.promotion_metrics if knowledge else None,
        }
