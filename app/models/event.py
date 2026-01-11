# =============================================================================
# Event Model - Greenhouse Webhook Event Tracking
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Event(Base):
    """
    Track received Greenhouse webhook events for idempotency.
    
    Uses greenhouse_event_id (from Greenhouse-Event-ID header) to ensure
    each webhook is processed exactly once, even if Greenhouse retries delivery.
    """
    
    __tablename__ = "events"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Greenhouse-Event-ID header - used for idempotency (UNIQUE constraint)
    greenhouse_event_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Event type (e.g., "new_candidate_application", "candidate_stage_change")
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    # Raw body JSON (for debugging/replay)
    raw_body_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    
    # Signature verification status
    signature_valid: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
    )
    
    # Processing status: 'pending', 'processed', 'failed', 'reconciled'
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
    )
    
    # Timestamps
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Error message if processing failed
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Indexes for common queries
    __table_args__ = (
        Index("ix_events_status_received_at", "status", "received_at"),
    )
    
    def __repr__(self) -> str:
        return f"<Event {self.greenhouse_event_id} ({self.event_type}) status={self.status}>"
