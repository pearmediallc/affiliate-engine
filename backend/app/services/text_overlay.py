"""Text overlay service - composites text onto images with real fonts"""
import os
import logging
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Optional

logger = logging.getLogger(__name__)

# Font directory
FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "fonts")
os.makedirs(FONTS_DIR, exist_ok=True)


class TextOverlayService:
    """Composites text onto images using Pillow for 100% accurate typography"""

    # Default font (system fallback)
    @staticmethod
    def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """Get font, trying bundled fonts first, then system fallbacks"""
        font_names = [
            "Inter-Bold.ttf" if bold else "Inter-Regular.ttf",
            "Arial Bold.ttf" if bold else "Arial.ttf",
            "Helvetica-Bold.ttf" if bold else "Helvetica.ttf",
        ]

        # Try bundled fonts
        for name in font_names:
            path = os.path.join(FONTS_DIR, name)
            if os.path.isfile(path):
                return ImageFont.truetype(path, size)

        # Try system fonts
        system_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for path in system_paths:
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size)
                except:
                    continue

        # Ultimate fallback
        return ImageFont.load_default()

    @staticmethod
    def overlay_text(
        image_path: str,
        headline: Optional[str] = None,
        subheading: Optional[str] = None,
        cta_text: Optional[str] = None,
        position: str = "bottom",  # top, center, bottom
        headline_color: str = "#FFFFFF",
        subheading_color: str = "#FFFFFF",
        cta_bg_color: str = "#0071e3",
        cta_text_color: str = "#FFFFFF",
        add_shadow: bool = True,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Overlay text onto an image with professional typography.

        Args:
            image_path: Path to the base image
            headline: Large headline text (top element)
            subheading: Smaller subheading text
            cta_text: Call-to-action button text
            position: Where to place text block: top, center, bottom
            headline_color: Hex color for headline
            subheading_color: Hex color for subheading
            cta_bg_color: Background color for CTA button
            cta_text_color: Text color for CTA button
            add_shadow: Add dark gradient behind text for readability
            output_path: Where to save result (default: overwrite input)

        Returns:
            Path to the composited image
        """
        if not headline and not subheading and not cta_text:
            return image_path

        try:
            img = Image.open(image_path).convert("RGBA")
            width, height = img.size

            # Create overlay layer
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Calculate font sizes relative to image width
            headline_size = max(int(width * 0.06), 28)
            subheading_size = max(int(width * 0.035), 18)
            cta_size = max(int(width * 0.03), 16)

            headline_font = TextOverlayService._get_font(headline_size, bold=True)
            subheading_font = TextOverlayService._get_font(subheading_size, bold=False)
            cta_font = TextOverlayService._get_font(cta_size, bold=True)

            # Calculate text block height
            padding = int(width * 0.05)
            line_spacing = int(headline_size * 0.4)
            block_height = padding * 2

            elements = []
            if headline:
                bbox = draw.textbbox((0, 0), headline, font=headline_font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                elements.append(("headline", headline, headline_font, tw, th, headline_color))
                block_height += th + line_spacing
            if subheading:
                bbox = draw.textbbox((0, 0), subheading, font=subheading_font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                elements.append(("subheading", subheading, subheading_font, tw, th, subheading_color))
                block_height += th + line_spacing
            if cta_text:
                bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                elements.append(("cta", cta_text, cta_font, tw, th, cta_text_color))
                block_height += th + int(cta_size * 1.5) + line_spacing

            # Determine Y start based on position
            if position == "top":
                y_start = padding
            elif position == "center":
                y_start = (height - block_height) // 2
            else:  # bottom
                y_start = height - block_height - padding

            # Add dark gradient behind text for readability
            if add_shadow:
                gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                gradient_draw = ImageDraw.Draw(gradient)

                if position == "bottom":
                    for i in range(block_height + padding * 2):
                        y = height - (block_height + padding * 2) + i
                        alpha = int(180 * (i / (block_height + padding * 2)))
                        gradient_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
                elif position == "top":
                    for i in range(block_height + padding * 2):
                        alpha = int(180 * (1 - i / (block_height + padding * 2)))
                        gradient_draw.line([(0, i), (width, i)], fill=(0, 0, 0, alpha))
                else:  # center
                    center_y = height // 2
                    spread = (block_height + padding * 2) // 2
                    for i in range(height):
                        dist = abs(i - center_y)
                        if dist < spread:
                            alpha = int(160 * (1 - dist / spread))
                            gradient_draw.line([(0, i), (width, i)], fill=(0, 0, 0, alpha))

                img = Image.alpha_composite(img, gradient)

            # Draw text elements
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            current_y = y_start
            for elem_type, text, font, tw, th, color in elements:
                x = (width - tw) // 2  # Center horizontally

                if elem_type == "cta":
                    # Draw CTA as a pill button
                    btn_padding_x = int(cta_size * 1.5)
                    btn_padding_y = int(cta_size * 0.6)
                    btn_width = tw + btn_padding_x * 2
                    btn_height = th + btn_padding_y * 2
                    btn_x = (width - btn_width) // 2
                    btn_y = current_y

                    # Parse hex color for button bg
                    r, g, b = int(cta_bg_color[1:3], 16), int(cta_bg_color[3:5], 16), int(cta_bg_color[5:7], 16)
                    draw.rounded_rectangle(
                        [btn_x, btn_y, btn_x + btn_width, btn_y + btn_height],
                        radius=btn_height // 2,
                        fill=(r, g, b, 230),
                    )

                    # Center text in button
                    text_x = btn_x + (btn_width - tw) // 2
                    text_y = btn_y + (btn_height - th) // 2
                    draw.text((text_x, text_y), text, font=font, fill=cta_text_color)
                    current_y += btn_height + line_spacing
                else:
                    # Draw text shadow for depth
                    shadow_offset = max(2, headline_size // 20)
                    draw.text((x + shadow_offset, current_y + shadow_offset), text, font=font, fill=(0, 0, 0, 100))
                    # Draw main text
                    draw.text((x, current_y), text, font=font, fill=color)
                    current_y += th + line_spacing

            # Composite
            result = Image.alpha_composite(img, overlay)
            result = result.convert("RGB")

            save_path = output_path or image_path
            result.save(save_path, "PNG", quality=95)

            logger.info(f"Text overlay applied: {save_path}")
            return save_path

        except Exception as e:
            logger.error(f"Text overlay failed: {e}")
            return image_path
