from sqlalchemy import Column, String, Text, Integer, Float, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base


class Template(Base):
    __tablename__ = "templates"

    id = Column(String, primary_key=True)
    vertical = Column(String, nullable=False, index=True)  # e.g., "home_insurance"
    template_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # Base prompt template
    prompt_base = Column(Text, nullable=False)

    # Performance metrics
    success_rate = Column(Float, default=0.0)  # Percentage 0-100
    avg_ctr = Column(Float, default=0.0)  # Average click-through rate
    avg_conversion_rate = Column(Float, default=0.0)

    # Image dimensions
    width = Column(Integer, default=1200)
    height = Column(Integer, default=628)

    # Cost estimate for this template
    estimated_cost = Column(Float, default=0.02)

    # Active status
    is_active = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    images = relationship("Image", back_populates="template")

    def __repr__(self):
        return f"<Template {self.vertical}/{self.template_name}>"
