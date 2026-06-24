from fastapi import APIRouter
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from . import (
    health, templates, images, analytics, speech, scripts, video_analysis,
    transcription, video_download, feedback, auth, admin, tiktok, lip_sync,
    video_creation, video_enhance, marketing, research, jobs, audit,
    campaigns, characters, scene_settings, variations, music, stock, video_edit,
    harness, regen,
)

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "uploads",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)


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

    # Campaign pipeline
    router.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
    router.include_router(characters.router, prefix="/characters", tags=["characters"])
    router.include_router(scene_settings.router, prefix="/scene-settings", tags=["scene-settings"])
    router.include_router(variations.router, prefix="/variations", tags=["variations"])
    router.include_router(music.router, prefix="/music", tags=["music"])
    router.include_router(stock.router, prefix="/stock", tags=["stock"])
    router.include_router(video_edit.router, prefix="/video-edit", tags=["video-edit"])
    router.include_router(harness.router, prefix="/harness", tags=["harness"])
    router.include_router(regen.router, prefix="/regen", tags=["regen"])

    # Serve uploaded reference files (portraits, setting images)
    @router.get("/uploads/{filename}")
    async def serve_upload(filename: str):
        path = os.path.join(UPLOAD_DIR, filename)
        if not os.path.isfile(path):
            from fastapi import HTTPException
            raise HTTPException(404, detail="File not found")
        return FileResponse(path)

    return router
