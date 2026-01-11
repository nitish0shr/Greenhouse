"""Greenhouse Harvest API client with rate limiting and retries."""

import asyncio
from datetime import datetime
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class GreenhouseAPIError(Exception):
    """Base exception for Greenhouse API errors."""

    def __init__(self, message: str, status_code: int | None = None, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class GreenhouseRateLimitError(GreenhouseAPIError):
    """Raised when rate limit is hit."""

    def __init__(self, retry_after: int = 60):
        super().__init__(f"Rate limit exceeded, retry after {retry_after}s")
        self.retry_after = retry_after


class GreenhouseNotFoundError(GreenhouseAPIError):
    """Raised when resource is not found."""
    pass


class GreenhouseClient:
    """
    Greenhouse Harvest API client.

    Features:
    - Automatic retry with exponential backoff
    - Rate limit handling
    - Connection pooling
    - Structured logging
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        mock_mode: bool = False,
    ):
        self.api_key = api_key or settings.greenhouse_api_key.get_secret_value()
        self.base_url = base_url or settings.greenhouse_api_base_url
        self.mock_mode = mock_mode or settings.mock_mode

        # Rate limiting state
        self._request_count = 0
        self._last_request_time: datetime | None = None
        self._rate_limit_remaining: int | None = None

        # HTTP client (will be initialized lazily)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                auth=(self.api_key, ""),  # Greenhouse uses Basic Auth with key as username
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "RecruiterAutopilot/1.0",
                },
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _check_rate_limit(self, response: httpx.Response) -> None:
        """Check and update rate limit state from response headers."""
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining:
            self._rate_limit_remaining = int(remaining)
            if self._rate_limit_remaining < 10:
                logger.warning(
                    "Greenhouse rate limit low",
                    remaining=self._rate_limit_remaining,
                )

    @retry(
        retry=retry_if_exception_type(GreenhouseRateLimitError),
        stop=stop_after_attempt(settings.greenhouse_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.greenhouse_retry_base_delay,
            min=1,
            max=60,
        ),
    )
    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> dict | list:
        """
        Make an API request with retry logic.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            path: API path (e.g., "/applications/123")
            params: Query parameters
            json_data: JSON body for POST/PATCH

        Returns:
            Parsed JSON response

        Raises:
            GreenhouseAPIError: On API errors
            GreenhouseRateLimitError: On rate limit (will be retried)
            GreenhouseNotFoundError: On 404
        """
        if self.mock_mode:
            return await self._mock_request(method, path, params, json_data)

        client = await self._get_client()

        logger.debug(
            "Greenhouse API request",
            method=method,
            path=path,
            params=params,
        )

        try:
            response = await client.request(
                method=method,
                url=path,
                params=params,
                json=json_data,
            )

            # Check rate limit
            self._check_rate_limit(response)

            # Handle rate limit
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "60"))
                logger.warning(
                    "Greenhouse rate limit hit",
                    retry_after=retry_after,
                )
                await asyncio.sleep(retry_after)
                raise GreenhouseRateLimitError(retry_after)

            # Handle not found
            if response.status_code == 404:
                raise GreenhouseNotFoundError(
                    f"Resource not found: {path}",
                    status_code=404,
                )

            # Handle other errors
            if response.status_code >= 400:
                error_data = response.json() if response.content else {}
                raise GreenhouseAPIError(
                    f"API error: {response.status_code}",
                    status_code=response.status_code,
                    response=error_data,
                )

            # Parse response
            if response.content:
                return response.json()
            return {}

        except httpx.RequestError as e:
            logger.error("Greenhouse API request failed", error=str(e))
            raise GreenhouseAPIError(f"Request failed: {str(e)}")

    async def _mock_request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> dict | list:
        """Return mock data for testing."""
        logger.debug("Mock Greenhouse API request", method=method, path=path)

        if "/applications/" in path and method == "GET":
            app_id = int(path.split("/")[-1]) if path.split("/")[-1].isdigit() else 12345
            return self._mock_application(app_id)

        if "/candidates/" in path and method == "GET":
            cand_id = int(path.split("/")[-1]) if path.split("/")[-1].isdigit() else 54321
            return self._mock_candidate(cand_id)

        if "/jobs/" in path and method == "GET":
            job_id = int(path.split("/")[-1]) if path.split("/")[-1].isdigit() else 99999
            return self._mock_job(job_id)

        return {}

    def _mock_application(self, app_id: int) -> dict:
        """Generate mock application data."""
        return {
            "id": app_id,
            "candidate_id": 54321,
            "prospect": False,
            "applied_at": "2024-01-15T10:00:00.000Z",
            "rejected_at": None,
            "last_activity_at": "2024-01-15T10:00:00.000Z",
            "source": {"id": 1, "public_name": "LinkedIn"},
            "credited_to": {"id": 100, "name": "John Recruiter"},
            "rejection_reason": None,
            "rejection_details": None,
            "jobs": [{"id": 99999, "name": "Software Engineer"}],
            "status": "active",
            "current_stage": {"id": 1001, "name": "Application Review"},
            "answers": [],
            "custom_fields": {},
            "attachments": [
                {
                    "filename": "resume.pdf",
                    "url": "https://example.com/resume.pdf",
                    "type": "resume",
                }
            ],
        }

    def _mock_candidate(self, cand_id: int) -> dict:
        """Generate mock candidate data."""
        return {
            "id": cand_id,
            "first_name": "Jane",
            "last_name": "Doe",
            "company": "Acme Corp",
            "title": "Senior Developer",
            "created_at": "2024-01-15T09:00:00.000Z",
            "updated_at": "2024-01-15T10:00:00.000Z",
            "last_activity": "2024-01-15T10:00:00.000Z",
            "is_private": False,
            "photo_url": None,
            "application_ids": [12345],
            "email_addresses": [
                {"value": "jane.doe@example.com", "type": "personal"}
            ],
            "phone_numbers": [
                {"value": "+1-555-123-4567", "type": "mobile"}
            ],
            "addresses": [],
            "website_addresses": [
                {"value": "https://linkedin.com/in/janedoe", "type": "linkedin"}
            ],
            "social_media_addresses": [],
            "recruiter": {"id": 100, "name": "John Recruiter"},
            "coordinator": None,
            "can_email": True,
            "tags": ["python", "backend"],
            "applications": [],
            "attachments": [],
            "custom_fields": {},
        }

    def _mock_job(self, job_id: int) -> dict:
        """Generate mock job data."""
        return {
            "id": job_id,
            "name": "Software Engineer",
            "requisition_id": "REQ-001",
            "notes": None,
            "confidential": False,
            "status": "open",
            "created_at": "2024-01-01T00:00:00.000Z",
            "opened_at": "2024-01-01T00:00:00.000Z",
            "closed_at": None,
            "updated_at": "2024-01-15T00:00:00.000Z",
            "departments": [{"id": 1, "name": "Engineering"}],
            "offices": [{"id": 1, "name": "San Francisco"}],
            "hiring_team": {
                "hiring_managers": [{"id": 200, "name": "Alice Manager"}],
                "recruiters": [{"id": 100, "name": "John Recruiter"}],
                "coordinators": [],
            },
        }

    # ==================== Application Methods ====================

    async def get_application(self, application_id: int) -> dict:
        """
        Get a single application by ID.

        Returns full application details including candidate, job, stage, etc.
        """
        return await self._request("GET", f"/applications/{application_id}")

    async def list_applications(
        self,
        job_id: int | None = None,
        status: str | None = None,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict]:
        """
        List applications with optional filters.

        Args:
            job_id: Filter by job
            status: Filter by status (active, rejected, hired)
            per_page: Results per page (max 500)
            page: Page number
        """
        params = {"per_page": per_page, "page": page}
        if job_id:
            params["job_id"] = job_id
        if status:
            params["status"] = status

        return await self._request("GET", "/applications", params=params)

    async def advance_application(
        self,
        application_id: int,
        from_stage_id: int,
    ) -> dict:
        """
        Advance an application to the next stage.

        Args:
            application_id: The application to advance
            from_stage_id: Current stage ID (for validation)
        """
        return await self._request(
            "POST",
            f"/applications/{application_id}/advance",
            json_data={"from_stage_id": from_stage_id},
        )

    async def move_application(
        self,
        application_id: int,
        from_stage_id: int,
        to_stage_id: int,
    ) -> dict:
        """
        Move an application to a specific stage.

        Args:
            application_id: The application to move
            from_stage_id: Current stage ID
            to_stage_id: Target stage ID
        """
        return await self._request(
            "POST",
            f"/applications/{application_id}/move",
            json_data={
                "from_stage_id": from_stage_id,
                "to_stage_id": to_stage_id,
            },
        )

    async def reject_application(
        self,
        application_id: int,
        rejection_reason_id: int | None = None,
        notes: str | None = None,
        rejection_email_id: int | None = None,
        send_email: bool = False,
    ) -> dict:
        """
        Reject an application.

        Args:
            application_id: The application to reject
            rejection_reason_id: Greenhouse rejection reason ID
            notes: Optional notes about the rejection
            rejection_email_id: Email template to send
            send_email: Whether to send rejection email
        """
        data: dict[str, Any] = {}
        if rejection_reason_id:
            data["rejection_reason_id"] = rejection_reason_id
        if notes:
            data["notes"] = notes
        if rejection_email_id and send_email:
            data["rejection_email"] = {
                "send_email_at": datetime.utcnow().isoformat() + "Z",
                "email_template_id": rejection_email_id,
            }

        return await self._request(
            "POST",
            f"/applications/{application_id}/reject",
            json_data=data,
        )

    async def add_application_note(
        self,
        application_id: int,
        body: str,
        user_id: int,
        visibility: str = "public",
    ) -> dict:
        """
        Add a note to an application.

        Args:
            application_id: The application
            body: Note content (HTML supported)
            user_id: The user adding the note
            visibility: "public" or "private"
        """
        return await self._request(
            "POST",
            f"/applications/{application_id}/notes",
            json_data={
                "user_id": user_id,
                "body": body,
                "visibility": visibility,
            },
        )

    async def add_application_tag(
        self,
        application_id: int,
        tag: str,
    ) -> dict:
        """Add a tag to an application."""
        return await self._request(
            "PUT",
            f"/applications/{application_id}/add_tag",
            json_data={"tag": tag},
        )

    async def update_application_custom_fields(
        self,
        application_id: int,
        custom_fields: dict,
    ) -> dict:
        """
        Update custom fields on an application.

        Args:
            application_id: The application
            custom_fields: Dict of custom field name to value
        """
        return await self._request(
            "PATCH",
            f"/applications/{application_id}",
            json_data={"custom_fields": custom_fields},
        )

    # ==================== Candidate Methods ====================

    async def get_candidate(self, candidate_id: int) -> dict:
        """Get a candidate by ID."""
        return await self._request("GET", f"/candidates/{candidate_id}")

    async def update_candidate(
        self,
        candidate_id: int,
        data: dict,
    ) -> dict:
        """Update candidate information."""
        return await self._request(
            "PATCH",
            f"/candidates/{candidate_id}",
            json_data=data,
        )

    async def add_candidate_tag(
        self,
        candidate_id: int,
        tag: str,
    ) -> dict:
        """Add a tag to a candidate."""
        return await self._request(
            "PUT",
            f"/candidates/{candidate_id}/add_tag",
            json_data={"tag": tag},
        )

    # ==================== Job Methods ====================

    async def get_job(self, job_id: int) -> dict:
        """Get a job by ID."""
        return await self._request("GET", f"/jobs/{job_id}")

    async def list_jobs(
        self,
        status: str | None = None,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict]:
        """List jobs with optional filters."""
        params = {"per_page": per_page, "page": page}
        if status:
            params["status"] = status

        return await self._request("GET", "/jobs", params=params)

    async def get_job_stages(self, job_id: int) -> list[dict]:
        """Get stages for a job."""
        return await self._request("GET", f"/jobs/{job_id}/stages")

    # ==================== Attachment Methods ====================

    async def download_attachment(self, url: str) -> bytes:
        """
        Download an attachment from Greenhouse.

        Args:
            url: The attachment URL from Greenhouse

        Returns:
            Raw file bytes
        """
        if self.mock_mode:
            # Return a mock PDF header
            return b"%PDF-1.4 mock resume content"

        client = await self._get_client()

        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.content

        except httpx.RequestError as e:
            logger.error("Failed to download attachment", url=url, error=str(e))
            raise GreenhouseAPIError(f"Download failed: {str(e)}")

    # ==================== Interview Methods ====================

    async def get_scheduled_interviews(
        self,
        application_id: int,
    ) -> list[dict]:
        """Get scheduled interviews for an application."""
        return await self._request(
            "GET",
            f"/applications/{application_id}/scheduled_interviews",
        )

    async def get_scorecards(
        self,
        application_id: int,
    ) -> list[dict]:
        """Get scorecards for an application."""
        return await self._request(
            "GET",
            f"/applications/{application_id}/scorecards",
        )

    # ==================== User Methods ====================

    async def get_user(self, user_id: int) -> dict:
        """Get a user by ID."""
        return await self._request("GET", f"/users/{user_id}")

    async def list_users(
        self,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict]:
        """List users."""
        return await self._request(
            "GET",
            "/users",
            params={"per_page": per_page, "page": page},
        )

    # ==================== Rejection Reasons ====================

    async def list_rejection_reasons(self) -> list[dict]:
        """List all rejection reasons."""
        return await self._request("GET", "/rejection_reasons")


# Singleton instance for convenience
_greenhouse_client: GreenhouseClient | None = None


def get_greenhouse_client() -> GreenhouseClient:
    """Get or create the Greenhouse client singleton."""
    global _greenhouse_client
    if _greenhouse_client is None:
        _greenhouse_client = GreenhouseClient()
    return _greenhouse_client
