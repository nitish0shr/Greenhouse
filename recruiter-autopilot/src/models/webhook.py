"""Webhook event model for idempotency tracking."""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class WebhookSource(str, Enum):
    """Source of the webhook event."""

    GREENHOUSE = "greenhouse"
    MICROSOFT_GRAPH = "microsoft_graph"


class WebhookStatus(str, Enum):
    """Processing status of the webhook event."""

    RECEIVED = "received"  # Just received, not yet processed
    QUEUED = "queued"  # Pushed to worker queue
    PROCESSING = "processing"  # Currently being processed
    COMPLETED = "completed"  # Successfully processed
    FAILED = "failed"  # Processing failed
    IGNORED = "ignored"  # Duplicate or irrelevant event


class WebhookEvent(Base, TimestampMixin):
    """
    Tracks webhook events for idempotency and audit purposes.

    Every webhook is logged here before processing.
    Duplicate event_ids are detected and ignored.
    """

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Event identification
    source: Mapped[WebhookSource] = mapped_column(
        SQLEnum(WebhookSource), nullable=False, index=True
    )
    event_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # Unique per source
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )  # e.g., "application_updated"

    # Processing status
    status: Mapped[WebhookStatus] = mapped_column(
        SQLEnum(WebhookStatus), default=WebhookStatus.RECEIVED, nullable=False, index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Related entities
    greenhouse_application_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    greenhouse_candidate_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    greenhouse_job_id: Mapped[int | None] = mapped_column(BigInteger, index=True)

    # Raw payload (stored for debugging/replay)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Signature verification
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    signature_header: Mapped[str | None] = mapped_column(String(500))

    # Processing details
    worker_task_id: Mapped[str | None] = mapped_column(String(255))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_duration_ms: Mapped[int | None] = mapped_column()

    # Error handling
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Correlation
    correlation_id: Mapped[str | None] = mapped_column(String(100))

    def __repr__(self) -> str:
        return f"<WebhookEvent(id={self.id}, source={self.source.value}, event_type={self.event_type})>"

    @property
    def is_duplicate(self) -> bool:
        """Check if this event has already been processed."""
        return self.status in {WebhookStatus.COMPLETED, WebhookStatus.IGNORED}

    @property
    def can_retry(self) -> bool:
        """Check if this event can be retried."""
        return self.status == WebhookStatus.FAILED and self.retry_count < self.max_retries

    def mark_queued(self, task_id: str) -> None:
        """Mark event as queued for processing."""
        self.status = WebhookStatus.QUEUED
        self.worker_task_id = task_id

    def mark_processing(self) -> None:
        """Mark event as currently being processed."""
        self.status = WebhookStatus.PROCESSING
        self.processing_started_at = datetime.utcnow()

    def mark_completed(self) -> None:
        """Mark event as successfully processed."""
        self.status = WebhookStatus.COMPLETED
        self.processed_at = datetime.utcnow()
        if self.processing_started_at:
            delta = datetime.utcnow() - self.processing_started_at
            self.processing_duration_ms = int(delta.total_seconds() * 1000)

    def mark_failed(self, error: str) -> None:
        """Mark event as failed."""
        self.status = WebhookStatus.FAILED
        self.error_message = error
        self.retry_count += 1
