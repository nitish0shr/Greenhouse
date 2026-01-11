"""Email template engine using Jinja2."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class TemplateRenderError(Exception):
    """Raised when template rendering fails."""
    pass


class TemplateEngine:
    """
    Email template engine with Jinja2.

    Features:
    - Variable substitution
    - Default values
    - HTML and plain text rendering
    - Template validation
    """

    def __init__(self, templates_dir: str | None = None):
        self.templates_dir = Path(templates_dir or "templates/emails")

        # Create Jinja environment
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Add custom filters
        self.env.filters["format_date"] = self._format_date
        self.env.filters["format_datetime"] = self._format_datetime

    def _format_date(self, value: Any, format: str = "%B %d, %Y") -> str:
        """Format a date for display."""
        if hasattr(value, "strftime"):
            return value.strftime(format)
        return str(value)

    def _format_datetime(self, value: Any, format: str = "%B %d, %Y at %I:%M %p") -> str:
        """Format a datetime for display."""
        if hasattr(value, "strftime"):
            return value.strftime(format)
        return str(value)

    def render(
        self,
        template_name: str,
        variables: dict[str, Any],
        default_values: dict[str, Any] | None = None,
    ) -> tuple[str, str, str]:
        """
        Render an email template.

        Args:
            template_name: Name of the template (without extension)
            variables: Template variables
            default_values: Default values for optional variables

        Returns:
            Tuple of (subject, html_body, text_body)

        Raises:
            TemplateRenderError: If rendering fails
        """
        # Merge defaults with provided variables
        context = {**(default_values or {}), **variables}

        try:
            # Render subject
            subject_template = self.env.get_template(f"{template_name}/subject.txt")
            subject = subject_template.render(context).strip()

            # Render HTML body
            html_template = self.env.get_template(f"{template_name}/body.html")
            html_body = html_template.render(context)

            # Render plain text body (optional)
            try:
                text_template = self.env.get_template(f"{template_name}/body.txt")
                text_body = text_template.render(context)
            except TemplateNotFound:
                # Generate plain text from HTML (basic)
                text_body = self._html_to_text(html_body)

            return subject, html_body, text_body

        except TemplateNotFound as e:
            raise TemplateRenderError(f"Template not found: {e}")
        except Exception as e:
            raise TemplateRenderError(f"Template rendering failed: {e}")

    def render_inline(
        self,
        subject_template: str,
        body_html_template: str,
        body_text_template: str | None,
        variables: dict[str, Any],
    ) -> tuple[str, str, str]:
        """
        Render templates from inline strings.

        Useful for database-stored templates.
        """
        from jinja2 import Template

        try:
            subject = Template(subject_template).render(variables).strip()
            html_body = Template(body_html_template).render(variables)

            if body_text_template:
                text_body = Template(body_text_template).render(variables)
            else:
                text_body = self._html_to_text(html_body)

            return subject, html_body, text_body

        except Exception as e:
            raise TemplateRenderError(f"Inline template rendering failed: {e}")

    def _html_to_text(self, html: str) -> str:
        """Basic HTML to plain text conversion."""
        import re

        # Remove style and script tags
        text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)

        # Convert common elements
        text = re.sub(r"<br\s*/?>", "\n", text)
        text = re.sub(r"<p[^>]*>", "\n\n", text)
        text = re.sub(r"</p>", "", text)
        text = re.sub(r"<li[^>]*>", "\n- ", text)

        # Remove remaining tags
        text = re.sub(r"<[^>]+>", "", text)

        # Clean up whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" +", " ", text)

        # Decode HTML entities
        import html
        text = html.unescape(text)

        return text.strip()

    def validate_template(self, template_name: str) -> list[str]:
        """
        Validate a template exists and has required files.

        Returns list of validation errors (empty if valid).
        """
        errors = []
        template_path = self.templates_dir / template_name

        if not template_path.exists():
            errors.append(f"Template directory not found: {template_name}")
            return errors

        required_files = ["subject.txt", "body.html"]
        for filename in required_files:
            if not (template_path / filename).exists():
                errors.append(f"Missing required file: {filename}")

        return errors


# Singleton instance
_template_engine: TemplateEngine | None = None


def get_template_engine() -> TemplateEngine:
    """Get or create the template engine singleton."""
    global _template_engine
    if _template_engine is None:
        _template_engine = TemplateEngine()
    return _template_engine


def render_template(
    template_name: str,
    variables: dict[str, Any],
    default_values: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """Convenience function to render a template."""
    return get_template_engine().render(template_name, variables, default_values)


# Built-in template definitions (for database seeding or fallback)
BUILT_IN_TEMPLATES = {
    "initial_outreach": {
        "name": "Initial Outreach",
        "description": "First contact email to new applicants",
        "subject": "Thank you for applying to {{ job_title }} at {{ company_name }}",
        "body_html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #2563eb; color: white; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .footer { background: #f5f5f5; padding: 15px; text-align: center; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{{ company_name }}</h1>
        </div>
        <div class="content">
            <p>Dear {{ candidate_name }},</p>

            <p>Thank you for your interest in the <strong>{{ job_title }}</strong> position at {{ company_name }}.</p>

            <p>We have received your application and our team is currently reviewing it. We appreciate your patience during this process.</p>

            <p>If your qualifications match our requirements, a member of our recruiting team will be in touch to discuss next steps.</p>

            <p>Best regards,<br>
            The {{ company_name }} Recruiting Team</p>
        </div>
        <div class="footer">
            <p>&copy; {{ company_name }}. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
""",
        "available_variables": ["candidate_name", "job_title", "company_name"],
        "required_variables": ["candidate_name", "job_title", "company_name"],
    },
    "interview_invite": {
        "name": "Interview Invitation",
        "description": "Invite candidate to schedule an interview",
        "subject": "Interview Invitation: {{ job_title }} at {{ company_name }}",
        "body_html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .content { padding: 20px; }
        .cta-button { display: inline-block; background: #2563eb; color: white;
                      padding: 12px 24px; text-decoration: none; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="content">
            <p>Dear {{ candidate_name }},</p>

            <p>Great news! After reviewing your application for the <strong>{{ job_title }}</strong> position, we would like to invite you to the next step in our interview process.</p>

            {% if scheduling_link %}
            <p>Please use the link below to schedule a time that works best for you:</p>
            <p style="text-align: center;">
                <a href="{{ scheduling_link }}" class="cta-button">Schedule Your Interview</a>
            </p>
            {% else %}
            <p>Please respond to this email with your availability for the next two weeks, and we will coordinate a time.</p>
            {% endif %}

            <p>The interview will be approximately {{ interview_duration }} minutes and will be conducted {{ interview_format }}.</p>

            <p>If you have any questions, please don't hesitate to reach out.</p>

            <p>Best regards,<br>
            {{ recruiter_name }}<br>
            {{ company_name }} Recruiting Team</p>
        </div>
    </div>
</body>
</html>
""",
        "available_variables": [
            "candidate_name", "job_title", "company_name", "scheduling_link",
            "interview_duration", "interview_format", "recruiter_name"
        ],
        "required_variables": ["candidate_name", "job_title", "company_name"],
    },
    "rejection": {
        "name": "Application Rejection",
        "description": "Polite rejection email",
        "subject": "Update on your {{ job_title }} application",
        "body_html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .content { padding: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="content">
            <p>Dear {{ candidate_name }},</p>

            <p>Thank you for your interest in the <strong>{{ job_title }}</strong> position at {{ company_name }} and for taking the time to apply.</p>

            <p>After careful consideration, we have decided to move forward with other candidates whose experience more closely aligns with our current needs.</p>

            <p>We encourage you to apply for future openings that match your skills and experience. We will keep your application on file for future opportunities.</p>

            <p>We wish you the best in your job search and future career endeavors.</p>

            <p>Best regards,<br>
            The {{ company_name }} Recruiting Team</p>
        </div>
    </div>
</body>
</html>
""",
        "available_variables": ["candidate_name", "job_title", "company_name"],
        "required_variables": ["candidate_name", "job_title", "company_name"],
    },
    "scorecard_reminder": {
        "name": "Scorecard Reminder",
        "description": "Remind interviewers to submit scorecards",
        "subject": "Action Required: Submit scorecard for {{ candidate_name }}",
        "body_html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .content { padding: 20px; }
        .cta-button { display: inline-block; background: #2563eb; color: white;
                      padding: 12px 24px; text-decoration: none; border-radius: 4px; }
        .warning { background: #fef3c7; border: 1px solid #f59e0b; padding: 15px; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="content">
            <p>Hi {{ interviewer_name }},</p>

            <div class="warning">
                <strong>Reminder:</strong> Your scorecard for {{ candidate_name }} is pending.
            </div>

            <p>You interviewed {{ candidate_name }} for the {{ job_title }} position on {{ interview_date | format_date }}.</p>

            <p>Please submit your scorecard within 24 hours to keep the hiring process moving:</p>

            <p style="text-align: center;">
                <a href="{{ scorecard_link }}" class="cta-button">Submit Scorecard</a>
            </p>

            <p>Thank you for helping us hire great people!</p>

            <p>Best,<br>
            The Recruiting Team</p>
        </div>
    </div>
</body>
</html>
""",
        "available_variables": [
            "interviewer_name", "candidate_name", "job_title",
            "interview_date", "scorecard_link"
        ],
        "required_variables": ["interviewer_name", "candidate_name", "job_title"],
    },
}
