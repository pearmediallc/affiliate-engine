from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class TemplateResponse(BaseModel):
    """Response for a single template"""
    id: str
    vertical: str
    template_name: str
    description: Optional[str] = None
    prompt_base: str
    success_rate: float
    avg_ctr: float
    avg_conversion_rate: float
    width: int
    height: int
    estimated_cost: float
    is_active: bool
    is_featured: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TemplateListResponse(BaseModel):
    """List of templates grouped by vertical"""
    vertical: str
    total: int
    templates: List[TemplateResponse]

    class Config:
        from_attributes = True
