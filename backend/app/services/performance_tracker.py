"""Performance Tracker - manual campaign metrics input for learning engine feedback"""
import logging
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from ..config import settings

logger = logging.getLogger(__name__)


class PerformanceTrackerService:
    """Tracks campaign performance and feeds real conversion data into the learning engine"""

    @staticmethod
    def record_campaign_metrics(
        db: Session,
        user_id: str,
        campaign_name: str,
        vertical: str,
        creative_ids: list = None,
        metrics: dict = None,
    ) -> dict:
        """Record campaign performance metrics and calculate KPIs"""
        from ..models.learning import LearningRecord

        m = metrics or {}
        spend = m.get("spend", 0)
        impressions = m.get("impressions", 0)
        clicks = m.get("clicks", 0)
        lp_views = m.get("lp_views", 0)
        conversions = m.get("conversions", 0)
        revenue = m.get("revenue", 0)

        # Calculate KPIs
        ctr = (clicks / impressions * 100) if impressions > 0 else 0
        lp_ctr = (lp_views / clicks * 100) if clicks > 0 else 0
        conv_rate = (conversions / lp_views * 100) if lp_views > 0 else 0
        cpc = (spend / clicks) if clicks > 0 else 0
        cpa = (spend / conversions) if conversions > 0 else 0
        roas = (revenue / spend) if spend > 0 else 0
        epc = (revenue / clicks) if clicks > 0 else 0

        calculated = {
            "ctr": round(ctr, 2),
            "lp_ctr": round(lp_ctr, 2),
            "conversion_rate": round(conv_rate, 2),
            "cpc": round(cpc, 2),
            "cpa": round(cpa, 2),
            "roas": round(roas, 2),
            "epc": round(epc, 4),
        }

        # Determine performance rating based on benchmarks
        rating = "positive"
        issues = []
        if ctr < 1.0 and impressions > 100:
            issues.append("low_ctr")
        if conv_rate < 2.0 and lp_views > 50:
            issues.append("low_conversion")
        if roas < 1.0 and spend > 10:
            issues.append("negative_roas")
            rating = "negative"
        if cpa > 50 and conversions > 0:
            issues.append("high_cpa")

        # Store as learning record — this feeds the AI learning engine
        record = LearningRecord(
            id=str(uuid.uuid4()),
            user_id=user_id,
            vertical=vertical,
            feature="campaign_performance",
            input_data={
                "campaign_name": campaign_name,
                "creative_ids": creative_ids or [],
                "raw_metrics": m,
            },
            output_data={
                "calculated_kpis": calculated,
                "benchmarks": {
                    "ctr_benchmark": "1-3%",
                    "conv_rate_benchmark": "2-5%",
                    "roas_benchmark": ">2x",
                },
            },
            feedback_rating=rating,
            feedback_issues=issues if issues else None,
        )
        db.add(record)
        db.commit()

        return {
            "campaign": campaign_name,
            "vertical": vertical,
            "raw_metrics": m,
            "calculated_kpis": calculated,
            "performance_rating": rating,
            "issues": issues,
            "record_id": record.id,
        }

    @staticmethod
    def get_campaign_history(db: Session, user_id: str, vertical: str = None, limit: int = 20) -> list:
        from ..models.learning import LearningRecord

        query = db.query(LearningRecord).filter(
            LearningRecord.user_id == user_id,
            LearningRecord.feature == "campaign_performance",
        )
        if vertical:
            query = query.filter(LearningRecord.vertical == vertical)

        records = query.order_by(LearningRecord.created_at.desc()).limit(limit).all()

        return [
            {
                "id": r.id,
                "campaign": (r.input_data or {}).get("campaign_name", "Unknown"),
                "vertical": r.vertical,
                "kpis": (r.output_data or {}).get("calculated_kpis", {}),
                "rating": r.feedback_rating,
                "issues": r.feedback_issues,
                "created_at": str(r.created_at),
            }
            for r in records
        ]
