"""Service for optimizing prompts using Gemini API"""
import google.generativeai as genai
from ..config import settings
import logging

logger = logging.getLogger(__name__)


class PromptOptimizerService:
    """Service for enhancing and optimizing image prompts using Gemini"""

    def __init__(self):
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            self.gemini_model = genai.GenerativeModel("gemini-2.5-flash")  # Latest Gemini for optimization
            self.gemma_model = genai.GenerativeModel("gemma-4-26b-a4b-it")  # Gemma for fast variations
        else:
            logger.warning("Gemini API key not configured. Prompt optimization will be limited.")

    def optimize_prompt(
        self,
        base_prompt: str,
        vertical: str,
        state: str = None,
        additional_context: str = None,
    ) -> str:
        """
        Optimize a base prompt with context for better image generation

        Args:
            base_prompt: Base template prompt
            vertical: Vertical category (e.g., "home_insurance")
            state: Optional state for regional variation
            additional_context: Additional context from user

        Returns:
            Optimized prompt
        """
        try:
            optimization_instruction = f"""You are an expert in creating high-converting ad image prompts.

Given a base image description template for a {vertical} advertisement, enhance it with conversion-optimizing details.

Base template:
{base_prompt}

{f'State/Region: {state}' if state else ''}
{f'Additional context: {additional_context}' if additional_context else ''}

Enhance this prompt to:
1. Add specific, actionable visual details that drive conversions
2. Include psychological triggers relevant to {vertical}
3. Ensure professional, stock photo quality
4. Maintain exact dimensions mentioned (1200x628px if present)
5. Add subtle emotional appeal appropriate for the vertical

Return ONLY the enhanced prompt, no explanations."""

            if not settings.gemini_api_key:
                logger.warning("Gemini API key not configured. Returning base prompt.")
                return base_prompt

            try:
                response = self.gemini_model.generate_content(optimization_instruction)
                optimized = response.text.strip()
                logger.info(f"Prompt optimized for {vertical} using Gemini 2.0 Flash")
                return optimized
            except Exception as inner_e:
                logger.error(f"Gemini optimization failed: {str(inner_e)}")
                return base_prompt

        except Exception as e:
            logger.error(f"Error optimizing prompt: {str(e)}")
            # Fallback: return base prompt if optimization fails
            return base_prompt

    def generate_variations(
        self,
        base_prompt: str,
        vertical: str,
        count: int = 3,
    ) -> list[str]:
        """
        Generate variations of a prompt for A/B testing

        Args:
            base_prompt: Base prompt to create variations from
            vertical: Vertical category
            count: Number of variations to generate

        Returns:
            List of prompt variations
        """
        try:
            variation_instruction = f"""You are expert in creating high-converting ad image prompts.

Generate {count} DIFFERENT variations of this image prompt for {vertical} ads.
Each variation should emphasize different emotional triggers or visual elements.

Original prompt:
{base_prompt}

Requirements:
- Each variation should be distinct but aligned with the same core message
- All should maintain professional quality standards
- Each should work for 1200x628px horizontal format
- No text overlays
- Focus on different psychological angles (trust, family, safety, relief, achievement, etc.)

Return only the {count} variations, one per line, numbered 1-{count}."""

            if not settings.gemini_api_key:
                logger.warning("Gemini API key not configured. Returning base prompt.")
                return [base_prompt]

            try:
                # Use Gemma for fast variation generation (lighter model, faster response)
                response = self.gemma_model.generate_content(variation_instruction)
                text = response.text.strip()

                # Parse the numbered variations
                variations = []
                import re

                # Split by numbered patterns (1. or 1) at start of line)
                parts = re.split(r'(?m)(?=^\d+[.)]\s)', text)

                for part in parts:
                    part = part.strip()
                    if part:
                        # Remove leading number
                        cleaned = re.sub(r'^\d+[.)]\s*', '', part).strip()
                        if cleaned:
                            variations.append(cleaned)

                # Fallback: simple line splitting if not enough
                if len(variations) < count:
                    variations = []
                    for line in text.split("\n"):
                        line = line.strip()
                        if line and not line.lower().startswith("here") and not line.lower().startswith("these"):
                            cleaned = re.sub(r'^\d+[.)]\s*', '', line).strip()
                            if cleaned and len(cleaned) > 20:
                                variations.append(cleaned)

                logger.info(f"Generated {len(variations)} prompt variations for {vertical} using Gemma (requested {count})")
                return variations[:count] if variations else [base_prompt]
            except Exception as inner_e:
                logger.error(f"Gemma variation generation failed: {str(inner_e)}, falling back to Gemini 2.5 Flash")
                # Fallback to Gemini if Gemma fails
                try:
                    response = self.gemini_model.generate_content(variation_instruction)
                    text = response.text.strip()
                    variations = []
                    for line in text.split("\n"):
                        line = line.strip()
                        if line and line[0].isdigit() and "." in line:
                            line = line.split(".", 1)[1].strip()
                        if line:
                            variations.append(line)
                    return variations[:count] if variations else [base_prompt]
                except Exception as fallback_e:
                    logger.error(f"Both Gemma and Gemini failed: {str(fallback_e)}")
                    return [base_prompt]

        except Exception as e:
            logger.error(f"Error generating variations: {str(e)}")
            return [base_prompt]  # Fallback

    def generate_variations_from_reference(
        self,
        reference_text: str,
        vertical: str,
        count: int = 5,
    ) -> list[str]:
        """
        Generate image prompts based on a reference using Gemma

        This uses Gemma to analyze a reference (image description, style, mood, etc.)
        and creates multiple variations for image generation

        Args:
            reference_text: Description or reference for variation generation
            vertical: Vertical category (e.g., "home_insurance")
            count: Number of variations to generate

        Returns:
            List of image generation prompts
        """
        try:
            instruction = f"""You are an expert AI image generation prompt engineer specializing in {vertical} advertising.

A user has provided a reference or description:
"{reference_text}"

Your task: Create {count} DIFFERENT, high-quality image generation prompts based on this reference.
Each prompt should be suitable for generating professional ad images for {vertical} campaigns.

Requirements for each prompt:
1. 200-300 words, descriptive and specific
2. Include visual composition details (lighting, colors, mood)
3. Specify image format: 1200x628px horizontal
4. Professional, high-quality stock photo style
5. No text overlays in the image
6. Each variation should explore different aspects of the reference
7. Variations should differ in: composition, perspective, emotion, styling

Format: Return exactly {count} prompts, separated by "---PROMPT_SEPARATOR---"
Number each one: "PROMPT 1: [prompt text]" etc.

Generate now:"""

            if not settings.gemini_api_key:
                logger.warning("Gemini API key not configured. Returning reference text.")
                return [reference_text] * min(count, 3)

            try:
                # Try Gemma first for faster response
                response = self.gemma_model.generate_content(instruction)
                text = response.text.strip()
            except Exception as gemma_e:
                logger.warning(f"Gemma failed, falling back to Gemini 2.5 Flash: {str(gemma_e)}")
                try:
                    response = self.gemini_model.generate_content(instruction)
                    text = response.text.strip()
                except Exception as gemini_e:
                    logger.error(f"Both Gemma and Gemini failed: {str(gemini_e)}")
                    return [reference_text] * min(count, 3)

            # Parse the prompts
            prompts = []
            for section in text.split("---PROMPT_SEPARATOR---"):
                section = section.strip()
                if section:
                    # Remove "PROMPT X:" prefix if present
                    if section.startswith("PROMPT"):
                        section = section.split(":", 1)[1].strip() if ":" in section else section
                    if section:
                        prompts.append(section)

            logger.info(f"Generated {len(prompts)} prompts from reference for {vertical}")
            return prompts[:count] if prompts else [reference_text]

        except Exception as e:
            logger.error(f"Error generating variations from reference: {str(e)}")
            # Fallback: return a basic version of the reference
            return [reference_text] * min(count, 3)
