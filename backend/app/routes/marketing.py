"""Marketing routes - offer angles, ad copy, landing pages"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import APIResponse
from ..middleware.auth import get_optional_user, log_usage
from ..services.offer_engine import OfferEngineService
from ..services.ad_copy_generator import AdCopyGeneratorService
from ..services.landing_page import LandingPageService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class AngleRequest(BaseModel):
    product_name: str
    product_description: str = ""
    target_audience: str = ""
    vertical: str = "general"
    product_url: str = ""

class AdCopyRequest(BaseModel):
    product_name: str
    product_description: str = ""
    angle: str = "benefit"
    target_audience: str = ""
    platforms: List[str] = ["meta", "tiktok"]
    hook_text: str = ""
    transcript: str = ""
    vertical: str = "general"
    variations: int = 3

class LandingPageRequest(BaseModel):
    vertical: str = "home_insurance"
    product_name: str = ""
    product_description: str = ""
    transcript: str = ""  # The ad creative transcript the user is running
    offer_url: str = ""   # The actual offer/product page URL
    target_audience: str = ""
    commission: str = ""
    bonuses: List[str] = []
    page_type: str = "single"

class LPAnalyzeRequest(BaseModel):
    lp_url: str = ""
    lp_html: str = ""
    spend: float = 0
    lp_views: int = 0
    lp_clicks: int = 0
    conversions: int = 0
    revenue: float = 0


@router.post("/angles/generate")
async def generate_angles(request: AngleRequest, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    try:
        result = await OfferEngineService.generate_angles(
            product_name=request.product_name,
            product_description=request.product_description,
            target_audience=request.target_audience,
            vertical=request.vertical,
            product_url=request.product_url,
        )
        if user:
            log_usage("angle_generation", user.id, db, cost_usd=0.01)
            try:
                from ..services.job_service import JobService
                JobService.save_sync_result(
                    db=db, user_id=user.id, job_type="angle_generation",
                    input_data={"product_name": request.product_name, "target_audience": request.target_audience},
                    result_data=result, vertical=request.vertical, provider="gemini",
                )
            except Exception:
                pass
        return APIResponse(success=True, message=f"Generated {len(result.get('angles', []))} angles", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/angles/frameworks")
async def get_frameworks():
    return APIResponse(success=True, message="Frameworks", data={"frameworks": OfferEngineService.get_frameworks()})


@router.post("/ad-copy/generate")
async def generate_ad_copy(request: AdCopyRequest, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    try:
        result = await AdCopyGeneratorService.generate_ad_copy(
            product_name=request.product_name,
            product_description=request.product_description,
            angle=request.angle,
            target_audience=request.target_audience,
            platforms=request.platforms,
            hook_text=request.hook_text,
            transcript=request.transcript,
            vertical=request.vertical,
            variations=request.variations,
        )
        if user:
            log_usage("ad_copy_generation", user.id, db, cost_usd=0.01)
            try:
                from ..services.job_service import JobService
                JobService.save_sync_result(
                    db=db, user_id=user.id, job_type="ad_copy",
                    input_data={"product_name": request.product_name, "angle": request.angle, "platforms": request.platforms},
                    result_data=result, vertical=request.vertical, provider="gemini",
                )
            except Exception:
                pass
        return APIResponse(success=True, message="Ad copy generated", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/landing-page/generate")
async def generate_landing_page(request: LandingPageRequest, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    try:
        result = await LandingPageService.generate_landing_page(
            vertical=request.vertical,
            transcript=request.transcript,
            offer_url=request.offer_url,
            target_audience=request.target_audience,
            bonuses=request.bonuses,
            product_name=request.product_name,
            product_description=request.product_description,
            commission=request.commission,
            page_type=request.page_type,
        )
        if user:
            log_usage("landing_page_generation", user.id, db, cost_usd=0.02)
            try:
                from ..services.job_service import JobService
                JobService.save_sync_result(
                    db=db, user_id=user.id, job_type="landing_page",
                    input_data={"product_name": request.product_name, "vertical": request.vertical, "page_type": request.page_type},
                    result_data=result, vertical=request.vertical, provider="gemini", cost_usd=0.02,
                )
            except Exception:
                pass
        return APIResponse(success=True, message="Landing page generated", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/landing-page/analyze")
async def analyze_landing_page(request: LPAnalyzeRequest, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    try:
        metrics = None
        if request.spend > 0 or request.lp_views > 0:
            metrics = {
                "spend": request.spend,
                "lp_views": request.lp_views,
                "lp_clicks": request.lp_clicks,
                "conversions": request.conversions,
                "revenue": request.revenue,
            }
        result = await LandingPageService.analyze_landing_page(
            lp_url=request.lp_url,
            lp_html=request.lp_html,
            metrics=metrics,
        )
        if user:
            log_usage("lp_analysis", user.id, db, cost_usd=0.01)
            try:
                from ..services.job_service import JobService
                JobService.save_sync_result(
                    db=db, user_id=user.id, job_type="lp_analysis",
                    input_data={"lp_url": request.lp_url},
                    result_data=result, provider="gemini",
                )
            except Exception:
                pass
        return APIResponse(success=True, message="Landing page analyzed", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
