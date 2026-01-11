# =============================================================================
# Message Mapping Model - Email Correlation Tracking
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MessageMapping(Base):
    """
    Track email message correlations for reply handling.
    
    Maps Graph conversationId, internetMessageId, and tracking tokens to
    applications for deterministic reply correlation.
    """
    
    __tablename__ = "message_mappings"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Foreign key to application
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id"),
        nullable=False,
        index=True,
    )
    
    # Graph conversation ID
    conversation_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    
    # Internet message ID
    internet_message_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # Tracking token (e.g., "[APP:12345]")
    tracking_token: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    
    # Candidate email (required for correlation)
    candidate_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    # UNIQUE constraint: conversation_id + candidate_email (for deterministic correlation)
    __table_args__ = (
        UniqueConstraint("conversation_id", "candidate_email", name="uq_message_mappings_conversation_email"),
    )
    
    def __repr__(self) -> str:
        return f"<MessageMapping application_id={self.application_id} conversation_id={self.conversation_id}>"
