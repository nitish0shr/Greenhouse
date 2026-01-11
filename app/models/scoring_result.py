# =============================================================================
# Scoring Result Model - Scoring Output Cache & Audit
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScoringResult(Base):
    """
    Cache scoring results for audit and debugging.
    
    Stores the complete scoring output (strict JSON schema) for each application.
    """
    
    __tablename__ = "scoring_results"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Foreign key to application
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id"),
        nullable=False,
        index=True,
    )
    
    # Rubric version used
    rubric_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    # Scoring output (strict JSON schema from evaluator)
    score_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<ScoringResult application_id={self.application_id} rubric_version={self.rubric_version}>"
