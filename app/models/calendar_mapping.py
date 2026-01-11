# =============================================================================
# Calendar Mapping Model - Interview Event Synchronization
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CalendarMapping(Base):
    """
    Track calendar event mappings between Outlook and Greenhouse.
    
    Maps external_event_id (Outlook) to greenhouse_interview_id for
    synchronization of reschedules and cancellations.
    """
    
    __tablename__ = "calendar_mappings"
    
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
    
    # Outlook event ID (UNIQUE constraint)
    external_event_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Greenhouse interview ID
    greenhouse_interview_id: Mapped[Optional[int]] = mapped_column(
        nullable=True,
    )
    
    # Status: 'scheduled', 'rescheduled', 'cancelled'
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="scheduled",
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<CalendarMapping external_event_id={self.external_event_id} greenhouse_interview_id={self.greenhouse_interview_id}>"
