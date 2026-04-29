from fastapi import APIRouter
from . import health, templates, images, analytics, speech, scripts, video_analysis, transcription, video_download, feedback, auth, admin, tiktok, lip_sync, video_creation, video_enhance, marketing, research, jobs, audit

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
    # Admin tools — mount audit-log endpoints under /admin alongside the main admin router
    router.include_router(admin.router, prefix="/admin", tags=["admin"])
    router.include_router(audit.router, prefix="/admin", tags=["admin-audit"])
    # Public-side audit endpoint (POST /audit/track-screen) for the frontend page tracker
    router.include_router(audit.router, prefix="/audit", tags=["audit"])
    router.include_router(tiktok.router, prefix="/tiktok", tags=["tiktok"])
    router.include_router(lip_sync.router, prefix="/lip-sync", tags=["lip-sync"])
    router.include_router(video_creation.router, prefix="/video", tags=["video-creation"])
    router.include_router(video_enhance.router, prefix="/video-enhance", tags=["video-enhance"])
    router.include_router(marketing.router, prefix="/marketing", tags=["marketing"])
    router.include_router(research.router, prefix="/research", tags=["research"])
    router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])

    return router
