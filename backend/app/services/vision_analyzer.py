"""Service for analyzing reference images using Gemini Vision"""
import google.generativeai as genai
from ..config import settings
import logging
import base64
from typing import Optional

logger = logging.getLogger(__name__)


class VisionAnalyzerService:
    """Uses Gemini Vision to analyze reference images and generate variations"""

    def __init__(self):
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            # Use latest Gemini model with vision capabilities
            self.vision_model = genai.GenerativeModel("gemini-2.5-flash")
        else:
            logger.warning("Gemini API key not configured. Vision analysis unavailable.")
            self.vision_model = None

    def analyze_reference_image(
        self,
        image_base64: str,
        vertical: str,
        analysis_type: str = "style"
    ) -> str:
        """
        Analyze a reference image using Gemini Vision

        Args:
            image_base64: Base64 encoded image data
            vertical: Vertical category (e.g., "home_insurance")
            analysis_type: Type of analysis (style, composition, mood, conversion_elements)

        Returns:
            Detailed analysis of the image
        """
        if not self.vision_model:
            logger.warning("Vision model not available")
            return ""

        try:
            # Create analysis prompt based on type
            if analysis_type == "style":
                analysis_prompt = f"""Analyze this {vertical} advertisement image and describe:

1. VISUAL STYLE:
   - Photography style (realistic, illustrated, cinematic, minimalist, etc.)
   - Color palette (dominant colors, mood)
   - Lighting (natural, dramatic, soft, bright, etc.)
   - Composition (rule of thirds, symmetry, leading lines)

2. ELEMENTS:
   - Main subjects and their positioning
   - Background elements
   - Any text, CTAs, or overlays visible

3. EMOTIONAL TONE:
   - What emotion does this image convey?
   - What makes it effective/ineffective for {vertical}?

4. AD CREATIVE CHARACTERISTICS:
   - Is this a professional ad or stock photo?
   - What conversion elements are present?
   - How could variations improve conversion?

Provide detailed, actionable insights for creating similar variations."""

            else:  # composition
                analysis_prompt = f"""Analyze the composition and layout of this {vertical} ad image:

1. LAYOUT STRUCTURE:
   - How is the image divided?
   - Where are the focal points?
   - How is space used?

2. VISUAL HIERARCHY:
   - What draws attention first?
   - How do elements guide the eye?
   - Where should a CTA be placed?

3. TECHNICAL ASPECTS:
   - Aspect ratio and framing
   - Depth of field and focus areas
   - Scale and proportions

4. ADAPTATION FOR VARIATIONS:
   - What elements could be varied?
   - What should remain consistent?
   - How to create 5 distinct but cohesive variations?"""

            try:
                # Try with base64 string directly (Gemini may handle it)
                response = self.vision_model.generate_content([
                    f"data:image/png;base64,{image_base64}",
                    analysis_prompt
                ])
                analysis = response.text.strip()
                logger.info(f"Image analyzed successfully using Gemini Vision")
                return analysis
            except Exception as vision_e:
                # Fallback: if image analysis fails, return a generic prompt
                logger.warning(f"Gemini Vision image analysis failed: {str(vision_e)}, using generic analysis")
                return f"Unable to analyze image directly. Using generic {vertical} ad analysis framework."

        except Exception as e:
            logger.error(f"Error analyzing image with Gemini Vision: {str(e)}")
            # Don't raise - let it fall back to text-based variations
            return ""

    def generate_variations_from_image(
        self,
        image_base64: str,
        vertical: str,
        count: int = 5
    ) -> list[str]:
        """
        Analyze a reference image and generate prompt variations

        Args:
            image_base64: Base64 encoded reference image
            vertical: Vertical category
            count: Number of variations to generate

        Returns:
            List of image generation prompts based on the reference
        """
        if not self.vision_model:
            logger.warning("Vision model not available")
            return []

        try:
            # First, analyze the image
            analysis = self.analyze_reference_image(
                image_base64=image_base64,
                vertical=vertical,
                analysis_type="style"
            )

            # Then generate variations based on analysis
            variation_prompt = f"""Based on this analysis of a reference image:

{analysis}

Generate {count} DIFFERENT image generation prompts for {vertical} ads that:
1. Maintain the core style and visual appeal of the reference
2. Vary the composition, subjects, or specific elements
3. Are suitable for FAL.ai FLUX image generation
4. Include specific visual details (colors, lighting, composition)
5. Emphasize different aspects of the reference (composition, mood, style, etc.)

REQUIREMENTS FOR EACH PROMPT:
- 200-300 words, descriptive and specific
- Include visual composition details (lighting, colors, mood)
- Specify image format: 1200x628px landscape ad format
- Professional, high-quality ad creative style
- Detailed text overlay specifications if applicable
- Each should be distinct but thematically coherent

FORMAT: Return exactly {count} prompts separated by "---SEPARATOR---"
Start each with "PROMPT [number]:" then the full prompt text.

Generate the variations now:"""

            try:
                # Try with image and prompt
                response = self.vision_model.generate_content([
                    f"data:image/png;base64,{image_base64}",
                    variation_prompt
                ])
                text = response.text.strip()
            except Exception as vision_e:
                logger.warning(f"Gemini Vision variation generation failed: {str(vision_e)}, falling back to text-based")
                # Fallback: generate variations based on analysis only
                from .prompt_optimizer import PromptOptimizerService
                prompt_optimizer = PromptOptimizerService()
                return prompt_optimizer.generate_variations_from_reference(
                    reference_text=analysis or "Professional ad creative",
                    vertical=vertical,
                    count=count
                )

            # Parse the variations
            variations = []
            for section in text.split("---SEPARATOR---"):
                section = section.strip()
                if section:
                    # Remove "PROMPT X:" prefix if present
                    if section.startswith("PROMPT"):
                        section = section.split(":", 1)[1].strip() if ":" in section else section
                    if section:
                        variations.append(section)

            logger.info(f"Generated {len(variations)} variations from reference image using Gemini Vision")
            return variations[:count] if variations else []

        except Exception as e:
            logger.error(f"Error generating variations from image: {str(e)}")
            # Fallback to text-based variations
            try:
                from .prompt_optimizer import PromptOptimizerService
                prompt_optimizer = PromptOptimizerService()
                return prompt_optimizer.generate_variations_from_reference(
                    reference_text="Professional ad creative with conversion focus",
                    vertical=vertical,
                    count=count
                )
            except Exception as fallback_e:
                logger.error(f"Even fallback failed: {str(fallback_e)}")
                return []
