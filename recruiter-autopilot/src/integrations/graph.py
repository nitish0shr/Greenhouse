"""Microsoft Graph API client for Outlook email and calendar."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import httpx
import msal

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class GraphAPIError(Exception):
    """Base exception for Graph API errors."""

    def __init__(self, message: str, status_code: int | None = None, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class GraphRateLimitError(GraphAPIError):
    """Raised when rate limit is hit."""

    def __init__(self, retry_after: int = 60):
        super().__init__(f"Rate limit exceeded, retry after {retry_after}s")
        self.retry_after = retry_after


class MicrosoftGraphClient:
    """
    Microsoft Graph API client for email and calendar operations.

    Features:
    - OAuth2 client credentials flow
    - Token caching and refresh
    - Rate limit handling
    - Shared mailbox support
    """

    def __init__(
        self,
        tenant_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        shared_mailbox: str | None = None,
        mock_mode: bool = False,
    ):
        self.tenant_id = tenant_id or settings.ms_tenant_id
        self.client_id = client_id or settings.ms_client_id
        self.client_secret = client_secret or settings.ms_client_secret.get_secret_value()
        self.shared_mailbox = shared_mailbox or settings.ms_shared_mailbox
        self.mock_mode = mock_mode or settings.mock_mode
        self.base_url = settings.ms_graph_base_url

        # Token state
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

        # MSAL app
        self._msal_app: msal.ConfidentialClientApplication | None = None

        # HTTP client
        self._client: httpx.AsyncClient | None = None

    def _get_msal_app(self) -> msal.ConfidentialClientApplication:
        """Get or create MSAL application."""
        if self._msal_app is None:
            self._msal_app = msal.ConfidentialClientApplication(
                client_id=self.client_id,
                client_credential=self.client_secret,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            )
        return self._msal_app

    async def _get_access_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        if self.mock_mode:
            return "mock-token"

        # Check if current token is still valid
        if self._access_token and self._token_expires_at:
            if datetime.utcnow() < self._token_expires_at - timedelta(minutes=5):
                return self._access_token

        # Acquire new token
        msal_app = self._get_msal_app()

        result = msal_app.acquire_token_for_client(scopes=settings.ms_graph_scopes)

        if "access_token" in result:
            self._access_token = result["access_token"]
            self._token_expires_at = datetime.utcnow() + timedelta(
                seconds=result.get("expires_in", 3600)
            )
            logger.debug("Acquired new Graph access token")
            return self._access_token

        error = result.get("error", "unknown")
        error_desc = result.get("error_description", "No description")
        logger.error("Failed to acquire Graph token", error=error, description=error_desc)
        raise GraphAPIError(f"Token acquisition failed: {error} - {error_desc}")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with valid auth."""
        token = await self._get_access_token()

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "RecruiterAutopilot/1.0",
                },
                timeout=httpx.Timeout(30.0),
            )

        # Update authorization header
        self._client.headers["Authorization"] = f"Bearer {token}"
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> dict | list:
        """Make an authenticated API request."""
        if self.mock_mode:
            return await self._mock_request(method, path, params, json_data)

        client = await self._get_client()

        logger.debug(
            "Graph API request",
            method=method,
            path=path,
        )

        try:
            response = await client.request(
                method=method,
                url=path,
                params=params,
                json=json_data,
            )

            # Handle rate limit
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "60"))
                logger.warning("Graph rate limit hit", retry_after=retry_after)
                await asyncio.sleep(retry_after)
                raise GraphRateLimitError(retry_after)

            # Handle errors
            if response.status_code >= 400:
                error_data = response.json() if response.content else {}
                raise GraphAPIError(
                    f"API error: {response.status_code}",
                    status_code=response.status_code,
                    response=error_data,
                )

            if response.content:
                return response.json()
            return {}

        except httpx.RequestError as e:
            logger.error("Graph API request failed", error=str(e))
            raise GraphAPIError(f"Request failed: {str(e)}")

    async def _mock_request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> dict | list:
        """Return mock data for testing."""
        logger.debug("Mock Graph API request", method=method, path=path)

        if "sendMail" in path and method == "POST":
            return {}  # Success, no response body

        if "/events" in path and method == "POST":
            return {
                "id": "mock-event-id-123",
                "subject": json_data.get("subject", "Mock Event") if json_data else "Mock Event",
                "start": json_data.get("start", {}) if json_data else {},
                "end": json_data.get("end", {}) if json_data else {},
                "webLink": "https://outlook.com/calendar/mock-event",
            }

        if "/calendarView" in path or "/events" in path:
            return {"value": []}

        if "/messages" in path:
            return {"value": []}

        return {}

    # ==================== Email Methods ====================

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body_html: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        importance: str = "normal",
        save_to_sent_items: bool = True,
    ) -> dict:
        """
        Send an email via the shared mailbox.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            body_html: HTML body content
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            reply_to: Optional reply-to address
            importance: "low", "normal", or "high"
            save_to_sent_items: Whether to save to sent folder
        """
        message = {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body_html,
            },
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
            "importance": importance,
        }

        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

        if bcc:
            message["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in bcc]

        if reply_to:
            message["replyTo"] = [{"emailAddress": {"address": reply_to}}]

        # Use shared mailbox
        endpoint = f"/users/{self.shared_mailbox}/sendMail"

        return await self._request(
            "POST",
            endpoint,
            json_data={
                "message": message,
                "saveToSentItems": save_to_sent_items,
            },
        )

    async def get_message(self, message_id: str) -> dict:
        """Get a specific email message."""
        return await self._request(
            "GET",
            f"/users/{self.shared_mailbox}/messages/{message_id}",
        )

    async def list_messages(
        self,
        folder: str = "inbox",
        top: int = 50,
        filter_query: str | None = None,
        select: list[str] | None = None,
    ) -> list[dict]:
        """
        List messages in a folder.

        Args:
            folder: Folder name (inbox, sentitems, etc.)
            top: Number of messages to return
            filter_query: OData filter query
            select: Fields to select
        """
        params: dict[str, Any] = {"$top": top}

        if filter_query:
            params["$filter"] = filter_query

        if select:
            params["$select"] = ",".join(select)

        result = await self._request(
            "GET",
            f"/users/{self.shared_mailbox}/mailFolders/{folder}/messages",
            params=params,
        )

        return result.get("value", [])

    # ==================== Calendar Methods ====================

    async def create_event(
        self,
        subject: str,
        start: datetime,
        end: datetime,
        attendees: list[str],
        body_html: str | None = None,
        location: str | None = None,
        is_online_meeting: bool = True,
        timezone: str = "UTC",
    ) -> dict:
        """
        Create a calendar event.

        Args:
            subject: Event title
            start: Start datetime
            end: End datetime
            attendees: List of attendee email addresses
            body_html: Optional HTML body
            location: Optional location string
            is_online_meeting: Create Teams meeting link
            timezone: Timezone for the event
        """
        event = {
            "subject": subject,
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": timezone,
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": timezone,
            },
            "attendees": [
                {
                    "emailAddress": {"address": email},
                    "type": "required",
                }
                for email in attendees
            ],
            "isOnlineMeeting": is_online_meeting,
        }

        if body_html:
            event["body"] = {
                "contentType": "HTML",
                "content": body_html,
            }

        if location:
            event["location"] = {"displayName": location}

        if is_online_meeting:
            event["onlineMeetingProvider"] = "teamsForBusiness"

        return await self._request(
            "POST",
            f"/users/{self.shared_mailbox}/events",
            json_data=event,
        )

    async def update_event(
        self,
        event_id: str,
        updates: dict,
    ) -> dict:
        """Update an existing calendar event."""
        return await self._request(
            "PATCH",
            f"/users/{self.shared_mailbox}/events/{event_id}",
            json_data=updates,
        )

    async def delete_event(self, event_id: str) -> None:
        """Delete a calendar event."""
        await self._request(
            "DELETE",
            f"/users/{self.shared_mailbox}/events/{event_id}",
        )

    async def get_event(self, event_id: str) -> dict:
        """Get a specific calendar event."""
        return await self._request(
            "GET",
            f"/users/{self.shared_mailbox}/events/{event_id}",
        )

    async def get_calendar_view(
        self,
        start: datetime,
        end: datetime,
        user_email: str | None = None,
    ) -> list[dict]:
        """
        Get calendar events in a time range.

        Args:
            start: Start of range
            end: End of range
            user_email: Optional user email (defaults to shared mailbox)
        """
        email = user_email or self.shared_mailbox

        result = await self._request(
            "GET",
            f"/users/{email}/calendarView",
            params={
                "startDateTime": start.isoformat() + "Z",
                "endDateTime": end.isoformat() + "Z",
            },
        )

        return result.get("value", [])

    async def get_free_busy(
        self,
        user_emails: list[str],
        start: datetime,
        end: datetime,
        interval_minutes: int = 30,
    ) -> dict:
        """
        Get free/busy status for users.

        Returns availability information for scheduling.
        """
        schedules = user_emails

        result = await self._request(
            "POST",
            "/me/calendar/getSchedule",
            json_data={
                "schedules": schedules,
                "startTime": {
                    "dateTime": start.isoformat(),
                    "timeZone": "UTC",
                },
                "endTime": {
                    "dateTime": end.isoformat(),
                    "timeZone": "UTC",
                },
                "availabilityViewInterval": interval_minutes,
            },
        )

        return result

    async def find_meeting_times(
        self,
        attendees: list[str],
        duration_minutes: int,
        start: datetime,
        end: datetime,
        max_candidates: int = 5,
    ) -> list[dict]:
        """
        Find available meeting times.

        Uses the Graph findMeetingTimes endpoint to suggest times.
        """
        result = await self._request(
            "POST",
            f"/users/{self.shared_mailbox}/findMeetingTimes",
            json_data={
                "attendees": [
                    {"emailAddress": {"address": email}}
                    for email in attendees
                ],
                "timeConstraint": {
                    "timeslots": [
                        {
                            "start": {
                                "dateTime": start.isoformat(),
                                "timeZone": "UTC",
                            },
                            "end": {
                                "dateTime": end.isoformat(),
                                "timeZone": "UTC",
                            },
                        }
                    ]
                },
                "meetingDuration": f"PT{duration_minutes}M",
                "maxCandidates": max_candidates,
                "isOrganizerOptional": False,
                "returnSuggestionReasons": True,
            },
        )

        return result.get("meetingTimeSuggestions", [])

    # ==================== Subscription Methods ====================

    async def create_subscription(
        self,
        resource: str,
        change_type: str,
        notification_url: str,
        expiration_datetime: datetime,
        client_state: str | None = None,
    ) -> dict:
        """
        Create a change notification subscription.

        Args:
            resource: Resource to watch (e.g., "/users/{id}/messages")
            change_type: "created", "updated", "deleted" (comma-separated)
            notification_url: Webhook endpoint URL (must be HTTPS)
            expiration_datetime: When subscription expires
            client_state: Optional secret for validation
        """
        subscription = {
            "changeType": change_type,
            "notificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": expiration_datetime.isoformat() + "Z",
        }

        if client_state:
            subscription["clientState"] = client_state

        return await self._request(
            "POST",
            "/subscriptions",
            json_data=subscription,
        )

    async def renew_subscription(
        self,
        subscription_id: str,
        expiration_datetime: datetime,
    ) -> dict:
        """Renew an existing subscription."""
        return await self._request(
            "PATCH",
            f"/subscriptions/{subscription_id}",
            json_data={
                "expirationDateTime": expiration_datetime.isoformat() + "Z",
            },
        )

    async def delete_subscription(self, subscription_id: str) -> None:
        """Delete a subscription."""
        await self._request(
            "DELETE",
            f"/subscriptions/{subscription_id}",
        )

    async def list_subscriptions(self) -> list[dict]:
        """List all active subscriptions."""
        result = await self._request("GET", "/subscriptions")
        return result.get("value", [])


# Singleton instance
_graph_client: MicrosoftGraphClient | None = None


def get_graph_client() -> MicrosoftGraphClient:
    """Get or create the Graph client singleton."""
    global _graph_client
    if _graph_client is None:
        _graph_client = MicrosoftGraphClient()
    return _graph_client
