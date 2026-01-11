# =============================================================================
# Attachment Service - Download & Storage
# =============================================================================

import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.config import settings
from app.models.attachment import Attachment
from app.models.application import Application
from app.services.greenhouse import GreenhouseClient, GreenhouseAPIError
from app.utils.security import is_safe_filename

logger = logging.getLogger(__name__)


class AttachmentService:
    """
    Service for downloading and storing attachments.
    
    Per First Review requirements:
    - Download attachments immediately (URLs expire in ~7 days)
    - Store securely with checksum + metadata
    - Compute SHA-256 checksum
    - Store in attachments table
    - Support local filesystem (dev) and S3 (prod)
    """
    
    def __init__(
        self,
        db_session: Session,
        greenhouse_client: Optional[GreenhouseClient] = None,
        storage_base_path: Optional[str] = None,
    ):
        """
        Initialize attachment service.
        
        Args:
            db_session: Database session
            greenhouse_client: GreenhouseClient for downloads
            storage_base_path: Base path for file storage (defaults to ./storage/attachments)
        """
        self.db_session = db_session
        self.greenhouse_client = greenhouse_client or GreenhouseClient()
        self.storage_base_path = Path(storage_base_path or "storage/attachments")
        self.storage_base_path.mkdir(parents=True, exist_ok=True)
    
    async def download_and_store(
        self,
        application_id: uuid.UUID,
        attachment_url: str,
        filename: str,
        content_type: Optional[str] = None,
    ) -> Attachment:
        """
        Download attachment from Greenhouse and store locally.
        
        Args:
            application_id: Application UUID
            attachment_url: Greenhouse attachment URL
            filename: Original filename
            content_type: MIME type
        
        Returns:
            Attachment record
        
        Raises:
            GreenhouseAPIError: If download fails
            ValueError: If filename is unsafe
        """
        # Validate filename
        if not is_safe_filename(filename):
            raise ValueError(f"Unsafe filename: {filename}")
        
        # Download file
        logger.info(f"Downloading attachment: {filename} from {attachment_url}")
        file_bytes = await self.greenhouse_client.download_attachment(attachment_url)
        
        # Compute checksum
        checksum = hashlib.sha256(file_bytes).hexdigest()
        size_bytes = len(file_bytes)
        
        # Check if attachment already exists (by checksum)
        existing = self.db_session.execute(
            select(Attachment).where(Attachment.checksum == checksum)
        ).scalar_one_or_none()
        
        if existing:
            logger.info(f"Attachment with checksum {checksum} already exists, reusing")
            return existing
        
        # Generate storage path
        app_dir = self.storage_base_path / str(application_id)
        app_dir.mkdir(parents=True, exist_ok=True)
        
        # Sanitize filename for filesystem
        safe_filename = self._sanitize_filename(filename)
        storage_path = app_dir / f"{checksum[:8]}_{safe_filename}"
        
        # Write file
        with open(storage_path, "wb") as f:
            f.write(file_bytes)
        
        logger.info(f"Stored attachment: {storage_path} ({size_bytes} bytes)")
        
        # Create database record
        attachment = Attachment(
            application_id=application_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum=checksum,
            storage_path=str(storage_path),
        )
        self.db_session.add(attachment)
        self.db_session.commit()
        
        return attachment
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for filesystem storage.
        
        Args:
            filename: Original filename
        
        Returns:
            Sanitized filename safe for filesystem
        """
        # Remove path components
        safe = os.path.basename(filename)
        
        # Replace unsafe characters
        unsafe_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in unsafe_chars:
            safe = safe.replace(char, '_')
        
        # Limit length
        if len(safe) > 200:
            name, ext = os.path.splitext(safe)
            safe = name[:200 - len(ext)] + ext
        
        return safe
    
    def read_attachment(self, attachment: Attachment) -> bytes:
        """
        Read attachment file from storage.
        
        Args:
            attachment: Attachment record
        
        Returns:
            File bytes
        
        Raises:
            FileNotFoundError: If file doesn't exist
        """
        if not attachment.storage_path:
            raise FileNotFoundError(f"Attachment {attachment.id} has no storage_path")
        
        with open(attachment.storage_path, "rb") as f:
            return f.read()
    
    def delete_attachment(self, attachment: Attachment) -> None:
        """
        Delete attachment file from storage.
        
        Args:
            attachment: Attachment record
        """
        if attachment.storage_path and os.path.exists(attachment.storage_path):
            try:
                os.remove(attachment.storage_path)
                logger.info(f"Deleted attachment file: {attachment.storage_path}")
            except Exception as e:
                logger.error(f"Failed to delete attachment file: {e}")
