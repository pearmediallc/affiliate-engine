from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ImageGenerateRequest(BaseModel):
    """Request to generate images"""
    vertical: str = Field(default="home_insurance", description="Vertical category")
    template_id: str = Field(default=None, description="Template ID to use")
    state: Optional[str] = Field(default=None, description="Optional state targeting")
    additional_context: Optional[str] = Field(default=None, description="Additional context for prompt")
    count: int = Field(default=5, ge=1, le=20, description="Number of images to generate")
    use_gemma_variations: bool = Field(default=False, description="Generate variations using Gemini Vision to analyze reference image")
    reference_text: Optional[str] = Field(default=None, description="Reference text or base64 image data for Gemini Vision analysis")
    reference_image_base64: Optional[str] = Field(default=None, description="Base64 encoded image for Gemini Vision analysis")

    # Affiliate-specific
    use_affiliate_angles: bool = Field(default=True, description="Use affiliate marketing angles (pain point, benefit, etc.)")
    affiliate_angle: Optional[str] = Field(
        default="benefit",
        description="Affiliate angle: pain_point, benefit, social_proof, curiosity, urgency"
    )

    # Style options
    style: str = Field(
        default="professional_photography",
        description="Image style: professional_photography, modern_illustrated, ghibli, minimalist, cinematic, 3d_render, watercolor, anime"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "vertical": "home_insurance",
                "template_id": "home_insurance_family_safety",
                "state": "California",
                "additional_context": "Focus on young family, modern home",
                "count": 5
            }
        }


class ImageResponse(BaseModel):
    """Response for a single generated image"""
    id: str
    client_id: str
    vertical: str
    template_id: str
    prompt_used: str
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    generation_provider: str
    generation_model: Optional[str] = None
    cost_usd: float
    quality_score: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ImageListResponse(BaseModel):
    """List of images with pagination"""
    total: int
    page: int
    page_size: int
    images: List[ImageResponse]

    class Config:
        from_attributes = True
