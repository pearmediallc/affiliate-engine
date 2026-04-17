"""Service for analyzing winning images and extracting template patterns"""
import logging
import base64
from typing import Optional
import google.generativeai as genai
from ..config import settings

logger = logging.getLogger(__name__)


class TemplateAnalyzerService:
    """Analyzes winning images to extract ad patterns and create templates"""

    def __init__(self):
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            self.model = genai.GenerativeModel("gemini-2.5-flash")
        else:
            self.model = None
            logger.warning("Gemini not configured for template analysis")

    async def analyze_winning_image(self, image_base64: str) -> dict:
        """
        Analyze a winning image to extract ad patterns

        Args:
            image_base64: Base64 encoded image data

        Returns:
            Dictionary with extracted patterns and template suggestions
        """
        if not self.model:
            raise ValueError("Gemini not configured")

        try:
            analysis_prompt = """Analyze this winning affiliate ad image and extract:

1. VISUAL ELEMENTS:
   - Background type (real photo, person, product, etc.)
   - Color scheme (main colors used)
   - Typography style (font sizes, weights, colors)
   - Layout (text placement, button positions)

2. TEXT CONTENT:
   - Headline (main message)
   - Subheading (supporting text)
   - CTA text (button or action text)
   - Any trust badges/seals visible

3. CONVERSION ELEMENTS:
   - Target audience (who is this for?)
   - Emotional trigger (urgency, curiosity, fear, benefit?)
   - Action buttons (colors, text, placement)
   - Trust signals (badges, guarantees, social proof)

4. AFFILIATE INDICATORS:
   - Vertical/industry (insurance, health, finance, etc.)
   - Geographic targeting (state names, cities)
   - Demographic targeting (age, lifestyle)
   - Angle used (pain point, benefit, social proof, curiosity, urgency)

5. TEMPLATE SUGGESTION:
   Suggest a reusable template based on this design with:
   - Variable elements (headline, subheading, CTA)
   - Fixed elements (layout, colors, styling)
   - Customization options (audience, urgency, angle)

Format as JSON with these exact keys: visual_elements, text_content, conversion_elements, affiliate_indicators, template_suggestion"""

            response = self.model.generate_content([
                f"data:image/png;base64,{image_base64}",
                analysis_prompt
            ])

            analysis_text = response.text.strip()

            # Parse the analysis
            try:
                import json
                # Try to extract JSON from the response
                json_start = analysis_text.find('{')
                json_end = analysis_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = analysis_text[json_start:json_end]
                    analysis = json.loads(json_str)
                else:
                    analysis = {"raw_analysis": analysis_text}
            except:
                analysis = {"raw_analysis": analysis_text}

            logger.info("Image analysis completed successfully")
            return analysis

        except Exception as e:
            logger.error(f"Image analysis failed: {str(e)}", exc_info=True)
            raise

    async def extract_template_from_images(self, images_base64: list[str]) -> dict:
        """
        Extract common template from multiple winning images

        Args:
            images_base64: List of base64 encoded images

        Returns:
            Extracted template pattern
        """
        if not self.model:
            raise ValueError("Gemini not configured")

        try:
            # Analyze each image
            analyses = []
            for i, image_b64 in enumerate(images_base64):
                try:
                    analysis = await self.analyze_winning_image(image_b64)
                    analyses.append(analysis)
                except Exception as e:
                    logger.warning(f"Failed to analyze image {i+1}: {str(e)}")
                    continue

            if not analyses:
                raise Exception("Could not analyze any images")

            # Generate consolidated template
            consolidation_prompt = f"""Analyze these {len(analyses)} winning ad image analyses and extract:

1. COMMON PATTERNS across all images
2. SUCCESS FACTORS that appear in winning ads
3. OPTIMAL TEMPLATE STRUCTURE
4. VARIABLE ELEMENTS that change between ads
5. FIXED ELEMENTS that should stay consistent

Analyses to consolidate:
{analyses}

Provide a unified template that can be used to create similar high-converting ads, with:
- Required elements (must have)
- Optional elements (nice to have)
- Variable sections (customize per campaign)
- Color schemes that work
- Typography guidelines
- Button/CTA best practices
"""

            response = self.model.generate_content(consolidation_prompt)
            template = response.text.strip()

            logger.info("Template extraction completed")
            return {
                "individual_analyses": analyses,
                "consolidated_template": template,
            }

        except Exception as e:
            logger.error(f"Template extraction failed: {str(e)}", exc_info=True)
            raise
