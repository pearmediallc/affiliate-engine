from pydantic import BaseModel
from typing import Optional, Any, Dict


class APIResponse(BaseModel):
    """Standard API response wrapper"""
    success: bool
    message: str
    data: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Operation successful",
                "data": {"id": "123", "name": "Example"},
                "error": None
            }
        }
