# =============================================================================
# Exception Model - Dead Letter Queue & Error Tracking
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Exception(Base):
    """
    Exception tracking and dead-letter queue.
    
    Stores exceptions for API failures, missing mappings, scheduling mismatches,
    reply correlation failures, etc. Supports retries and replay.
    """
    
    __tablename__ = "exceptions"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Foreign key to application (optional)
    application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id"),
        nullable=True,
        index=True,
    )
    
    # Exception type: 'api_failure', 'missing_mapping', 'scheduling_mismatch',
    # 'reply_correlation_failed', etc.
    exception_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    # Reason/description
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    # Status: 'open', 'resolved', 'retrying'
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="open",
        index=True,
    )
    
    # Retry tracking
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    
    # Error details
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Payload references (JSONB) - store greenhouse_event_id, autopilot_action_id, etc.
    payload_refs: Mapped[dict] = mapped_column(
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
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_exceptions_status_next_retry", "status", "next_retry_at"),
    )
    
    def __repr__(self) -> str:
        return f"<Exception {self.exception_type} status={self.status} retry_count={self.retry_count}>"
