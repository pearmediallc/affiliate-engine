from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    image_id = Column(String, ForeignKey("images.id"), nullable=False, unique=True)

    # Campaign metrics
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    ctr = Column(Float, nullable=True)  # Click-through rate (%)
    conversion_rate = Column(Float, nullable=True)  # Conversion rate (%)
    revenue_generated = Column(Float, default=0.0)  # USD

    # Cost metrics
    spend = Column(Float, default=0.0)  # Total spend on this image
    cpc = Column(Float, nullable=True)  # Cost per click
    cpa = Column(Float, nullable=True)  # Cost per acquisition

    # ROI
    roas = Column(Float, nullable=True)  # Return on ad spend

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    client = relationship("Client", back_populates="performances")
    image = relationship("Image", back_populates="performance")

    def calculate_metrics(self):
        """Calculate derived metrics"""
        if self.clicks and self.impressions:
            self.ctr = (self.clicks / self.impressions) * 100
        if self.conversions and self.clicks:
            self.conversion_rate = (self.conversions / self.clicks) * 100
        if self.clicks and self.spend:
            self.cpc = self.spend / self.clicks
        if self.conversions and self.spend:
            self.cpa = self.spend / self.conversions
        if self.spend and self.spend > 0:
            self.roas = self.revenue_generated / self.spend
        return self

    def __repr__(self):
        return f"<PerformanceMetric {self.image_id}>"
