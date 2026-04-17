from fastapi import APIRouter
from . import health, templates, images, analytics, speech, scripts, video_analysis, transcription, video_download, feedback, auth, admin

def create_router() -> APIRouter:
    """Create API router with all routes"""
    router = APIRouter()

    # Include routers
    router.include_router(health.router, prefix="/health", tags=["health"])
    router.include_router(templates.router, prefix="/templates", tags=["templates"])
    router.include_router(images.router, prefix="/images", tags=["images"])
    router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
    router.include_router(speech.router, prefix="/speech", tags=["speech"])
    router.include_router(scripts.router, prefix="/scripts", tags=["scripts"])
    router.include_router(video_analysis.router, prefix="/video-analysis", tags=["video-analysis"])
    router.include_router(transcription.router, prefix="/transcription", tags=["transcription"])
    router.include_router(video_download.router, prefix="/video-download", tags=["video-download"])
    router.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
    router.include_router(auth.router, prefix="/auth", tags=["auth"])
    router.include_router(admin.router, prefix="/admin", tags=["admin"])

    return router
