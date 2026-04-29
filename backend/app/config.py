from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


# The literal default string we used to ship as a fallback. Anyone who copies
# this back into config or paste it into env "to make it work" needs to be
# loudly stopped — that's how the production breach happens.
_LEGACY_INSECURE_KEY = "change-me-in-production-use-a-real-secret-key"


class Settings(BaseSettings):
    """Application configuration - loaded from .env or environment variables"""

    # App
    app_name: str = "Affiliate Image Engine"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./affiliate_images.db"  # Default SQLite, override with DATABASE_URL env var for Postgres

    # Auth / JWT.
    # SECRET_KEY is REQUIRED in env. There is no fallback default — that's the
    # whole point of a secret. Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(64))"
    # Use DIFFERENT keys per environment (dev != staging != prod).
    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 1440  # 24 hours

    @field_validator("secret_key")
    @classmethod
    def _secret_key_strong_enough(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "SECRET_KEY env var is required. Generate one with "
                "`python -c 'import secrets; print(secrets.token_urlsafe(64))'` "
                "and add it to your .env (or Render env vars in production)."
            )
        if v.strip() == _LEGACY_INSECURE_KEY:
            raise ValueError(
                "SECRET_KEY is set to the legacy public placeholder string — "
                "this key is in the GitHub repo and anyone can forge JWTs. "
                "Generate a fresh one immediately."
            )
        if len(v) < 32:
            raise ValueError(
                f"SECRET_KEY is too short ({len(v)} chars). Use at least 32 chars; "
                "we recommend 64 from secrets.token_urlsafe(64)."
            )
        return v

    # API Keys
    gemini_api_key: Optional[str] = None  # Google Gemini API key
    openai_api_key: Optional[str] = None
    google_api_key: Optional[str] = None  # Google Cloud API key
    fal_api_key: Optional[str] = None  # FAL.ai API key for image generation
    ideogram_api_key: Optional[str] = None  # Ideogram API key for text-heavy image generation
    deepgram_api_key: Optional[str] = None  # Deepgram API key for transcription
    tiktok_access_token: Optional[str] = None
    tiktok_advertiser_id: Optional[str] = None
    replicate_api_token: Optional[str] = None  # Replicate API for lip-sync, upscaling, etc.

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
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://localhost:8000"]
    cors_allow_all: bool = True  # In production, set CORS_ORIGINS env var and set this to False

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields from .env


settings = Settings()
