from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Image
from ..schemas import ImageGenerateRequest, ImageResponse, ImageListResponse, APIResponse
from ..services import ImageGeneratorService, PromptOptimizerService, VerticalTemplatesService, VisionAnalyzerService, StyleManager
from ..services.affiliate_prompt_engineer import AffiliatePromptEngineer
from ..services.learning_service import LearningService
from ..services.image_generator import IMAGES_DIR
from ..config import settings
from ..middleware.auth import get_optional_user, log_usage
import uuid
import logging
import requests
import io
import os

logger = logging.getLogger(__name__)

router = APIRouter()
image_generator = ImageGeneratorService()
prompt_optimizer = PromptOptimizerService()
vision_analyzer = VisionAnalyzerService()


class GeneratePromptRequest(BaseModel):
    description: str
    vertical: str = "home_insurance"
    style: str = "professional_photography"


@router.post("/generate-prompt", response_model=APIResponse)
async def generate_prompt(
    request: GeneratePromptRequest,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """
    Use Gemini to generate an optimized image generation prompt
    from a plain-language description.
    """
    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)

        system_prompt = (
            "You are an expert image prompt engineer. Given a user's plain-language description, "
            "generate a detailed, optimized prompt for an AI image generator (Imagen/DALL-E).\n\n"
            "Rules:\n"
            "- If the user wants text/headlines in the image, include them with EXACT spelling, "
            "placement (top/center/bottom), and styling (bold, font size, color). "
            "Specify every character precisely so the image model renders it correctly.\n"
            "- If the user does NOT mention text, do not add any.\n"
            "- Include specific details about composition, lighting, color palette, mood, and camera angle.\n"
            f"- Tailor the prompt to the '{request.vertical.replace('_', ' ')}' vertical.\n"
            f"- Target a '{request.style.replace('_', ' ')}' visual style.\n"
            "- Keep the prompt under 200 words.\n"
            "- Output ONLY the prompt text. No explanations, no preamble, no labels."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{system_prompt}\n\nUser description: {request.description}",
        )

        generated_prompt = response.text.strip()

        if user:
            log_usage("image_generation", user.id, db, cost_usd=0.01)

        return APIResponse(
            success=True,
            message="Prompt generated successfully",
            data={"prompt": generated_prompt},
        )

    except ImportError:
        raise HTTPException(status_code=500, detail="google-genai package is not installed")
    except Exception as e:
        logger.error(f"Prompt generation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Prompt generation failed: {str(e)}")


