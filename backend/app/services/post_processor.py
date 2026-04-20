"""Post-processing pipeline - adds film-look effects to remove AI plastic aesthetic"""
import os
import logging
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance
from typing import Optional

logger = logging.getLogger(__name__)

PRESETS = {
    "raw": {"grain": 0, "vignette": 0, "aberration": 0, "desaturate": 0},
    "editorial": {"grain": 0.15, "vignette": 0.12, "aberration": 1, "desaturate": 0.05},
    "film": {"grain": 0.3, "vignette": 0.2, "aberration": 2, "desaturate": 0.1},
    "vintage": {"grain": 0.4, "vignette": 0.25, "aberration": 2, "desaturate": 0.15, "warm_tint": 0.08},
}


class PostProcessor:
    """Applies film-look effects to AI-generated images for photorealism"""

    @staticmethod
    def add_film_grain(img: Image.Image, intensity: float = 0.2) -> Image.Image:
        if intensity <= 0:
            return img
        arr = np.array(img).astype(np.float32)
        noise = np.random.normal(0, intensity * 25, arr.shape)
        arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
        return Image.fromarray(arr)

    @staticmethod
    def add_vignette(img: Image.Image, strength: float = 0.15) -> Image.Image:
        if strength <= 0:
            return img
        w, h = img.size
        arr = np.array(img).astype(np.float32)
        Y, X = np.ogrid[:h, :w]
        cx, cy = w / 2, h / 2
        max_dist = np.sqrt(cx**2 + cy**2)
        dist = np.sqrt((X - cx)**2 + (Y - cy)**2) / max_dist
        vignette = 1 - (dist ** 1.5) * strength
        vignette = np.clip(vignette, 0, 1)
        for c in range(3):
            arr[:, :, c] *= vignette
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    @staticmethod
    def add_chromatic_aberration(img: Image.Image, offset: int = 1) -> Image.Image:
        if offset <= 0:
            return img
        arr = np.array(img)
        result = arr.copy()
        # Shift red channel right, blue channel left
        result[:, offset:, 0] = arr[:, :-offset, 0]  # Red shift right
        result[:, :-offset, 2] = arr[:, offset:, 2]   # Blue shift left
        return Image.fromarray(result)

    @staticmethod
    def desaturate(img: Image.Image, amount: float = 0.08) -> Image.Image:
        if amount <= 0:
            return img
        enhancer = ImageEnhance.Color(img)
        return enhancer.enhance(1.0 - amount)

    @staticmethod
    def warm_tint(img: Image.Image, amount: float = 0.05) -> Image.Image:
        if amount <= 0:
            return img
        arr = np.array(img).astype(np.float32)
        arr[:, :, 0] = np.clip(arr[:, :, 0] * (1 + amount), 0, 255)  # More red
        arr[:, :, 2] = np.clip(arr[:, :, 2] * (1 - amount * 0.5), 0, 255)  # Less blue
        return Image.fromarray(arr.astype(np.uint8))

    @staticmethod
    def process(image_path: str, preset: str = "editorial", output_path: str = None) -> str:
        """Apply a preset of post-processing effects to an image"""
        if preset not in PRESETS:
            preset = "editorial"

        settings = PRESETS[preset]
        if preset == "raw":
            return image_path

        try:
            img = Image.open(image_path).convert("RGB")

            img = PostProcessor.add_film_grain(img, settings.get("grain", 0))
            img = PostProcessor.add_vignette(img, settings.get("vignette", 0))
            img = PostProcessor.add_chromatic_aberration(img, settings.get("aberration", 0))
            img = PostProcessor.desaturate(img, settings.get("desaturate", 0))
            if "warm_tint" in settings:
                img = PostProcessor.warm_tint(img, settings["warm_tint"])

            save_path = output_path or image_path
            img.save(save_path, "PNG", quality=95)
            logger.info(f"Post-processing applied ({preset}): {save_path}")
            return save_path
        except Exception as e:
            logger.error(f"Post-processing failed: {e}")
            return image_path

    @staticmethod
    def get_available_presets() -> dict:
        return {k: v for k, v in PRESETS.items()}
