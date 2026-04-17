from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application configuration - loaded from .env or environment variables"""

    # App
    app_name: str = "Affiliate Image Engine"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./affiliate_images.db"  # Default SQLite, override with DATABASE_URL env var for Postgres

    # Auth / JWT
    secret_key: str = "change-me-in-production-use-a-real-secret-key"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 1440  # 24 hours

    # API Keys
    gemini_api_key: Optional[str] = None  # Google Gemini API key
    openai_api_key: Optional[str] = None
    google_api_key: Optional[str] = None  # Google Cloud API key
    fal_api_key: Optional[str] = None  # FAL.ai API key for image generation
    deepgram_api_key: Optional[str] = None  # Deepgram API key for transcription

    # Image Generation
    image_provider: str = "gemini"  # Primary: Gemini 3.1 Flash Image, Fallback: OpenAI DALL-E 3, Then FAL.ai
    gemini_model: str = "gemini-2.5-flash"  # For prompt optimization and vision
    gemini_image_model: str = "imagen-4.0-generate-001"  # For image generation
    gemma_model: str = "gemma-4-26b-a4b-it"  # For fast prompt variations

    # Costs (in USD)
    image_generation_cost: float = 0.02
    gemini_prompt_cost: float = 0.0001

    # Verticals
    default_vertical: str = "home_insurance"

    # Image generation
    images_per_generation: int = 5
    default_image_width: int = 1200
    default_image_height: int = 628

    # API
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://localhost:8000", "https://app.yourdomain.com"]

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields from .env


settings = Settings()
