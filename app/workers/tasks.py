# =============================================================================
# Celery Background Tasks
# =============================================================================

import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple

from celery import shared_task
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SyncSessionLocal
from app.models.application import Application
from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.event import Event
from app.models.exception import Exception as ExceptionModel
from app.models.human_review import HumanReviewQueue
from app.models.webhook_event import WebhookEvent
from app.services.greenhouse import GreenhouseClient, GreenhouseAPIError
from app.services.microsoft_graph import GraphClient, GraphAPIError
from app.services.resume_parser import ResumeParser, ResumeParserError
from app.services.scorer import CandidateScorer, ScoringResult
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Pattern to detect AUTOPILOT_ACTION_ID markers in notes/payloads
AUTOPILOT_ACTION_ID_PATTERN = re.compile(r'AUTOPILOT_ACTION_ID:([a-f0-9\-]{36})', re.IGNORECASE)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def get_db_session() -> Session:
    """Get a synchronous database session for Celery tasks."""
    return SyncSessionLocal()


def create_audit_log(
    session: Session,
    action_type: str,
    description: str,
    application_id: Optional[str] = None,
    candidate_id: Optional[str] = None,
    greenhouse_application_id: Optional[int] = None,
    greenhouse_candidate_id: Optional[int] = None,
    triggered_by: str = "system",
    status: str = "success",
    metadata: Optional[dict] = None,
    error_message: Optional[str] = None,
):
    """Create an audit log entry."""
    log = AuditLog(
        action_type=action_type,
        description=description,
        application_id=application_id,
        candidate_id=candidate_id,
        greenhouse_application_id=greenhouse_application_id,
        greenhouse_candidate_id=greenhouse_candidate_id,
        triggered_by=triggered_by,
        status=status,
        metadata=metadata or {},
        error_message=error_message,
    )
    session.add(log)
    session.commit()
    return log


def create_exception_record(
    session: Session,
    exception_type: str,
    reason: str,
    application_id: Optional[uuid.UUID] = None,
    payload_refs: Optional[dict] = None,
) -> ExceptionModel:
    """
    Create an exception record for DLQ tracking.

    Args:
        session: Database session
        exception_type: Type of exception (api_failure, missing_mapping, etc.)
        reason: Human-readable reason
        application_id: Related application UUID
        payload_refs: References to greenhouse_event_id, autopilot_action_id, etc.

    Returns:
        Created ExceptionModel record
    """
    exc = ExceptionModel(
        application_id=application_id,
        exception_type=exception_type,
        reason=reason,
        status="open",
        retry_count=0,
        payload_refs=payload_refs or {},
    )
    session.add(exc)
    session.commit()
    logger.warning(f"Created exception: {exception_type} - {reason}")
    return exc


def check_for_autopilot_action(
    session: Session,
    payload: dict,
) -> Tuple[bool, Optional[uuid.UUID]]:
    """
    Check if an event was triggered by an Autopilot action (loop prevention).

    Looks for AUTOPILOT_ACTION_ID markers in:
    1. Notes in the payload
    2. Activity feed items
    3. Any text content containing the marker

    Args:
        session: Database session
        payload: Webhook event payload

    Returns:
        Tuple of (is_autopilot_action, action_id if found)
    """
    # Convert payload to string to search for markers
    payload_str = str(payload)

    # Search for AUTOPILOT_ACTION_ID pattern
    match = AUTOPILOT_ACTION_ID_PATTERN.search(payload_str)

    if match:
        action_id_str = match.group(1)
        try:
            action_id = uuid.UUID(action_id_str)

            # Verify this action exists in our database (confirms it's our action)
            existing_action = session.execute(
                select(Action).where(Action.autopilot_action_id == action_id)
            ).scalar_one_or_none()

            if existing_action:
                logger.info(
                    f"Loop prevention: Event triggered by Autopilot action {action_id}, "
                    f"type={existing_action.action_type}, status={existing_action.status}"
                )
                return True, action_id
            else:
                # Marker found but not in our database - might be from another system
                logger.warning(f"AUTOPILOT_ACTION_ID marker found ({action_id}) but not in our database")
                return False, None

        except ValueError:
            # Invalid UUID format
            logger.warning(f"Invalid AUTOPILOT_ACTION_ID format: {action_id_str}")
            return False, None

    return False, None


