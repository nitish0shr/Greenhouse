"""Calendar event models for interview scheduling."""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class CalendarEventStatus(str, Enum):
    """Status of a calendar event."""

    PENDING = "pending"  # Proposed but not confirmed
    CONFIRMED = "confirmed"  # Accepted by all parties
    TENTATIVE = "tentative"  # Tentatively accepted
    CANCELLED = "cancelled"  # Cancelled
    COMPLETED = "completed"  # Event occurred


class CalendarEventType(str, Enum):
    """Type of calendar event."""

    PHONE_SCREEN = "phone_screen"
    VIDEO_INTERVIEW = "video_interview"
    ONSITE_INTERVIEW = "onsite_interview"
    TECHNICAL_INTERVIEW = "technical_interview"
    PANEL_INTERVIEW = "panel_interview"
    HIRING_MANAGER_INTERVIEW = "hiring_manager_interview"
    FINAL_ROUND = "final_round"
    OTHER = "other"


class CalendarEvent(Base, TimestampMixin):
    """
    Represents a scheduled interview or meeting.

    Synced with Microsoft Outlook calendar.
    """

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Related entities
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id"), nullable=False, index=True
    )

    # Event type
    event_type: Mapped[CalendarEventType] = mapped_column(
        SQLEnum(CalendarEventType), nullable=False
    )

    # Scheduling
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")

    # Location/connection
    location: Mapped[str | None] = mapped_column(String(500))
    meeting_url: Mapped[str | None] = mapped_column(String(1000))
    meeting_id: Mapped[str | None] = mapped_column(String(255))
    meeting_passcode: Mapped[str | None] = mapped_column(String(100))

    # Participants
    organizer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    interviewer_emails: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    candidate_email: Mapped[str] = mapped_column(String(255), nullable=False)
    optional_attendees: Mapped[list[str] | None] = mapped_column(JSONB, default=list)

    # Content
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    interview_instructions: Mapped[str | None] = mapped_column(Text)

    # Status
    status: Mapped[CalendarEventStatus] = mapped_column(
        SQLEnum(CalendarEventStatus), default=CalendarEventStatus.PENDING, index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    # Reminders
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Rescheduling
    is_rescheduled: Mapped[bool] = mapped_column(Boolean, default=False)
    reschedule_count: Mapped[int] = mapped_column(Integer, default=0)
    original_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rescheduled_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("calendar_events.id")
    )

    # Scorecard tracking
    scorecards_expected: Mapped[int] = mapped_column(Integer, default=1)
    scorecards_submitted: Mapped[int] = mapped_column(Integer, default=0)
    scorecard_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    # Correlation
    correlation_id: Mapped[str | None] = mapped_column(String(100))

    def __repr__(self) -> str:
        return f"<CalendarEvent(id={self.id}, type={self.event_type.value}, status={self.status.value})>"


class CalendarEventMapping(Base, TimestampMixin):
    """
    Maps internal calendar events to external calendar IDs.

    Allows syncing with multiple calendar systems.
    """

    __tablename__ = "calendar_event_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Internal event
    calendar_event_id: Mapped[int] = mapped_column(
        ForeignKey("calendar_events.id"), nullable=False, index=True
    )

    # External system
    external_system: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "outlook", "google", "greenhouse"

    # External IDs
    external_event_id: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    external_calendar_id: Mapped[str | None] = mapped_column(String(500))
    external_change_key: Mapped[str | None] = mapped_column(String(500))

    # Sync status
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_error: Mapped[str | None] = mapped_column(Text)
    needs_sync: Mapped[bool] = mapped_column(Boolean, default=False)

    # Greenhouse-specific
    greenhouse_interview_id: Mapped[int | None] = mapped_column(BigInteger)
    greenhouse_scheduled_interview_id: Mapped[int | None] = mapped_column(BigInteger)

    def __repr__(self) -> str:
        return f"<CalendarEventMapping(event_id={self.calendar_event_id}, system={self.external_system})>"
