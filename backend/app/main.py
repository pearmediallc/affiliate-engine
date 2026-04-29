from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .config import settings
from .database import init_db
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

    # Initialize default templates
    db = SessionLocal()
    try:
        VerticalTemplatesService.initialize_default_templates(db)
        logger.info("Default templates initialized")
    finally:
        db.close()


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