def is_feature_enabled(session: Session, flag_name: str, job_id: Optional[int] = None) -> bool:
    """
    Check if a feature flag is enabled.

    Args:
        session: Database session
        flag_name: Feature flag name
        job_id: Optional job ID for job-specific flags

    Returns:
        True if enabled, False otherwise
    """
    # For now, check config settings as fallback
    # In full implementation, would check feature_flags table

    # Global flags from settings
    if flag_name == "ENABLE_AUTOPILOT_GLOBAL":
        return not settings.mock_mode or True  # Always enabled unless explicitly disabled

    # Default to enabled for core features
    return True


# -----------------------------------------------------------------------------
# Webhook Event Processing Task (First Review Implementation)
# -----------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=7, default_retry_delay=60)
def process_greenhouse_event(
    self,
    greenhouse_event_id: str,
    event_type: str,
    payload: dict,
):
    """
    Process a Greenhouse webhook event (per First Review requirements).

    This task:
    1. Checks global feature flags
    2. Checks for loop prevention (AUTOPILOT_ACTION_ID markers)
    3. Routes to appropriate handler based on event_type
    4. Updates event status in events table
    5. Dispatches to specific processing tasks

    Args:
        greenhouse_event_id: Greenhouse-Event-ID header value
        event_type: Event action type (e.g., "new_candidate_application")
        payload: Full webhook payload
    """
    session = get_db_session()

    try:
        logger.info(f"Processing Greenhouse event: {greenhouse_event_id} ({event_type})")

        # Update event status to processing
        event = session.execute(
            select(Event).where(Event.greenhouse_event_id == greenhouse_event_id)
        ).scalar_one_or_none()

        if not event:
            logger.error(f"Event not found: {greenhouse_event_id}")
            return

        event.status = "processing"
        event.processed_at = datetime.utcnow()
        session.commit()

        # =======================================================================
        # FEATURE FLAG CHECK: Is autopilot globally enabled?
        # =======================================================================
        if not is_feature_enabled(session, "ENABLE_AUTOPILOT_GLOBAL"):
            logger.info(f"Autopilot globally disabled, skipping event {greenhouse_event_id}")
            event.status = "skipped"
            event.error_message = "Autopilot globally disabled"
            session.commit()
            return

        # =======================================================================
        # LOOP PREVENTION CHECK: Was this event triggered by our own action?
        # =======================================================================
        is_our_action, action_id = check_for_autopilot_action(session, payload)

        if is_our_action:
            logger.info(
                f"Loop prevention: Skipping event {greenhouse_event_id} "
                f"(triggered by our action {action_id})"
            )
            event.status = "reconciled"
            event.error_message = f"Triggered by autopilot action {action_id}"
            session.commit()

            # Create audit log for visibility
            create_audit_log(
                session,
                action_type="loop_prevention",
                description=f"Skipped event triggered by autopilot action",
                metadata={
                    "greenhouse_event_id": greenhouse_event_id,
                    "event_type": event_type,
                    "autopilot_action_id": str(action_id),
                },
            )
            return

        # =======================================================================
        # ROUTE TO APPROPRIATE HANDLER
        # =======================================================================
        if event_type == "new_candidate_application":
            application_id = payload.get("application", {}).get("id")
            if application_id:
                process_new_application.delay(
                    application_id=application_id,
                    greenhouse_event_id=greenhouse_event_id,
                    payload=payload,
                )
            else:
                logger.warning(f"new_candidate_application event missing application ID")
                event.status = "failed"
                event.error_message = "Missing application ID"
                session.commit()

        elif event_type == "candidate_stage_change":
            application_id = payload.get("application", {}).get("id")
            if application_id:
                process_stage_change.delay(
                    application_id=application_id,
                    greenhouse_event_id=greenhouse_event_id,
                    payload=payload,
                )
            else:
                logger.warning(f"candidate_stage_change event missing application ID")

        elif event_type == "candidate_hired":
            # Handle hired events
            logger.info(f"Candidate hired event: {greenhouse_event_id}")
            event.status = "processed"
            session.commit()

        elif event_type == "candidate_rejected":
            # Handle rejection events (may be triggered by us or manually)
            logger.info(f"Candidate rejected event: {greenhouse_event_id}")
            event.status = "processed"
            session.commit()

        elif event_type == "candidate_updated":
            # Handle candidate updates
            logger.info(f"Candidate updated event: {greenhouse_event_id}")
            event.status = "processed"
            session.commit()

        else:
            logger.info(f"Unhandled event type: {event_type}")
            event.status = "processed"  # Mark as processed even if unhandled
            session.commit()

    except Exception as e:
        logger.error(f"Failed to process event {greenhouse_event_id}: {e}", exc_info=True)
        session.rollback()

        # Update event status
        event = session.execute(
            select(Event).where(Event.greenhouse_event_id == greenhouse_event_id)
        ).scalar_one_or_none()
        if event:
            event.status = "failed"
            event.error_message = str(e)
            session.commit()

        # Create exception for DLQ
        create_exception_record(
            session,
            exception_type="event_processing_failure",
            reason=f"Failed to process {event_type}: {str(e)}",
            payload_refs={"greenhouse_event_id": greenhouse_event_id, "event_type": event_type},
        )

        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=min(300, 2 ** self.request.retries))

    finally:
        session.close()


