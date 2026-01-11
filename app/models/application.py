# =============================================================================
# Application Model - Tracks Application State and Scoring
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Application(Base):
    """
    Track applications and their processing state.
    
    Each application represents a candidate's application to a specific job.
    Stores scoring results, processing status, and automation decisions.
    """
    
    __tablename__ = "applications"
    
    # Primary key (internal)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Greenhouse application ID (external) - matches First Review schema
    greenhouse_application_id: Mapped[int] = mapped_column(
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Foreign key to candidate
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id"),
        nullable=False,
        index=True,
    )
    candidate = relationship("Candidate", back_populates="applications")
    
    # Greenhouse candidate ID (for convenience)
    greenhouse_candidate_id: Mapped[int] = mapped_column(
        nullable=False,
        index=True,
    )
    
    # Job information - matches First Review schema
    greenhouse_job_id: Mapped[int] = mapped_column(
        nullable=False,
        index=True,
    )
    
    # Current stage in Greenhouse - matches First Review schema
    current_stage_id: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        index=True,
    )
    
    # Application status: 'active', 'rejected', 'hired'
    status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    
    # Application source
    source: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # Processing status
    processing_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
    )  # pending, processing, completed, failed, human_review
    
    # Scoring results
    score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        index=True,
    )
    score_breakdown: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    
    # Automation decisions
    auto_decision: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )  # None, advance, reject, human_review
    
    hard_reject_reasons: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    
    # Greenhouse rejection reason ID (if rejected)
    rejection_reason_id: Mapped[Optional[int]] = mapped_column(
        nullable=True,
    )
    
    # Resume attachment info
    resume_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    resume_downloaded: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )
    resume_download_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Processing errors
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    
    # Full raw data from Greenhouse API
    raw_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
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
    greenhouse_applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    scored_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Relationships
    actions = relationship("Action", back_populates="application")
    
    # Indexes
    __table_args__ = (
        Index("ix_applications_job_status", "greenhouse_job_id", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<Application {self.greenhouse_application_id} for job {self.greenhouse_job_id}>"
