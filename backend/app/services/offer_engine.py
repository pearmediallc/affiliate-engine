"""Offer + Angle Generator - generates 10 unique marketing angles for any product"""
import logging
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)

ANGLE_FRAMEWORKS = [
    {"id": "fear", "name": "Fear-Based", "hook": "What you're losing by NOT using this", "trigger": "loss aversion, FOMO"},
    {"id": "curiosity", "name": "Curiosity Gap", "hook": "The hidden method nobody talks about", "trigger": "information gap, intrigue"},
    {"id": "authority", "name": "Authority", "hook": "Experts recommend this approach", "trigger": "credibility, trust, social proof from experts"},
    {"id": "contrarian", "name": "Contrarian", "hook": "Everything you've been told is wrong", "trigger": "pattern interrupt, challenges beliefs"},
    {"id": "social_proof", "name": "Social Proof", "hook": "Join 10,000+ people who already switched", "trigger": "herd mentality, belonging"},
    {"id": "urgency", "name": "Urgency", "hook": "This won't last — prices going up", "trigger": "scarcity, time pressure"},
    {"id": "aspiration", "name": "Aspiration", "hook": "Imagine your life after this change", "trigger": "dream outcome, future pacing"},
    {"id": "pain_agitate", "name": "Pain + Agitate", "hook": "Your current solution is costing you more than you think", "trigger": "problem awareness, frustration amplification"},
    {"id": "transformation", "name": "Before/After", "hook": "From struggling to thriving in 30 days", "trigger": "proof of change, relatability"},
    {"id": "hidden_secret", "name": "Hidden Secret", "hook": "The industry doesn't want you to know this", "trigger": "insider knowledge, exclusivity"},
]


class OfferEngineService:
    """Generates marketing angles and offer frameworks for affiliate products"""

    @staticmethod
    async def generate_angles(
        product_name: str,
        product_description: str = "",
        target_audience: str = "",
        vertical: str = "general",
        product_url: str = "",
    ) -> dict:
        """Generate 10 unique marketing angles for a product using Gemini"""
        from google import genai

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        client = genai.Client(api_key=settings.gemini_api_key)

        frameworks_text = "\n".join([
            f"- {f['id']}: {f['name']} — Hook: \"{f['hook']}\" — Trigger: {f['trigger']}"
            for f in ANGLE_FRAMEWORKS
        ])

        prompt = f"""You are an expert affiliate marketing strategist. Generate 10 unique marketing angles for this product.

PRODUCT: {product_name}
DESCRIPTION: {product_description or 'Not provided'}
TARGET AUDIENCE: {target_audience or 'General consumers'}
VERTICAL: {vertical}
URL: {product_url or 'Not provided'}

ANGLE FRAMEWORKS TO USE (one per angle):
{frameworks_text}

For EACH of the 10 angles, provide:
1. angle_id: the framework ID from above
2. angle_name: the framework name
3. headline: a compelling ad headline (under 60 chars)
4. hook_line: the opening hook for a video/post (under 100 chars)
5. primary_text: ad primary text for Meta (under 125 chars)
6. emotional_trigger: the specific psychological trigger being used
7. target_segment: who this angle resonates with most
8. recommended_visual: what the ad image should show
9. recommended_style: image generation style (professional_photography/cinematic/modern_illustrated)
10. cta: call-to-action text

Return as a JSON array of 10 objects. Output ONLY valid JSON, no markdown.
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
            angles = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: return framework-based angles without AI
            angles = [
                {
                    "angle_id": f["id"],
                    "angle_name": f["name"],
                    "headline": f"{product_name}: {f['hook'][:40]}",
                    "hook_line": f["hook"],
                    "primary_text": f["hook"],
                    "emotional_trigger": f["trigger"],
                    "target_segment": target_audience or "General",
                    "recommended_visual": "Product in use",
                    "recommended_style": "professional_photography",
                    "cta": "Learn More",
                }
                for f in ANGLE_FRAMEWORKS
            ]

        return {
            "product": product_name,
            "vertical": vertical,
            "angles": angles,
            "frameworks": ANGLE_FRAMEWORKS,
        }

    @staticmethod
    def get_frameworks() -> list:
        return ANGLE_FRAMEWORKS