# -----------------------------------------------------------------------------
# Application Processing Tasks
# -----------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_new_application(
    self,
    application_id: int,
    greenhouse_event_id: str,  # Changed from webhook_event_id
    payload: dict,
):
    """
    Process a new application from Greenhouse webhook.
    
    This is the main pipeline that:
    1. Fetches application and candidate data from Greenhouse
    2. Downloads resume attachments
    3. Extracts text from resume
    4. Scores the candidate
    5. Takes action based on score (advance, reject, or queue for review)
    6. Writes results back to Greenhouse
    """
    session = get_db_session()
    greenhouse = GreenhouseClient()
    
    try:
        logger.info(f"Processing new application: {application_id}")
        
        # Update event status (using Event model with greenhouse_event_id)
        session.execute(
            update(Event)
            .where(Event.greenhouse_event_id == greenhouse_event_id)
            .values(status="processing", processed_at=datetime.utcnow())
        )
        session.commit()
        
        # Step 1: Fetch application from Greenhouse
        try:
            import asyncio
            app_data = asyncio.get_event_loop().run_until_complete(
                greenhouse.get_application(application_id)
            )
        except GreenhouseAPIError as e:
            logger.error(f"Failed to fetch application {application_id}: {e}")
            raise self.retry(exc=e)
        
        create_audit_log(
            session,
            action_type="application_fetched",
            description=f"Fetched application {application_id} from Greenhouse",
            greenhouse_application_id=application_id,
            metadata={"job_id": app_data.get("job", {}).get("id")},
        )
        
        # Extract candidate info
        candidate_id = app_data.get("candidate_id")
        job_data = app_data.get("job", {})
        
        # Step 2: Fetch candidate details
        try:
            import asyncio
            candidate_data = asyncio.get_event_loop().run_until_complete(
                greenhouse.get_candidate(candidate_id)
            )
        except GreenhouseAPIError as e:
            logger.error(f"Failed to fetch candidate {candidate_id}: {e}")
            raise self.retry(exc=e)
        
        # Step 3: Create/update local candidate record
        candidate = session.execute(
            select(Candidate).where(Candidate.greenhouse_candidate_id == candidate_id)
        ).scalar_one_or_none()
        
        if not candidate:
            candidate = Candidate(
                greenhouse_candidate_id=candidate_id,
                first_name=candidate_data.get("first_name", ""),
                last_name=candidate_data.get("last_name", ""),
                email=candidate_data.get("email_addresses", [{}])[0].get("value"),
                raw_data=candidate_data,
            )
            session.add(candidate)
            session.commit()
        
        # Step 4: Create application record
        application = Application(
            greenhouse_application_id=application_id,
            candidate_id=candidate.id,
            greenhouse_candidate_id=candidate_id,
            greenhouse_job_id=job_data.get("id", 0),
            job_name=job_data.get("name", "Unknown"),
            current_stage_id=app_data.get("current_stage", {}).get("id"),
            current_stage_name=app_data.get("current_stage", {}).get("name"),
            source=app_data.get("source", {}).get("public_name"),
            processing_status="processing",
            raw_data=app_data,
        )
        session.add(application)
        session.commit()
        
        # Step 5: Download and parse resume attachments
        resume_text = ""
        attachments = candidate_data.get("attachments", [])
        resume_attachments = [
            a for a in attachments 
            if a.get("type") == "resume"
        ]
        
        if resume_attachments:
            parser = ResumeParser()
            
            for attachment in resume_attachments:
                attachment_url = attachment.get("url")
                filename = attachment.get("filename", "resume")
                
                if not attachment_url:
                    continue
                
                try:
                    # Download attachment (URLs expire!)
                    import asyncio
                    file_bytes = asyncio.get_event_loop().run_until_complete(
                        greenhouse.download_attachment(attachment_url)
                    )
                    
                    application.resume_downloaded = True
                    application.resume_url = attachment_url
                    
                    create_audit_log(
                        session,
                        action_type="resume_downloaded",
                        description=f"Downloaded resume: {filename}",
                        application_id=str(application.id),
                        greenhouse_application_id=application_id,
                    )
                    
                    # Extract text
                    text = parser.extract_text(file_bytes, filename=filename)
                    resume_text += text + "\n\n"
                    
                    create_audit_log(
                        session,
                        action_type="resume_parsed",
                        description=f"Extracted {len(text)} characters from resume",
                        application_id=str(application.id),
                        greenhouse_application_id=application_id,
                    )
                    
                except GreenhouseAPIError as e:
                    logger.warning(f"Failed to download attachment: {e}")
                    application.resume_download_error = str(e)
                    
                except ResumeParserError as e:
                    logger.warning(f"Failed to parse resume: {e}")
                
                # Only process first resume
                break
        
        # Store resume text on candidate
        if resume_text:
            candidate.resume_text = resume_text
            session.commit()
        
        # Step 6: Score the candidate
        scorer = CandidateScorer()
        result: ScoringResult = scorer.score(
            resume_text=resume_text,
            application_data=app_data,
        )
        
        # Update application with score
        application.score = result.score
        application.score_breakdown = result.score_breakdown
        application.confidence_score = result.confidence
        application.hard_reject_reasons = result.failed_constraints
        application.scored_at = datetime.utcnow()
        
        create_audit_log(
            session,
            action_type="candidate_scored",
            description=f"Scored candidate: {result.score:.1f} (confidence: {result.confidence:.2f})",
            application_id=str(application.id),
            greenhouse_application_id=application_id,
            metadata={
                "score": result.score,
                "confidence": result.confidence,
                "hard_reject": result.hard_reject,
                "matched_skills": result.matched_skills,
                "missing_skills": result.missing_skills,
                "suggested_action": result.suggested_action,
            },
        )
        
        # Step 7: Take action based on score
        import asyncio
        
        if result.hard_reject:
            # Auto-reject for hard constraint failures
            application.auto_decision = "reject"
            application.processing_status = "completed"
            
            try:
                asyncio.get_event_loop().run_until_complete(
                    greenhouse.reject_application(
                        application_id=application_id,
                        rejection_reason_id=result.rejection_reason_id,
                        notes=f"Auto-rejected: {', '.join(result.failed_constraints)}",
                    )
                )
                
                create_audit_log(
                    session,
                    action_type="application_rejected",
                    description=f"Auto-rejected application: {result.failed_constraints}",
                    application_id=str(application.id),
                    greenhouse_application_id=application_id,
                    metadata={"reason": result.failed_constraints},
                )
                
            except GreenhouseAPIError as e:
                logger.error(f"Failed to reject application: {e}")
                application.error_message = f"Rejection failed: {e}"
        
        elif result.suggested_action == "advance":
            # Auto-advance high scorers
            application.auto_decision = "advance"
            application.processing_status = "completed"
            
            try:
                asyncio.get_event_loop().run_until_complete(
                    greenhouse.advance_application(
                        application_id=application_id,
                        from_stage_id=application.current_stage_id,
                    )
                )
                
                create_audit_log(
                    session,
                    action_type="stage_advanced",
                    description=f"Auto-advanced application (score: {result.score:.1f})",
                    application_id=str(application.id),
                    greenhouse_application_id=application_id,
                )
                
            except GreenhouseAPIError as e:
                logger.error(f"Failed to advance application: {e}")
                application.error_message = f"Advance failed: {e}"
        
        elif result.suggested_action == "reject":
            # Auto-reject low scorers (with caution)
            if result.confidence >= 0.7:
                application.auto_decision = "reject"
                application.processing_status = "completed"
                
                try:
                    asyncio.get_event_loop().run_until_complete(
                        greenhouse.reject_application(
                            application_id=application_id,
                            notes=f"Auto-rejected: Score {result.score:.1f}",
                        )
                    )
                    
                    create_audit_log(
                        session,
                        action_type="application_rejected",
                        description=f"Auto-rejected low scorer: {result.score:.1f}",
                        application_id=str(application.id),
                        greenhouse_application_id=application_id,
                    )
                    
                except GreenhouseAPIError as e:
                    logger.error(f"Failed to reject application: {e}")
                    application.error_message = f"Rejection failed: {e}"
            else:
                # Low confidence - send to human review
                application.auto_decision = "human_review"
                application.processing_status = "human_review"
                add_to_human_review(session, application, result)
        
        else:
            # Human review for uncertain cases
            application.auto_decision = "human_review"
            application.processing_status = "human_review"
            add_to_human_review(session, application, result)
        
        # Step 8: Add tags and notes to Greenhouse
        try:
            # Add score tag
            score_tag = f"auto-score-{int(result.score)}"
            asyncio.get_event_loop().run_until_complete(
                greenhouse.add_tag(candidate_id, score_tag)
            )
            
            # Add processing note
            note = f"""
**Automated Screening Results**
- Score: {result.score:.1f}/100
- Confidence: {result.confidence:.0%}
- Decision: {result.suggested_action.upper()}

**Matched Skills:** {', '.join(result.matched_skills) or 'None'}
**Missing Skills:** {', '.join(result.missing_skills) or 'None'}
"""
            if result.warnings:
                note += f"\n**Warnings:** {', '.join(result.warnings)}"
            
            asyncio.get_event_loop().run_until_complete(
                greenhouse.add_note_to_candidate(candidate_id, note)
            )
            
            create_audit_log(
                session,
                action_type="note_added",
                description="Added scoring results note to candidate",
                application_id=str(application.id),
                greenhouse_application_id=application_id,
            )
            
        except GreenhouseAPIError as e:
            logger.warning(f"Failed to add tags/notes: {e}")
        
        # Mark application and event as completed
        application.processed_at = datetime.utcnow()
        
        session.execute(
            update(Event)
            .where(Event.greenhouse_event_id == greenhouse_event_id)
            .values(status="processed", processed_at=datetime.utcnow())
        )
        
        session.commit()
        
        logger.info(
            f"Completed processing application {application_id}: "
            f"score={result.score:.1f}, action={result.suggested_action}"
        )
        
        return {
            "application_id": application_id,
            "score": result.score,
            "action": result.suggested_action,
            "status": "completed",
        }
        
    except Exception as e:
        logger.exception(f"Error processing application {application_id}")
        
        # Update status to failed
        session.execute(
            update(Event)
            .where(Event.greenhouse_event_id == greenhouse_event_id)
            .values(status="failed", error_message=str(e))
        )
        session.commit()
        
        raise self.retry(exc=e)
        
    finally:
        session.close()


