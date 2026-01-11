# =============================================================================
# Microsoft Graph API Client
# =============================================================================

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from msal import ConfidentialClientApplication

from app.config import settings

logger = logging.getLogger(__name__)


class GraphAPIError(Exception):
    """Base exception for Microsoft Graph API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class GraphClient:
    """
    Client for Microsoft Graph API.
    
    Supports both:
    - Application permissions (daemon/service account) - for shared mailboxes
    - Delegated permissions (on behalf of user) - for individual mailboxes
    
    This implementation uses application permissions by default.
    For delegated permissions, you'll need an OAuth flow to get user tokens.
    """
    
    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
    GRAPH_SCOPE = "https://graph.microsoft.com/.default"
    
    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        mailbox: Optional[str] = None,
    ):
        """
        Initialize the Graph client.
        
        Args:
            tenant_id: Azure AD tenant ID
            client_id: App registration client ID
            client_secret: App registration client secret
            mailbox: Default mailbox for sending emails
        """
        self.tenant_id = tenant_id or settings.ms_tenant_id
        self.client_id = client_id or settings.ms_client_id
        self.client_secret = client_secret or settings.ms_client_secret
        self.mailbox = mailbox or settings.ms_mailbox
        
        # Token cache
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        
        # MSAL client for token acquisition
        self._msal_app: Optional[ConfidentialClientApplication] = None
    
    def _get_msal_app(self) -> ConfidentialClientApplication:
        """Get or create MSAL application."""
        if self._msal_app is None:
            authority = f"https://login.microsoftonline.com/{self.tenant_id}"
            self._msal_app = ConfidentialClientApplication(
                client_id=self.client_id,
                client_credential=self.client_secret,
                authority=authority,
            )
        return self._msal_app
    
    async def _get_access_token(self) -> str:
        """
        Get access token for Graph API.
        
        Uses client credentials flow (application permissions).
        Caches token until near expiry.
        
        Returns:
            Access token string
        """
        # Return cached token if still valid
        if self._token and self._token_expires:
            if datetime.utcnow() < self._token_expires - timedelta(minutes=5):
                return self._token
        
        # Acquire new token
        msal_app = self._get_msal_app()
        result = msal_app.acquire_token_for_client(scopes=[self.GRAPH_SCOPE])
        
        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise GraphAPIError(f"Failed to acquire token: {error}")
        
        self._token = result["access_token"]
        # Token usually expires in 1 hour
        self._token_expires = datetime.utcnow() + timedelta(seconds=result.get("expires_in", 3600))
        
        return self._token
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """
        Make an authenticated request to Graph API.
        
        Args:
            method: HTTP method
            endpoint: API endpoint (without base URL)
            **kwargs: Additional arguments for httpx request
        
        Returns:
            JSON response data
        """
        token = await self._get_access_token()
        url = f"{self.GRAPH_BASE_URL}{endpoint}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs,
            )
            
            if response.status_code >= 400:
                error_data = None
                try:
                    error_data = response.json()
                except Exception:
                    pass
                
                raise GraphAPIError(
                    f"Graph API error: {response.status_code}",
                    status_code=response.status_code,
                    response=error_data,
                )
            
            if response.status_code == 204:
                return {}
            
            return response.json()
    
    # -------------------------------------------------------------------------
    # Email Operations
    # -------------------------------------------------------------------------
    
    async def send_mail(
        self,
        to: list[str],
        subject: str,
        body: str,
        body_type: str = "HTML",
        from_mailbox: Optional[str] = None,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        save_to_sent: bool = True,
        importance: str = "normal",
    ) -> dict:
        """
        Send an email via Microsoft Graph.
        
        POST /users/{mailbox}/sendMail
        
        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Email body (HTML or text)
            body_type: "HTML" or "Text"
            from_mailbox: Sender mailbox (defaults to configured mailbox)
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            save_to_sent: Whether to save to Sent Items
            importance: "low", "normal", or "high"
        
        Returns:
            Empty dict on success (202 response)
        """
        mailbox = from_mailbox or self.mailbox
        
        # Build recipients
        to_recipients = [{"emailAddress": {"address": addr}} for addr in to]
        cc_recipients = [{"emailAddress": {"address": addr}} for addr in (cc or [])]
        bcc_recipients = [{"emailAddress": {"address": addr}} for addr in (bcc or [])]
        
        payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": body_type,
                    "content": body,
                },
                "toRecipients": to_recipients,
                "ccRecipients": cc_recipients,
                "bccRecipients": bcc_recipients,
                "importance": importance,
            },
            "saveToSentItems": save_to_sent,
        }
        
        logger.info(f"Sending email to {to} from {mailbox}")
        
        return await self._request(
            "POST",
            f"/users/{mailbox}/sendMail",
            json=payload,
        )
    
    async def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        body_type: str = "HTML",
        from_mailbox: Optional[str] = None,
    ) -> dict:
        """
        Create a draft email.
        
        POST /users/{mailbox}/messages
        
        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Email body
            body_type: "HTML" or "Text"
            from_mailbox: Mailbox to create draft in
        
        Returns:
            Created message data including ID
        """
        mailbox = from_mailbox or self.mailbox
        
        to_recipients = [{"emailAddress": {"address": addr}} for addr in to]
        
        payload = {
            "subject": subject,
            "body": {
                "contentType": body_type,
                "content": body,
            },
            "toRecipients": to_recipients,
        }
        
        return await self._request(
            "POST",
            f"/users/{mailbox}/messages",
            json=payload,
        )
    
    async def get_messages(
        self,
        mailbox: Optional[str] = None,
        folder: str = "inbox",
        top: int = 10,
        filter_query: Optional[str] = None,
    ) -> list:
        """
        Get messages from a mailbox folder.
        
        GET /users/{mailbox}/mailFolders/{folder}/messages
        
        Args:
            mailbox: Mailbox to query
            folder: Folder name (inbox, sentitems, etc.)
            top: Number of messages to retrieve
            filter_query: OData filter query
        
        Returns:
            List of message objects
        """
        mailbox = mailbox or self.mailbox
        
        params = {
            "$top": top,
            "$orderby": "receivedDateTime desc",
        }
        
        if filter_query:
            params["$filter"] = filter_query
        
        result = await self._request(
            "GET",
            f"/users/{mailbox}/mailFolders/{folder}/messages",
            params=params,
        )
        
        return result.get("value", [])
    
    async def get_message(
        self,
        message_id: str,
        mailbox: Optional[str] = None,
    ) -> dict:
        """
        Get a specific message by ID.
        
        GET /users/{mailbox}/messages/{id}
        
        Args:
            message_id: Graph message ID
            mailbox: Mailbox to query
        
        Returns:
            Message object with full details
        """
        mailbox = mailbox or self.mailbox
        
        return await self._request(
            "GET",
            f"/users/{mailbox}/messages/{message_id}",
        )
    
    # -------------------------------------------------------------------------
    # Calendar Operations
    # -------------------------------------------------------------------------
    
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
        """
        Create a calendar event.
        
        POST /users/{mailbox}/events
        
        Args:
            subject: Event subject
            start: Start datetime
            end: End datetime
            attendees: List of attendee email addresses
            mailbox: Calendar owner mailbox
            location: Event location
            body: Event description
            is_online_meeting: Whether to create a Teams meeting
        
        Returns:
            Created event data including ID
        """
        mailbox = mailbox or self.mailbox
        
        attendee_list = [
            {
                "emailAddress": {"address": addr},
                "type": "required",
            }
            for addr in attendees
        ]
        
        payload = {
            "subject": subject,
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": "UTC",
            },
            "attendees": attendee_list,
            "isOnlineMeeting": is_online_meeting,
        }
        
        if location:
            payload["location"] = {"displayName": location}
        
        if body:
            payload["body"] = {
                "contentType": "HTML",
                "content": body,
            }
        
        if is_online_meeting:
            payload["onlineMeetingProvider"] = "teamsForBusiness"
        
        logger.info(f"Creating calendar event: {subject}")
        
        return await self._request(
            "POST",
            f"/users/{mailbox}/events",
            json=payload,
        )
    
    async def update_calendar_event(
        self,
        event_id: str,
        mailbox: Optional[str] = None,
        subject: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        location: Optional[str] = None,
    ) -> dict:
        """
        Update a calendar event.
        
        PATCH /users/{mailbox}/events/{id}
        
        Args:
            event_id: Event ID to update
            mailbox: Calendar owner mailbox
            subject: New subject
            start: New start datetime
            end: New end datetime
            location: New location
        
        Returns:
            Updated event data
        """
        mailbox = mailbox or self.mailbox
        
        payload = {}
        
        if subject:
            payload["subject"] = subject
        if start:
            payload["start"] = {
                "dateTime": start.isoformat(),
                "timeZone": "UTC",
            }
        if end:
            payload["end"] = {
                "dateTime": end.isoformat(),
                "timeZone": "UTC",
            }
        if location:
            payload["location"] = {"displayName": location}
        
        return await self._request(
            "PATCH",
            f"/users/{mailbox}/events/{event_id}",
            json=payload,
        )
    
    async def delete_calendar_event(
        self,
        event_id: str,
        mailbox: Optional[str] = None,
    ) -> dict:
        """
        Delete a calendar event.
        
        DELETE /users/{mailbox}/events/{id}
        
        Args:
            event_id: Event ID to delete
            mailbox: Calendar owner mailbox
        
        Returns:
            Empty dict on success
        """
        mailbox = mailbox or self.mailbox
        
        return await self._request(
            "DELETE",
            f"/users/{mailbox}/events/{event_id}",
        )
    
    async def get_free_busy_schedule(
        self,
        user_emails: list[str],
        start_time: datetime,
        end_time: datetime,
        availability_view_interval: int = 30,  # minutes
    ) -> dict:
        """
        Get free/busy availability for users.
        
        POST /users/{user}/calendar/getSchedule
        
        Per First Review requirements:
        - Used for "Propose 3 slots" scheduling mode
        - Returns availability view for determining open slots
        
        Args:
            user_emails: List of user email addresses to check
            start_time: Start of time range to check
            end_time: End of time range to check
            availability_view_interval: Interval in minutes for availability view
        
        Returns:
            Dict with schedules for each user, including availabilityView
        """
        payload = {
            "schedules": user_emails,
            "startTime": {
                "dateTime": start_time.isoformat(),
                "timeZone": "UTC",
            },
            "endTime": {
                "dateTime": end_time.isoformat(),
                "timeZone": "UTC",
            },
            "availabilityViewInterval": availability_view_interval,
        }
        
        logger.info(f"Getting free/busy schedule for {len(user_emails)} users")
        
        return await self._request(
            "POST",
            f"/users/{self.mailbox}/calendar/getSchedule",
            json=payload,
        )
    
    async def find_free_slots(
        self,
        interviewer_emails: list[str],
        start_range: datetime,
        end_range: datetime,
        duration_minutes: int = 60,
        num_slots: int = 3,
        working_hours_start: int = 9,  # 9 AM
        working_hours_end: int = 17,   # 5 PM
    ) -> list[dict]:
        """
        Find available meeting slots for interviewers.
        
        Per First Review requirements:
        - Find 3 available slots using Graph free/busy (availabilityView)
        - Consider working hours
        - All specified interviewers must be free
        
        Args:
            interviewer_emails: Emails of required attendees
            start_range: Start of search range
            end_range: End of search range  
            duration_minutes: Required slot duration
            num_slots: Number of slots to find
            working_hours_start: Start hour (0-23)
            working_hours_end: End hour (0-23)
        
        Returns:
            List of available slot dicts with start/end times
        """
        # Get free/busy data
        schedule_data = await self.get_free_busy_schedule(
            user_emails=interviewer_emails,
            start_time=start_range,
            end_time=end_range,
            availability_view_interval=30,  # 30-minute granularity
        )
        
        schedules = schedule_data.get("value", [])
        
        # Parse availability views
        # availabilityView is a string where each character represents a slot:
        # 0 = free, 1 = tentative, 2 = busy, 3 = out of office, 4 = working elsewhere
        availability_views = []
        for schedule in schedules:
            view = schedule.get("availabilityView", "")
            availability_views.append(view)
        
        if not availability_views:
            return []
        
        # Find slots where all interviewers are free (value 0)
        min_length = min(len(v) for v in availability_views) if availability_views else 0
        
        available_slots = []
        current_time = start_range
        interval_minutes = 30
        slots_needed = duration_minutes // interval_minutes
        
        for i in range(min_length - slots_needed + 1):
            # Check if all interviewers are free for the required duration
            all_free = True
            for view in availability_views:
                for j in range(slots_needed):
                    if i + j >= len(view) or view[i + j] != '0':
                        all_free = False
                        break
                if not all_free:
                    break
            
            if all_free:
                slot_start = start_range + timedelta(minutes=i * interval_minutes)
                slot_end = slot_start + timedelta(minutes=duration_minutes)
                
                # Check working hours
                if (working_hours_start <= slot_start.hour < working_hours_end and
                    working_hours_start <= slot_end.hour <= working_hours_end):
                    
                    # Skip weekends
                    if slot_start.weekday() < 5:  # Monday = 0, Friday = 4
                        available_slots.append({
                            "start": slot_start.isoformat(),
                            "end": slot_end.isoformat(),
                            "timezone": "UTC",
                        })
                        
                        if len(available_slots) >= num_slots:
                            break
        
        logger.info(f"Found {len(available_slots)} available slots for interviewers")
        return available_slots

    # -------------------------------------------------------------------------
    # Change Notifications (Webhooks)
    # -------------------------------------------------------------------------
    
    async def create_subscription(
        self,
        resource: str,
        notification_url: str,
        change_types: list[str],
        expiration_minutes: int = 4230,  # Max ~3 days for most resources
        client_state: Optional[str] = None,
    ) -> dict:
        """
        Create a change notification subscription.
        
        POST /subscriptions
        
        This allows receiving webhooks when resources change.
        
        Args:
            resource: Resource to watch (e.g., "users/{id}/messages")
            notification_url: HTTPS endpoint to receive notifications
            change_types: Types to watch: "created", "updated", "deleted"
            expiration_minutes: Subscription duration in minutes
            client_state: Secret to validate notifications
        
        Returns:
            Created subscription data including ID
        """
        expiration = datetime.utcnow() + timedelta(minutes=expiration_minutes)
        
        payload = {
            "changeType": ",".join(change_types),
            "notificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": expiration.isoformat() + "Z",
        }
        
        if client_state:
            payload["clientState"] = client_state
        
        logger.info(f"Creating Graph subscription for: {resource}")
        
        return await self._request(
            "POST",
            "/subscriptions",
            json=payload,
        )
    
    async def renew_subscription(
        self,
        subscription_id: str,
        expiration_minutes: int = 4230,
    ) -> dict:
        """
        Renew a subscription.
        
        PATCH /subscriptions/{id}
        
        Args:
            subscription_id: Subscription ID to renew
            expiration_minutes: New expiration duration
        
        Returns:
            Updated subscription data
        """
        expiration = datetime.utcnow() + timedelta(minutes=expiration_minutes)
        
        payload = {
            "expirationDateTime": expiration.isoformat() + "Z",
        }
        
        return await self._request(
            "PATCH",
            f"/subscriptions/{subscription_id}",
            json=payload,
        )
    
    async def delete_subscription(
        self,
        subscription_id: str,
    ) -> dict:
        """
        Delete a subscription.
        
        DELETE /subscriptions/{id}
        
        Args:
            subscription_id: Subscription ID to delete
        
        Returns:
            Empty dict on success
        """
        return await self._request(
            "DELETE",
            f"/subscriptions/{subscription_id}",
        )


# Create default client instance
graph_client = GraphClient()
