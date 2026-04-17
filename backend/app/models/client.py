from sqlalchemy import Column, String, DateTime, Boolean, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base


class Client(Base):
    __tablename__ = "clients"

    id = Column(String, primary_key=True)
    company_name = Column(String, nullable=False)
    api_key = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=False)

    # Active status
    is_active = Column(Boolean, default=True)

    # Cost tracking
    total_cost = Column(Float, default=0.0)
    monthly_cost = Column(Float, default=0.0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    images = relationship("Image", back_populates="client", cascade="all, delete-orphan")
    performances = relationship("PerformanceMetric", back_populates="client", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Client {self.company_name}>"
