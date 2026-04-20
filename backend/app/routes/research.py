"""Research + Performance routes - affiliate search, hooks, metrics"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_optional_user, get_current_user, log_usage
from ..services.affiliate_search import AffiliateSearchService
from ..services.hook_library import HookLibraryService
from ..services.performance_tracker import PerformanceTrackerService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Affiliate Program Search ---

@router.get("/affiliate-search")
async def search_affiliate_programs(
    q: str = Query(default="", description="Search query"),
    reward_type: str = Query(default="", description="cps_recurring, cps_one_time, cpl, cpc"),
    tags: str = Query(default="", description="Comma-separated tags"),
    min_cookie_days: int = Query(default=0),
    sort: str = Query(default="trending", description="trending, new, top"),
    limit: int = Query(default=20, ge=1, le=30),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    try:
        result = AffiliateSearchService.search_programs(
            query=q, reward_type=reward_type, tags=tags,
            min_cookie_days=min_cookie_days, sort=sort, limit=limit,
        )
        if user:
            log_usage("affiliate_search", user.id, db)
        return APIResponse(success=True, message=f"Found {result['total']} programs", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/affiliate-search/reward-types")
async def get_reward_types():
    return APIResponse(success=True, message="Reward types", data={"types": AffiliateSearchService.get_reward_types()})


# --- Hook Library ---

@router.get("/hooks")
async def get_hooks(
    vertical: str = Query(default=""),
    platform: str = Query(default=""),
    limit: int = Query(default=20),
    db: Session = Depends(get_db),
):
    hooks = HookLibraryService.get_top_hooks(db, vertical=vertical or None, platform=platform or None, limit=limit)
    return APIResponse(success=True, message=f"Found {len(hooks)} hooks", data={"hooks": hooks})


@router.post("/hooks/add")
async def add_hook(
    hook_text: str,
    vertical: str,
    platform: str = "unknown",
    emotional_trigger: str = "",
    effectiveness_score: float = 5.0,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    rid = HookLibraryService.extract_and_store(
        db=db, hook_text=hook_text, vertical=vertical,
        source="manual", effectiveness_score=effectiveness_score,
        platform=platform, emotional_trigger=emotional_trigger,
    )
    return APIResponse(success=True, message="Hook stored", data={"id": rid})


# --- Performance Metrics ---

class CampaignMetricsRequest(BaseModel):
    campaign_name: str
    vertical: str = "general"
    creative_ids: List[str] = []
    spend: float = 0
    impressions: int = 0
    clicks: int = 0
    lp_views: int = 0
    conversions: int = 0
    revenue: float = 0


@router.post("/performance/record")
async def record_performance(
    request: CampaignMetricsRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = PerformanceTrackerService.record_campaign_metrics(
            db=db,
            user_id=user.id,
            campaign_name=request.campaign_name,
            vertical=request.vertical,
            creative_ids=request.creative_ids,
            metrics={
                "spend": request.spend,
                "impressions": request.impressions,
                "clicks": request.clicks,
                "lp_views": request.lp_views,
                "conversions": request.conversions,
                "revenue": request.revenue,
            },
        )
        return APIResponse(success=True, message=f"Campaign metrics recorded (ROAS: {result['calculated_kpis']['roas']}x)", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/history")
async def get_performance_history(
    vertical: str = Query(default=""),
    limit: int = Query(default=20),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    history = PerformanceTrackerService.get_campaign_history(
        db=db, user_id=user.id, vertical=vertical or None, limit=limit,
    )
    return APIResponse(success=True, message=f"Found {len(history)} campaigns", data={"campaigns": history})
