"""Learning service - builds institutional knowledge from generation data + feedback"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..models.learning import LearningRecord, VerticalKnowledge, AISuggestion
from ..config import settings

logger = logging.getLogger(__name__)


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

        # Build analysis data
        positive = [r for r in records if r.feedback_rating == "positive"]
        negative = [r for r in records if r.feedback_rating == "negative"]

        # Collect issue frequencies
        issue_counts = {}
        for r in negative:
            if r.feedback_issues:
                for issue in r.feedback_issues:
                    issue_counts[issue] = issue_counts.get(issue, 0) + 1

        total = len(records)
        satisfaction = len(positive) / total if total > 0 else 0

        # Use Gemini to analyze patterns
        analysis_prompt = f"""Analyze these image generation results for the "{vertical}" vertical and derive rules.

STATISTICS:
- Total generations with feedback: {total}
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

            learned_rules = json.loads(text)

        except Exception as e:
            logger.error(f"Gemini analysis failed: {e}")
            # Fallback: derive basic rules from data
            learned_rules = {
                "prompt_rules": [
                    {"rule": f"Avoid: {issue}", "confidence": count / len(negative) if negative else 0, "evidence_count": count}
                    for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1])[:5]
                ],
                "style_preferences": {},
                "provider_performance": {},
            }

        # Update or create VerticalKnowledge
        knowledge = db.query(VerticalKnowledge).filter(
            VerticalKnowledge.vertical == vertical
        ).first()

        if not knowledge:
            knowledge = VerticalKnowledge(
                id=str(uuid.uuid4()),
                vertical=vertical,
            )
            db.add(knowledge)

        knowledge.learned_rules = learned_rules
        knowledge.total_samples = total
        knowledge.avg_satisfaction = satisfaction
        knowledge.last_analyzed_at = datetime.utcnow()
        db.commit()

        return {
            "status": "analyzed",
            "vertical": vertical,
            "total_samples": total,
            "satisfaction": satisfaction,
            "rules_count": len(learned_rules.get("prompt_rules", [])),
        }

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
        }
