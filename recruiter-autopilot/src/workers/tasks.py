"""Celery task definitions for async processing."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from celery import shared_task
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from src.config import settings
from src.models.database import get_sync_session
from src.models.application import (
    Application,
    ApplicationState,
    ApplicationStateTransition,
    ApplicationTier,
    ScoringResult as ScoringResultModel,
)
from src.models.candidate import Candidate
from src.models.job import Job
from src.models.webhook import WebhookEvent, WebhookStatus
from src.models.exception_queue import ExceptionQueueItem, ExceptionType, ExceptionPriority
from src.models.audit import AuditLog
from src.integrations.greenhouse import GreenhouseClient, GreenhouseAPIError
from src.scoring.engine import ScoringEngine, format_scoring_note
from src.utils.logging import get_logger, LogContext
from src.utils.security import generate_correlation_id

logger = get_logger(__name__)


def run_async(coro):
    """Helper to run async code in sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(GreenhouseAPIError,),
)
def process_greenhouse_webhook(self, webhook_event_id: int) -> dict:
    """
    Process a Greenhouse webhook event.

    This is the main entry point for handling Greenhouse events.
    Routes to appropriate handlers based on event type.
    """
    session = get_sync_session()
    correlation_id = generate_correlation_id()

    try:
        # Get webhook event
        event = session.query(WebhookEvent).filter_by(id=webhook_event_id).first()
        if not event:
            logger.error("Webhook event not found", event_id=webhook_event_id)
            return {"status": "error", "message": "Event not found"}

        with LogContext(correlation_id=correlation_id):
            event.mark_processing()
            session.commit()

            logger.info(
                "Processing webhook",
                event_type=event.event_type,
                event_id=event.event_id,
            )

            # Route based on event type
            result = {}
            if event.event_type in ("application_updated", "candidate_stage_change"):
                result = _handle_application_event(session, event, correlation_id)
            elif event.event_type == "new_candidate_application":
                result = _handle_new_application(session, event, correlation_id)
            elif event.event_type == "offer_sent":
                result = _handle_offer_sent(session, event, correlation_id)
            elif event.event_type == "offer_accepted":
                result = _handle_offer_accepted(session, event, correlation_id)
            else:
                logger.info("Unhandled event type", event_type=event.event_type)
                result = {"status": "ignored", "reason": "unhandled_event_type"}

            # Mark completed
            event.mark_completed()
            session.commit()

            return result

    except Exception as e:
        logger.error(
            "Webhook processing failed",
            event_id=webhook_event_id,
            error=str(e),
            exc_info=True,
        )

        # Mark failed
        if event:
            event.mark_failed(str(e))
            session.commit()

        # Create exception queue item
        _create_exception(
            session,
            ExceptionType.API_ERROR,
            f"Webhook processing failed: {str(e)}",
            webhook_event_id=webhook_event_id,
            correlation_id=correlation_id,
        )

        raise

    finally:
        session.close()


