# =============================================================================
# Human Review Queue Model - Low Confidence Applications
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class HumanReviewQueue(Base):
    """
    Queue for applications requiring human review.
    
    When scoring confidence is low or certain flags are triggered,
    applications are added here for manual review before any
    automated action is taken.
    """
    
    __tablename__ = "human_review_queue"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Application reference
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    application = relationship("Application")
    
    # Greenhouse IDs for convenience
    greenhouse_application_id: Mapped[int] = mapped_column(
        nullable=False,
        index=True,
    )
    greenhouse_candidate_id: Mapped[int] = mapped_column(
        nullable=False,
        index=True,
    )
    
    # Job info for filtering
    job_id: Mapped[int] = mapped_column(
        nullable=False,
        index=True,
    )
    job_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    
    # Review status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
    )  # pending, approved, rejected, skipped
    
    # Priority (lower = more urgent)
    priority: Mapped[int] = mapped_column(
        default=5,
        nullable=False,
        index=True,
    )
    
    # Why this needs review
    review_reasons: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    
    # Scoring context
    auto_score: Mapped[Optional[float]] = mapped_column(
        nullable=True,
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(
        nullable=True,
    )
    suggested_action: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )  # advance, reject, need_more_info
    
    # Reviewer info
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Review decision
    decision: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )  # approve, reject, advance, hold
    decision_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_review_queue_status_priority", "status", "priority", "created_at"),
        Index("ix_review_queue_job_status", "job_id", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<HumanReviewQueue {self.greenhouse_application_id} ({self.status})>"
