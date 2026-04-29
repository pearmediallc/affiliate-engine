from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .database import init_db
from .routes import create_router
from .services import VerticalTemplatesService
from .database import SessionLocal
from .middleware.audit import AuditLogMiddleware
import logging

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