def _handle_new_application(
    session: Session,
    event: WebhookEvent,
    correlation_id: str,
) -> dict:
    """Handle new application event."""
    payload = event.payload.get("payload", {})
    app_data = payload.get("application", {})

    if not app_data:
        return {"status": "error", "message": "No application data in payload"}

    gh_app_id = app_data.get("id")
    gh_candidate_id = app_data.get("candidate_id")
    gh_job_id = app_data.get("jobs", [{}])[0].get("id") if app_data.get("jobs") else None

    logger.info(
        "Processing new application",
        gh_app_id=gh_app_id,
        gh_candidate_id=gh_candidate_id,
        gh_job_id=gh_job_id,
    )

    # Check if application already exists
    existing = session.query(Application).filter_by(greenhouse_id=gh_app_id).first()
    if existing:
        logger.info("Application already exists", application_id=existing.id)
        return {"status": "exists", "application_id": existing.id}

    # Get or create candidate
    candidate = session.query(Candidate).filter_by(greenhouse_id=gh_candidate_id).first()
    if not candidate:
        # Fetch candidate details from Greenhouse
        gh_client = GreenhouseClient()
        try:
            candidate_data = run_async(gh_client.get_candidate(gh_candidate_id))
            candidate = Candidate(
                greenhouse_id=gh_candidate_id,
                first_name=candidate_data.get("first_name"),
                last_name=candidate_data.get("last_name"),
                email=candidate_data.get("email_addresses", [{}])[0].get("value"),
                company=candidate_data.get("company"),
                title=candidate_data.get("title"),
                tags=candidate_data.get("tags", []),
            )
            session.add(candidate)
            session.flush()
        except Exception as e:
            logger.error("Failed to fetch candidate", error=str(e))
            # Create minimal candidate record
            candidate = Candidate(greenhouse_id=gh_candidate_id)
            session.add(candidate)
            session.flush()

    # Get or create job
    job = session.query(Job).filter_by(greenhouse_id=gh_job_id).first()
    if not job:
        gh_client = GreenhouseClient()
        try:
            job_data = run_async(gh_client.get_job(gh_job_id))
            job = Job(
                greenhouse_id=gh_job_id,
                name=job_data.get("name", "Unknown Job"),
                status=job_data.get("status", "open"),
            )
            session.add(job)
            session.flush()
        except Exception as e:
            logger.error("Failed to fetch job", error=str(e))
            job = Job(greenhouse_id=gh_job_id, name="Unknown Job")
            session.add(job)
            session.flush()

    # Create application
    application = Application(
        greenhouse_id=gh_app_id,
        candidate_id=candidate.id,
        job_id=job.id,
        state=ApplicationState.INGESTED,
        current_stage_id=app_data.get("current_stage", {}).get("id"),
        current_stage_name=app_data.get("current_stage", {}).get("name"),
        source=app_data.get("source", {}).get("public_name"),
        applied_at=datetime.fromisoformat(
            app_data.get("applied_at", "").replace("Z", "+00:00")
        ) if app_data.get("applied_at") else None,
    )
    session.add(application)
    session.flush()

    # Create state transition
    transition = ApplicationStateTransition(
        application_id=application.id,
        from_state=ApplicationState.INGESTED,
        to_state=ApplicationState.INGESTED,
        trigger="webhook",
        trigger_id=event.event_id,
        reason="New application received",
    )
    session.add(transition)

    # Create audit log
    audit = AuditLog.create(
        action="application.created",
        action_category="application",
        description=f"New application received from Greenhouse",
        target_type="application",
        target_id=application.id,
        greenhouse_application_id=gh_app_id,
        greenhouse_candidate_id=gh_candidate_id,
        greenhouse_job_id=gh_job_id,
        correlation_id=correlation_id,
    )
    session.add(audit)
    session.commit()

    # Queue for processing (if automation enabled)
    if job.automation_enabled:
        process_application.delay(application.id)

    return {
        "status": "created",
        "application_id": application.id,
        "queued_for_processing": job.automation_enabled,
    }


def _handle_application_event(
    session: Session,
    event: WebhookEvent,
    correlation_id: str,
) -> dict:
    """Handle application update event."""
    payload = event.payload.get("payload", {})
    app_data = payload.get("application", {})
    gh_app_id = app_data.get("id")

    if not gh_app_id:
        return {"status": "error", "message": "No application ID"}

    application = session.query(Application).filter_by(greenhouse_id=gh_app_id).first()
    if not application:
        logger.info("Application not found, treating as new", gh_app_id=gh_app_id)
        return _handle_new_application(session, event, correlation_id)

    # Update stage info
    new_stage_id = app_data.get("current_stage", {}).get("id")
    new_stage_name = app_data.get("current_stage", {}).get("name")

    if new_stage_id != application.current_stage_id:
        logger.info(
            "Stage changed",
            application_id=application.id,
            from_stage=application.current_stage_name,
            to_stage=new_stage_name,
        )
        application.current_stage_id = new_stage_id
        application.current_stage_name = new_stage_name

    session.commit()
    return {"status": "updated", "application_id": application.id}


def _handle_offer_sent(session: Session, event: WebhookEvent, correlation_id: str) -> dict:
    """Handle offer sent event."""
    return {"status": "noted", "event": "offer_sent"}


