# =============================================================================
# Greenhouse Harvest API Client
# =============================================================================

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class OAuthTokenManager:
    """Manages OAuth 2.0 tokens for Greenhouse Harvest V3 API."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str = "https://id.greenhouse.io/oauth/token",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    @property
    def is_token_valid(self) -> bool:
        """Check if current token is still valid (with 5-minute buffer)."""
        if not self._access_token or not self._token_expires_at:
            return False
        return datetime.now() < (self._token_expires_at - timedelta(minutes=5))

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self.is_token_valid:
            return self._access_token

        return await self._fetch_new_token()

    async def _fetch_new_token(self) -> str:
        """Fetch a new access token using client credentials flow."""
        logger.info("Fetching new OAuth access token from Greenhouse")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                error_msg = f"Failed to obtain OAuth token: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg += f" - {error_data}"
                except Exception:
                    pass
                logger.error(error_msg)
                raise GreenhouseAPIError(error_msg, status_code=response.status_code)

            token_data = response.json()
            self._access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)  # Default 1 hour
            self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)

            logger.info(f"Successfully obtained OAuth token, expires in {expires_in}s")
            return self._access_token

    def invalidate_token(self):
        """Invalidate the current token (e.g., after a 401 response)."""
        self._access_token = None
        self._token_expires_at = None


class GreenhouseAPIError(Exception):
    """Base exception for Greenhouse API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class GreenhouseRateLimitError(GreenhouseAPIError):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, retry_after: int = 60):
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")
        self.retry_after = retry_after