def add_to_human_review(
    session: Session,
    application: Application,
    result: ScoringResult,
):
    """Add application to human review queue."""
    review_reasons = []
    
    if result.confidence < 0.5:
        review_reasons.append(f"Low confidence score: {result.confidence:.0%}")
    
    if result.warnings:
        review_reasons.extend(result.warnings)
    
    if not result.hard_reject and result.suggested_action == "reject":
        review_reasons.append(f"Low score ({result.score:.1f}) needs confirmation")
    
    review_item = HumanReviewQueue(
        application_id=application.id,
        greenhouse_application_id=application.greenhouse_application_id,
        greenhouse_candidate_id=application.greenhouse_candidate_id,
        job_id=application.greenhouse_job_id,
        job_name=job_data.get("name", "Unknown"),  # Get from job_data fetched earlier
        status="pending",
        review_reasons=review_reasons,
        auto_score=result.score,
        confidence_score=result.confidence,
        suggested_action=result.suggested_action,
    )
    
    session.add(review_item)
    
    create_audit_log(
        session,
        action_type="human_review_added",
        description=f"Added to human review queue: {review_reasons}",
        application_id=str(application.id),
        greenhouse_application_id=application.greenhouse_application_id,
    )


@celery_app.task(bind=True, max_retries=3)
def process_stage_change(
    self,
    application_id: int,
    greenhouse_event_id: str,  # Changed from webhook_event_id
    payload: dict,
):
    """
    Process a stage change event.
    
    This can trigger additional automations based on the new stage.
    """
    logger.info(f"Processing stage change for application: {application_id}")
    
    session = get_db_session()
    
    try:
        new_stage = payload.get("application", {}).get("current_stage", {})
        stage_name = new_stage.get("name", "Unknown")
        stage_id = new_stage.get("id")
        
        # Update local application record if exists
        result = session.execute(
            select(Application).where(Application.greenhouse_application_id == application_id)
        )
        application = result.scalar_one_or_none()
        
        if application:
            application.current_stage_id = stage_id
            application.current_stage_name = stage_name
            
            create_audit_log(
                session,
                action_type="stage_change_received",
                description=f"Application moved to stage: {stage_name}",
                application_id=str(application.id),
                greenhouse_application_id=application_id,
                metadata={"stage_id": stage_id, "stage_name": stage_name},
            )
        
        # Update event status
        session.execute(
            update(Event)
            .where(Event.greenhouse_event_id == greenhouse_event_id)
            .values(status="processed", processed_at=datetime.utcnow())
        )
        
        session.commit()
        
        return {"application_id": application_id, "stage": stage_name}
        
    except Exception as e:
        logger.exception(f"Error processing stage change: {e}")
        session.execute(
            update(Event)
            .where(Event.greenhouse_event_id == greenhouse_event_id)
            .values(status="failed", error_message=str(e))
        )
        session.commit()
        raise self.retry(exc=e)
        
    finally:
        session.close()


