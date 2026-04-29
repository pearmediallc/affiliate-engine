"""Service for analytics and performance tracking.

Spend aggregation reads from BOTH Image.cost_usd (image gen) and Job.cost_usd
(everything else: Veo videos, lip-sync, TTS, transcription, long-video, ...).
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..models import Image, PerformanceMetric, Template
from ..models.job import Job
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _job_filter(query, *, user_id: Optional[str], client_id: Optional[str]):
    """Apply user/client scoping to a Job query.

    - When a real user_id is provided we filter to that user's jobs.
    - When only a sentinel client_id ('demo-client') is provided we don't
      filter, so the dashboard reflects all activity for the demo namespace.
    """
    if user_id:
        return query.filter(Job.user_id == user_id)
    return query


class AnalyticsService:
    """Service for tracking and analyzing image + job performance"""

    @staticmethod
    def get_client_analytics(db: Session, client_id: str, user_id: Optional[str] = None) -> dict:
        """Get overall analytics for a client/user."""
        total_images = db.query(Image).filter(Image.client_id == client_id).count()

        image_cost = db.query(func.coalesce(func.sum(Image.cost_usd), 0.0)).filter(
            Image.client_id == client_id
        ).scalar() or 0.0

        job_cost_q = db.query(func.coalesce(func.sum(Job.cost_usd), 0.0))
        job_cost = (_job_filter(job_cost_q, user_id=user_id, client_id=client_id).scalar()) or 0.0

        total_cost = float(image_cost) + float(job_cost)

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

        # Job-side counts (videos, TTS, etc.)
        job_count_q = db.query(func.count(Job.id))
        total_jobs = (_job_filter(job_count_q, user_id=user_id, client_id=client_id).scalar()) or 0

        return {
            "total_images": total_images,
            "total_jobs": int(total_jobs),
            "total_cost": round(total_cost, 4),
            "image_cost": round(float(image_cost), 4),
            "job_cost": round(float(job_cost), 4),
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "total_revenue": round(total_revenue, 2),
            "average_ctr": round(avg_ctr, 2),
            "roi_percent": round(roi, 2),
        }

    @staticmethod
    def get_vertical_analytics(db: Session, client_id: str, vertical: str, user_id: Optional[str] = None) -> dict:
        """Get analytics for a specific vertical."""
        images = db.query(Image).filter(
            Image.client_id == client_id,
            Image.vertical == vertical
        ).all()

        image_ids = [img.id for img in images]
        performances = (
            db.query(PerformanceMetric)
            .filter(PerformanceMetric.image_id.in_(image_ids))
            .all() if image_ids else []
        )

        image_cost = sum((img.cost_usd or 0.0) for img in images)

        job_cost_q = db.query(func.coalesce(func.sum(Job.cost_usd), 0.0)).filter(Job.vertical == vertical)
        job_cost = (_job_filter(job_cost_q, user_id=user_id, client_id=client_id).scalar()) or 0.0
        total_cost = float(image_cost) + float(job_cost)

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
            "total_cost": round(total_cost, 4),
            "image_cost": round(float(image_cost), 4),
            "job_cost": round(float(job_cost), 4),
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
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """Get analytics over time. Combines Image + Job spend per day."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        # Image side
        img_rows = (
            db.query(
                func.date(Image.created_at).label("date"),
                func.count(Image.id).label("img_count"),
                func.coalesce(func.sum(Image.cost_usd), 0.0).label("img_cost"),
                func.coalesce(func.sum(PerformanceMetric.revenue_generated), 0.0).label("revenue"),
            )
            .outerjoin(PerformanceMetric, Image.id == PerformanceMetric.image_id)
            .filter(
                Image.client_id == client_id,
                Image.created_at >= cutoff_date,
            )
            .group_by(func.date(Image.created_at))
            .all()
        )
        # Job side
        job_q = (
            db.query(
                func.date(Job.created_at).label("date"),
                func.count(Job.id).label("job_count"),
                func.coalesce(func.sum(Job.cost_usd), 0.0).label("job_cost"),
            )
            .filter(Job.created_at >= cutoff_date)
            .group_by(func.date(Job.created_at))
        )
        job_rows = _job_filter(job_q, user_id=user_id, client_id=client_id).all()

        per_day: dict = {}
        for r in img_rows:
            d = str(r[0])
            per_day.setdefault(d, {"images_generated": 0, "jobs": 0, "daily_cost": 0.0, "daily_revenue": 0.0})
            per_day[d]["images_generated"] += int(r[1] or 0)
            per_day[d]["daily_cost"] += float(r[2] or 0.0)
            per_day[d]["daily_revenue"] += float(r[3] or 0.0)
        for r in job_rows:
            d = str(r[0])
            per_day.setdefault(d, {"images_generated": 0, "jobs": 0, "daily_cost": 0.0, "daily_revenue": 0.0})
            per_day[d]["jobs"] += int(r[1] or 0)
            per_day[d]["daily_cost"] += float(r[2] or 0.0)

        return [
            {
                "date": d,
                "images_generated": v["images_generated"],
                "jobs": v["jobs"],
                "daily_cost": round(v["daily_cost"], 4),
                "daily_revenue": round(v["daily_revenue"], 2),
            }
            for d, v in sorted(per_day.items())
        ]

    @staticmethod
    def get_billing_breakdown(db: Session, client_id: str, user_id: Optional[str] = None) -> dict:
        """
        Per-provider / per-model billing breakdown — combines Image + Job costs.

        Image table provides image-gen breakdowns; Job table provides everything
        else (Veo, TTS, lip-sync, transcription, long-video).
        """
        # ----- Image side -----
        img_base = db.query(Image).filter(Image.client_id == client_id)

        image_total = img_base.with_entities(func.coalesce(func.sum(Image.cost_usd), 0.0)).scalar() or 0.0

        # By provider (image)
        by_provider: dict = {}
        for row in (
            img_base.with_entities(
                Image.generation_provider, func.count(Image.id), func.sum(Image.cost_usd)
            ).group_by(Image.generation_provider).all()
        ):
            key = row[0] or "unknown"
            by_provider[key] = by_provider.get(key, {"provider": key, "count": 0, "total_cost": 0.0})
            by_provider[key]["count"] += int(row[1] or 0)
            by_provider[key]["total_cost"] += float(row[2] or 0.0)

        # By vertical (image)
        by_vertical: dict = {}
        for row in (
            img_base.with_entities(
                Image.vertical, func.count(Image.id), func.sum(Image.cost_usd)
            ).group_by(Image.vertical).all()
        ):
            key = row[0] or "unknown"
            by_vertical[key] = by_vertical.get(key, {"vertical": key, "count": 0, "total_cost": 0.0})
            by_vertical[key]["count"] += int(row[1] or 0)
            by_vertical[key]["total_cost"] += float(row[2] or 0.0)

        # By model (image)
        by_model: dict = {}
        for row in (
            img_base.with_entities(
                Image.generation_model, func.count(Image.id), func.sum(Image.cost_usd)
            ).group_by(Image.generation_model).all()
        ):
            key = row[0] or "unknown"
            by_model[key] = by_model.get(key, {"model": key, "count": 0, "total_cost": 0.0})
            by_model[key]["count"] += int(row[1] or 0)
            by_model[key]["total_cost"] += float(row[2] or 0.0)

        # ----- Job side -----
        job_base = db.query(Job)
        job_base = _job_filter(job_base, user_id=user_id, client_id=client_id)

        job_total = job_base.with_entities(func.coalesce(func.sum(Job.cost_usd), 0.0)).scalar() or 0.0

        for row in (
            job_base.with_entities(
                Job.provider, func.count(Job.id), func.sum(Job.cost_usd)
            ).group_by(Job.provider).all()
        ):
            key = row[0] or "unknown"
            by_provider[key] = by_provider.get(key, {"provider": key, "count": 0, "total_cost": 0.0})
            by_provider[key]["count"] += int(row[1] or 0)
            by_provider[key]["total_cost"] += float(row[2] or 0.0)

        for row in (
            job_base.with_entities(
                Job.vertical, func.count(Job.id), func.sum(Job.cost_usd)
            ).group_by(Job.vertical).all()
        ):
            key = row[0] or "unknown"
            by_vertical[key] = by_vertical.get(key, {"vertical": key, "count": 0, "total_cost": 0.0})
            by_vertical[key]["count"] += int(row[1] or 0)
            by_vertical[key]["total_cost"] += float(row[2] or 0.0)

        # Job table doesn't carry generation_model — bucket by job_type instead.
        for row in (
            job_base.with_entities(
                Job.job_type, func.count(Job.id), func.sum(Job.cost_usd)
            ).group_by(Job.job_type).all()
        ):
            key = row[0] or "unknown"
            by_model[key] = by_model.get(key, {"model": key, "count": 0, "total_cost": 0.0})
            by_model[key]["count"] += int(row[1] or 0)
            by_model[key]["total_cost"] += float(row[2] or 0.0)

        # Round all totals
        for m in by_provider.values():
            m["total_cost"] = round(m["total_cost"], 4)
        for m in by_vertical.values():
            m["total_cost"] = round(m["total_cost"], 4)
        for m in by_model.values():
            m["total_cost"] = round(m["total_cost"], 4)

        # Recent generations: combine image + job, newest first
        recent: list[dict] = []
        for img in img_base.order_by(Image.created_at.desc()).limit(20).all():
            recent.append({
                "id": img.id,
                "kind": "image",
                "provider": img.generation_provider,
                "model": img.generation_model,
                "cost": round(img.cost_usd or 0.0, 4),
                "vertical": img.vertical,
                "created_at": img.created_at.isoformat() if img.created_at else None,
            })
        for job in job_base.order_by(Job.created_at.desc()).limit(20).all():
            recent.append({
                "id": job.id,
                "kind": job.job_type,
                "provider": job.provider,
                "model": job.job_type,
                "cost": round(job.cost_usd or 0.0, 4),
                "vertical": job.vertical,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            })
        recent.sort(key=lambda r: r["created_at"] or "", reverse=True)
        recent = recent[:20]

        # Daily spend (last 30 days, image + job)
        cutoff = datetime.utcnow() - timedelta(days=30)
        daily: dict = {}
        for r in (
            db.query(func.date(Image.created_at), func.coalesce(func.sum(Image.cost_usd), 0.0))
            .filter(Image.client_id == client_id, Image.created_at >= cutoff)
            .group_by(func.date(Image.created_at)).all()
        ):
            daily[str(r[0])] = daily.get(str(r[0]), 0.0) + float(r[1] or 0.0)
        job_daily_q = (
            db.query(func.date(Job.created_at), func.coalesce(func.sum(Job.cost_usd), 0.0))
            .filter(Job.created_at >= cutoff)
            .group_by(func.date(Job.created_at))
        )
        for r in _job_filter(job_daily_q, user_id=user_id, client_id=client_id).all():
            daily[str(r[0])] = daily.get(str(r[0]), 0.0) + float(r[1] or 0.0)

        daily_spend = [{"date": d, "total": round(t, 4)} for d, t in sorted(daily.items())]

        total_spent = float(image_total) + float(job_total)
        return {
            "total_spent": round(total_spent, 4),
            "image_total": round(float(image_total), 4),
            "job_total": round(float(job_total), 4),
            "by_provider": list(by_provider.values()),
            "by_vertical": list(by_vertical.values()),
            "by_model": list(by_model.values()),
            "recent_generations": recent,
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
