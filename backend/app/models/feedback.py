from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from datetime import datetime
from ..database import Base


class GenerationFeedback(Base):
    __tablename__ = "generation_feedback"

    id = Column(String, primary_key=True)
    image_id = Column(String, ForeignKey("images.id"), nullable=False, index=True)
    rating = Column(String, nullable=False)  # "positive" or "negative"
    issues = Column(String, nullable=True)  # comma-separated tags
    comment = Column(Text, nullable=True)
    vertical = Column(String, nullable=False, index=True)
    prompt_used = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<GenerationFeedback {self.id} - {self.rating}>"
