"""Exception queue for handling processing failures and items needing review."""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class ExceptionType(str, Enum):
    """Type of exception or reason for queuing."""

    # Processing errors
    PARSE_ERROR = "parse_error"  # Resume/attachment parsing failed
    SCORING_ERROR = "scoring_error"  # Scoring engine error
    API_ERROR = "api_error"  # External API error
    VALIDATION_ERROR = "validation_error"  # Data validation failed

    # Review required
    LOW_CONFIDENCE = "low_confidence"  # Scoring confidence below threshold
    BORDERLINE_SCORE = "borderline_score"  # Score near tier boundary
    MISSING_INFO = "missing_info"  # Critical info missing from resume
    CONFLICTING_DATA = "conflicting_data"  # Data inconsistencies detected

    # Email issues
    EMAIL_BOUNCE = "email_bounce"  # Email bounced
    NO_REPLY = "no_reply"  # No reply after multiple attempts
    UNCLEAR_INTENT = "unclear_intent"  # Reply intent unclear

    # Scheduling issues
    SCHEDULING_CONFLICT = "scheduling_conflict"  # No available slots
    RESCHEDULE_REQUEST = "reschedule_request"  # Candidate requested reschedule
    NO_SHOW = "no_show"  # Candidate didn't show up

    # Compliance/safety
    PROTECTED_TRAIT_MENTION = "protected_trait_mention"  # Potential bias concern
    UNUSUAL_PATTERN = "unusual_pattern"  # Suspicious activity

    # Manual escalation
    MANUAL_REVIEW = "manual_review"  # Manually flagged for review
    HIRING_MANAGER_ESCALATION = "hiring_manager_escalation"  # Escalated to HM


class ExceptionPriority(str, Enum):
    """Priority level for exception handling."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ExceptionQueueItem(Base, TimestampMixin):
    """
    Queue for exceptions and items requiring human review.

    Items can be resolved, retried, or escalated.
    """

    __tablename__ = "exception_queue"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Related entities
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id"), index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id"), index=True
    )
    webhook_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("webhook_events.id")
    )

    # Exception details
    exception_type: Mapped[ExceptionType] = mapped_column(
        SQLEnum(ExceptionType), nullable=False, index=True
    )
    priority: Mapped[ExceptionPriority] = mapped_column(
        SQLEnum(ExceptionPriority), default=ExceptionPriority.MEDIUM, index=True
    )

    # Context
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    stack_trace: Mapped[str | None] = mapped_column(Text)

    # Related data
    context_data: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    # Stores relevant info like: scoring result, email content, etc.

    # Processing state at time of exception
    processing_stage: Mapped[str | None] = mapped_column(String(100))
    worker_task_id: Mapped[str | None] = mapped_column(String(255))

    # Retry controls
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    can_auto_retry: Mapped[bool] = mapped_column(Boolean, default=False)

    # Resolution
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolution_type: Mapped[str | None] = mapped_column(String(50))
    # Types: "auto_retry", "manual_fix", "ignored", "escalated", "resolved"
    resolution_notes: Mapped[str | None] = mapped_column(Text)

    # Assignment
    assigned_to: Mapped[str | None] = mapped_column(String(255))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Escalation
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_to: Mapped[str | None] = mapped_column(String(255))

    # Greenhouse IDs (for quick filtering)
    greenhouse_application_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    greenhouse_candidate_id: Mapped[int | None] = mapped_column(BigInteger)
    greenhouse_job_id: Mapped[int | None] = mapped_column(BigInteger)

    # Correlation
    correlation_id: Mapped[str | None] = mapped_column(String(100))

    def __repr__(self) -> str:
        return f"<ExceptionQueueItem(id={self.id}, type={self.exception_type.value}, resolved={self.resolved})>"

    def mark_resolved(self, by: str, resolution_type: str, notes: str | None = None) -> None:
        """Mark this item as resolved."""
        self.resolved = True
        self.resolved_at = datetime.utcnow()
        self.resolved_by = by
        self.resolution_type = resolution_type
        self.resolution_notes = notes

    def escalate(self, to: str) -> None:
        """Escalate this item."""
        self.escalated = True
        self.escalated_at = datetime.utcnow()
        self.escalated_to = to
        self.priority = ExceptionPriority.HIGH

    def assign(self, to: str) -> None:
        """Assign this item to someone."""
        self.assigned_to = to
        self.assigned_at = datetime.utcnow()
