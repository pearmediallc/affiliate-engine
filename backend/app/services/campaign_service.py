"""
Campaign service — orchestrates the full pipeline:

  draft → briefing → scripting → storyboarding → generating → editing → review → completed

Each phase transition is a separate call so the frontend can show progress
and the user can intervene between steps.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from ..models.campaign import Campaign, Shot, Variation, Character, SceneSetting
from ..services.pricing import Pricing

logger = logging.getLogger(__name__)


class CampaignService:

    # ─────────────────────────────────────── CREATE / READ

    @staticmethod
    def create(
        db: Session,
        user_id: str,
        name: str,
        vertical: str,
        brief_text: str = "",
        reference_video_path: Optional[str] = None,
        reference_image_path: Optional[str] = None,
    ) -> Campaign:
        campaign = Campaign(
            user_id=user_id,
            name=name,
            vertical=vertical,
            brief_text=brief_text,
            reference_video_path=reference_video_path,
            reference_image_path=reference_image_path,
            status="draft",
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        logger.info(f"Created campaign {campaign.id} for user {user_id}")
        return campaign

    @staticmethod
    def get(db: Session, campaign_id: str, user_id: str) -> Optional[Campaign]:
        return (
            db.query(Campaign)
            .filter(Campaign.id == campaign_id, Campaign.user_id == user_id)
            .first()
        )

    @staticmethod
    def list_for_user(db: Session, user_id: str, limit: int = 50) -> list[Campaign]:
        return (
            db.query(Campaign)
            .filter(Campaign.user_id == user_id)
            .order_by(Campaign.created_at.desc())
            .limit(limit)
            .all()
        )

    # ─────────────────────────────────────── PHASE: BRIEFING (analyze reference)

    @staticmethod
    def run_briefing(db: Session, campaign: Campaign) -> Campaign:
        """
        Phase: briefing.
        Analyzes reference video/image (if any) and merges with brief_text.
        Stores result in campaign.analyzed_brief.
        """
        from .reference_analyzer import ReferenceAnalyzerService

        analyzed = {}

        if campaign.reference_video_path:
            logger.info(f"Analyzing reference video for campaign {campaign.id}")
            analysis = ReferenceAnalyzerService.analyze_video(
                campaign.reference_video_path,
                context=campaign.brief_text or "",
            )
            analyzed = ReferenceAnalyzerService.extract_brief_for_campaign(
                analysis,
                vertical=campaign.vertical or "",
                offer=campaign.brief_text or "",
            )
        elif campaign.reference_image_path:
            logger.info(f"Analyzing reference image for campaign {campaign.id}")
            analysis = ReferenceAnalyzerService.analyze_image(
                campaign.reference_image_path,
                context=campaign.brief_text or "",
            )
            analyzed = {
                "vertical": campaign.vertical,
                "offer": campaign.brief_text,
                "reference_image_analysis": analysis,
                "hook_style": "image-driven",
                "visual_rhythm": "mixed",
                "ad_arc": "lifestyle",
                "cta_style": "verbal",
                "color_palette": analysis.get("color_palette", ""),
                "camera_style": "mixed",
                "reference_characters": [],
                "reference_settings": [],
                "key_insights": [],
                "estimated_duration": 30,
            }
        else:
            # Text-only brief
            analyzed = {
                "vertical": campaign.vertical,
                "offer": campaign.brief_text,
                "hook_style": "direct",
                "visual_rhythm": "mixed",
                "ad_arc": "problem-solution",
                "cta_style": "verbal",
                "color_palette": "",
                "camera_style": "mixed",
                "reference_characters": [],
                "reference_settings": [],
                "key_insights": [],
                "estimated_duration": 30,
            }

        campaign.analyzed_brief = analyzed
        campaign.status = "briefing"
        db.commit()
        db.refresh(campaign)
        return campaign

    # ─────────────────────────────────────── PHASE: SCRIPTING

    @staticmethod
    def run_scripting(
        db: Session,
        campaign: Campaign,
        target_duration: int = 30,
        extra_instructions: str = "",
    ) -> Campaign:
        """
        Phase: scripting.
        Generates a full ad script using Gemini directly from the analyzed brief.
        """
        from ..config import settings
        from google import genai
        from google.genai import types as gtypes

        brief = campaign.analyzed_brief or {}
        vertical = campaign.vertical or "general"
        offer = brief.get("offer") or campaign.brief_text or ""

        system = (
            "You are an elite direct-response copywriter specialising in short-form video ad scripts. "
            "Write punchy, high-converting scripts with a strong hook, clear problem-solution arc, and CTA. "
            "Format: plain text scene-by-scene with [HOOK], [PROBLEM], [SOLUTION], [PROOF], [CTA] labels. "
            "No markdown, no explanations — just the script."
        )

        user = f"""Write a {target_duration}-second video ad script.