# -----------------------------------------------------------------------------
# Email Tasks
# -----------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=3)
def send_candidate_email(
    self,
    candidate_id: int,
    greenhouse_candidate_id: int,
    to_email: str,
    subject: str,
    body: str,
    from_mailbox: Optional[str] = None,
):
    """
    Send an email to a candidate via Microsoft Graph.
    
    Also logs the email to Greenhouse activity feed.
    """
    session = get_db_session()
    graph = GraphClient()
    greenhouse = GreenhouseClient()
    
    try:
        import asyncio
        
        # Send email via Graph
        asyncio.get_event_loop().run_until_complete(
            graph.send_mail(
                to=[to_email],
                subject=subject,
                body=body,
                from_mailbox=from_mailbox,
            )
        )
        
        logger.info(f"Sent email to {to_email}: {subject}")
        
        create_audit_log(
            session,
            action_type="email_sent",
            description=f"Sent email to {to_email}: {subject}",
            greenhouse_candidate_id=greenhouse_candidate_id,
            metadata={"subject": subject, "to": to_email},
        )
        
        # Log email to Greenhouse
        asyncio.get_event_loop().run_until_complete(
            greenhouse.add_email_note(
                candidate_id=greenhouse_candidate_id,
                to=to_email,
                from_email=from_mailbox or settings.ms_mailbox,
                subject=subject,
                body=body,
            )
        )
        
        session.commit()
        
        return {"status": "sent", "to": to_email}
        
    except (GraphAPIError, GreenhouseAPIError) as e:
        logger.error(f"Failed to send email: {e}")
        raise self.retry(exc=e)
        
    finally:
        session.close()


