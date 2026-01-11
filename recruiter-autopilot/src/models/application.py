"""Application model with state machine for tracking processing status."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.candidate import Candidate
    from src.models.job import Job


class ApplicationState(str, Enum):
    """
    Application state machine states.

    Flow: ingested -> parsed -> scored -> actioned -> contacted ->
          scheduling -> scheduled -> interviewed -> decision_pending -> closed
    """

    INGESTED = "ingested"  # Just received from webhook
    PARSED = "parsed"  # Resume extracted
    SCORED = "scored"  # Rubric scoring complete
    ACTIONED = "actioned"  # Tags/notes written, stage action taken
    CONTACTED = "contacted"  # Initial outreach sent
    SCHEDULING = "scheduling"  # In scheduling flow
    SCHEDULED = "scheduled"  # Interview scheduled
    INTERVIEWED = "interviewed"  # Interview completed
    DECISION_PENDING = "decision_pending"  # Awaiting hiring decision
    CLOSED = "closed"  # Final state (hired, rejected, withdrawn)

    # Error/exception states
    NEEDS_REVIEW = "needs_review"  # Flagged for human review
    EXCEPTION = "exception"  # Processing error


class ApplicationTier(str, Enum):
    """Scoring tier based on rubric evaluation."""

    A = "A"  # Top tier - auto-advance
    B = "B"  # Good - advance with review
    C = "C"  # Below bar - hold or reject
    REJECT = "REJECT"  # Hard reject - auto-reject if enabled


class Application(Base, TimestampMixin):
    """
    Represents an application to a specific job.

    This is the central entity for tracking automation state.
    """

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("greenhouse_id", name="uq_applications_greenhouse_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Greenhouse IDs
    greenhouse_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id"), nullable=False, index=True
    )

    # Greenhouse stage info
    current_stage_id: Mapped[int | None] = mapped_column(BigInteger)
    current_stage_name: Mapped[str | None] = mapped_column(String(255))

    # State machine
    state: Mapped[ApplicationState] = mapped_column(
        SQLEnum(ApplicationState),
        default=ApplicationState.INGESTED,
        nullable=False,
        index=True,
    )
    previous_state: Mapped[ApplicationState | None] = mapped_column(
        SQLEnum(ApplicationState)
    )
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )

    # Scoring
    tier: Mapped[ApplicationTier | None] = mapped_column(SQLEnum(ApplicationTier))
    score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    rubric_version: Mapped[str | None] = mapped_column(String(50))
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Automation tracking
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    human_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    human_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    human_reviewed_by: Mapped[str | None] = mapped_column(String(255))

    # Email tracking
    last_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_email_template: Mapped[str | None] = mapped_column(String(100))
    emails_sent_count: Mapped[int] = mapped_column(Integer, default=0)

    # Reply tracking
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reply_intent: Mapped[str | None] = mapped_column(String(50))

    # Interview tracking
    scheduled_interview_id: Mapped[int | None] = mapped_column(BigInteger)
    scheduled_interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interview_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scorecards_submitted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Rejection tracking
    rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason_id: Mapped[int | None] = mapped_column(BigInteger)
    rejection_reason: Mapped[str | None] = mapped_column(String(255))

    # Outcome
    outcome: Mapped[str | None] = mapped_column(String(50))  # hired, rejected, withdrawn

    # Error tracking
    last_error: Mapped[str | None] = mapped_column(Text)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Metadata
    source: Mapped[str | None] = mapped_column(String(255))
    referrer: Mapped[str | None] = mapped_column(String(255))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Custom fields written back to Greenhouse
    custom_fields: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Automation notes/evidence (internal)
    automation_notes: Mapped[list[dict] | None] = mapped_column(JSONB, default=list)

    # Relationships
    candidate: Mapped["Candidate"] = relationship(
        "Candidate", back_populates="applications", lazy="joined"
    )
    job: Mapped["Job"] = relationship("Job", back_populates="applications", lazy="joined")
    state_transitions: Mapped[list["ApplicationStateTransition"]] = relationship(
        "ApplicationStateTransition",
        back_populates="application",
        lazy="selectin",
        order_by="ApplicationStateTransition.created_at.desc()",
    )
    scoring_results: Mapped[list["ScoringResult"]] = relationship(
        "ScoringResult",
        back_populates="application",
        lazy="selectin",
        order_by="ScoringResult.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Application(id={self.id}, gh_id={self.greenhouse_id}, state={self.state.value})>"

    def can_transition_to(self, new_state: ApplicationState) -> bool:
        """Check if transition to new state is valid."""
        valid_transitions: dict[ApplicationState, set[ApplicationState]] = {
            ApplicationState.INGESTED: {
                ApplicationState.PARSED,
                ApplicationState.EXCEPTION,
                ApplicationState.NEEDS_REVIEW,
            },
            ApplicationState.PARSED: {
                ApplicationState.SCORED,
                ApplicationState.EXCEPTION,
                ApplicationState.NEEDS_REVIEW,
            },
            ApplicationState.SCORED: {
                ApplicationState.ACTIONED,
                ApplicationState.NEEDS_REVIEW,
                ApplicationState.EXCEPTION,
            },
            ApplicationState.ACTIONED: {
                ApplicationState.CONTACTED,
                ApplicationState.CLOSED,  # Immediate rejection
                ApplicationState.NEEDS_REVIEW,
            },
            ApplicationState.CONTACTED: {
                ApplicationState.SCHEDULING,
                ApplicationState.CLOSED,
                ApplicationState.NEEDS_REVIEW,
            },
            ApplicationState.SCHEDULING: {
                ApplicationState.SCHEDULED,
                ApplicationState.CONTACTED,  # Re-contact if scheduling fails
                ApplicationState.NEEDS_REVIEW,
            },
            ApplicationState.SCHEDULED: {
                ApplicationState.INTERVIEWED,
                ApplicationState.SCHEDULING,  # Reschedule
                ApplicationState.NEEDS_REVIEW,
            },
            ApplicationState.INTERVIEWED: {
                ApplicationState.DECISION_PENDING,
                ApplicationState.CLOSED,
                ApplicationState.NEEDS_REVIEW,
            },
            ApplicationState.DECISION_PENDING: {
                ApplicationState.CLOSED,
                ApplicationState.NEEDS_REVIEW,
            },
            ApplicationState.NEEDS_REVIEW: {
                # Can transition to any state after human review
                ApplicationState.INGESTED,
                ApplicationState.PARSED,
                ApplicationState.SCORED,
                ApplicationState.ACTIONED,
                ApplicationState.CONTACTED,
                ApplicationState.SCHEDULING,
                ApplicationState.SCHEDULED,
                ApplicationState.CLOSED,
            },
            ApplicationState.EXCEPTION: {
                # Can retry from exception
                ApplicationState.INGESTED,
                ApplicationState.NEEDS_REVIEW,
            },
            ApplicationState.CLOSED: set(),  # Terminal state
        }
        return new_state in valid_transitions.get(self.state, set())


class ApplicationStateTransition(Base, TimestampMixin):
    """Tracks state transitions for audit purposes."""

    __tablename__ = "application_state_transitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )

    from_state: Mapped[ApplicationState] = mapped_column(
        SQLEnum(ApplicationState), nullable=False
    )
    to_state: Mapped[ApplicationState] = mapped_column(
        SQLEnum(ApplicationState), nullable=False
    )

    # Trigger info
    trigger: Mapped[str] = mapped_column(String(100), nullable=False)  # webhook, worker, admin, etc.
    trigger_id: Mapped[str | None] = mapped_column(String(255))  # event_id, task_id, etc.
    triggered_by: Mapped[str | None] = mapped_column(String(255))  # user or system

    # Context
    reason: Mapped[str | None] = mapped_column(Text)
    metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationship
    application: Mapped["Application"] = relationship(
        "Application", back_populates="state_transitions"
    )


class ScoringResult(Base, TimestampMixin):
    """Stores detailed scoring results for an application."""

    __tablename__ = "scoring_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )

    # Rubric info
    rubric_id: Mapped[int | None] = mapped_column(ForeignKey("rubrics.id"))
    rubric_version: Mapped[str] = mapped_column(String(50), nullable=False)

    # Overall scores
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    max_score: Mapped[float] = mapped_column(Float, nullable=False)
    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[ApplicationTier] = mapped_column(SQLEnum(ApplicationTier), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # Dimension scores
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Example: {"experience": {"score": 8, "max": 10, "evidence": "..."}, ...}

    # Hard constraints
    hard_constraints_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failed_constraints: Mapped[list[str] | None] = mapped_column(JSONB, default=list)

    # Evidence and reasoning
    evidence: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    missing_info: Mapped[list[str] | None] = mapped_column(JSONB, default=list)
    recommendation: Mapped[str | None] = mapped_column(Text)

    # Flags
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons: Mapped[list[str] | None] = mapped_column(JSONB, default=list)

    # Relationship
    application: Mapped["Application"] = relationship(
        "Application", back_populates="scoring_results"
    )
