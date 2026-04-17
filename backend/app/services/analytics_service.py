"""Service for analytics and performance tracking"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..models import Image, PerformanceMetric, Template
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for tracking and analyzing image performance"""

    @staticmethod
    def get_client_analytics(db: Session, client_id: str) -> dict:
        """Get overall analytics for a client"""
        total_images = db.query(Image).filter(Image.client_id == client_id).count()

        total_cost = db.query(func.sum(Image.cost_usd)).filter(
            Image.client_id == client_id
        ).scalar() or 0

        # Performance data
        performances = (
            db.query(PerformanceMetric)
            .filter(PerformanceMetric.client_id == client_id)
            .all()
        )

        total_clicks = sum(p.clicks for p in performances)
        total_conversions = sum(p.conversions for p in performances)
        total_revenue = sum(p.revenue_generated for p in performances)

        avg_ctr = (
            sum(p.ctr for p in performances if p.ctr) / len([p for p in performances if p.ctr])
            if any(p.ctr for p in performances)
            else 0
        )

        roi = ((total_revenue - total_cost) / total_cost * 100) if total_cost > 0 else 0

        return {
            "total_images": total_images,
            "total_cost": round(total_cost, 2),
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "total_revenue": round(total_revenue, 2),
            "average_ctr": round(avg_ctr, 2),
            "roi_percent": round(roi, 2),
        }

    @staticmethod
    def get_vertical_analytics(db: Session, client_id: str, vertical: str) -> dict:
        """Get analytics for a specific vertical"""
        images = db.query(Image).filter(
            Image.client_id == client_id,
            Image.vertical == vertical
        ).all()

        if not images:
            return {
                "vertical": vertical,
                "total_images": 0,
                "images": [],
            }

        image_ids = [img.id for img in images]
        performances = (
            db.query(PerformanceMetric)
            .filter(PerformanceMetric.image_id.in_(image_ids))
            .all()
        )

        total_cost = sum(img.cost_usd for img in images)
        total_clicks = sum(p.clicks for p in performances)
        total_conversions = sum(p.conversions for p in performances)
        total_revenue = sum(p.revenue_generated for p in performances)

        avg_ctr = (
            sum(p.ctr for p in performances if p.ctr) / len([p for p in performances if p.ctr])
            if any(p.ctr for p in performances)
            else 0
        )

        return {
            "vertical": vertical,
            "total_images": len(images),
            "total_cost": round(total_cost, 2),
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "total_revenue": round(total_revenue, 2),
            "average_ctr": round(avg_ctr, 2),
            "roi_percent": round(
                ((total_revenue - total_cost) / total_cost * 100) if total_cost > 0 else 0, 2
            ),
        }

    @staticmethod
    def get_top_templates(db: Session, client_id: str, limit: int = 5) -> list[dict]:
        """Get best performing templates for a client"""
        # Join images and templates, order by performance
        top_templates = (
            db.query(
                Template.id,
                Template.template_name,
                Template.vertical,
                func.count(Image.id).label("use_count"),
                func.avg(PerformanceMetric.ctr).label("avg_ctr"),
            )
            .join(Image, Template.id == Image.template_id)
            .outerjoin(PerformanceMetric, Image.id == PerformanceMetric.image_id)
            .filter(Image.client_id == client_id)
            .group_by(Template.id, Template.template_name, Template.vertical)
            .order_by(func.avg(PerformanceMetric.ctr).desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "template_id": t[0],
                "template_name": t[1],
                "vertical": t[2],
                "use_count": t[3],
                "average_ctr": round(t[4], 2) if t[4] else 0,
            }
            for t in top_templates
        ]

    @staticmethod
    def get_time_series_analytics(
        db: Session,
        client_id: str,
        days: int = 30,
    ) -> list[dict]:
        """Get analytics over time"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        daily_data = (
            db.query(
                func.date(Image.created_at).label("date"),
                func.count(Image.id).label("images_generated"),
                func.sum(Image.cost_usd).label("daily_cost"),
                func.sum(PerformanceMetric.revenue_generated).label("daily_revenue"),
            )
            .outerjoin(PerformanceMetric, Image.id == PerformanceMetric.image_id)
            .filter(
                Image.client_id == client_id,
                Image.created_at >= cutoff_date,
            )
            .group_by(func.date(Image.created_at))
            .order_by(func.date(Image.created_at))
            .all()
        )

        return [
            {
                "date": str(d[0]),
                "images_generated": d[1],
                "daily_cost": round(d[2] or 0, 2),
                "daily_revenue": round(d[3] or 0, 2),
            }
            for d in daily_data
        ]

    @staticmethod
    def get_billing_breakdown(db: Session, client_id: str) -> dict:
        """Get per-provider billing breakdown for a client"""
        base_query = db.query(Image).filter(Image.client_id == client_id)

        total_spent = base_query.with_entities(func.sum(Image.cost_usd)).scalar() or 0

        # By provider
        by_provider_rows = (
            base_query.with_entities(
                Image.generation_provider,
                func.count(Image.id),
                func.sum(Image.cost_usd),
            )
            .group_by(Image.generation_provider)
            .all()
        )
        by_provider = [
            {"provider": row[0] or "unknown", "count": row[1], "total_cost": round(row[2] or 0, 4)}
            for row in by_provider_rows
        ]

        # By vertical
        by_vertical_rows = (
            base_query.with_entities(
                Image.vertical,
                func.count(Image.id),
                func.sum(Image.cost_usd),
            )
            .group_by(Image.vertical)
            .all()
        )
        by_vertical = [
            {"vertical": row[0] or "unknown", "count": row[1], "total_cost": round(row[2] or 0, 4)}
            for row in by_vertical_rows
        ]

        # By model
        by_model_rows = (
            base_query.with_entities(
                Image.generation_model,
                func.count(Image.id),
                func.sum(Image.cost_usd),
            )
            .group_by(Image.generation_model)
            .all()
        )
        by_model = [
            {"model": row[0] or "unknown", "count": row[1], "total_cost": round(row[2] or 0, 4)}
            for row in by_model_rows
        ]

        # Recent generations (last 20)
        recent_rows = (
            base_query.order_by(Image.created_at.desc())
            .limit(20)
            .all()
        )
        recent_generations = [
            {
                "id": img.id,
                "provider": img.generation_provider,
                "model": img.generation_model,
                "cost": round(img.cost_usd or 0, 4),
                "vertical": img.vertical,
                "created_at": img.created_at.isoformat() if img.created_at else None,
            }
            for img in recent_rows
        ]

        # Daily spend (last 30 days)
        cutoff = datetime.utcnow() - timedelta(days=30)
        daily_rows = (
            db.query(
                func.date(Image.created_at).label("date"),
                func.sum(Image.cost_usd).label("daily_total"),
            )
            .filter(Image.client_id == client_id, Image.created_at >= cutoff)
            .group_by(func.date(Image.created_at))
            .order_by(func.date(Image.created_at))
            .all()
        )
        daily_spend = [
            {"date": str(row[0]), "total": round(row[1] or 0, 4)}
            for row in daily_rows
        ]

        return {
            "total_spent": round(total_spent, 4),
            "by_provider": by_provider,
            "by_vertical": by_vertical,
            "by_model": by_model,
            "recent_generations": recent_generations,
            "daily_spend": daily_spend,
        }

    @staticmethod
    def update_performance_metric(
        db: Session,
        image_id: str,
        impressions: int = 0,
        clicks: int = 0,
        conversions: int = 0,
        spend: float = 0,
        revenue: float = 0,
    ) -> PerformanceMetric:
        """Update performance metrics for an image"""
        metric = db.query(PerformanceMetric).filter(
            PerformanceMetric.image_id == image_id
        ).first()

        if not metric:
            image = db.query(Image).filter(Image.id == image_id).first()
            if not image:
                raise ValueError(f"Image {image_id} not found")

            metric = PerformanceMetric(
                id=f"perf_{image_id[:12]}",
                image_id=image_id,
                client_id=image.client_id,
            )

        metric.impressions = impressions
        metric.clicks = clicks
        metric.conversions = conversions
        metric.spend = spend
        metric.revenue_generated = revenue
        metric.calculate_metrics()

        db.add(metric)
        db.commit()
        db.refresh(metric)

        logger.info(f"Performance metrics updated for image {image_id}")
        return metric
