"""Audit log model for tracking all system actions."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class AuditLog(Base):
    """
    Comprehensive audit log for all system actions.

    Tracks who did what, when, and with what result.
    Critical for compliance and debugging.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Timestamp (no updated_at for immutable audit logs)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False, index=True
    )

    # Actor
    actor_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "system", "worker", "admin", "webhook"
    actor_id: Mapped[str | None] = mapped_column(String(255))  # user email, worker id, etc.

    # Action
    action: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )  # "application.scored", "email.sent", etc.
    action_category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # "application", "email", "calendar", etc.

    # Target entities
    target_type: Mapped[str | None] = mapped_column(String(50))  # "application", "candidate", etc.
    target_id: Mapped[int | None] = mapped_column(BigInteger, index=True)

    # Greenhouse IDs (for filtering)
    greenhouse_application_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    greenhouse_candidate_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    greenhouse_job_id: Mapped[int | None] = mapped_column(BigInteger, index=True)

    # Action details
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Before/after state (for mutations)
    previous_state: Mapped[dict | None] = mapped_column(JSONB)
    new_state: Mapped[dict | None] = mapped_column(JSONB)

    # Full context (redacted of PII in logs)
    context: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Result
    success: Mapped[bool] = mapped_column(default=True)
    error_message: Mapped[str | None] = mapped_column(Text)

    # External API calls
    external_api: Mapped[str | None] = mapped_column(String(50))  # "greenhouse", "graph", etc.
    external_request_id: Mapped[str | None] = mapped_column(String(255))
    external_response_code: Mapped[int | None] = mapped_column()

    # Correlation
    correlation_id: Mapped[str | None] = mapped_column(String(100), index=True)
    parent_audit_id: Mapped[int | None] = mapped_column(BigInteger)

    # IP and user agent (for admin actions)
    ip_address: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, success={self.success})>"

    @classmethod
    def create(
        cls,
        action: str,
        action_category: str,
        description: str,
        actor_type: str = "system",
        actor_id: str | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        greenhouse_application_id: int | None = None,
        greenhouse_candidate_id: int | None = None,
        greenhouse_job_id: int | None = None,
        previous_state: dict | None = None,
        new_state: dict | None = None,
        context: dict | None = None,
        success: bool = True,
        error_message: str | None = None,
        correlation_id: str | None = None,
        external_api: str | None = None,
        external_request_id: str | None = None,
        external_response_code: int | None = None,
    ) -> "AuditLog":
        """Factory method to create an audit log entry."""
        return cls(
            action=action,
            action_category=action_category,
            description=description,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            greenhouse_application_id=greenhouse_application_id,
            greenhouse_candidate_id=greenhouse_candidate_id,
            greenhouse_job_id=greenhouse_job_id,
            previous_state=previous_state,
            new_state=new_state,
            context=context,
            success=success,
            error_message=error_message,
            correlation_id=correlation_id,
            external_api=external_api,
            external_request_id=external_request_id,
            external_response_code=external_response_code,
        )
