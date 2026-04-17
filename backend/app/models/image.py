from sqlalchemy import Column, String, Text, Float, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base


class Image(Base):
    __tablename__ = "images"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    template_id = Column(String, ForeignKey("templates.id"), nullable=False)

    vertical = Column(String, nullable=False, index=True)  # e.g., "home_insurance"
    state = Column(String, nullable=True)  # Optional: state targeting

    # Image generation details
    prompt_used = Column(Text, nullable=False)
    image_url = Column(String, nullable=True)  # S3 or local path for MVP
    image_path = Column(String, nullable=True)  # Local filesystem path

    # Generation metadata
    generation_provider = Column(String, default="gemini")
    generation_model = Column(String, nullable=True)
    seed = Column(Integer, nullable=True)  # For reproducibility

    # Cost tracking
    cost_usd = Column(Float, default=0.0)

    # Quality scoring
    quality_score = Column(Float, nullable=True)  # 1-10
    professional_appearance = Column(Float, nullable=True)
    brand_alignment = Column(Float, nullable=True)
    conversion_potential = Column(Float, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    client = relationship("Client", back_populates="images")
    template = relationship("Template", back_populates="images")
    performance = relationship("PerformanceMetric", back_populates="image", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Image {self.id} - {self.vertical}>"
