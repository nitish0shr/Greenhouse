# Database Models Package - All models exported here

from app.models.event import Event
from app.models.candidate import Candidate
from app.models.application import Application
from app.models.action import Action
from app.models.job_config import JobConfig
from app.models.rubric_version import RubricVersion
from app.models.exception import Exception as ExceptionModel
from app.models.graph_subscription import GraphSubscription
from app.models.message_mapping import MessageMapping
from app.models.calendar_mapping import CalendarMapping
from app.models.attachment import Attachment
from app.models.scoring_result import ScoringResult

# Legacy imports (if still used)
from app.models.audit_log import AuditLog
from app.models.human_review import HumanReviewQueue
from app.models.webhook_event import WebhookEvent

__all__ = [
    # Core models (First Review schema)
    "Event",
    "Candidate",
    "Application",
    "Action",
    "JobConfig",
    "RubricVersion",
    "ExceptionModel",
    "GraphSubscription",
    "MessageMapping",
    "CalendarMapping",
    "Attachment",
    "ScoringResult",
    # Legacy models (if still needed)
    "AuditLog",
    "HumanReviewQueue",
    "WebhookEvent",
]