@router.post("/generate", response_model=APIResponse)
async def generate_images(
    request: ImageGenerateRequest,
    client_id: str = Query("demo-client", description="Client ID"),
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """
    Generate images based on template or Gemma variations

    Supports:
    1. Template mode: Use pre-built template with optional refinements
    2. Gemma variations mode: AI analyzes reference and generates variations

    For MVP, client_id can be passed as query param. In production,
    this would come from authenticated user context.
    """
    images = []

    try:
        # Get learned context for this vertical
        learned_context = LearningService.get_generation_context(db, request.vertical)

        # Generate prompts using appropriate method
        # Priority: Custom prompt > Gemma variations > Affiliate angles > Template

        if request.additional_context and not request.template_id and not request.use_gemma_variations:
            # HIGHEST PRIORITY: Custom prompt without template or variations
            # Use additional_context as the custom prompt directly
            if request.count > 1:
                # Generate variations of the custom prompt
                prompts = prompt_optimizer.generate_variations(
                    base_prompt=request.additional_context,
                    vertical=request.vertical,
                    count=request.count,
                )
            else:
                prompts = [request.additional_context]
            logger.info(f"Using custom prompt mode: generated {len(prompts)} prompts")

        elif request.use_gemma_variations:
            # Gemini Vision variation mode: Analyze reference image or text and generate variations
            if request.reference_image_base64:
                # Use Gemini Vision to analyze the image
                try:
                    prompts = vision_analyzer.generate_variations_from_image(
                        image_base64=request.reference_image_base64,
                        vertical=request.vertical,
                        count=request.count,
                    )
                    logger.info(f"Generated {len(prompts)} prompts using Gemini Vision image analysis")
                except Exception as e:
                    logger.error(f"Gemini Vision analysis failed: {str(e)}, falling back to text analysis")
                    # Fallback to text-based if vision fails
                    prompts = prompt_optimizer.generate_variations_from_reference(
                        reference_text=request.reference_text or "Professional ad creative",
                        vertical=request.vertical,
                        count=request.count,
                    )
            elif request.reference_text:
                # Text-based variations
                prompts = prompt_optimizer.generate_variations_from_reference(
                    reference_text=request.reference_text,
                    vertical=request.vertical,
                    count=request.count,
                )
            else:
                raise HTTPException(status_code=400, detail="Please provide a reference image or text for variations")
        elif request.use_affiliate_angles:
            # Use affiliate marketing angles for better conversions
            angle = request.affiliate_angle or "benefit"
            base_prompt = AffiliatePromptEngineer.get_angle_prompt(
                vertical=request.vertical,
                angle=angle,
                custom_context=request.additional_context,
            )

            if request.count > 1:
                # Generate variations on the angle
                prompts = prompt_optimizer.generate_variations(
                    base_prompt=base_prompt,
                    vertical=request.vertical,
                    count=request.count,
                )
            else:
                prompts = [base_prompt]

            logger.info(f"Generated {len(prompts)} prompts using affiliate angle: {angle}")
        else:
            # Template mode: Get template and optimize
            if not request.template_id:
                raise HTTPException(status_code=400, detail="Please select a template, use custom prompt, or enable Gemma variations")

            template = VerticalTemplatesService.get_template_by_id(db, request.template_id)
            if not template:
                raise HTTPException(status_code=404, detail="Template not found")

            # Generate prompts (either optimized single or variations)
            if request.count > 1:
                # Generate variations of the template
                prompts = prompt_optimizer.generate_variations(
                    base_prompt=template.prompt_base,
                    vertical=request.vertical,
                    count=request.count,
                )
            else:
                # Single optimized prompt
                optimized = prompt_optimizer.optimize_prompt(
                    base_prompt=template.prompt_base,
                    vertical=request.vertical,
                    state=request.state,
                    additional_context=request.additional_context,
                )
                prompts = [optimized]

        # Generate images from prompts (with style augmentation)
        for i, prompt in enumerate(prompts):
            try:
                # Prepend learned rules if available
                if learned_context:
                    prompt = f"{learned_context}\n\nIMAGE PROMPT:\n{prompt}"

                # Augment prompt with style directive
                style = request.style if hasattr(request, 'style') and request.style else "professional_photography"
                augmented_prompt = StyleManager.augment_prompt(prompt, style)

                image = await image_generator.generate_image(
                    client_id=client_id,
                    template_id=request.template_id or f"custom_{uuid.uuid4().hex[:8]}",
                    prompt=augmented_prompt,
                    vertical=request.vertical,
                    state=request.state,
                    db=db,
                )
                images.append(ImageResponse.model_validate(image))
            except Exception as e:
                logger.error(f"Failed to generate image {i+1}: {str(e)}", exc_info=True)
                continue

        if not images:
            logger.error("No images were generated from prompts")
            raise HTTPException(status_code=500, detail=f"Failed to generate any images. Generated {len(prompts)} prompts but none succeeded.")

        # Record generation for learning
        for img in images:
            try:
                LearningService.record_generation(
                    db=db,
                    user_id=user.id if user else None,
                    vertical=request.vertical,
                    feature="image_generation",
                    input_data={
                        "prompt": img.prompt_used,
                        "style": request.style if hasattr(request, 'style') else "professional_photography",
                        "vertical": request.vertical,
                        "template_id": request.template_id,
                    },
                    output_data={
                        "image_id": img.id,
                        "image_url": img.image_url,
                        "provider": img.generation_provider,
                        "model": img.generation_model,
                        "cost": img.cost_usd,
                    },
                )
            except Exception as learn_err:
                logger.warning(f"Failed to record learning: {learn_err}")

        total_cost = sum(img.cost_usd for img in images)
        if user:
            log_usage("image_generation", user.id, db, cost_usd=total_cost)

        return APIResponse(
            success=True,
            message=f"Generated {len(images)} images",
            data={
                "count": len(images),
                "images": images,
                "total_cost": sum(img.cost_usd for img in images),
                "mode": "gemma_variations" if request.use_gemma_variations else "template",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")


@router.get("/list", response_model=ImageListResponse)
async def list_images(
    client_id: str = Query("demo-client", description="Client ID"),
    vertical: str = Query("home_insurance", description="Filter by vertical"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List images for a client with pagination"""
    query = db.query(Image).filter(
        Image.client_id == client_id,
        Image.vertical == vertical,
    )

    total = query.count()
    images = query.offset((page - 1) * page_size).limit(page_size).all()

    return ImageListResponse(
        total=total,
        page=page,
        page_size=page_size,
        images=[ImageResponse.model_validate(img) for img in images],
    )


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(
    image_id: str,
    db: Session = Depends(get_db),
):
    """Get a specific image"""
    image = db.query(Image).filter(Image.id == image_id).first()

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    return ImageResponse.model_validate(image)


@router.get("/angles/{vertical}", response_model=APIResponse)
async def get_affiliate_angles(vertical: str = "home_insurance"):
    """Get available affiliate marketing angles for a vertical"""
    angles = AffiliatePromptEngineer.get_all_angles_for_vertical(vertical)

    if not angles:
        raise HTTPException(status_code=404, detail=f"No angles defined for vertical: {vertical}")

    return APIResponse(
        success=True,
        message=f"Available angles for {vertical}",
        data={
            "vertical": vertical,
            "angles": [
                {"id": angle_id, "name": angle_id.replace("_", " ").title(), "description": description}
                for angle_id, description in angles.items()
            ],
        }
    )


@router.get("/serve/{filename}")
async def serve_image(filename: str):
    """Serve a generated image file from disk"""
    # Sanitize filename to prevent path traversal
    filename = os.path.basename(filename)
    filepath = os.path.join(IMAGES_DIR, filename)

    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(filepath, media_type="image/png")


@router.get("/download/{image_id}")
async def download_image(
    image_id: str,
    db: Session = Depends(get_db),
):
    """Download image by ID - proxy for external image URLs"""
    image = db.query(Image).filter(Image.id == image_id).first()

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if not image.image_url:
        raise HTTPException(status_code=400, detail="Image URL not available")

    try:
        import base64 as b64

        download_name = f"affiliate-image-{image_id[:12]}.png"

        # Handle local file path (images saved to disk)
        if image.image_path and os.path.isfile(image.image_path):
            return FileResponse(
                image.image_path,
                media_type="image/png",
                headers={"Content-Disposition": f"attachment; filename={download_name}"}
            )

        # Handle /api/v1/images/serve/ URLs (local serve path)
        if image.image_url and "/images/serve/" in image.image_url:
            filename = os.path.basename(image.image_url)
            filepath = os.path.join(IMAGES_DIR, filename)
            if os.path.isfile(filepath):
                return FileResponse(
                    filepath,
                    media_type="image/png",
                    headers={"Content-Disposition": f"attachment; filename={download_name}"}
                )

        # Handle base64 data URIs (legacy)
        if image.image_url and image.image_url.startswith("data:"):
            header, encoded = image.image_url.split(",", 1)
            mime_type = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
            image_bytes = b64.b64decode(encoded)
            return StreamingResponse(
                io.BytesIO(image_bytes),
                media_type=mime_type,
                headers={"Content-Disposition": f"attachment; filename={download_name}"}
            )

        # Handle external URLs (OpenAI, FAL, etc.)
        if image.image_url and image.image_url.startswith("http"):
            response = requests.get(image.image_url, timeout=30)
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to retrieve image from source")
            return StreamingResponse(
                io.BytesIO(response.content),
                media_type="image/png",
                headers={"Content-Disposition": f"attachment; filename={download_name}"}
            )

        raise HTTPException(status_code=400, detail="No valid image source available")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading image {image_id}: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Failed to download image: {str(e)}")