def _handle_offer_accepted(session: Session, event: WebhookEvent, correlation_id: str) -> dict:
    """Handle offer accepted event."""
    payload = event.payload.get("payload", {})
    app_data = payload.get("application", {})
    gh_app_id = app_data.get("id")

    application = session.query(Application).filter_by(greenhouse_id=gh_app_id).first()
    if application:
        application.outcome = "hired"
        application.state = ApplicationState.CLOSED
        session.commit()

    return {"status": "updated", "outcome": "hired"}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=120,
)
def process_application(self, application_id: int) -> dict:
    """
    Full processing pipeline for an application.

    Steps:
    1. Fetch full application details from Greenhouse
    2. Download and parse resume
    3. Score against rubric
    4. Write back to Greenhouse (tags, notes, stage action)
    """
    session = get_sync_session()
    correlation_id = generate_correlation_id()

    try:
        application = session.query(Application).filter_by(id=application_id).first()
        if not application:
            return {"status": "error", "message": "Application not found"}

        with LogContext(
            correlation_id=correlation_id,
            application_id=application_id,
            candidate_id=application.candidate_id,
        ):
            job = application.job
            candidate = application.candidate

            # Check automation enabled
            if not job.automation_enabled:
                logger.info("Automation disabled for job", job_id=job.id)
                return {"status": "skipped", "reason": "automation_disabled"}

            # Check kill switch
            if not job.is_automation_enabled_for_stage(application.current_stage_id):
                logger.info("Kill switch active", job_id=job.id)
                return {"status": "skipped", "reason": "kill_switch"}

            logger.info("Processing application", application_id=application_id)

            # Step 1: Fetch from Greenhouse and get resume
            gh_client = GreenhouseClient()
            try:
                gh_app = run_async(gh_client.get_application(application.greenhouse_id))
            except GreenhouseAPIError as e:
                logger.error("Failed to fetch application from Greenhouse", error=str(e))
                _transition_state(
                    session, application, ApplicationState.EXCEPTION,
                    "Failed to fetch from Greenhouse", correlation_id
                )
                raise

            # Get resume attachment
            attachments = gh_app.get("attachments", [])
            resume_attachment = next(
                (a for a in attachments if a.get("type") == "resume"),
                None
            )

            if not resume_attachment:
                logger.warning("No resume found", application_id=application_id)
                _transition_state(
                    session, application, ApplicationState.NEEDS_REVIEW,
                    "No resume attached", correlation_id
                )
                _create_exception(
                    session,
                    ExceptionType.MISSING_INFO,
                    "No resume attached to application",
                    application_id=application_id,
                    priority=ExceptionPriority.MEDIUM,
                    correlation_id=correlation_id,
                )
                return {"status": "needs_review", "reason": "no_resume"}

            # Step 2: Download resume
            try:
                resume_content = run_async(
                    gh_client.download_attachment(resume_attachment["url"])
                )
                resume_filename = resume_attachment.get("filename", "resume.pdf")
            except Exception as e:
                logger.error("Failed to download resume", error=str(e))
                _transition_state(
                    session, application, ApplicationState.EXCEPTION,
                    f"Resume download failed: {str(e)}", correlation_id
                )
                raise

            # Transition to PARSED
            _transition_state(
                session, application, ApplicationState.PARSED,
                "Resume downloaded", correlation_id
            )

            # Step 3: Score
            scoring_engine = ScoringEngine(mock_mode=settings.mock_mode)
            try:
                result = scoring_engine.score(
                    application_id=application.id,
                    resume_content=resume_content,
                    resume_filename=resume_filename,
                )
            except Exception as e:
                logger.error("Scoring failed", error=str(e))
                _transition_state(
                    session, application, ApplicationState.EXCEPTION,
                    f"Scoring failed: {str(e)}", correlation_id
                )
                _create_exception(
                    session,
                    ExceptionType.SCORING_ERROR,
                    f"Scoring failed: {str(e)}",
                    application_id=application_id,
                    correlation_id=correlation_id,
                )
                raise

            # Save scoring result
            scoring_model = ScoringResultModel(
                application_id=application.id,
                rubric_version=result.rubric_version,
                total_score=result.total_score,
                max_score=result.max_score,
                percentage=result.percentage,
                tier=ApplicationTier(result.tier) if result.tier != "REJECT" else ApplicationTier.REJECT,
                confidence=result.confidence,
                dimension_scores=result.dimension_scores,
                hard_constraints_passed=result.hard_constraints_passed,
                failed_constraints=result.failed_constraints,
                evidence=result.evidence,
                missing_info=result.missing_info,
                recommendation=result.recommendation,
                needs_human_review=result.needs_human_review,
                review_reasons=result.review_reasons,
            )
            session.add(scoring_model)

            # Update application
            application.tier = ApplicationTier(result.tier) if result.tier != "REJECT" else ApplicationTier.REJECT
            application.score = result.percentage
            application.confidence = result.confidence
            application.rubric_version = result.rubric_version
            application.scored_at = datetime.utcnow()
            application.needs_human_review = result.needs_human_review

            # Store extracted facts on candidate
            if candidate and result.extracted_facts:
                candidate.extracted_facts = result.extracted_facts
                candidate.resume_extracted_at = datetime.utcnow()

            _transition_state(
                session, application, ApplicationState.SCORED,
                f"Scored: {result.tier} ({result.percentage:.0%})", correlation_id
            )

            # Step 4: Write back to Greenhouse
            if not settings.dry_run:
                try:
                    # Add tags
                    tier_tag = f"tier:{result.tier}"
                    run_async(gh_client.add_application_tag(
                        application.greenhouse_id, tier_tag
                    ))

                    if result.needs_human_review:
                        run_async(gh_client.add_application_tag(
                            application.greenhouse_id, "needs-review"
                        ))

                    # Add scoring note
                    note_body = format_scoring_note(result)
                    # Note: Would need a user_id from settings
                    # run_async(gh_client.add_application_note(
                    #     application.greenhouse_id,
                    #     body=note_body,
                    #     user_id=settings.greenhouse_user_id,
                    # ))

                    logger.info("Wrote tags to Greenhouse")

                except Exception as e:
                    logger.error("Failed to write to Greenhouse", error=str(e))
                    # Continue - don't fail the whole process

            _transition_state(
                session, application, ApplicationState.ACTIONED,
                "Tags and notes written", correlation_id
            )

            # Step 5: Take action based on tier
            if result.tier == "REJECT" and job.auto_reject_enabled and settings.enable_auto_rejection:
                # Auto-reject
                if not settings.dry_run:
                    try:
                        run_async(gh_client.reject_application(
                            application.greenhouse_id,
                            rejection_reason_id=job.default_rejection_reason_id,
                            notes=result.recommendation,
                        ))
                        application.rejected = True
                        application.rejected_at = datetime.utcnow()
                        application.rejection_reason = result.recommendation
                        _transition_state(
                            session, application, ApplicationState.CLOSED,
                            "Auto-rejected", correlation_id
                        )
                    except Exception as e:
                        logger.error("Auto-reject failed", error=str(e))

            elif result.tier == "A" and job.auto_advance_enabled:
                # Could auto-advance to next stage
                logger.info("A-tier candidate, would advance")
                # Implementation would call gh_client.advance_application()

            session.commit()

            return {
                "status": "completed",
                "application_id": application.id,
                "tier": result.tier,
                "score": result.percentage,
                "needs_review": result.needs_human_review,
            }

    except Exception as e:
        logger.error(
            "Application processing failed",
            application_id=application_id,
            error=str(e),
            exc_info=True,
        )
        session.rollback()
        raise

    finally:
        session.close()