# -----------------------------------------------------------------------------
# Interview Scheduling Tasks
# -----------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=3)
def schedule_interview(
    self,
    application_id: int,
    interview_type_id: int,
    interviewer_ids: list[int],
    start_time: str,  # ISO format
    end_time: str,
    candidate_email: str,
    location: Optional[str] = None,
):
    """
    Schedule an interview in both Greenhouse and Outlook.
    
    Uses external_event_id to link the Outlook event to Greenhouse.
    """
    session = get_db_session()
    graph = GraphClient()
    greenhouse = GreenhouseClient()
    
    try:
        import asyncio
        from datetime import datetime
        
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
        
        # First, create Outlook calendar event
        event_data = asyncio.get_event_loop().run_until_complete(
            graph.create_calendar_event(
                subject=f"Interview - Application {application_id}",
                start=start,
                end=end,
                attendees=[candidate_email],
                location=location,
                is_online_meeting=True,
            )
        )
        
        outlook_event_id = event_data.get("id")
        
        logger.info(f"Created Outlook event: {outlook_event_id}")
        
        # Then create Greenhouse interview with external_event_id
        interviewers = [{"user_id": uid} for uid in interviewer_ids]
        
        interview_data = asyncio.get_event_loop().run_until_complete(
            greenhouse.create_scheduled_interview(
                application_id=application_id,
                interview_id=interview_type_id,
                interviewers=interviewers,
                start=start,
                end=end,
                external_event_id=outlook_event_id,
                location=location,
            )
        )
        
        create_audit_log(
            session,
            action_type="interview_scheduled",
            description=f"Scheduled interview for application {application_id}",
            greenhouse_application_id=application_id,
            metadata={
                "outlook_event_id": outlook_event_id,
                "greenhouse_interview_id": interview_data.get("id"),
                "start": start_time,
                "end": end_time,
            },
        )
        
        session.commit()
        
        return {
            "status": "scheduled",
            "outlook_event_id": outlook_event_id,
            "greenhouse_interview_id": interview_data.get("id"),
        }
        
    except Exception as e:
        logger.exception(f"Failed to schedule interview: {e}")
        raise self.retry(exc=e)
        
    finally:
        session.close()


