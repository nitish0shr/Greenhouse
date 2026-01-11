# =============================================================================
# Rubric Version Model - Scoring Rubric Versions
# =============================================================================

from datetime import datetime
import uuid

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RubricVersion(Base):
    """
    Store rubric YAML versions.
    
    Each version contains the complete rubric YAML for scoring candidates.
    """
    
    __tablename__ = "rubric_versions"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Version string (e.g., "1.0.0") - UNIQUE constraint
    version: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
    )
    
    # Rubric YAML content
    rubric_yaml: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<RubricVersion {self.version}>"
