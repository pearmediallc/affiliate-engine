from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .config import settings
from .database import init_db
from .migrations import run_migrations
from .routes import create_router
from .services import VerticalTemplatesService
from .database import SessionLocal
from .middleware.audit import AuditLogMiddleware
import logging
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Affiliate Marketing Image Generation Engine",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Audit log middleware — must be added BEFORE CORS so it sees the response status
app.add_middleware(AuditLogMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.cors_allow_all else settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler — guarantees CORS headers on 500 responses too.
# Without this, an unhandled exception bubbles past CORSMiddleware and the
# browser sees a CORS error instead of the real 500. We attach Allow-Origin
# explicitly here so error responses still pass the browser's CORS check.
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    origin = request.headers.get("origin", "")
    headers = {}
    # Reflect the request origin if cors_allow_all is on, OR if origin is in the allowlist.
    if origin and (settings.cors_allow_all or origin in settings.cors_origins):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": exc.__class__.__name__},
        headers=headers,
    )


@app.on_event("startup")
async def startup_event():
    """Initialize database and load default data on startup"""
    logger.info("Initializing database...")
    init_db()
    run_migrations()

    # Initialize default templates
    db = SessionLocal()
    try:
        VerticalTemplatesService.initialize_default_templates(db)
        logger.info("Default templates initialized")
    finally:
        db.close()

    # Recover any lip-sync renders that were mid-flight when we last restarted (no orphaned jobs)
    try:
        import asyncio
        from .routes.regen import resume_pending_lipsync
        asyncio.create_task(resume_pending_lipsync())
    except Exception as e:
        logger.warning(f"lip-sync resume hook failed to start: {e}")

    # Nightly learning heartbeat — OFF unless LEARN_NIGHTLY=true. Safe to run unattended: the
    # holdout gate + admin-approval gate mean nightly tuning only ever creates PROPOSALS, never
    # changes the engine. Minimal asyncio loop (no new dependency), mirrors the resume hook above.
    try:
        import os
        if str(os.getenv("LEARN_NIGHTLY", "")).lower() in ("1", "true", "yes"):
            import asyncio
            asyncio.create_task(_nightly_learning_loop())
            logger.info("nightly learning heartbeat enabled (LEARN_NIGHTLY)")
    except Exception as e:
        logger.warning(f"nightly learning heartbeat failed to start: {e}")


async def _nightly_learning_loop():
    """Run creative_tuner.run_all() once per LEARN_NIGHTLY_INTERVAL_SEC (default 24h). Never raises
    out of the loop — only ever produces RuleProposals (pending_admin), so it can run unattended."""
    import asyncio, os
    interval = int(os.getenv("LEARN_NIGHTLY_INTERVAL_SEC", str(24 * 3600)))
    while True:
        try:
            await asyncio.sleep(interval)
            from .services import creative_tuner as ctun
            db = SessionLocal()
            try:
                results = ctun.run_all(db)
                logger.info(f"[nightly-learn] ran {len(results)} brain tuners")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[nightly-learn] cycle failed: {e}")


# Include all routes under /api/v1
api_router = create_router()
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
