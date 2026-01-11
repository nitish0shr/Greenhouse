"""Celery application configuration."""

from celery import Celery
from celery.signals import task_failure, task_success, worker_ready

from src.config import settings
from src.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

# Create Celery app
celery_app = Celery(
    "recruiter_autopilot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "src.workers.tasks",
    ],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution settings
    task_acks_late=True,  # Acknowledge after task completes (for reliability)
    task_reject_on_worker_lost=True,  # Reject task if worker dies
    task_time_limit=600,  # 10 minute hard limit
    task_soft_time_limit=540,  # 9 minute soft limit

    # Retry settings
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,

    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time for fair distribution
    worker_concurrency=4,  # Number of worker processes

    # Result backend settings
    result_expires=86400,  # Results expire after 1 day

    # Queue routing
    task_routes={
        "src.workers.tasks.process_greenhouse_webhook": {"queue": "webhooks"},
        "src.workers.tasks.process_application": {"queue": "processing"},
        "src.workers.tasks.send_email_task": {"queue": "email"},
        "src.workers.tasks.check_sla_violations": {"queue": "scheduled"},
        "src.workers.tasks.send_scorecard_reminders": {"queue": "scheduled"},
    },

    # Default queue
    task_default_queue=settings.celery_task_default_queue,

    # Beat schedule (periodic tasks)
    beat_schedule={
        "check-sla-violations-hourly": {
            "task": "src.workers.tasks.check_sla_violations",
            "schedule": 3600.0,  # Every hour
        },
        "send-scorecard-reminders-hourly": {
            "task": "src.workers.tasks.send_scorecard_reminders",
            "schedule": 3600.0,  # Every hour
        },
        "send-weekly-digest": {
            "task": "src.workers.tasks.send_weekly_digest",
            "schedule": 604800.0,  # Weekly
        },
    },
)


@worker_ready.connect
def on_worker_ready(**kwargs):
    """Log when worker is ready."""
    setup_logging(settings.log_level, json_logs=settings.is_production)
    logger.info("Celery worker ready")


@task_success.connect
def on_task_success(sender=None, result=None, **kwargs):
    """Log successful task completion."""
    logger.debug(
        "Task completed successfully",
        task=sender.name if sender else "unknown",
    )


@task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, **kwargs):
    """Log task failures."""
    logger.error(
        "Task failed",
        task=sender.name if sender else "unknown",
        task_id=task_id,
        error=str(exception),
    )
