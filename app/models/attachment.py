# =============================================================================
# Attachment Model - Resume and Document Storage
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Attachment(Base):
    """
    Store attachment metadata and extracted text.
    
    Tracks resume and document attachments downloaded from Greenhouse,
    with extracted text for scoring.
    """
    
    __tablename__ = "attachments"
    
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
    
    # Filename
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    # Content type (MIME type)
    content_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    # Size in bytes
    size_bytes: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
    )
    
    # SHA-256 checksum (hex)
    checksum: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    
    # Storage path (filesystem or S3)
    storage_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Extracted text content
    extracted_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<Attachment {self.filename} application_id={self.application_id}>"
