"""Stock footage routes — search Pexels free B-roll clips."""
import logging
from fastapi import APIRouter, Depends, Query
from ..schemas import APIResponse
from ..middleware.auth import get_current_user
from ..services.stock_footage import StockFootageService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/search")
async def search_stock(
    query: str = Query(...),
    orientation: str = Query(default="portrait"),
    duration_min: int = Query(default=3),
    duration_max: int = Query(default=15),
    per_page: int = Query(default=10, le=20),
    user=Depends(get_current_user),
):
    """Search Pexels for free stock B-roll footage."""
    clips = StockFootageService.search(
        query=query,
        orientation=orientation,
        duration_min=duration_min,
        duration_max=duration_max,
        per_page=per_page,
    )
    return APIResponse(
        success=True,
        message=f"Found {len(clips)} clips",
        data={"clips": clips, "query": query},
    )
