# =============================================================================
# Audit Log Model - Track All Automated Actions
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    """
    Comprehensive audit log for all automated actions.
    
    Every action taken by the system is logged here for compliance,
    debugging, and manual review purposes.
    """
    
    __tablename__ = "audit_logs"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Action type
    action_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    # Types: webhook_received, application_fetched, resume_downloaded,
    #        resume_parsed, candidate_scored, stage_advanced,
    #        application_rejected, email_sent, note_added, tag_added,
    #        interview_scheduled, human_review_added, manual_approval,
    #        manual_rejection, rescore_requested
    
    # Related entities
    application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id"),
        nullable=True,
        index=True,
    )
    candidate_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id"),
        nullable=True,
        index=True,
    )
    
    # Greenhouse IDs for external reference
    greenhouse_application_id: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        index=True,
    )
    greenhouse_candidate_id: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        index=True,
    )
    
    # Who/what triggered the action
    triggered_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="system",
    )  # system, webhook, admin:<username>, scheduled
    
    # Action details
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    # Additional metadata
    metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    
    # Request/response for API calls
    request_data: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    response_data: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    # Status and errors
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="success",
    )  # success, failed, pending
    
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Duration for performance tracking
    duration_ms: Mapped[Optional[int]] = mapped_column(
        nullable=True,
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    
    # Indexes for common queries
    __table_args__ = (
        Index("ix_audit_logs_candidate_created", "candidate_id", "created_at"),
        Index("ix_audit_logs_application_created", "application_id", "created_at"),
        Index("ix_audit_logs_type_status", "action_type", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<AuditLog {self.action_type} at {self.created_at}>"