Vertical: {vertical}
Offer / product: {offer}
Hook style: {brief.get("hook_style", "direct")}
Ad arc: {brief.get("ad_arc", "problem-solution")}
Visual rhythm: {brief.get("visual_rhythm", "mixed")}
Key insights: {"; ".join(brief.get("key_insights", [])) or "none"}
{f"Extra instructions: {extra_instructions}" if extra_instructions else ""}

Target {target_duration} seconds of spoken narration. Each scene should have clear narration text."""

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=user,
            config=gtypes.GenerateContentConfig(
                system_instruction=system,
                temperature=0.8,
                max_output_tokens=2048,
            ),
        )
        script_text = response.text or ""

        campaign.script = script_text
        campaign.status = "scripting"
        db.commit()
        db.refresh(campaign)
        return campaign

    # ─────────────────────────────────────── PHASE: STORYBOARDING

    @staticmethod
    def run_storyboarding(
        db: Session,
        campaign: Campaign,
        character_ids: list[str],
        setting_ids: list[str],
        target_duration: int = 30,
    ) -> Campaign:
        """
        Phase: storyboarding.
        Generates a shot list using StoryboardService and persists it as Shot rows.
        """
        from .storyboard_service import StoryboardService

        characters = db.query(Character).filter(Character.id.in_(character_ids)).all() if character_ids else []
        scene_settings = db.query(SceneSetting).filter(SceneSetting.id.in_(setting_ids)).all() if setting_ids else []

        brief = campaign.analyzed_brief or {}
        script = campaign.script or ""

        char_dicts = [{"id": c.id, "name": c.name, "description": c.description} for c in characters]
        setting_dicts = [{"id": s.id, "name": s.name, "description": s.description} for s in scene_settings]

        result = StoryboardService.generate(
            brief=brief,
            script=script,
            characters=char_dicts,
            scene_settings=setting_dicts,
            target_duration=target_duration,
        )

        shots_data = result["shots"]
        campaign.storyboard = shots_data

        # Persist Shot rows
        db.query(Shot).filter(Shot.campaign_id == campaign.id, Shot.variation_id == None).delete()

        # Map character/setting names back to IDs
        char_by_name = {c.name.lower(): c.id for c in characters}
        setting_by_name = {s.name.lower(): s.id for s in scene_settings}

        for shot_dict in shots_data:
            char_id = None
            if shot_dict.get("character_ref") and characters:
                char_id = characters[0].id  # use first character as default

            setting_id = None
            if shot_dict.get("setting_ref") and scene_settings:
                setting_id = scene_settings[0].id

            shot = Shot(
                campaign_id=campaign.id,
                sequence_num=shot_dict.get("sequence_num", 1),
                shot_type=shot_dict.get("shot_type", "b_roll"),
                character_id=char_id,
                setting_id=setting_id,
                prompt=shot_dict.get("prompt", ""),
                model_id=shot_dict.get("routed_model"),
                duration=int(shot_dict.get("duration", 6)),
                status="pending",
            )
            db.add(shot)

        campaign.total_cost_usd = result["estimated_cost_usd"]
        campaign.status = "storyboarding"
        db.commit()
        db.refresh(campaign)
        return campaign

    # ─────────────────────────────────────── PHASE: GENERATING

    @staticmethod
    def start_generation(
        db: Session,
        campaign: Campaign,
        background_tasks=None,
    ) -> Campaign:
        """
        Phase: generating.
        Kicks off video generation for each Shot in parallel (via background tasks).
        """
        campaign.status = "generating"
        db.commit()

        # Reset failed + pending shots. Also reset any shots stuck in "generating"
        # (background task died on Render restart without updating DB).
        shots = (
            db.query(Shot)
            .filter(
                Shot.campaign_id == campaign.id,
                Shot.variation_id == None,
                Shot.status.in_(["pending", "failed", "generating"]),
            )
            .order_by(Shot.sequence_num)
            .all()
        )
        for shot in shots:
            shot.status = "pending"
        db.commit()

        for shot in shots:
            if background_tasks:
                background_tasks.add_task(
                    CampaignService._generate_shot_bg,
                    campaign_id=campaign.id,
                    shot_id=shot.id,
                )

        db.refresh(campaign)
        return campaign

    @staticmethod
    def _generate_shot_bg(campaign_id: str, shot_id: str):
        """Background task: generate one shot."""
        from ..database import SessionLocal
        from .multi_provider_video import MultiProviderVideoService

        db = SessionLocal()
        try:
            shot = db.query(Shot).filter(Shot.id == shot_id).first()
            if not shot:
                return

            shot.status = "generating"
            db.commit()

            # Resolve character portrait for image-to-video if applicable
            image_path = None
            if shot.character_id:
                char = db.query(Character).filter(Character.id == shot.character_id).first()
                if char and char.portrait_path:
                    image_path = char.portrait_path

            result = MultiProviderVideoService.generate(
                prompt=shot.prompt,
                shot_type=shot.shot_type or "b_roll",
                preferred_model=shot.model_id,
                image_path=image_path,
                duration=shot.duration or 6,
            )

            if result.get("async"):
                # Veo: poll until done
                from .video_creator import VideoCreatorService
                import time
                op_name = result["operation_name"]
                for _ in range(60):
                    time.sleep(10)
                    status = VideoCreatorService.check_status(op_name)
                    if status.get("done"):
                        shot.video_path = status.get("video_path")
                        shot.video_url = status.get("download_url")
                        shot.status = "completed"
                        shot.cost_usd = result.get("cost_usd", 0)
                        break
                else:
                    shot.status = "failed"
            else:
                shot.video_path = result.get("video_path")
                shot.video_url = result.get("download_url")
                shot.status = "completed"
                shot.cost_usd = result.get("cost_usd", 0)

            db.commit()

            # Check if all shots done → advance campaign
            CampaignService._check_and_advance(db, campaign_id)

        except Exception as e:
            logger.error(f"Shot generation failed {shot_id}: {e}", exc_info=True)
            db.query(Shot).filter(Shot.id == shot_id).update({"status": "failed"})
            db.commit()
            # Still check advancement — all shots may be done (failed counts as done)
            CampaignService._check_and_advance(db, campaign_id)
        finally:
            db.close()

    @staticmethod
    def _check_and_advance(db: Session, campaign_id: str):
        """After each shot finishes (success or failure), advance if nothing is still running."""
        in_flight = (
            db.query(Shot)
            .filter(
                Shot.campaign_id == campaign_id,
                Shot.variation_id == None,
                Shot.status.in_(["pending", "generating"]),
            )
            .count()
        )
        if in_flight == 0:
            db.query(Campaign).filter(Campaign.id == campaign_id).update({"status": "editing"})
            db.commit()

    # ─────────────────────────────────────── HELPERS

    @staticmethod
    def get_shots(db: Session, campaign_id: str) -> list[Shot]:
        return (
            db.query(Shot)
            .filter(Shot.campaign_id == campaign_id, Shot.variation_id == None)
            .order_by(Shot.sequence_num)
            .all()
        )

    @staticmethod
    def get_cost_estimate(db: Session, campaign_id: str) -> dict:
        shots = db.query(Shot).filter(Shot.campaign_id == campaign_id).all()
        estimated = sum(Pricing.video(s.model_id or "wan-2.2", s.duration or 6) for s in shots)
        actual = sum(s.cost_usd or 0 for s in shots if s.status == "completed")
        return {
            "shot_count": len(shots),
            "estimated_cost_usd": round(estimated, 4),
            "actual_cost_usd": round(actual, 4),
        }

    @staticmethod
    def to_dict(campaign: Campaign, include_shots: bool = False, db: Session = None) -> dict:
        d = {
            "id": campaign.id,
            "name": campaign.name,
            "vertical": campaign.vertical,
            "brief_text": campaign.brief_text,
            "analyzed_brief": campaign.analyzed_brief,
            "script": campaign.script,
            "storyboard": campaign.storyboard,
            "status": campaign.status,
            "total_cost_usd": campaign.total_cost_usd,
            "created_at": str(campaign.created_at),
            "updated_at": str(campaign.updated_at),
        }
        if include_shots and db:
            shots = CampaignService.get_shots(db, campaign.id)
            d["shots"] = [
                {
                    "id": s.id,
                    "sequence_num": s.sequence_num,
                    "shot_type": s.shot_type,
                    "prompt": s.prompt,
                    "model_id": s.model_id,
                    "duration": s.duration,
                    "status": s.status,
                    "video_url": s.video_url,
                    "cost_usd": s.cost_usd,
                }
                for s in shots
            ]
        return d
