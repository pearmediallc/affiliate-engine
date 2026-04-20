"""Ad Copy Generator - generates platform-formatted ad copy for Meta, TikTok, Google"""
import logging
from typing import Optional
from ..config import settings
from .knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class AdCopyGeneratorService:
    """Generates conversion-optimized ad copy for multiple platforms"""

    @staticmethod
    async def generate_ad_copy(
        product_name: str,
        product_description: str = "",
        angle: str = "benefit",
        target_audience: str = "",
        platforms: list = None,
        hook_text: str = "",
        transcript: str = "",
        vertical: str = "general",
        variations: int = 3,
    ) -> dict:
        """Generate ad copy formatted for specific ad platforms"""
        from google import genai

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        if not platforms:
            platforms = ["meta", "tiktok"]

        client = genai.Client(api_key=settings.gemini_api_key)

        # Get platform rules from knowledge base
        platform_rules = KnowledgeService.get_platform_rules()
        compliance = KnowledgeService.get_ftc_compliance()

        context = ""
        if hook_text:
            context += f"\nHOOK/ANGLE TO USE: {hook_text}"
        if transcript:
            context += f"\nVIDEO TRANSCRIPT TO BASE COPY ON: {transcript[:1000]}"

        prompt = f"""You are an expert performance marketer. Generate {variations} ad copy variations for each platform.

PRODUCT: {product_name}
DESCRIPTION: {product_description}
ANGLE: {angle}
TARGET AUDIENCE: {target_audience or 'General'}
VERTICAL: {vertical}
{context}

PLATFORM RULES:
{platform_rules[:1500] if platform_rules else 'Follow standard ad platform guidelines.'}

FTC COMPLIANCE:
{compliance[:500] if compliance else 'Include affiliate disclosure.'}

Generate ad copy for these platforms: {', '.join(platforms)}

FORMAT FOR EACH VARIATION:

For META (Facebook/Instagram):
- primary_text: max 125 characters, compelling, includes hook
- headline: max 40 characters, clear value prop
- description: max 30 characters, supporting text
- cta: "Learn More" / "Shop Now" / "Sign Up" / "Get Offer"

For TIKTOK:
- caption: max 150 characters, includes hashtags, casual tone
- cta_text: 2-3 words for the CTA button
- hashtags: 3-5 relevant hashtags

For GOOGLE:
- headline_1: max 30 characters
- headline_2: max 30 characters
- headline_3: max 30 characters
- description_1: max 90 characters
- description_2: max 90 characters

Return as JSON: {{"meta": [...], "tiktok": [...], "google": [...]}}
Only include platforms that were requested. Output ONLY valid JSON.
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        import json
        try:
            ad_copy = json.loads(text)
        except json.JSONDecodeError:
            ad_copy = {"error": "Failed to parse ad copy", "raw": text[:500]}

        return {
            "product": product_name,
            "angle": angle,
            "platforms": platforms,
            "variations": variations,
            "ad_copy": ad_copy,
        }