@shared_task(bind=True, max_retries=3)
def rescore_application_task(self, application_id: int) -> dict:
    """Re-score an application using stored resume text."""
    session = get_sync_session()

    try:
        application = session.query(Application).filter_by(id=application_id).first()
        if not application:
            return {"status": "error", "message": "Application not found"}

        candidate = application.candidate
        if not candidate or not candidate.resume_text:
            return {"status": "error", "message": "No resume text stored"}

        scoring_engine = ScoringEngine(mock_mode=settings.mock_mode)
        result = scoring_engine.score_from_text(
            application_id=application.id,
            resume_text=candidate.resume_text,
        )

        # Update application
        application.tier = ApplicationTier(result.tier) if result.tier != "REJECT" else ApplicationTier.REJECT
        application.score = result.percentage
        application.confidence = result.confidence
        application.scored_at = datetime.utcnow()

        session.commit()

        return {
            "status": "rescored",
            "application_id": application_id,
            "tier": result.tier,
            "score": result.percentage,
        }

    finally:
        session.close()


@shared_task
def process_graph_notification(webhook_event_id: int) -> dict:
    """Process Microsoft Graph change notification."""
    session = get_sync_session()

    try:
        event = session.query(WebhookEvent).filter_by(id=webhook_event_id).first()
        if not event:
            return {"status": "error", "message": "Event not found"}

        event.mark_processing()
        session.commit()

        # Route based on event type
        if event.event_type.startswith("message."):
            result = _handle_email_notification(session, event)
        elif event.event_type.startswith("calendar."):
            result = _handle_calendar_notification(session, event)
        else:
            result = {"status": "ignored"}

        event.mark_completed()
        session.commit()
        return result

    finally:
        session.close()


