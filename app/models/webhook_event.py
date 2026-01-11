# =============================================================================
# Webhook Event Model - Idempotency Tracking
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebhookEvent(Base):
    """
    Track received webhook events for idempotency.
    
    Uses Greenhouse-Event-ID to ensure each webhook is processed exactly once,
    even if Greenhouse retries delivery.
    """
    
    __tablename__ = "webhook_events"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Greenhouse-Event-ID header - used for idempotency
    greenhouse_event_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Event details
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    
    # Raw payload for debugging/replay
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    
    # Processing status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="received",
        index=True,
    )  # received, processing, completed, failed
    
    # Error details if processing failed
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Related entity IDs (for quick lookups)
    application_id: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        index=True,
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        index=True,
    )
    
    # Timestamps
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Indexes for common queries
    __table_args__ = (
        Index("ix_webhook_events_received_status", "received_at", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<WebhookEvent {self.greenhouse_event_id} ({self.event_type})>"
