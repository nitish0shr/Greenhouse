"""Email log and template models."""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class EmailStatus(str, Enum):
    """Status of an outbound email."""

    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    FAILED = "failed"


class EmailDirection(str, Enum):
    """Direction of email."""

    OUTBOUND = "outbound"
    INBOUND = "inbound"


class EmailLog(Base, TimestampMixin):
    """
    Log of all emails sent/received through the system.

    Outbound emails are sent via Microsoft Graph.
    Inbound emails are received via Graph change notifications.
    """

    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Direction
    direction: Mapped[EmailDirection] = mapped_column(
        SQLEnum(EmailDirection), nullable=False, index=True
    )

    # Related entities
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id"), index=True
    )

    # Email details
    message_id: Mapped[str | None] = mapped_column(String(500), unique=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(500), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(500))

    # Addresses
    from_address: Mapped[str] = mapped_column(String(255), nullable=False)
    to_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    cc_addresses: Mapped[list[str] | None] = mapped_column(JSONB, default=list)
    bcc_addresses: Mapped[list[str] | None] = mapped_column(JSONB, default=list)
    reply_to: Mapped[str | None] = mapped_column(String(255))

    # Content
    subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    body_preview: Mapped[str | None] = mapped_column(Text)  # First 500 chars
    body_html: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)

    # Template info (for outbound)
    template_name: Mapped[str | None] = mapped_column(String(100))
    template_version: Mapped[str | None] = mapped_column(String(50))
    template_variables: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Status
    status: Mapped[EmailStatus] = mapped_column(
        SQLEnum(EmailStatus), default=EmailStatus.PENDING, nullable=False, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Bounce/error details
    error_message: Mapped[str | None] = mapped_column(Text)
    bounce_type: Mapped[str | None] = mapped_column(String(50))

    # Inbound processing (for replies)
    intent_classified: Mapped[str | None] = mapped_column(String(50))
    intent_confidence: Mapped[float | None] = mapped_column()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Graph API details
    graph_message_id: Mapped[str | None] = mapped_column(String(500))
    graph_change_key: Mapped[str | None] = mapped_column(String(500))

    # Greenhouse note ID (if logged to timeline)
    greenhouse_note_id: Mapped[int | None] = mapped_column(BigInteger)

    # Correlation
    correlation_id: Mapped[str | None] = mapped_column(String(100))

    def __repr__(self) -> str:
        return f"<EmailLog(id={self.id}, direction={self.direction.value}, status={self.status.value})>"


class EmailTemplate(Base, TimestampMixin):
    """
    Email templates with variable substitution.

    Templates use Jinja2 syntax for variable substitution.
    """

    __tablename__ = "email_templates"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Identification
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(50), default="1.0")

    # Template content
    subject_template: Mapped[str] = mapped_column(String(1000), nullable=False)
    body_html_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_text_template: Mapped[str | None] = mapped_column(Text)

    # Available variables
    available_variables: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Example: ["candidate_name", "job_title", "company_name", "interview_date"]

    # Required variables (template won't render without these)
    required_variables: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # Default values for optional variables
    default_values: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Usage context
    use_cases: Mapped[list[str] | None] = mapped_column(JSONB, default=list)
    # Example: ["initial_outreach", "interview_invite", "rejection"]

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Audit
    created_by: Mapped[str | None] = mapped_column(String(255))
    last_modified_by: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:
        return f"<EmailTemplate(id={self.id}, name={self.name}, version={self.version})>"
