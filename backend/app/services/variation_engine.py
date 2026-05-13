"""
Variation engine — takes one completed campaign and produces N variants.

Variant strategies:
  hook         — replace first shot with a different hook angle
  character    — swap character; regenerate character-shots only
  style        — swap video model for all shots (different visual style)
  setting      — swap setting; regenerate setting-shots only
  vertical_port — rewrite copy for a different vertical, keep visual rhythm

Cost efficiency:
  hook variants reuse all shots except shot 1 → cheapest
  style variants reuse keyframes, just re-route the model → cheap
  character/setting variants regenerate subset of shots
  vertical_port requires script + storyboard regen but reuses structure
"""
import copy
import logging
from typing import Optional
from sqlalchemy.orm import Session
from ..models.campaign import Campaign, Shot, Variation
from .pricing import Pricing
from .multi_provider_video import MultiProviderVideoService

logger = logging.getLogger(__name__)


class VariationEngine:

    @staticmethod
    def plan_variants(
        db: Session,
        campaign_id: str,
        strategies: list[str],
        num_per_strategy: int = 3,
    ) -> list[dict]:
        """
        Plan (but don't generate) a list of variants.
        Returns list of variant plan dicts with estimated cost.
        """
        base_shots = (
            db.query(Shot)
            .filter(Shot.campaign_id == campaign_id, Shot.variation_id == None)
            .order_by(Shot.sequence_num)
            .all()
        )
        if not base_shots:
            return []

        plans = []
        for strategy in strategies:
            for i in range(num_per_strategy):
                plan = VariationEngine._plan_one(base_shots, strategy, index=i)
                plans.append(plan)
        return plans

    @staticmethod
    def _plan_one(base_shots: list[Shot], strategy: str, index: int = 0) -> dict:
        """Describe what a single variant would regenerate + estimated cost."""
        shots_to_regen = []
        label = ""

        if strategy == "hook":
            hooks = [
                "urgency — time-limited offer, scarcity",
                "curiosity — open loop question",
                "social proof — testimonial opener",
                "transformation — before/after reveal",
                "fear of loss — pain agitation",
            ]
            label = f"Hook: {hooks[index % len(hooks)]}"
            shots_to_regen = [base_shots[0].id] if base_shots else []

        elif strategy == "character":
            label = f"Character variant {index + 1}"
            shots_to_regen = [s.id for s in base_shots if s.character_id]

        elif strategy == "style":
            # Different model for all shots
            style_models = ["luma-ray-2", "hailuo-02", "veo-3.1-fast", "wan-2.2", "higgsfield-v1"]
            model = style_models[index % len(style_models)]
            label = f"Style: {model}"
            shots_to_regen = [s.id for s in base_shots]

        elif strategy == "setting":
            label = f"Setting variant {index + 1}"
            shots_to_regen = [s.id for s in base_shots if s.setting_id]

        elif strategy == "vertical_port":
            label = f"Vertical port {index + 1}"
            shots_to_regen = [s.id for s in base_shots]  # all shots need new prompts

        else:
            label = f"{strategy} variant {index + 1}"
            shots_to_regen = [s.id for s in base_shots]

        # Estimate cost
        regen_shots = [s for s in base_shots if s.id in shots_to_regen]
        cost = sum(Pricing.video(s.model_id or "wan-2.2", s.duration or 6) for s in regen_shots)

        return {
            "strategy": strategy,
            "label": label,
            "shots_to_regenerate": len(shots_to_regen),
            "total_shots": len(base_shots),
            "estimated_cost_usd": round(cost, 4),
        }

    @staticmethod
    def create_variation(
        db: Session,
        campaign: Campaign,
        strategy: str,
        label: str,
        shots_config: Optional[dict] = None,
        new_character_id: Optional[str] = None,
        new_setting_id: Optional[str] = None,
        style_model: Optional[str] = None,
        new_vertical: Optional[str] = None,
    ) -> Variation:
        """
        Create a Variation record + its Shot rows (copied from base, with overrides).
        Does not generate yet — call start_generation next.
        """
        base_shots = (
            db.query(Shot)
            .filter(Shot.campaign_id == campaign.id, Shot.variation_id == None)
            .order_by(Shot.sequence_num)
            .all()
        )

        variation = Variation(
            campaign_id=campaign.id,
            variation_type=strategy,
            label=label,
            shots_config=shots_config or {},
            status="pending",
        )
        db.add(variation)
        db.flush()  # get variation.id

        for base_shot in base_shots:
            new_shot = Shot(
                campaign_id=campaign.id,
                variation_id=variation.id,
                sequence_num=base_shot.sequence_num,
                shot_type=base_shot.shot_type,
                character_id=new_character_id if (strategy == "character" and base_shot.character_id) else base_shot.character_id,
                setting_id=new_setting_id if (strategy == "setting" and base_shot.setting_id) else base_shot.setting_id,
                prompt=base_shot.prompt,
                model_id=style_model if strategy == "style" else base_shot.model_id,
                duration=base_shot.duration,
                # Re-use completed base video when the shot doesn't need regeneration
                video_path=base_shot.video_path,
                video_url=base_shot.video_url,
                status="completed" if not VariationEngine._needs_regen(base_shot, strategy) else "pending",
            )
            db.add(new_shot)

        db.commit()
        db.refresh(variation)
        return variation

    @staticmethod
    def _needs_regen(shot: Shot, strategy: str) -> bool:
        if strategy == "hook":
            return shot.sequence_num == 1
        if strategy == "character":
            return bool(shot.character_id)
        if strategy == "style":
            return True
        if strategy == "setting":
            return bool(shot.setting_id)
        if strategy == "vertical_port":
            return True
        return False

    @staticmethod
    def start_generation(
        db: Session,
        variation: Variation,
        background_tasks=None,
    ) -> Variation:
        """Kick off generation for all pending shots in this variation."""
        variation.status = "generating"
        db.commit()

        pending_shots = (
            db.query(Shot)
            .filter(Shot.variation_id == variation.id, Shot.status == "pending")
            .all()
        )

        for shot in pending_shots:
            if background_tasks:
                background_tasks.add_task(
                    _generate_variation_shot_bg,
                    variation_id=variation.id,
                    shot_id=shot.id,
                )

        db.refresh(variation)
        return variation

    @staticmethod
    def get_variations(db: Session, campaign_id: str) -> list[Variation]:
        return (
            db.query(Variation)
            .filter(Variation.campaign_id == campaign_id)
            .order_by(Variation.created_at)
            .all()
        )

    @staticmethod
    def approve(db: Session, variation: Variation) -> Variation:
        variation.review_status = "approved"
        db.commit()
        db.refresh(variation)
        return variation

    @staticmethod
    def reject(db: Session, variation: Variation) -> Variation:
        variation.review_status = "rejected"
        db.commit()
        db.refresh(variation)
        return variation

    @staticmethod
    def to_dict(variation: Variation, include_shots: bool = False, db: Session = None) -> dict:
        d = {
            "id": variation.id,
            "campaign_id": variation.campaign_id,
            "variation_type": variation.variation_type,
            "label": variation.label,
            "status": variation.status,
            "review_status": variation.review_status,
            "final_video_url": variation.final_video_url,
            "final_video_9_16": variation.final_video_9_16,
            "final_video_1_1": variation.final_video_1_1,
            "total_cost_usd": variation.total_cost_usd,
            "created_at": str(variation.created_at),
        }
        if include_shots and db:
            shots = db.query(Shot).filter(Shot.variation_id == variation.id).order_by(Shot.sequence_num).all()
            d["shots"] = [
                {
                    "id": s.id,
                    "sequence_num": s.sequence_num,
                    "shot_type": s.shot_type,
                    "status": s.status,
                    "video_url": s.video_url,
                    "duration": s.duration,
                    "cost_usd": s.cost_usd,
                }
                for s in shots
            ]
        return d


def _generate_variation_shot_bg(variation_id: str, shot_id: str):
    """Background task for variation shot generation."""
    from ..database import SessionLocal
    from ..models.campaign import Character

    db = SessionLocal()
    try:
        shot = db.query(Shot).filter(Shot.id == shot_id).first()
        if not shot:
            return

        shot.status = "generating"
        db.commit()

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
            from ..services.video_creator import VideoCreatorService
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

        # Check if all variation shots done
        pending = db.query(Shot).filter(Shot.variation_id == variation_id, Shot.status.in_(["pending", "generating"])).count()
        if pending == 0:
            db.query(Variation).filter(Variation.id == variation_id).update({"status": "editing"})
            db.commit()

    except Exception as e:
        logger.error(f"Variation shot failed {shot_id}: {e}", exc_info=True)
        db.query(Shot).filter(Shot.id == shot_id).update({"status": "failed"})
        db.commit()
    finally:
        db.close()
