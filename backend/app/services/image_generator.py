"""Service for generating images using various providers"""
import asyncio
import uuid
import logging
import os
from typing import Optional
from ..config import settings
from ..models import Image
from sqlalchemy.orm import Session
import requests
import io
import base64

# Directory where generated images are saved
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "generated_images")
os.makedirs(IMAGES_DIR, exist_ok=True)

# For Gemini image generation via google.genai (new library)
GOOGLE_GENAI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types
    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    try:
        import google.generativeai as genai_legacy
        GOOGLE_GENAI_AVAILABLE = True
    except ImportError:
        pass

logger = logging.getLogger(__name__)


class ImageGeneratorService:
    """Service for image generation with multiple provider support"""

    def __init__(self):
        self.provider = settings.image_provider
        self.cost_per_image = settings.image_generation_cost

    async def generate_image(
        self,
        client_id: str,
        template_id: str,
        prompt: str,
        vertical: str,
        state: Optional[str] = None,
        db: Session = None,
    ) -> Image:
        """
        Generate a single image

        Args:
            client_id: Client ID
            template_id: Template ID
            prompt: Image prompt
            vertical: Vertical category
            state: Optional state
            db: Database session

        Returns:
            Generated Image object
        """
        image_id = f"img_{uuid.uuid4().hex[:12]}"

        try:
            # Generate image based on configured provider
            image_data = await self._generate_with_provider(prompt)

            # Determine actual provider from model name
            model_name = image_data.get("model", "")
            if "imagen" in model_name or "gemini" in model_name:
                actual_provider = "gemini"
            elif "dall-e" in model_name:
                actual_provider = "openai"
            elif "ideogram" in model_name:
                actual_provider = "ideogram"
            elif "flux" in model_name:
                actual_provider = "fal"
            else:
                actual_provider = self.provider

            # Create image record
            image = Image(
                id=image_id,
                client_id=client_id,
                template_id=template_id,
                vertical=vertical,
                state=state,
                prompt_used=prompt,
                image_url=image_data.get("url"),
                image_path=image_data.get("path"),
                generation_provider=actual_provider,
                generation_model=image_data.get("model"),
                seed=image_data.get("seed"),
                cost_usd=self.cost_per_image,
            )

            if db:
                db.add(image)
                db.commit()
                db.refresh(image)

            logger.info(f"Image {image_id} generated successfully")
            return image

        except Exception as e:
            logger.error(f"Error generating image: {str(e)}")
            raise

    async def _generate_with_provider(self, prompt: str) -> dict:
        """
        Generate image with provider chain: Gemini (PRIMARY) → OpenAI (SECONDARY) → FAL (TERTIARY)

        Provider precedence order:
        1. Gemini 2.0 Flash (PRIMARY - for high-quality ad creatives with text overlays)
        2. OpenAI DALL-E 3 (SECONDARY - fallback if Gemini fails)
        3. FAL.ai (TERTIARY - final fallback)

        Args:
            prompt: Image generation prompt

        Returns:
            Dictionary with url, path, model, seed
        """
        logger.info(f"Image generation chain: Gemini PRIMARY → OpenAI SECONDARY → FAL TERTIARY")

        # Smart routing: check if a specific provider is best for this prompt
        route = self._smart_route(prompt)
        if route == "ideogram":
            try:
                logger.info("Smart route: Using Ideogram (text-heavy content detected)")
                return await self._generate_with_ideogram(prompt)
            except Exception as e:
                logger.warning(f"Ideogram smart route failed: {e}, falling back to default chain")

        # STEP 1: Try Gemini (PRIMARY) - Always attempt first regardless of provider setting
        if GOOGLE_GENAI_AVAILABLE and settings.gemini_api_key:
            try:
                logger.info("Step 1: Attempting Gemini 2.0 Flash (PRIMARY)")
                return await self._generate_with_gemini_image(prompt)
            except Exception as gemini_e:
                logger.warning(f"Step 1 FAILED: Gemini error: {str(gemini_e)}")
                logger.info("Falling back to OpenAI...")
        else:
            logger.warning("Gemini not available - missing library or API key")

        # STEP 2: Try OpenAI (SECONDARY)
        if settings.openai_api_key:
            try:
                logger.info("Step 2: Attempting OpenAI DALL-E 3 (SECONDARY)")
                return await self._generate_with_openai(prompt)
            except Exception as openai_e:
                logger.warning(f"Step 2 FAILED: OpenAI error: {str(openai_e)}")
                logger.info("Falling back to FAL...")
        else:
            logger.warning("OpenAI API key not configured")

        # STEP 3: Use FAL (TERTIARY) - final fallback
        try:
            logger.info("Step 3: Attempting FAL.ai (TERTIARY)")
            return await self._generate_with_fal(prompt)
        except Exception as fal_e:
            logger.error(f"Step 3 FAILED: FAL error: {str(fal_e)}")
            raise Exception("All image generation providers failed")

    def _smart_route(self, prompt: str, has_text_overlay: bool = False) -> str:
        """Determine the best provider based on prompt content"""
        prompt_lower = prompt.lower()

        # If user wants text in the image, prefer Ideogram (90-95% text accuracy)
        if has_text_overlay or any(kw in prompt_lower for kw in ['"', 'text overlay', 'headline', 'cta button', 'banner text', 'sign that says']):
            if settings.ideogram_api_key:
                return "ideogram"

        # Default chain
        return "default"

    async def _generate_with_ideogram(self, prompt: str) -> dict:
        """Generate image using Ideogram 3.0 - best for text-heavy images"""
        if not settings.ideogram_api_key:
            raise ValueError("IDEOGRAM_API_KEY not set")

        try:
            headers = {
                "Api-Key": settings.ideogram_api_key,
                "Content-Type": "application/json",
            }

            payload = {
                "image_request": {
                    "prompt": prompt,
                    "model": "V_3",
                    "aspect_ratio": "ASPECT_16_9",
                    "magic_prompt_option": "AUTO",
                }
            }

            response = requests.post(
                "https://api.ideogram.ai/generate",
                json=payload,
                headers=headers,
                timeout=120,
            )

            if response.status_code != 200:
                raise Exception(f"Ideogram API error: {response.status_code} - {response.text[:200]}")

            data = response.json()

            if data.get("data") and len(data["data"]) > 0:
                image_url = data["data"][0].get("url")
                if image_url:
                    # Download and save to disk
                    img_response = requests.get(image_url, timeout=30)
                    if img_response.status_code == 200:
                        filename = f"{uuid.uuid4().hex[:12]}.png"
                        filepath = os.path.join(IMAGES_DIR, filename)
                        with open(filepath, "wb") as f:
                            f.write(img_response.content)

                        logger.info(f"Image generated with Ideogram 3.0, saved: {filepath}")
                        return {
                            "url": f"/api/v1/images/serve/{filename}",
                            "path": filepath,
                            "model": "ideogram-v3",
                            "seed": uuid.uuid4().hex[:8],
                        }

            raise Exception("Ideogram returned no image data")
        except Exception as e:
            logger.error(f"Ideogram generation failed: {str(e)}")
            raise

    async def _generate_with_openai(self, prompt: str) -> dict:
        """
        Generate image using OpenAI DALL-E 3

        Args:
            prompt: Image generation prompt

        Returns:
            Dictionary with url, path, model, seed
        """
        try:
            if not settings.openai_api_key:
                logger.error("OpenAI API key not configured")
                raise ValueError("OPENAI_API_KEY not set")

            # Call OpenAI DALL-E API
            headers = {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": "dall-e-3",
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",  # DALL-E 3 standard sizes
                "quality": "standard",
                "response_format": "url",
            }

            response = requests.post(
                "https://api.openai.com/v1/images/generations",
                json=payload,
                headers=headers,
                timeout=60,
            )

            if response.status_code != 200:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                logger.error(f"OpenAI API error: {error_detail}")
                raise Exception(f"OpenAI API error: {error_detail}")

            data = response.json()
            image_url = data["data"][0]["url"]

            logger.info(f"Image generated successfully with OpenAI DALL-E 3")

            return {
                "url": image_url,
                "path": None,
                "model": "dall-e-3",
                "seed": uuid.uuid4().hex[:8],
            }

        except Exception as e:
            logger.error(f"OpenAI image generation failed: {str(e)}")
            raise

    async def _generate_with_gemini_image(self, prompt: str) -> dict:
        """
        Generate image using Google Gemini via google.genai Client

        Uses the correct google.genai library with imagen or gemini-2.0-flash-exp
        for actual image generation (not text generation).

        Args:
            prompt: Image generation prompt

        Returns:
            Dictionary with url, path, model, seed
        """
        if not GOOGLE_GENAI_AVAILABLE:
            raise ValueError("google.genai library not installed")

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not set")

        try:
            client = genai.Client(api_key=settings.gemini_api_key)

            # Use Imagen 4 for image generation (Google's latest dedicated image model)
            image_model = "imagen-4.0-generate-001"

            logger.info(f"Generating image with {image_model}: {prompt[:100]}...")

            response = client.models.generate_images(
                model=image_model,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="16:9",
                ),
            )

            # Extract image from response and save to disk
            if response.generated_images and len(response.generated_images) > 0:
                raw = response.generated_images[0].image.image_bytes
                # Gemini returns base64-encoded bytes, decode to actual PNG
                image_bytes = base64.b64decode(raw) if not raw[:4] == b'\x89PNG' else raw
                filename = f"{uuid.uuid4().hex[:12]}.png"
                filepath = os.path.join(IMAGES_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(image_bytes)

                logger.info(f"Image generated and saved: {filepath}")
                return {
                    "url": f"/api/v1/images/serve/{filename}",
                    "path": filepath,
                    "model": image_model,
                    "seed": uuid.uuid4().hex[:8],
                }

            raise Exception("Imagen 4 returned no image data")

        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Imagen 4 generation failed: {error_msg}")

            # Fallback: try gemini-2.5-flash-image with image output
            try:
                logger.info("Trying gemini-2.5-flash-image with image output...")
                client = genai.Client(api_key=settings.gemini_api_key)

                response = client.models.generate_content(
                    model="gemini-2.5-flash-image",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                    ),
                )

                # Extract image parts and save to disk
                if response.candidates and response.candidates[0].content:
                    for part in response.candidates[0].content.parts:
                        if part.inline_data and part.inline_data.mime_type and "image" in part.inline_data.mime_type:
                            raw = part.inline_data.data
                            image_bytes = base64.b64decode(raw) if isinstance(raw, (str, bytes)) and not (isinstance(raw, bytes) and raw[:4] == b'\x89PNG') else raw
                            filename = f"{uuid.uuid4().hex[:12]}.png"
                            filepath = os.path.join(IMAGES_DIR, filename)
                            with open(filepath, "wb") as f:
                                f.write(image_bytes)

                            logger.info(f"Image generated with gemini-2.5-flash-image, saved: {filepath}")
                            return {
                                "url": f"/api/v1/images/serve/{filename}",
                                "path": filepath,
                                "model": "gemini-2.5-flash-image",
                                "seed": uuid.uuid4().hex[:8],
                            }

                raise Exception("gemini-2.5-flash-image returned no image data")

            except Exception as fallback_e:
                logger.error(f"Both Imagen 4 and gemini-2.5-flash-image failed: {str(fallback_e)}")
                raise

    async def _generate_with_fal(self, prompt: str) -> dict:
        """
        Generate image using FAL.ai FLUX model

        FLUX is excellent for detailed ad creatives with text overlays, CTAs, and layout specifications
        """
        try:
            if not settings.fal_api_key:
                logger.warning("FAL API key not configured. Please add FAL_API_KEY to .env")
                raise ValueError("FAL_API_KEY not configured")

            # Call FAL.ai FLUX API
            # FLUX v1.3 is optimized for detailed prompts and text rendering
            headers = {
                "Authorization": f"Key {settings.fal_api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "prompt": prompt,
                "image_size": "landscape_16_9",  # 1216x684 which is close to our 1200x628
                "num_inference_steps": 28,
                "guidance_scale": 7.5,
                "num_images": 1,
                "enable_safety_checker": True,
            }

            logger.info(f"Calling FAL.ai FLUX with prompt: {prompt[:100]}...")

            response = requests.post(
                "https://fal.run/fal-ai/flux/dev",
                json=payload,
                headers=headers,
                timeout=120,
            )

            if response.status_code not in [200, 201]:
                error_msg = response.text
                logger.error(f"FAL API error ({response.status_code}): {error_msg}")
                raise Exception(f"FAL API error: {error_msg}")

            data = response.json()

            # Extract image URL from response
            if "images" in data and len(data["images"]) > 0:
                image_url = data["images"][0].get("url")
                if image_url:
                    logger.info(f"Image generated successfully with FAL.ai FLUX")
                    return {
                        "url": image_url,
                        "path": None,
                        "model": "flux-dev",
                        "seed": data.get("seed", uuid.uuid4().hex[:8]),
                    }

            logger.error(f"FAL response missing image data: {data}")
            raise Exception("FAL API returned no image data")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"FAL image generation failed: {error_msg}")

            # If balance is exhausted, return demo image
            if "Exhausted balance" in error_msg or "locked" in error_msg.lower():
                logger.info("FAL balance exhausted - returning demo image")
                return {
                    "url": f"https://via.placeholder.com/1200x628?text=Demo+Image+(FAL+balance+exhausted)",
                    "path": None,
                    "model": "demo",
                    "seed": uuid.uuid4().hex[:8],
                }

            raise

    async def generate_batch(
        self,
        client_id: str,
        template_id: str,
        prompts: list[str],
        vertical: str,
        state: Optional[str] = None,
        db: Session = None,
    ) -> list[Image]:
        """
        Generate multiple images

        Args:
            client_id: Client ID
            template_id: Template ID
            prompts: List of prompts
            vertical: Vertical category
            state: Optional state
            db: Database session

        Returns:
            List of generated Images
        """
        semaphore = asyncio.Semaphore(3)

        async def generate_one(prompt):
            async with semaphore:
                return await self.generate_image(client_id, template_id, prompt, vertical, state, db)

        tasks = [generate_one(p) for p in prompts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        images = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Failed to generate image: {result}")
            else:
                images.append(result)
        return images