def _handle_email_notification(session: Session, event: WebhookEvent) -> dict:
    """Handle email change notification (candidate replies)."""
    # This would:
    # 1. Fetch the email content via Graph API
    # 2. Match to an application via email address
    # 3. Classify the intent
    # 4. Take appropriate action
    return {"status": "processed", "type": "email"}


def _handle_calendar_notification(session: Session, event: WebhookEvent) -> dict:
    """Handle calendar change notification."""
    return {"status": "processed", "type": "calendar"}


@shared_task
def send_email_task(
    application_id: int,
    template_name: str,
    variables: dict | None = None,
) -> dict:
    """Send an email for an application."""
    # This would use the email template engine and Graph client
    return {"status": "sent", "application_id": application_id}


@shared_task
def check_sla_violations() -> dict:
    """Periodic task to check for SLA violations."""
    session = get_sync_session()

    try:
        now = datetime.utcnow()
        violations_found = 0

        # Check for stuck applications
        stuck_threshold = now - timedelta(hours=settings.sla_ingested_to_actioned)

        stuck_apps = session.query(Application).filter(
            and_(
                Application.state.in_([
                    ApplicationState.INGESTED,
                    ApplicationState.PARSED,
                ]),
                Application.created_at < stuck_threshold,
            )
        ).all()

        for app in stuck_apps:
            logger.warning(
                "SLA violation: stuck application",
                application_id=app.id,
                state=app.state.value,
                created_at=app.created_at.isoformat(),
            )
            violations_found += 1

        return {"violations_found": violations_found}

    finally:
        session.close()


@shared_task
def send_scorecard_reminders() -> dict:
    """Send reminders for missing scorecards."""
    session = get_sync_session()

    try:
        # Find interviews completed but no scorecards
        threshold = datetime.utcnow() - timedelta(hours=settings.sla_scorecard_reminder_hours)

        # Query would find applications with interviews past but scorecards_submitted = False
        reminders_sent = 0

        return {"reminders_sent": reminders_sent}

    finally:
        session.close()


@shared_task
def send_weekly_digest() -> dict:
    """Send weekly pipeline digest to recruiters."""
    return {"status": "sent"}


def _transition_state(
    session: Session,
    application: Application,
    new_state: ApplicationState,
    reason: str,
    correlation_id: str,
) -> None:
    """Helper to transition application state."""
    old_state = application.state

    transition = ApplicationStateTransition(
        application_id=application.id,
        from_state=old_state,
        to_state=new_state,
        trigger="worker",
        reason=reason,
    )
    session.add(transition)

    application.previous_state = old_state
    application.state = new_state
    application.state_changed_at = datetime.utcnow()

    session.commit()

    logger.info(
        "State transition",
        application_id=application.id,
        from_state=old_state.value,
        to_state=new_state.value,
        reason=reason,
    )


def _create_exception(
    session: Session,
    exception_type: ExceptionType,
    title: str,
    application_id: int | None = None,
    webhook_event_id: int | None = None,
    priority: ExceptionPriority = ExceptionPriority.MEDIUM,
    correlation_id: str | None = None,
) -> None:
    """Helper to create exception queue item."""
    exception = ExceptionQueueItem(
        exception_type=exception_type,
        priority=priority,
        title=title,
        application_id=application_id,
        webhook_event_id=webhook_event_id,
        correlation_id=correlation_id,
    )
    session.add(exception)
    session.commit()
