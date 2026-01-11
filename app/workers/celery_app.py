# =============================================================================
# Celery Application Configuration
# =============================================================================

from celery import Celery

from app.config import settings

# Create Celery app
celery_app = Celery(
    "recruiter_autopilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
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
    task_acks_late=True,  # Acknowledge after task completes
    task_reject_on_worker_lost=True,  # Retry if worker dies
    
    # Retry settings
    task_default_retry_delay=60,  # 1 minute default retry
    task_max_retries=3,
    
    # Result backend settings
    result_expires=86400,  # Results expire after 1 day
    
    # Worker settings
    worker_prefetch_multiplier=4,  # Tasks per worker
    worker_concurrency=4,  # Number of concurrent workers
    
    # Task routes (optional - for scaling)
    task_routes={
        "app.workers.tasks.process_new_application": {"queue": "applications"},
        "app.workers.tasks.send_candidate_email": {"queue": "emails"},
        "app.workers.tasks.schedule_interview": {"queue": "interviews"},
    },
    
    # Beat schedule (for periodic tasks)
    beat_schedule={
        # Cleanup old webhook events
        "cleanup-old-events": {
            "task": "app.workers.tasks.cleanup_old_events",
            "schedule": 86400.0,  # Daily
        },
        # Retry failed tasks
        "retry-failed-applications": {
            "task": "app.workers.tasks.retry_failed_applications",
            "schedule": 3600.0,  # Hourly
        },
        # Renew Graph subscriptions (24h before expiry)
        "renew-graph-subscriptions": {
            "task": "app.workers.renewal_tasks.renew_graph_subscriptions",
            "schedule": 3600.0,  # Hourly (checks for subscriptions expiring in next 24h)
        },
        # Pipeline Nudge Tasks
        "nudge-no-reply-candidates": {
            "task": "app.workers.tasks.nudge_no_reply_candidates",
            "schedule": 86400.0,  # Daily (check for candidates with no reply after 3 days)
        },
        "chase-missing-scorecards": {
            "task": "app.workers.tasks.chase_missing_scorecards",
            "schedule": 43200.0,  # Every 12 hours (check for missing scorecards after 24h)
        },
        "check-stuck-in-stage": {
            "task": "app.workers.tasks.check_stuck_in_stage",
            "schedule": 86400.0,  # Daily (check for SLA breaches at 5 days)
        },
    },
)

# Export for use in other modules
app = celery_app