class GreenhouseClient:
    """
    Client for Greenhouse Harvest API.

    Features:
    - OAuth 2.0 client credentials flow (Harvest V3 API)
    - Fallback to Basic Auth (legacy API key)
    - Automatic rate limit handling with exponential backoff
    - On-Behalf-Of header for write operations
    - Async HTTP requests
    - Attachment download with expiration handling
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        on_behalf_of: Optional[int] = None,
        base_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        token_url: Optional[str] = None,
    ):
        """
        Initialize the Greenhouse client.

        Args:
            api_key: Harvest API key (legacy, defaults to config)
            on_behalf_of: User ID for On-Behalf-Of header (defaults to config)
            base_url: API base URL (defaults to config)
            client_id: OAuth client ID (defaults to config)
            client_secret: OAuth client secret (defaults to config)
            token_url: OAuth token URL (defaults to config)
        """
        self.api_key = api_key or settings.greenhouse_api_key
        self.on_behalf_of = on_behalf_of or settings.greenhouse_on_behalf_of
        self.base_url = base_url or settings.greenhouse_api_base_url

        # OAuth credentials
        self.client_id = client_id or settings.greenhouse_client_id
        self.client_secret = client_secret or settings.greenhouse_client_secret
        self.token_url = token_url or settings.greenhouse_token_url

        # Initialize OAuth token manager if OAuth credentials are configured
        self._token_manager: Optional[OAuthTokenManager] = None
        if self.client_id and self.client_secret:
            self._token_manager = OAuthTokenManager(
                client_id=self.client_id,
                client_secret=self.client_secret,
                token_url=self.token_url,
            )
            logger.info("Greenhouse client initialized with OAuth 2.0 authentication")
        elif self.api_key:
            logger.info("Greenhouse client initialized with Basic Auth (legacy API key)")
        else:
            logger.warning("Greenhouse client initialized without authentication credentials")

        # Rate limiting state
        self._rate_limit_until: Optional[datetime] = None
        self._consecutive_429s = 0

    @property
    def uses_oauth(self) -> bool:
        """Check if client is using OAuth authentication."""
        return self._token_manager is not None

    async def _get_headers(self, write_operation: bool = False) -> dict:
        """Get headers for API requests."""
        headers = {
            "Content-Type": "application/json",
        }

        # Add OAuth Bearer token if using OAuth
        if self._token_manager:
            access_token = await self._token_manager.get_access_token()
            headers["Authorization"] = f"Bearer {access_token}"

        # On-Behalf-Of header is required for write operations
        if write_operation and self.on_behalf_of:
            headers["On-Behalf-Of"] = str(self.on_behalf_of)

        return headers

    def _get_auth(self) -> Optional[httpx.BasicAuth]:
        """Get Basic auth with API key as username (legacy authentication)."""
        if self._token_manager:
            return None  # Using OAuth, no Basic Auth needed
        if self.api_key:
            return httpx.BasicAuth(self.api_key, "")
        return None
    
    async def _handle_rate_limit(self, response: httpx.Response) -> int:
        """
        Handle 429 rate limit response.
        
        Returns the number of seconds to wait before retrying.
        """
        self._consecutive_429s += 1
        
        # Get Retry-After header if present
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                wait_seconds = int(retry_after)
            except ValueError:
                wait_seconds = 60
        else:
            # Exponential backoff: 30s, 60s, 120s, 240s, max 300s
            wait_seconds = min(30 * (2 ** (self._consecutive_429s - 1)), 300)
        
        logger.warning(
            f"Rate limited by Greenhouse. Waiting {wait_seconds}s. "
            f"Consecutive 429s: {self._consecutive_429s}"
        )
        
        return wait_seconds
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        write_operation: bool = False,
        max_retries: int = 3,
        **kwargs,
    ) -> dict:
        """
        Make an API request with rate limit handling.

        Args:
            method: HTTP method
            endpoint: API endpoint (without base URL)
            write_operation: Whether this is a write operation
            max_retries: Maximum number of retries for rate limits
            **kwargs: Additional arguments for httpx request

        Returns:
            JSON response data

        Raises:
            GreenhouseAPIError: On API errors
            GreenhouseRateLimitError: When rate limit exhausted after retries
        """
        url = f"{self.base_url}{endpoint}"
        auth = self._get_auth()

        for attempt in range(max_retries + 1):
            try:
                # Get headers (async because it may fetch OAuth token)
                headers = await self._get_headers(write_operation)

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        auth=auth,
                        **kwargs,
                    )

                    # Handle rate limiting
                    if response.status_code == 429:
                        if attempt < max_retries:
                            wait_seconds = await self._handle_rate_limit(response)
                            await asyncio.sleep(wait_seconds)
                            continue
                        else:
                            raise GreenhouseRateLimitError()

                    # Handle 401 Unauthorized - invalidate OAuth token and retry
                    if response.status_code == 401 and self._token_manager:
                        if attempt < max_retries:
                            logger.warning("Received 401, invalidating OAuth token and retrying")
                            self._token_manager.invalidate_token()
                            continue
                        else:
                            raise GreenhouseAPIError(
                                "Authentication failed after token refresh",
                                status_code=401,
                            )

                    # Reset consecutive 429 counter on success
                    self._consecutive_429s = 0

                    # Handle other errors
                    if response.status_code >= 400:
                        error_data = None
                        try:
                            error_data = response.json()
                        except Exception:
                            pass

                        raise GreenhouseAPIError(
                            f"API error: {response.status_code}",
                            status_code=response.status_code,
                            response=error_data,
                        )

                    # Return JSON response (or empty dict for 204)
                    if response.status_code == 204:
                        return {}

                    return response.json()

            except httpx.TimeoutException as e:
                logger.warning(f"Request timeout on attempt {attempt + 1}: {e}")
                if attempt == max_retries:
                    raise GreenhouseAPIError(f"Request timeout after {max_retries + 1} attempts")
                await asyncio.sleep(5)
    
    # -------------------------------------------------------------------------
    # Read Operations
    # -------------------------------------------------------------------------
    
    async def get_application(self, application_id: int) -> dict:
        """
        Fetch application details.
        
        GET /applications/{id}
        
        Args:
            application_id: Greenhouse application ID
        
        Returns:
            Application data
        """
        return await self._request("GET", f"/applications/{application_id}")
    
    async def get_candidate(self, candidate_id: int) -> dict:
        """
        Fetch candidate details.
        
        GET /candidates/{id}
        
        Args:
            candidate_id: Greenhouse candidate ID
        
        Returns:
            Candidate data with applications and attachments
        """
        return await self._request("GET", f"/candidates/{candidate_id}")
    
    async def get_job(self, job_id: int) -> dict:
        """
        Fetch job details.
        
        GET /jobs/{id}
        
        Args:
            job_id: Greenhouse job ID
        
        Returns:
            Job data with stages
        """
        return await self._request("GET", f"/jobs/{job_id}")
    
    async def get_job_stages(self, job_id: int) -> list:
        """
        Fetch stages for a job.
        
        GET /jobs/{id}/stages
        
        Args:
            job_id: Greenhouse job ID
        
        Returns:
            List of stage objects
        """
        return await self._request("GET", f"/jobs/{job_id}/stages")
    
    async def get_rejection_reasons(self) -> list:
        """
        Fetch all rejection reasons.
        
        GET /rejection_reasons
        
        Returns:
            List of rejection reason objects
        """
        return await self._request("GET", "/rejection_reasons")
    
    # -------------------------------------------------------------------------
    # Attachment Download
    # -------------------------------------------------------------------------
    
    async def download_attachment(self, url: str) -> bytes:
        """
        Download an attachment from Greenhouse.
        
        IMPORTANT: Attachment URLs expire! Download immediately when received.
        
        Args:
            url: Attachment URL from candidate data
        
        Returns:
            Raw file bytes
        
        Raises:
            GreenhouseAPIError: If download fails
        """
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url)
                
                if response.status_code != 200:
                    raise GreenhouseAPIError(
                        f"Failed to download attachment: {response.status_code}",
                        status_code=response.status_code,
                    )
                
                return response.content
                
        except httpx.TimeoutException:
            raise GreenhouseAPIError("Attachment download timeout")
    
    # -------------------------------------------------------------------------
    # Write Operations (require On-Behalf-Of header)
    # -------------------------------------------------------------------------
    
    async def add_note_to_candidate(
        self,
        candidate_id: int,
        note: str,
        visibility: str = "public",
    ) -> dict:
        """
        Add a note to a candidate.
        
        POST /candidates/{id}/activity_feed/notes
        
        Args:
            candidate_id: Greenhouse candidate ID
            note: Note body text
            visibility: "public" or "private"
        
        Returns:
            Created note data
        """
        payload = {
            "user_id": self.on_behalf_of,
            "body": note,
            "visibility": visibility,
        }
        
        return await self._request(
            "POST",
            f"/candidates/{candidate_id}/activity_feed/notes",
            write_operation=True,
            json=payload,
        )
    
    async def add_email_note(
        self,
        candidate_id: int,
        to: str,
        from_email: str,
        subject: str,
        body: str,
    ) -> dict:
        """
        Add an email note to candidate activity feed.
        
        POST /candidates/{id}/activity_feed/emails
        
        This logs an email that was sent externally (via Outlook/Graph).
        
        Args:
            candidate_id: Greenhouse candidate ID
            to: Recipient email
            from_email: Sender email
            subject: Email subject
            body: Email body (HTML or text)
        
        Returns:
            Created email note data
        """
        payload = {
            "user_id": self.on_behalf_of,
            "to": to,
            "from": from_email,
            "subject": subject,
            "body": body,
        }
        
        return await self._request(
            "POST",
            f"/candidates/{candidate_id}/activity_feed/emails",
            write_operation=True,
            json=payload,
        )
    
    async def add_tag(self, candidate_id: int, tag: str) -> dict:
        """
        Add a tag to a candidate.
        
        PUT /candidates/{id}/tags
        
        Args:
            candidate_id: Greenhouse candidate ID
            tag: Tag name to add
        
        Returns:
            Updated tags
        """
        payload = {"tag": tag}
        
        return await self._request(
            "PUT",
            f"/candidates/{candidate_id}/tags/{tag}",
            write_operation=True,
        )
    
    async def update_candidate_custom_field(
        self,
        candidate_id: int,
        custom_field_id: int,
        value: Any,
    ) -> dict:
        """
        Update a custom field on a candidate.
        
        PATCH /candidates/{id}
        
        Args:
            candidate_id: Greenhouse candidate ID
            custom_field_id: ID of the custom field
            value: New value for the field
        
        Returns:
            Updated candidate data
        """
        payload = {
            "custom_fields": [
                {
                    "id": custom_field_id,
                    "value": value,
                }
            ]
        }
        
        return await self._request(
            "PATCH",
            f"/candidates/{candidate_id}",
            write_operation=True,
            json=payload,
        )
    
    # -------------------------------------------------------------------------
    # Stage Transitions
    # -------------------------------------------------------------------------
    
    async def advance_application(
        self,
        application_id: int,
        from_stage_id: Optional[int] = None,
    ) -> dict:
        """
        Advance an application to the next stage.
        
        POST /applications/{id}/advance
        
        Args:
            application_id: Greenhouse application ID
            from_stage_id: Current stage ID (optional, for verification)
        
        Returns:
            Updated application data
        """
        payload = {}
        if from_stage_id:
            payload["from_stage_id"] = from_stage_id
        
        return await self._request(
            "POST",
            f"/applications/{application_id}/advance",
            write_operation=True,
            json=payload if payload else None,
        )
    
    async def reject_application(
        self,
        application_id: int,
        rejection_reason_id: Optional[int] = None,
        rejection_email_template_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """
        Reject an application.
        
        POST /applications/{id}/reject
        
        WARNING: This action is irreversible via API!
        
        Args:
            application_id: Greenhouse application ID
            rejection_reason_id: ID of rejection reason
            rejection_email_template_id: Optional email template to send
            notes: Optional rejection notes
        
        Returns:
            Updated application data
        """
        payload = {}
        
        if rejection_reason_id:
            payload["rejection_reason_id"] = rejection_reason_id
        
        if rejection_email_template_id:
            payload["rejection_email"] = {
                "email_template_id": rejection_email_template_id,
                "send_email_at": None,  # Send immediately
            }
        
        if notes:
            payload["notes"] = notes
        
        return await self._request(
            "POST",
            f"/applications/{application_id}/reject",
            write_operation=True,
            json=payload if payload else None,
        )
    
    async def move_application_to_stage(
        self,
        application_id: int,
        stage_id: int,
    ) -> dict:
        """
        Move an application to a specific stage.
        
        PUT /applications/{id}/move
        
        Args:
            application_id: Greenhouse application ID
            stage_id: Target stage ID
        
        Returns:
            Updated application data
        """
        payload = {"to_stage_id": stage_id}
        
        return await self._request(
            "PUT",
            f"/applications/{application_id}/move",
            write_operation=True,
            json=payload,
        )
    
    # -------------------------------------------------------------------------
    # Interview Scheduling
    # -------------------------------------------------------------------------
    
    async def create_scheduled_interview(
        self,
        application_id: int,
        interview_id: int,
        interviewers: list[dict],
        start: datetime,
        end: datetime,
        external_event_id: Optional[str] = None,
        location: Optional[str] = None,
    ) -> dict:
        """
        Create a scheduled interview.
        
        POST /scheduled_interviews
        
        Note: Only interviews created via Harvest API can be updated/deleted
        via Harvest API.
        
        Args:
            application_id: Greenhouse application ID
            interview_id: Greenhouse interview type ID
            interviewers: List of interviewer dicts with user_id
            start: Interview start datetime
            end: Interview end datetime
            external_event_id: External calendar event ID (e.g., Outlook)
            location: Interview location
        
        Returns:
            Created scheduled interview data
        """
        payload = {
            "application_id": application_id,
            "interview_id": interview_id,
            "interviewers": interviewers,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        
        if external_event_id:
            payload["external_event_id"] = external_event_id
        
        if location:
            payload["location"] = location
        
        return await self._request(
            "POST",
            "/scheduled_interviews",
            write_operation=True,
            json=payload,
        )
    
    async def update_scheduled_interview(
        self,
        interview_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        location: Optional[str] = None,
        interviewers: Optional[list[dict]] = None,
    ) -> dict:
        """
        Update a scheduled interview.
        
        PATCH /v1/scheduled_interviews/{id}
        
        Args:
            interview_id: Scheduled interview ID
            start: New start time
            end: New end time
            location: New location
            interviewers: Updated interviewer list
        
        Returns:
            Updated interview data
        """
        payload = {}
        if start:
            payload["start"] = start.isoformat()
        if end:
            payload["end"] = end.isoformat()
        if location:
            payload["location"] = location
        if interviewers:
            payload["interviewers"] = interviewers
        
        return await self._request(
            "PATCH",
            f"/scheduled_interviews/{interview_id}",
            write_operation=True,
            json=payload,
        )
    
    async def delete_scheduled_interview(
        self,
        interview_id: int,
    ) -> dict:
        """
        Delete/cancel a scheduled interview.
        
        DELETE /v1/scheduled_interviews/{id}
        
        Args:
            interview_id: Scheduled interview ID
        
        Returns:
            Empty dict on success
        """
        return await self._request(
            "DELETE",
            f"/scheduled_interviews/{interview_id}",
            write_operation=True,
        )
    
    async def get_scheduled_interview(
        self,
        interview_id: int,
    ) -> dict:
        """
        Get scheduled interview details.
        
        GET /v1/scheduled_interviews/{id}
        
        Args:
            interview_id: Scheduled interview ID
        
        Returns:
            Interview data
        """
        return await self._request("GET", f"/scheduled_interviews/{interview_id}")
    
    async def update_scheduled_interview(
        self,
        scheduled_interview_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        external_event_id: Optional[str] = None,
        location: Optional[str] = None,
    ) -> dict:
        """
        Update a scheduled interview.
        
        PATCH /scheduled_interviews/{id}
        
        Note: Only interviews created via Harvest API can be updated.
        
        Args:
            scheduled_interview_id: Greenhouse scheduled interview ID
            start: New start datetime
            end: New end datetime
            external_event_id: External calendar event ID
            location: Interview location
        
        Returns:
            Updated scheduled interview data
        """
        payload = {}
        
        if start:
            payload["start"] = start.isoformat()
        if end:
            payload["end"] = end.isoformat()
        if external_event_id:
            payload["external_event_id"] = external_event_id
        if location:
            payload["location"] = location
        
        return await self._request(
            "PATCH",
            f"/scheduled_interviews/{scheduled_interview_id}",
            write_operation=True,
            json=payload,
        )
    
    async def delete_scheduled_interview(
        self,
        scheduled_interview_id: int,
    ) -> dict:
        """
        Delete a scheduled interview.
        
        DELETE /scheduled_interviews/{id}
        
        Note: Only interviews created via Harvest API can be deleted.
        
        Args:
            scheduled_interview_id: Greenhouse scheduled interview ID
        
        Returns:
            Empty dict on success
        """
        return await self._request(
            "DELETE",
            f"/scheduled_interviews/{scheduled_interview_id}",
            write_operation=True,
        )


# Create default client instance
greenhouse_client = GreenhouseClient()