# -----------------------------------------------------------------------------
# Maintenance Tasks
# -----------------------------------------------------------------------------

@celery_app.task
def cleanup_old_events():
    """Clean up old webhook events and audit logs."""
    session = get_db_session()
    
    try:
        # Delete webhook events older than 30 days
        cutoff = datetime.utcnow() - timedelta(days=30)
        
        deleted = session.query(WebhookEvent).filter(
            WebhookEvent.received_at < cutoff,
            WebhookEvent.status.in_(["completed", "failed"]),
        ).delete(synchronize_session=False)
        
        session.commit()
        
        logger.info(f"Cleaned up {deleted} old webhook events")
        
        return {"deleted_events": deleted}
        
    finally:
        session.close()


@celery_app.task
def retry_failed_applications():
    """Retry processing failed applications."""
    session = get_db_session()
    
    try:
        # Find failed applications with retry_count < 3
        failed = session.query(Application).filter(
            Application.processing_status == "failed",
            Application.retry_count < 3,
        ).all()
        
        retried = 0
        for app in failed:
            app.retry_count += 1
            app.processing_status = "pending"
            
            # Re-queue for processing
            process_new_application.delay(
                application_id=app.greenhouse_id,
                webhook_event_id=None,
                payload={},
            )
            retried += 1
        
        session.commit()
        
        logger.info(f"Retried {retried} failed applications")
        
        return {"retried": retried}
        
    finally:
        session.close()
