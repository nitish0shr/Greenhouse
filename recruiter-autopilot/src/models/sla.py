"""SLA configuration and violation tracking models."""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class SLAType(str, Enum):
    """Type of SLA being tracked."""

    INGESTED_TO_ACTIONED = "ingested_to_actioned"
    CONTACTED_TO_RESPONDED = "contacted_to_responded"
    SCHEDULING_TO_SCHEDULED = "scheduling_to_scheduled"
    SCHEDULED_TO_INTERVIEWED = "scheduled_to_interviewed"
    INTERVIEWED_TO_DECISION = "interviewed_to_decision"
    SCORECARD_SUBMISSION = "scorecard_submission"
    CUSTOM = "custom"


class SLAConfig(Base, TimestampMixin):
    """
    SLA configuration for a job or globally.

    Defines time limits and escalation paths.
    """

    __tablename__ = "sla_configs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Scope (null job_id = global default)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)

    # SLA type
    sla_type: Mapped[SLAType] = mapped_column(SQLEnum(SLAType), nullable=False)

    # Time limits (in hours)
    warning_threshold_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_threshold_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    breach_threshold_hours: Mapped[int] = mapped_column(Integer, nullable=False)

    # Actions
    warning_actions: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    # Example: {"send_email": true, "recipients": ["recruiter"]}

    critical_actions: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    # Example: {"send_email": true, "recipients": ["recruiter", "hiring_manager"]}

    breach_actions: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    # Example: {"send_email": true, "recipients": ["recruiter", "hiring_manager", "hr"]}

    # Notification templates
    warning_email_template: Mapped[str | None] = mapped_column(String(100))
    critical_email_template: Mapped[str | None] = mapped_column(String(100))
    breach_email_template: Mapped[str | None] = mapped_column(String(100))

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<SLAConfig(id={self.id}, type={self.sla_type.value}, job_id={self.job_id})>"


class SLAViolation(Base, TimestampMixin):
    """
    Tracks SLA violations for applications.

    Used for reporting and escalation tracking.
    """

    __tablename__ = "sla_violations"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Related entities
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    sla_config_id: Mapped[int] = mapped_column(
        ForeignKey("sla_configs.id"), nullable=False
    )

    # SLA details
    sla_type: Mapped[SLAType] = mapped_column(SQLEnum(SLAType), nullable=False)

    # Timing
    sla_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    warning_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    critical_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    breached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Current level
    current_level: Mapped[str] = mapped_column(
        String(20), default="normal"
    )  # normal, warning, critical, breached

    # Time metrics
    hours_elapsed: Mapped[int | None] = mapped_column(Integer)
    hours_over_sla: Mapped[int | None] = mapped_column(Integer)

    # Notifications sent
    warning_notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    critical_notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    breach_notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    # Resolution
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text)

    # Greenhouse IDs
    greenhouse_application_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    greenhouse_job_id: Mapped[int | None] = mapped_column(BigInteger)

    def __repr__(self) -> str:
        return f"<SLAViolation(id={self.id}, type={self.sla_type.value}, level={self.current_level})>"

    def escalate_to_warning(self) -> None:
        """Escalate to warning level."""
        if self.current_level == "normal":
            self.current_level = "warning"
            self.warning_at = datetime.utcnow()

    def escalate_to_critical(self) -> None:
        """Escalate to critical level."""
        if self.current_level in ("normal", "warning"):
            self.current_level = "critical"
            self.critical_at = datetime.utcnow()

    def escalate_to_breached(self) -> None:
        """Escalate to breached level."""
        if self.current_level != "breached":
            self.current_level = "breached"
            self.breached_at = datetime.utcnow()

    def resolve(self, notes: str | None = None) -> None:
        """Mark violation as resolved."""
        self.resolved = True
        self.resolved_at = datetime.utcnow()
        self.resolution_notes = notes
        if self.sla_started_at:
            delta = datetime.utcnow() - self.sla_started_at
            self.hours_elapsed = int(delta.total_seconds() / 3600)
