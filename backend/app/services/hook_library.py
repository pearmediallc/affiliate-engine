"""Hook Pattern Library - extracts and stores proven hook patterns from video analysis"""
import logging
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..config import settings

logger = logging.getLogger(__name__)


class HookLibraryService:
    """Extracts, stores, and retrieves proven hook patterns"""

    @staticmethod
    def extract_and_store(
        db: Session,
        hook_text: str,
        vertical: str,
        source: str = "manual",
        effectiveness_score: float = 0.0,
        platform: str = "unknown",
        emotional_trigger: str = "",
    ):
        """Store a hook pattern extracted from video analysis or manual input"""
        from ..models.learning import LearningRecord

        record = LearningRecord(
            id=str(uuid.uuid4()),
            vertical=vertical,
            feature="hook_pattern",
            input_data={
                "hook_text": hook_text,
                "platform": platform,
                "source": source,
                "emotional_trigger": emotional_trigger,
            },
            output_data={
                "effectiveness_score": effectiveness_score,
                "stored_at": datetime.utcnow().isoformat(),
            },
            feedback_rating="positive" if effectiveness_score >= 7 else None,
        )
        db.add(record)
        db.commit()
        return record.id

    @staticmethod
    def get_top_hooks(
        db: Session,
        vertical: str = None,
        platform: str = None,
        limit: int = 20,
    ) -> list:
        """Get top-performing hook patterns, optionally filtered by vertical/platform"""
        from ..models.learning import LearningRecord

        query = db.query(LearningRecord).filter(
            LearningRecord.feature == "hook_pattern",
        )

        if vertical:
            query = query.filter(LearningRecord.vertical == vertical)

        records = query.order_by(LearningRecord.created_at.desc()).limit(limit).all()

        hooks = []
        for r in records:
            input_data = r.input_data or {}
            output_data = r.output_data or {}
            hooks.append({
                "id": r.id,
                "hook_text": input_data.get("hook_text", ""),
                "vertical": r.vertical,
                "platform": input_data.get("platform", "unknown"),
                "emotional_trigger": input_data.get("emotional_trigger", ""),
                "effectiveness_score": output_data.get("effectiveness_score", 0),
                "source": input_data.get("source", "manual"),
                "created_at": str(r.created_at),
            })

        # Sort by effectiveness
        hooks.sort(key=lambda h: h.get("effectiveness_score", 0), reverse=True)

        return hooks

    @staticmethod
    async def auto_extract_hooks(
        analysis_text: str,
        vertical: str,
        platform: str,
        db: Session,
    ) -> list:
        """Extract hook patterns from a video analysis result using Gemini"""
        from google import genai

        if not settings.gemini_api_key:
            return []

        client = genai.Client(api_key=settings.gemini_api_key)

        prompt = f"""Extract specific hook patterns from this video analysis.
A "hook" is the opening 1-3 seconds technique that stops people from scrolling.

ANALYSIS:
{analysis_text[:2000]}

Extract each distinct hook pattern and return as JSON array:
[
  {{
    "hook_text": "The exact opening line or technique",
    "emotional_trigger": "fear/curiosity/authority/social_proof/urgency/etc",
    "effectiveness_score": 1-10,
    "why_it_works": "Brief explanation"
  }}
]

Output ONLY valid JSON array.
"""

        try:
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            import json
            hooks = json.loads(text)

            # Store each hook
            stored_ids = []
            for h in hooks:
                rid = HookLibraryService.extract_and_store(
                    db=db,
                    hook_text=h.get("hook_text", ""),
                    vertical=vertical,
                    source="auto_extracted",
                    effectiveness_score=h.get("effectiveness_score", 5),
                    platform=platform,
                    emotional_trigger=h.get("emotional_trigger", ""),
                )
                stored_ids.append(rid)

            return hooks
        except Exception as e:
            logger.warning(f"Hook extraction failed: {e}")
            return []

    @staticmethod
    def get_hooks_for_prompt(db: Session, vertical: str, limit: int = 5) -> str:
        """Get top hooks formatted for injection into script/copy generation prompts"""
        hooks = HookLibraryService.get_top_hooks(db, vertical=vertical, limit=limit)
        if not hooks:
            return ""

        lines = ["PROVEN HOOK PATTERNS FOR THIS VERTICAL (use these as inspiration):"]
        for h in hooks[:limit]:
            lines.append(f"- \"{h['hook_text']}\" (trigger: {h['emotional_trigger']}, score: {h['effectiveness_score']}/10)")

        return "\n".join(lines)
