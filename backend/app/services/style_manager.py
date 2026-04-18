"""Style management for image generation - adds visual style guidance to prompts"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)


class StyleManager:
    """Manages image style options and generates style-specific prompt augmentation"""

    # Style definitions with their unique characteristics
    STYLES = {
        "professional_photography": {
            "description": "High-quality professional photography, realistic, editorial aesthetic",
            "prompt_directive": """
VISUAL STYLE DIRECTIVE: Professional Editorial Photography
- Shot on Canon EOS R5 with 85mm f/1.4 lens, natural shallow depth-of-field
- Natural film grain (ISO 400-800), NOT digitally clean
- Mixed color temperature lighting (warm practicals + cool ambient)
- Subtle lens vignette and natural chromatic aberration
- Real skin texture with pores, not airbrushed or plastic
- Ambient occlusion shadows, NOT flat studio lighting
- Editorial magazine photography, NOT stock photo
- Natural color grading with slight desaturation, muted highlights
- Imperfect real-world elements: slight wrinkles in fabric, natural hair movement
- Environmental context with bokeh background, NOT solid color backdrop
- NO HDR over-processing, NO artificial sharpening, NO plastic skin
- Captured moment feeling, NOT posed mannequin look"""
        },
        "modern_illustrated": {
            "description": "Clean, modern illustrated style with vector aesthetic",
            "prompt_directive": """
VISUAL STYLE DIRECTIVE: Modern Illustrated
- Modern, clean vector-based illustration
- Flat design with subtle depth
- Bold, clear shapes and forms
- Limited color palette, cohesive
- Contemporary illustration style
- Clean lines, smooth gradients
- Friendly and approachable design
- Professional but approachable"""
        },
        "ghibli": {
            "description": "Studio Ghibli-inspired watercolor illustration with hand-painted feel",
            "prompt_directive": """
VISUAL STYLE DIRECTIVE: Studio Ghibli Style
- Ghibli-inspired watercolor painting style
- Hand-painted, soft edges
- Beautiful, whimsical character design
- Soft color palette with watercolor blending
- Detailed background with ethereal quality
- Magical realism aesthetic
- Careful attention to character emotion
- Japanese animation art style influence
- Dreamlike, fantastical atmosphere"""
        },
        "minimalist": {
            "description": "Minimalist design with essential elements only",
            "prompt_directive": """
VISUAL STYLE DIRECTIVE: Minimalist
- Minimalist design approach
- Only essential visual elements
- Clean, spacious composition
- Limited color palette (2-3 main colors)
- Geometric shapes and forms
- Negative space is important
- Modern, sophisticated aesthetic
- Typography-focused where applicable
- Uncluttered, elegant"""
        },
        "cinematic": {
            "description": "Cinematic film look with dramatic color grading",
            "prompt_directive": """
VISUAL STYLE DIRECTIVE: Cinematic Film
- Anamorphic lens look with 2.39:1 framing feel, horizontal lens flares
- Teal and orange color grading (blockbuster palette)
- Deep shadows with crushed blacks, lifted in post
- Dramatic side-lighting or rim-lighting, motivated light sources
- Film grain (35mm Kodak Vision3 500T look), NOT digitally clean
- Shallow depth-of-field with creamy bokeh
- Atmospheric haze, dust particles in light beams
- Dynamic camera angle suggesting movement (dolly, crane)
- Production design with practical set dressing
- Color-graded NOT color-corrected — mood over accuracy"""
        },
        "3d_render": {
            "description": "3D rendered computer graphics style",
            "prompt_directive": """
VISUAL STYLE DIRECTIVE: 3D Render
- Professional 3D rendered graphics
- High-quality 3D modeling and rendering
- Realistic materials and lighting
- Clean 3D environment
- Modern render farm quality
- Professional 3D visualization
- Smooth surfaces with realistic reflections
- Ray-traced lighting (if applicable)
- High polygon detail"""
        },
        "watercolor": {
            "description": "Watercolor painting style with traditional art aesthetic",
            "prompt_directive": """
VISUAL STYLE DIRECTIVE: Watercolor
- Traditional watercolor painting style
- Watercolor brush strokes visible
- Soft color transitions and washes
- Artistic, expressive composition
- Translucent color layers
- Paper texture visible
- Organic, fluid forms
- Fine art aesthetic
- Handcrafted appearance"""
        },
        "anime": {
            "description": "Japanese anime/manga illustration style",
            "prompt_directive": """
VISUAL STYLE DIRECTIVE: Anime
- Japanese anime/manga illustration style
- Anime character design and proportions
- Expressive eyes and emotions
- Dynamic action poses
- Manga-influenced linework
- Bright, saturated colors
- Anime background art quality
- Japanese pop culture aesthetic
- Clean cell-shading style"""
        },
    }

    @staticmethod
    def get_style_directive(style: Optional[str]) -> str:
        """Get the prompt directive for a specific style"""
        if not style:
            style = "professional_photography"

        if style not in StyleManager.STYLES:
            logger.warning(f"Unknown style '{style}', using professional_photography")
            style = "professional_photography"

        return StyleManager.STYLES[style]["prompt_directive"]

    @staticmethod
    def augment_prompt(
        base_prompt: str,
        style: Optional[str] = "professional_photography",
    ) -> str:
        """
        Augment a base prompt with style-specific guidance

        Args:
            base_prompt: The original prompt
            style: The desired style (default: professional_photography)

        Returns:
            Augmented prompt with style directive
        """
        if not style:
            style = "professional_photography"

        style_directive = StyleManager.get_style_directive(style)

        # Anti-plastic realism directive applied to ALL styles
        realism = """
CRITICAL REALISM RULES (apply to ALL styles):
- NO plastic, waxy, or airbrushed skin — show real texture
- NO over-saturated HDR look — keep natural dynamic range
- NO perfectly symmetrical compositions — slight asymmetry feels real
- NO stock-photo-smile poses — capture natural, candid moments
- Any TEXT in the image must be spelled EXACTLY as specified in the prompt, character-by-character. Double-check every letter."""

        augmented = f"""{base_prompt}

{style_directive}
{realism}"""

        return augmented

    @staticmethod
    def get_available_styles() -> dict:
        """Get all available styles with descriptions"""
        return {
            name: style["description"]
            for name, style in StyleManager.STYLES.items()
        }

    @staticmethod
    def validate_style(style: str) -> bool:
        """Check if a style is valid"""
        return style in StyleManager.STYLES
