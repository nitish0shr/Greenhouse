"""Candidate model - represents a person in Greenhouse."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.application import Application


class Candidate(Base, TimestampMixin):
    """
    Represents a candidate (person) from Greenhouse.

    A candidate can have multiple applications to different jobs.
    """

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Greenhouse IDs
    greenhouse_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )

    # Basic info (redacted in logs)
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))

    # Profile
    company: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    website_urls: Mapped[list[str] | None] = mapped_column(JSONB, default=list)

    # Resume data (extracted)
    resume_text: Mapped[str | None] = mapped_column(Text)
    resume_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_facts: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Source tracking
    source: Mapped[str | None] = mapped_column(String(255))
    referrer: Mapped[str | None] = mapped_column(String(255))

    # Tags from Greenhouse
    tags: Mapped[list[str] | None] = mapped_column(JSONB, default=list)

    # Metadata from Greenhouse
    greenhouse_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    greenhouse_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Sync status
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    needs_resync: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    applications: Mapped[list["Application"]] = relationship(
        "Application", back_populates="candidate", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Candidate(id={self.id}, greenhouse_id={self.greenhouse_id})>"

    @property
    def full_name(self) -> str:
        """Get candidate's full name."""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or "Unknown"

    @property
    def display_name(self) -> str:
        """Get a safe display name (for logging)."""
        if self.first_name:
            return f"{self.first_name} {self.last_name[0] if self.last_name else ''}."
        return f"Candidate #{self.greenhouse_id}"
