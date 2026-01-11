# =============================================================================
# Exception Service - DLQ Management & Retry Logic
# =============================================================================

import logging
from datetime import datetime, timedelta
from typing import Optional
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.exception import Exception as ExceptionModel

logger = logging.getLogger(__name__)


class ExceptionService:
    """
    Service for managing exceptions and dead-letter queue.
    
    Per First Review requirements:
    - Create exception records on failures
    - Retry logic with exponential backoff (max 7 retries)
    - Move to DLQ after max retries
    - Support replay
    """
    
    MAX_RETRIES = 7
    INITIAL_RETRY_DELAY = 60  # 1 minute
    MAX_RETRY_DELAY = 3600  # 1 hour
    
    def __init__(self, db_session: Session):
        """
        Initialize exception service.
        
        Args:
            db_session: Database session
        """
        self.db_session = db_session
    
    def create_exception(
        self,
        exception_type: str,
        reason: str,
        application_id: Optional[uuid.UUID] = None,
        payload_refs: Optional[dict] = None,
        last_error: Optional[str] = None,
    ) -> ExceptionModel:
        """
        Create an exception record.
        
        Args:
            exception_type: Type of exception (e.g., 'api_failure', 'missing_mapping')
            reason: Reason/description
            application_id: Application UUID (if applicable)
            payload_refs: Payload references (greenhouse_event_id, autopilot_action_id, etc.)
            last_error: Error message
        
        Returns:
            Created Exception record
        """
        exception = ExceptionModel(
            application_id=application_id,
            exception_type=exception_type,
            reason=reason,
            status="open",
            retry_count=0,
            next_retry_at=None,
            last_error=last_error,
            payload_refs=payload_refs or {},
        )
        self.db_session.add(exception)
        self.db_session.commit()
        
        logger.info(f"Created exception: {exception_type} - {reason}")
        return exception
    
    def increment_retry(
        self,
        exception_id: uuid.UUID,
        error_message: Optional[str] = None,
    ) -> Optional[ExceptionModel]:
        """
        Increment retry count and calculate next retry time.
        
        Args:
            exception_id: Exception ID
            error_message: Latest error message
        
        Returns:
            Updated Exception record, or None if max retries exceeded
        """
        exception = self.db_session.get(ExceptionModel, exception_id)
        if not exception:
            return None
        
        exception.retry_count += 1
        
        if exception.retry_count > self.MAX_RETRIES:
            # Move to DLQ (status = 'retrying' but won't retry anymore)
            exception.status = "retrying"
            exception.next_retry_at = None
            logger.warning(f"Exception {exception_id} exceeded max retries, moved to DLQ")
        else:
            # Calculate next retry time with exponential backoff
            delay = min(
                self.INITIAL_RETRY_DELAY * (2 ** (exception.retry_count - 1)),
                self.MAX_RETRY_DELAY
            )
            # Add jitter (random 0-10% of delay)
            import random
            jitter = delay * random.uniform(0, 0.1)
            delay = int(delay + jitter)
            
            exception.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
            exception.status = "retrying"
            logger.info(f"Exception {exception_id} retry {exception.retry_count}/{self.MAX_RETRIES}, next retry in {delay}s")
        
        if error_message:
            exception.last_error = error_message
        
        self.db_session.commit()
        return exception
    
    def resolve_exception(
        self,
        exception_id: uuid.UUID,
    ) -> ExceptionModel:
        """
        Mark exception as resolved.
        
        Args:
            exception_id: Exception ID
        
        Returns:
            Updated Exception record
        """
        exception = self.db_session.get(ExceptionModel, exception_id)
        if not exception:
            raise ValueError(f"Exception not found: {exception_id}")
        
        exception.status = "resolved"
        exception.resolved_at = datetime.utcnow()
        self.db_session.commit()
        
        logger.info(f"Resolved exception: {exception_id}")
        return exception
    
    def get_retryable_exceptions(self) -> list[ExceptionModel]:
        """
        Get exceptions ready for retry.
        
        Returns exceptions with status='retrying' and next_retry_at <= now.
        
        Returns:
            List of Exception records ready for retry
        """
        now = datetime.utcnow()
        
        result = self.db_session.execute(
            select(ExceptionModel).where(
                ExceptionModel.status == "retrying",
                ExceptionModel.next_retry_at <= now,
            ).order_by(ExceptionModel.next_retry_at)
        )
        
        return list(result.scalars().all())
    
    def get_dlq_exceptions(self) -> list[ExceptionModel]:
        """
        Get exceptions in dead-letter queue.
        
        Returns exceptions with retry_count > MAX_RETRIES.
        
        Returns:
            List of Exception records in DLQ
        """
        result = self.db_session.execute(
            select(ExceptionModel).where(
                ExceptionModel.retry_count > self.MAX_RETRIES,
                ExceptionModel.status != "resolved",
            ).order_by(ExceptionModel.created_at.desc())
        )
        
        return list(result.scalars().all())
