# =============================================================================
# Action Model - Audit Log for All Autopilot Actions
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Action(Base):
    """
    Audit log for all Autopilot actions.
    
    Every writeback to Greenhouse or Graph API creates an action record with
    autopilot_action_id (UUID) for loop prevention and audit trail.
    """
    
    __tablename__ = "actions"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Autopilot action ID (UUID) - used for loop prevention (UNIQUE constraint)
    autopilot_action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Foreign key to application
    application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id"),
        nullable=True,
        index=True,
    )
    application = relationship("Application", back_populates="actions")
    
    # Action type: 'tag_added', 'note_created', 'stage_moved', 'rejected',
    # 'email_sent', 'interview_created', 'interview_updated', 'interview_cancelled'
    action_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    # Request payload (what we sent)
    request_payload: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    # Response payload (what we received)
    response_payload: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    # Status: 'pending', 'completed', 'failed'
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Error message if action failed
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_actions_application_status", "application_id", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<Action {self.autopilot_action_id} ({self.action_type}) status={self.status}>"
