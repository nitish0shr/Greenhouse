# =============================================================================
# Reply Correlator - Email Reply Correlation Service
# =============================================================================

import logging
import re
from datetime import datetime, timedelta
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.message_mapping import MessageMapping
from app.models.application import Application
from app.services.microsoft_graph import GraphClient, GraphAPIError

logger = logging.getLogger(__name__)


class ReplyCorrelator:
    """
    Correlate email replies to applications.
    
    Per First Review requirements:
    - Primary: conversationId + candidate email
    - Fallback: tracking_token [APP:application_id] in subject/body
    - Store mappings in message_mappings table
    """
    
    TRACKING_TOKEN_PATTERN = re.compile(r'\[APP:(\d+)\]')
    
    def __init__(self, db_session: Session, graph_client: Optional[GraphClient] = None):
        """
        Initialize reply correlator.
        
        Args:
            db_session: Database session for MessageMapping model
            graph_client: GraphClient instance (for fetching message details)
        """
        self.db_session = db_session
        self.graph_client = graph_client or GraphClient()
    
    async def create_mapping_from_sent_email(
        self,
        application_id: uuid.UUID,
        candidate_email: str,
        conversation_id: Optional[str] = None,
        internet_message_id: Optional[str] = None,
        tracking_token: Optional[str] = None,
    ) -> MessageMapping:
        """
        Create a message mapping when sending an email.
        
        Called after sending email via Graph sendMail.
        
        Args:
            application_id: Application UUID
            candidate_email: Candidate email address
            conversation_id: Graph conversation ID (from sendMail response)
            internet_message_id: Internet message ID (from sendMail response)
            tracking_token: Tracking token (e.g., "[APP:12345]")
        
        Returns:
            Created MessageMapping record
        """
        # Generate tracking token if not provided
        if not tracking_token:
            app_result = self.db_session.execute(
                select(Application).where(Application.id == application_id)
            )
            application = app_result.scalar_one_or_none()
            if application:
                tracking_token = f"[APP:{application.greenhouse_application_id}]"
        
        # Check for existing mapping
        if conversation_id:
            existing = self.db_session.execute(
                select(MessageMapping).where(
                    MessageMapping.conversation_id == conversation_id,
                    MessageMapping.candidate_email == candidate_email,
                )
            ).scalar_one_or_none()
            
            if existing:
                # Update existing mapping
                existing.internet_message_id = internet_message_id
                existing.tracking_token = tracking_token
                self.db_session.commit()
                return existing
        
        # Create new mapping
        mapping = MessageMapping(
            application_id=application_id,
            conversation_id=conversation_id,
            internet_message_id=internet_message_id,
            tracking_token=tracking_token,
            candidate_email=candidate_email,
        )
        self.db_session.add(mapping)
        self.db_session.commit()
        
        logger.info(f"Created message mapping: application_id={application_id}, conversation_id={conversation_id}")
        return mapping
    
    async def correlate_reply(
        self,
        message_id: str,
        mailbox: Optional[str] = None,
    ) -> Optional[MessageMapping]:
        """
        Correlate an incoming email reply to an application.
        
        Correlation methods (in order):
        1. conversationId + candidate email (from message_mappings)
        2. tracking_token [APP:application_id] (from subject/body)
        3. candidate email + fuzzy match to recent applications
        
        Args:
            message_id: Graph message ID
            mailbox: Mailbox to fetch message from
        
        Returns:
            MessageMapping if correlation successful, None otherwise
        
        Raises:
            Exception: If multiple matches found (ambiguous correlation)
        """
        # Fetch message details from Graph
        try:
            message = await self.graph_client.get_message(message_id, mailbox=mailbox)
        except GraphAPIError as e:
            logger.error(f"Failed to fetch message {message_id}: {e}")
            return None
        
        conversation_id = message.get("conversationId")
        sender_email = None
        
        # Get sender email
        sender = message.get("from", {})
        if sender:
            sender_email = sender.get("emailAddress", {}).get("address")
        
        if not sender_email:
            logger.warning(f"Message {message_id} has no sender email")
            return None
        
        # Method 1: Lookup by conversationId + candidate email
        if conversation_id:
            mapping = self.db_session.execute(
                select(MessageMapping).where(
                    MessageMapping.conversation_id == conversation_id,
                    MessageMapping.candidate_email == sender_email,
                )
            ).scalar_one_or_none()
            
            if mapping:
                logger.info(f"Correlated reply by conversationId: {message_id} -> application_id={mapping.application_id}")
                return mapping
        
        # Method 2: Extract tracking token from subject/body
        subject = message.get("subject", "")
        body = message.get("body", {}).get("content", "")
        
        # Search for tracking token
        token_match = self.TRACKING_TOKEN_PATTERN.search(f"{subject} {body}")
        if token_match:
            greenhouse_app_id = int(token_match.group(1))
            
            # Find application by greenhouse_application_id
            app_result = self.db_session.execute(
                select(Application).where(
                    Application.greenhouse_application_id == greenhouse_app_id
                )
            )
            application = app_result.scalar_one_or_none()
            
            if application:
                # Check if mapping exists
                mapping = self.db_session.execute(
                    select(MessageMapping).where(
                        MessageMapping.application_id == application.id,
                        MessageMapping.tracking_token == token_match.group(0),
                    )
                ).scalar_one_or_none()
                
                if mapping:
                    # Update with conversation_id if available
                    if conversation_id and not mapping.conversation_id:
                        mapping.conversation_id = conversation_id
                        self.db_session.commit()
                    
                    logger.info(f"Correlated reply by tracking token: {message_id} -> application_id={application.id}")
                    return mapping
        
        # Method 3: Fuzzy match by candidate email + recent applications
        # Find applications for this candidate email in last 30 days
        cutoff = datetime.utcnow() - timedelta(days=30)
        
        # This is a fallback - should rarely be used
        # We'd need to join with Candidate table to get email
        # For now, return None and create exception for human review
        logger.warning(
            f"Could not correlate reply {message_id} from {sender_email} - "
            f"no conversationId match or tracking token found"
        )
        return None
    
    def extract_tracking_token(self, text: str) -> Optional[str]:
        """
        Extract tracking token from text.
        
        Args:
            text: Text to search (subject or body)
        
        Returns:
            Tracking token string if found, None otherwise
        """
        match = self.TRACKING_TOKEN_PATTERN.search(text)
        if match:
            return match.group(0)
        return None
