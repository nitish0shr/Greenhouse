# =============================================================================
# Job Config Model - Per-Job Automation Settings
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class JobConfig(Base):
    """
    Per-job automation configuration.
    
    Stores thresholds, enabled stages, templates, and scheduling mode per job.
    """
    
    __tablename__ = "job_configs"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Greenhouse job ID (UNIQUE constraint)
    greenhouse_job_id: Mapped[int] = mapped_column(
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Enabled flag (global kill switch per job)
    enabled: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
    )
    
    # Scoring thresholds
    advance_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=75,
    )
    reject_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=25,
    )
    human_review_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50,
    )
    
    # Scheduling mode: 'send_link' or 'propose_slots'
    scheduling_mode: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="propose_slots",
    )
    
    # Email templates (JSONB)
    email_templates: Mapped[dict] = mapped_column(
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
    
    def __repr__(self) -> str:
        return f"<JobConfig job_id={self.greenhouse_job_id} enabled={self.enabled}>"
