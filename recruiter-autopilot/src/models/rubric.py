"""Rubric model for scoring configuration."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.job import Job


class Rubric(Base, TimestampMixin):
    """
    Scoring rubric for evaluating candidates.

    Each rubric can have multiple versions for tracking changes.
    """

    __tablename__ = "rubrics"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)

    # Active version
    active_version: Mapped[str] = mapped_column(String(50), default="1.0")

    # Configuration (parsed from YAML)
    # Dimensions with weights
    dimensions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Example:
    # {
    #   "experience": {"weight": 0.3, "description": "...", "scoring": {...}},
    #   "skills": {"weight": 0.4, ...},
    #   ...
    # }

    # Hard constraints (auto-reject if not met)
    hard_constraints: Mapped[list[dict] | None] = mapped_column(JSONB, default=list)
    # Example:
    # [
    #   {"name": "min_experience", "type": "years", "min": 2},
    #   {"name": "required_skill", "type": "skill", "value": "Python"},
    # ]

    # Tier thresholds
    tier_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Example: {"A": 0.85, "B": 0.70, "C": 0.50}

    # Confidence settings
    confidence_threshold: Mapped[float] = mapped_column(default=0.7)
    low_confidence_triggers_review: Mapped[bool] = mapped_column(Boolean, default=True)

    # Flags for special handling
    needs_human_review_rules: Mapped[list[dict] | None] = mapped_column(JSONB, default=list)
    # Example:
    # [
    #   {"condition": "tier == 'B' and confidence < 0.8"},
    #   {"condition": "missing_info contains 'work_authorization'"},
    # ]

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Audit
    created_by: Mapped[str | None] = mapped_column(String(255))
    last_modified_by: Mapped[str | None] = mapped_column(String(255))

    # Relationships
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="rubric")
    versions: Mapped[list["RubricVersion"]] = relationship(
        "RubricVersion",
        back_populates="rubric",
        lazy="selectin",
        order_by="RubricVersion.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Rubric(id={self.id}, slug={self.slug}, version={self.active_version})>"

    @property
    def version_string(self) -> str:
        """Get full version string."""
        return f"{self.slug}@{self.active_version}"


class RubricVersion(Base, TimestampMixin):
    """Version history for rubrics."""

    __tablename__ = "rubric_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    rubric_id: Mapped[int] = mapped_column(
        ForeignKey("rubrics.id"), nullable=False, index=True
    )

    # Version info
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text)

    # Full configuration snapshot
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Audit
    created_by: Mapped[str | None] = mapped_column(String(255))

    # Relationship
    rubric: Mapped["Rubric"] = relationship("Rubric", back_populates="versions")
