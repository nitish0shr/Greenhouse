# =============================================================================
# Mock Graph Client - For Testing and Development
# =============================================================================

import logging
from typing import Optional
from datetime import datetime, timedelta
import uuid

logger = logging.getLogger(__name__)


class MockGraphClient:
    """
    Mock Microsoft Graph client for testing and mock mode.
    
    Provides the same interface as GraphClient but returns
    deterministic mock data instead of making real API calls.
    """
    
    def __init__(self):
        """Initialize mock client."""
        self.messages = {}
        self.events = {}
        self.subscriptions = {}
        self._setup_mock_data()
    
    def _setup_mock_data(self):
        """Setup initial mock data."""
        # Sample message
        self.messages["msg-123"] = {
            "id": "msg-123",
            "conversationId": "conv-123",
            "subject": "Test Email",
            "from": {
                "emailAddress": {
                    "address": "candidate@example.com",
                    "name": "Candidate",
                },
            },
            "body": {
                "content": "This is a test email",
                "contentType": "HTML",
            },
            "receivedDateTime": datetime.utcnow().isoformat(),
        }
        
        # Sample event
        self.events["event-123"] = {
            "id": "event-123",
            "subject": "Interview: John Doe - Software Engineer",
            "start": {
                "dateTime": (datetime.utcnow() + timedelta(days=7)).isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": (datetime.utcnow() + timedelta(days=7, hours=1)).isoformat(),
                "timeZone": "UTC",
            },
            "attendees": [
                {
                    "emailAddress": {"address": "candidate@example.com"},
                    "type": "required",
                },
            ],
        }
    
    async def send_mail(
        self,
        to: list[str],
        subject: str,
        body: str,
        mailbox: Optional[str] = None,
    ) -> dict:
        """Send email (mock)."""
        message_id = f"msg-{uuid.uuid4().hex[:8]}"
        message_data = {
            "id": message_id,
            "conversationId": f"conv-{uuid.uuid4().hex[:8]}",
            "subject": subject,
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
            "body": {"content": body, "contentType": "HTML"},
            "sentDateTime": datetime.utcnow().isoformat(),
        }
        self.messages[message_id] = message_data
        logger.info(f"[MOCK] Sent email: {subject} to {', '.join(to)}")
        return message_data
    
    async def create_calendar_event(
        self,
        subject: str,
        start: datetime,
        end: datetime,
        attendees: list[str],
        mailbox: Optional[str] = None,
        location: Optional[str] = None,
        body: Optional[str] = None,
        is_online_meeting: bool = False,
    ) -> dict:
        """Create calendar event (mock)."""
        event_id = f"event-{uuid.uuid4().hex[:8]}"
        event_data = {
            "id": event_id,
            "subject": subject,
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": "UTC",
            },
            "attendees": [
                {
                    "emailAddress": {"address": addr},
                    "type": "required",
                }
                for addr in attendees
            ],
            "location": {"displayName": location} if location else None,
            "body": {"content": body, "contentType": "HTML"} if body else None,
            "isOnlineMeeting": is_online_meeting,
        }
        self.events[event_id] = event_data
        logger.info(f"[MOCK] Created calendar event: {subject}")
        return event_data
    
    async def update_calendar_event(
        self,
        event_id: str,
        mailbox: Optional[str] = None,
        subject: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        location: Optional[str] = None,
    ) -> dict:
        """Update calendar event (mock)."""
        if event_id not in self.events:
            raise Exception(f"Event not found: {event_id}")
        
        event = self.events[event_id]
        if subject:
            event["subject"] = subject
        if start:
            event["start"] = {"dateTime": start.isoformat(), "timeZone": "UTC"}
        if end:
            event["end"] = {"dateTime": end.isoformat(), "timeZone": "UTC"}
        if location:
            event["location"] = {"displayName": location}
        
        logger.info(f"[MOCK] Updated calendar event: {event_id}")
        return event
    
    async def delete_calendar_event(
        self,
        event_id: str,
        mailbox: Optional[str] = None,
    ) -> dict:
        """Delete calendar event (mock)."""
        if event_id not in self.events:
            raise Exception(f"Event not found: {event_id}")
        
        del self.events[event_id]
        logger.info(f"[MOCK] Deleted calendar event: {event_id}")
        return {}
    
    async def get_message(
        self,
        message_id: str,
        mailbox: Optional[str] = None,
    ) -> dict:
        """Get message (mock)."""
        if message_id not in self.messages:
            raise Exception(f"Message not found: {message_id}")
        return self.messages[message_id]
    
    async def get_free_busy(
        self,
        mailbox: Optional[str] = None,
        schedules: Optional[list[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        availability_view_interval: int = 60,
    ) -> dict:
        """Get free/busy (mock - returns all free)."""
        # Return all free (all 0s in availability view)
        # Each character represents 15 minutes, so 96 chars = 24 hours
        availability_view = "0" * 96
        
        return {
            "value": [
                {
                    "scheduleId": schedule or mailbox or "user@example.com",
                    "availabilityView": availability_view,
                    "scheduleItems": [],
                }
                for schedule in (schedules or [mailbox or "user@example.com"])
            ],
        }
    
    async def create_subscription(
        self,
        resource: str,
        notification_url: str,
        change_types: list[str],
        expiration_minutes: int = 4230,
        client_state: Optional[str] = None,
    ) -> dict:
        """Create subscription (mock)."""
        subscription_id = f"sub-{uuid.uuid4().hex[:8]}"
        expiration = datetime.utcnow() + timedelta(minutes=expiration_minutes)
        
        subscription_data = {
            "id": subscription_id,
            "resource": resource,
            "notificationUrl": notification_url,
            "changeType": ",".join(change_types),
            "expirationDateTime": expiration.isoformat() + "Z",
            "clientState": client_state,
        }
        self.subscriptions[subscription_id] = subscription_data
        logger.info(f"[MOCK] Created subscription: {subscription_id}")
        return subscription_data
    
    async def renew_subscription(
        self,
        subscription_id: str,
        expiration_minutes: int = 4230,
    ) -> dict:
        """Renew subscription (mock)."""
        if subscription_id not in self.subscriptions:
            raise Exception(f"Subscription not found: {subscription_id}")
        
        subscription = self.subscriptions[subscription_id]
        expiration = datetime.utcnow() + timedelta(minutes=expiration_minutes)
        subscription["expirationDateTime"] = expiration.isoformat() + "Z"
        logger.info(f"[MOCK] Renewed subscription: {subscription_id}")
        return subscription
    
    async def delete_subscription(
        self,
        subscription_id: str,
    ) -> dict:
        """Delete subscription (mock)."""
        if subscription_id not in self.subscriptions:
            raise Exception(f"Subscription not found: {subscription_id}")
        
        del self.subscriptions[subscription_id]
        logger.info(f"[MOCK] Deleted subscription: {subscription_id}")
        return {}
