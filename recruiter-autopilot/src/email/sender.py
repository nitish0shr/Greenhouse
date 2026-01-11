"""Email sender using Microsoft Graph API."""

from datetime import datetime
from typing import Any

from src.config import settings
from src.integrations.graph import MicrosoftGraphClient, get_graph_client
from src.email.templates import TemplateEngine, get_template_engine, BUILT_IN_TEMPLATES
from src.utils.logging import get_logger

logger = get_logger(__name__)


class EmailSendError(Exception):
    """Raised when email sending fails."""
    pass


class EmailSender:
    """
    Email sender that combines templates with Graph API sending.

    Features:
    - Template rendering with variables
    - Graph API sending
    - Logging to Greenhouse timeline
    - Bounce handling
    """

    def __init__(
        self,
        graph_client: MicrosoftGraphClient | None = None,
        template_engine: TemplateEngine | None = None,
    ):
        self.graph_client = graph_client or get_graph_client()
        self.template_engine = template_engine or get_template_engine()

    async def send_template_email(
        self,
        to: list[str],
        template_name: str,
        variables: dict[str, Any],
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
    ) -> dict:
        """
        Send an email using a named template.

        Args:
            to: Recipient email addresses
            template_name: Name of the template
            variables: Template variables
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            reply_to: Optional reply-to address

        Returns:
            Result dict with status and message_id
        """
        # Get template (try built-in first)
        if template_name in BUILT_IN_TEMPLATES:
            template = BUILT_IN_TEMPLATES[template_name]
            subject, html_body, text_body = self.template_engine.render_inline(
                subject_template=template["subject"],
                body_html_template=template["body_html"],
                body_text_template=None,
                variables=variables,
            )
        else:
            # Try file-based template
            subject, html_body, text_body = self.template_engine.render(
                template_name=template_name,
                variables=variables,
            )

        # Send via Graph
        return await self.send_email(
            to=to,
            subject=subject,
            body_html=html_body,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
        )

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body_html: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        importance: str = "normal",
    ) -> dict:
        """
        Send an email directly via Graph API.

        Args:
            to: Recipient email addresses
            subject: Email subject
            body_html: HTML body content
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            reply_to: Optional reply-to address
            importance: Email importance (low, normal, high)

        Returns:
            Result dict with status
        """
        if settings.mock_mode or settings.dry_run:
            logger.info(
                "Email send (mock/dry-run)",
                to=to,
                subject=subject,
            )
            return {
                "status": "mock",
                "message_id": "mock-message-id",
                "sent_at": datetime.utcnow().isoformat(),
            }

        try:
            result = await self.graph_client.send_email(
                to=to,
                subject=subject,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to or settings.email_reply_to,
                importance=importance,
            )

            logger.info(
                "Email sent",
                to=to,
                subject=subject,
            )

            return {
                "status": "sent",
                "sent_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(
                "Email send failed",
                to=to,
                subject=subject,
                error=str(e),
            )
            raise EmailSendError(f"Failed to send email: {str(e)}")

    async def send_initial_outreach(
        self,
        candidate_email: str,
        candidate_name: str,
        job_title: str,
        company_name: str | None = None,
    ) -> dict:
        """Send initial outreach email to a new applicant."""
        return await self.send_template_email(
            to=[candidate_email],
            template_name="initial_outreach",
            variables={
                "candidate_name": candidate_name,
                "job_title": job_title,
                "company_name": company_name or settings.email_from_name,
            },
        )

    async def send_interview_invite(
        self,
        candidate_email: str,
        candidate_name: str,
        job_title: str,
        scheduling_link: str | None = None,
        interview_duration: str = "45 minutes",
        interview_format: str = "via video call",
        recruiter_name: str = "The Recruiting Team",
        company_name: str | None = None,
    ) -> dict:
        """Send interview invitation email."""
        return await self.send_template_email(
            to=[candidate_email],
            template_name="interview_invite",
            variables={
                "candidate_name": candidate_name,
                "job_title": job_title,
                "company_name": company_name or settings.email_from_name,
                "scheduling_link": scheduling_link,
                "interview_duration": interview_duration,
                "interview_format": interview_format,
                "recruiter_name": recruiter_name,
            },
        )

    async def send_rejection(
        self,
        candidate_email: str,
        candidate_name: str,
        job_title: str,
        company_name: str | None = None,
    ) -> dict:
        """Send rejection email."""
        return await self.send_template_email(
            to=[candidate_email],
            template_name="rejection",
            variables={
                "candidate_name": candidate_name,
                "job_title": job_title,
                "company_name": company_name or settings.email_from_name,
            },
        )

    async def send_scorecard_reminder(
        self,
        interviewer_email: str,
        interviewer_name: str,
        candidate_name: str,
        job_title: str,
        interview_date: datetime,
        scorecard_link: str,
    ) -> dict:
        """Send scorecard reminder to interviewer."""
        return await self.send_template_email(
            to=[interviewer_email],
            template_name="scorecard_reminder",
            variables={
                "interviewer_name": interviewer_name,
                "candidate_name": candidate_name,
                "job_title": job_title,
                "interview_date": interview_date,
                "scorecard_link": scorecard_link,
            },
        )


# Singleton instance
_email_sender: EmailSender | None = None


async def get_email_sender() -> EmailSender:
    """Get or create the email sender singleton."""
    global _email_sender
    if _email_sender is None:
        _email_sender = EmailSender()
    return _email_sender
