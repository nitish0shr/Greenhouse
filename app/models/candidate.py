# =============================================================================
# Candidate Model - Local Cache of Greenhouse Candidate Data
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Candidate(Base):
    """
    Local cache of candidate data from Greenhouse.
    
    Stores key candidate information for fast access and reduces API calls.
    Synced from Greenhouse when webhooks are received or manually refreshed.
    """
    
    __tablename__ = "candidates"
    
    # Primary key (internal)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Greenhouse candidate ID (external) - matches First Review schema
    greenhouse_candidate_id: Mapped[int] = mapped_column(
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Basic info
    first_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    last_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    # Contact info
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    # Location
    location: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Social profiles and links
    linkedin_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    website_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Parsed resume text (for scoring)
    resume_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Tags applied in Greenhouse
    tags: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    
    # Custom fields from Greenhouse
    custom_fields: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    
    # Full raw data from Greenhouse API
    raw_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
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
    greenhouse_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    greenhouse_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Relationships
    applications = relationship("Application", back_populates="candidate")
    
    # Indexes
    __table_args__ = (
        Index("ix_candidates_name", "first_name", "last_name"),
    )
    
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
    
    def __repr__(self) -> str:
        return f"<Candidate {self.greenhouse_candidate_id}: {self.full_name}>"
