from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
import base64
from ..database import get_db
from ..models import Template
from ..schemas import TemplateResponse, TemplateListResponse, APIResponse
from ..services import VerticalTemplatesService, TemplateAnalyzerService, StyleManager

router = APIRouter()


@router.get("/home-insurance", response_model=TemplateListResponse)
async def get_home_insurance_templates(db: Session = Depends(get_db)):
    """Get all home insurance templates"""
    templates = VerticalTemplatesService.get_home_insurance_templates(db)

    if not templates:
        # Initialize default templates if empty
        VerticalTemplatesService.initialize_default_templates(db)
        templates = VerticalTemplatesService.get_home_insurance_templates(db)

    return TemplateListResponse(
        vertical="home_insurance",
        total=len(templates),
        templates=[TemplateResponse.model_validate(t) for t in templates],
    )


@router.get("/vertical/{vertical}", response_model=TemplateListResponse)
async def get_templates_by_vertical(vertical: str, db: Session = Depends(get_db)):
    """Get all templates for a vertical"""
    templates = db.query(Template).filter(
        Template.vertical == vertical,
        Template.is_active == True,
    ).all()

    if not templates:
        # Initialize default templates if empty
        VerticalTemplatesService.initialize_default_templates(db)
        templates = db.query(Template).filter(
            Template.vertical == vertical,
            Template.is_active == True,
        ).all()

    if not templates:
        raise HTTPException(
            status_code=404,
            detail=f"No templates found for vertical: {vertical}"
        )

    return TemplateListResponse(
        vertical=vertical,
        total=len(templates),
        templates=[TemplateResponse.model_validate(t) for t in templates],
    )


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str, db: Session = Depends(get_db)):
    """Get a specific template"""
    template = VerticalTemplatesService.get_template_by_id(db, template_id)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return TemplateResponse.model_validate(template)


# Template Analysis Schemas
class AnalyzeImageRequest(BaseModel):
    image_base64: str


class ExtractTemplateRequest(BaseModel):
    images_base64: list[str]


# Template Analysis Endpoints
@router.post("/analyze")
async def analyze_winning_image(request: AnalyzeImageRequest):
    """Analyze a winning image to extract ad patterns"""
    try:
        analyzer = TemplateAnalyzerService()
        result = await analyzer.analyze_winning_image(request.image_base64)
        return APIResponse(success=True, message="Image analyzed successfully", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract")
async def extract_template_from_images(request: ExtractTemplateRequest):
    """Extract common template from multiple winning images"""
    try:
        if not request.images_base64 or len(request.images_base64) < 2:
            raise ValueError("At least 2 images required for template extraction")

        analyzer = TemplateAnalyzerService()
        result = await analyzer.extract_template_from_images(request.images_base64)
        return APIResponse(success=True, message="Template extracted successfully", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/styles/list")
async def get_available_styles():
    """Get all available image generation styles"""
    styles = StyleManager.get_available_styles()
    return APIResponse(
        success=True,
        message="Available styles retrieved successfully",
        data={
            "styles": styles,
            "count": len(styles),
            "default": "professional_photography"
        }
    )
