from fastapi import APIRouter
from ..schemas import APIResponse

router = APIRouter()


@router.get("")
async def health_check() -> APIResponse:
    """Health check endpoint"""
    return APIResponse(
        success=True,
        message="Service is healthy",
        data={"status": "ok"}
    )
