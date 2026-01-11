"""Job model with stage configuration and kill switches."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.application import Application
    from src.models.rubric import Rubric


class Job(Base, TimestampMixin):
    """
    Represents a job posting from Greenhouse.

    Contains configuration for automation behavior per job.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Greenhouse IDs
    greenhouse_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )

    # Job info
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="open")  # open, closed, draft
    department: Mapped[str | None] = mapped_column(String(255))
    office: Mapped[str | None] = mapped_column(String(255))

    # Hiring team
    hiring_manager_id: Mapped[int | None] = mapped_column(BigInteger)
    hiring_manager_email: Mapped[str | None] = mapped_column(String(255))
    recruiter_id: Mapped[int | None] = mapped_column(BigInteger)
    recruiter_email: Mapped[str | None] = mapped_column(String(255))
    coordinator_id: Mapped[int | None] = mapped_column(BigInteger)
    coordinator_email: Mapped[str | None] = mapped_column(String(255))

    # Automation config
    automation_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_advance_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_reject_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Rubric
    rubric_id: Mapped[int | None] = mapped_column(ForeignKey("rubrics.id"))

    # Stage mappings (job-specific)
    # Format: {"stage_name": {"id": 123, "auto_advance_to": 456, "email_template": "..."}}
    stage_config: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Email templates (job-specific overrides)
    email_templates: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Rejection settings
    default_rejection_reason_id: Mapped[int | None] = mapped_column(BigInteger)
    rejection_email_template: Mapped[str | None] = mapped_column(String(100))

    # Interview settings
    default_interview_duration_minutes: Mapped[int | None] = mapped_column(default=60)
    interview_buffer_minutes: Mapped[int | None] = mapped_column(default=15)

    # SLA overrides (hours, null = use default)
    sla_ingested_to_actioned: Mapped[int | None] = mapped_column()
    sla_contacted_to_responded: Mapped[int | None] = mapped_column()

    # Notes
    automation_notes: Mapped[str | None] = mapped_column(Text)

    # Greenhouse metadata
    greenhouse_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    greenhouse_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Sync
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    applications: Mapped[list["Application"]] = relationship(
        "Application", back_populates="job", lazy="selectin"
    )
    rubric: Mapped["Rubric | None"] = relationship("Rubric", back_populates="jobs")
    stage_configs: Mapped[list["JobStageConfig"]] = relationship(
        "JobStageConfig", back_populates="job", lazy="selectin"
    )
    kill_switches: Mapped[list["KillSwitch"]] = relationship(
        "KillSwitch", back_populates="job", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, gh_id={self.greenhouse_id}, name={self.name[:30]})>"

    def is_automation_enabled_for_stage(self, stage_id: int) -> bool:
        """Check if automation is enabled for a specific stage."""
        if not self.automation_enabled:
            return False

        for ks in self.kill_switches:
            if ks.is_active and (ks.stage_id == stage_id or ks.stage_id is None):
                return False

        return True


class JobStageConfig(Base, TimestampMixin):
    """Configuration for automation behavior at each job stage."""

    __tablename__ = "job_stage_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)

    # Stage info
    greenhouse_stage_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stage_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage_order: Mapped[int] = mapped_column(default=0)

    # Automation rules
    auto_advance_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_advance_to_stage_id: Mapped[int | None] = mapped_column(BigInteger)
    auto_advance_tier: Mapped[str | None] = mapped_column(String(10))  # A, B, etc.

    auto_reject_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason_id: Mapped[int | None] = mapped_column(BigInteger)

    # Email settings
    email_on_entry: Mapped[bool] = mapped_column(Boolean, default=False)
    entry_email_template: Mapped[str | None] = mapped_column(String(100))

    # Interview settings
    schedule_interview: Mapped[bool] = mapped_column(Boolean, default=False)
    interview_type: Mapped[str | None] = mapped_column(String(100))
    interviewer_ids: Mapped[list[int] | None] = mapped_column(JSONB, default=list)

    # Custom actions
    custom_tags: Mapped[list[str] | None] = mapped_column(JSONB, default=list)
    custom_actions: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationship
    job: Mapped["Job"] = relationship("Job", back_populates="stage_configs")


class KillSwitch(Base, TimestampMixin):
    """Kill switch to disable automation for a job or specific stage."""

    __tablename__ = "kill_switches"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)

    # Scope (null stage_id = entire job)
    stage_id: Mapped[int | None] = mapped_column(BigInteger)
    stage_name: Mapped[str | None] = mapped_column(String(255))

    # Switch state
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Context
    reason: Mapped[str | None] = mapped_column(Text)
    activated_by: Mapped[str | None] = mapped_column(String(255))
    deactivated_by: Mapped[str | None] = mapped_column(String(255))

    # Relationship
    job: Mapped["Job"] = relationship("Job", back_populates="kill_switches")

    def deactivate(self, by: str) -> None:
        """Deactivate this kill switch."""
        self.is_active = False
        self.deactivated_at = datetime.utcnow()
        self.deactivated_by = by
