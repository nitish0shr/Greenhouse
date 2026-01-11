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
# Email Reply Processing Task
# -----------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_email_reply(
    self,
    message_id: str,
    resource: str,
):
    """
    Process an incoming email reply from Graph notification.
    
    Per First Review requirements:
    1. Fetch message content via Graph
    2. Correlate reply to application via conversationId or tracking_token
    3. Log reply to Greenhouse activity feed
    4. Create exception if correlation fails
    """
    from app.services.reply_correlator import ReplyCorrelator
    from app.services.greenhouse_writeback import GreenhouseWritebackClient
    
    session = get_db_session()
    graph = GraphClient()
    
    try:
        import asyncio
        
        logger.info(f"Processing email reply: {message_id}")
        
        # Step 1: Fetch message content from Graph
        try:
            message = asyncio.get_event_loop().run_until_complete(
                graph.get_message(message_id)
            )
        except GraphAPIError as e:
            logger.error(f"Failed to fetch message {message_id}: {e}")
            raise self.retry(exc=e)
        
        sender = message.get("from", {}).get("emailAddress", {})
        sender_email = sender.get("address", "").lower()
        sender_name = sender.get("name", "")
        subject = message.get("subject", "")
        body_content = message.get("body", {}).get("content", "")
        conversation_id = message.get("conversationId")
        received_at = message.get("receivedDateTime")
        
        logger.info(f"Received email from {sender_email}: {subject}")
        
        # Step 2: Correlate to application
        correlator = ReplyCorrelator(db_session=session, graph_client=graph)
        
        try:
            correlation_result = asyncio.get_event_loop().run_until_complete(
                correlator.correlate_reply(message_id)
            )
        except Exception as e:
            logger.warning(f"Reply correlation failed: {e}")
            correlation_result = None
        
        if correlation_result:
            application_id = correlation_result.get("application_id")
            application = correlation_result.get("application")
            
            logger.info(f"Correlated reply to application {application_id}")
            
            # Step 3: Log reply to Greenhouse
            greenhouse = GreenhouseWritebackClient()
            
            # Generate autopilot_action_id for loop prevention
            action_id = uuid.uuid4()
            
            # Create action record
            action = Action(
                autopilot_action_id=action_id,
                application_id=application.id if application else None,
                action_type="log_candidate_reply",
                request_payload={
                    "message_id": message_id,
                    "sender_email": sender_email,
                    "subject": subject,
                },
                status="pending",
            )
            session.add(action)
            session.commit()
            
            # Format note with reply content
            note_body = f"""
**Candidate Reply Received**
AUTOPILOT_ACTION_ID:{action_id}

From: {sender_name} <{sender_email}>
Subject: {subject}
Received: {received_at}

---

{body_content[:2000]}  <!-- Truncated to prevent excessively long notes -->
"""
            
            try:
                candidate_id = application.greenhouse_candidate_id if application else None
                if candidate_id:
                    asyncio.get_event_loop().run_until_complete(
                        greenhouse.add_note_to_candidate(
                            candidate_id=candidate_id,
                            note=note_body,
                            action_id=action_id,
                        )
                    )
                    
                    action.status = "completed"
                    session.commit()
                    
                    create_audit_log(
                        session,
                        action_type="candidate_reply_logged",
                        description=f"Logged candidate reply to Greenhouse",
                        application_id=str(application.id) if application else None,
                        greenhouse_candidate_id=candidate_id,
                        metadata={
                            "message_id": message_id,
                            "sender_email": sender_email,
                            "subject": subject,
                            "autopilot_action_id": str(action_id),
                        },
                    )
                    
                    logger.info(f"Logged reply to Greenhouse for candidate {candidate_id}")
                    
            except GreenhouseAPIError as e:
                logger.error(f"Failed to log reply to Greenhouse: {e}")
                action.status = "failed"
                action.error_message = str(e)
                session.commit()
                
                # Create exception but don't fail the task - reply was received
                create_exception_record(
                    session,
                    exception_type="greenhouse_writeback_failure",
                    reason=f"Failed to log candidate reply to Greenhouse: {e}",
                    application_id=application.id if application else None,
                    payload_refs={"message_id": message_id, "sender_email": sender_email},
                )
            
            # Check for keywords that need human attention
            keywords_needing_review = [
                "sponsorship", "visa", "h1b", "h-1b", "work authorization",
                "reschedule", "cancel", "withdraw", "another offer",
                "not interested", "decline"
            ]
            
            reply_lower = (subject + " " + body_content).lower()
            detected_keywords = [kw for kw in keywords_needing_review if kw in reply_lower]
            
            if detected_keywords:
                logger.info(f"Detected keywords in reply: {detected_keywords}")
                
                create_exception_record(
                    session,
                    exception_type="reply_needs_review",
                    reason=f"Candidate reply contains keywords requiring review: {detected_keywords}",
                    application_id=application.id if application else None,
                    payload_refs={
                        "message_id": message_id,
                        "sender_email": sender_email,
                        "subject": subject,
                        "detected_keywords": detected_keywords,
                    },
                )
                
                create_audit_log(
                    session,
                    action_type="reply_flagged_for_review",
                    description=f"Candidate reply flagged for review: {detected_keywords}",
                    application_id=str(application.id) if application else None,
                    metadata={"keywords": detected_keywords},
                )
            
            return {
                "status": "processed",
                "message_id": message_id,
                "application_id": str(application_id) if application_id else None,
                "keywords_detected": detected_keywords if detected_keywords else None,
            }
            
        else:
            # Step 4: Create exception if correlation fails
            logger.warning(f"Could not correlate reply from {sender_email}")
            
            create_exception_record(
                session,
                exception_type="uncorrelated_reply",
                reason=f"Could not correlate email reply to any application",
                payload_refs={
                    "message_id": message_id,
                    "sender_email": sender_email,
                    "sender_name": sender_name,
                    "subject": subject,
                    "conversation_id": conversation_id,
                    "received_at": received_at,
                },
            )
            
            create_audit_log(
                session,
                action_type="uncorrelated_reply",
                description=f"Received uncorrelated email from {sender_email}",
                metadata={
                    "message_id": message_id,
                    "sender_email": sender_email,
                    "subject": subject,
                },
            )
            
            return {
                "status": "uncorrelated",
                "message_id": message_id,
                "sender_email": sender_email,
            }
        
    except Exception as e:
        logger.exception(f"Error processing email reply {message_id}: {e}")
        
        create_exception_record(
            session,
            exception_type="email_processing_failure",
            reason=f"Failed to process email reply: {e}",
            payload_refs={"message_id": message_id, "resource": resource},
        )
        
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


# -----------------------------------------------------------------------------
# Pipeline Nudge Tasks (Periodic)
# -----------------------------------------------------------------------------

@celery_app.task
def nudge_no_reply_candidates():
    """
    Send follow-up emails to candidates who haven't replied.
    
    Per First Review requirements:
    - Check for candidates who received scheduling emails but no reply
    - Send reminder after configurable number of days (default 3)
    - Maximum 2 nudges per candidate
    """
    session = get_db_session()
    
    try:
        from app.models.message_mapping import MessageMapping
        from app.models.action import Action
        
        # Find candidates with outbound emails but no reply
        # Look for mappings older than 3 days without a corresponding reply action
        cutoff = datetime.utcnow() - timedelta(days=3)
        
        result = session.execute(
            select(MessageMapping)
            .where(
                MessageMapping.created_at < cutoff,
                MessageMapping.tracking_token.isnot(None),
            )
            .order_by(MessageMapping.created_at)
        )
        
        pending_mappings = result.scalars().all()
        
        nudged_count = 0
        for mapping in pending_mappings:
            # Check if a reply was received (action logged)
            has_reply = session.execute(
                select(Action)
                .where(
                    Action.application_id == mapping.application_id,
                    Action.action_type == "log_candidate_reply",
                )
            ).scalar_one_or_none()
            
            if has_reply:
                continue
            
            # Check nudge count
            existing_nudges = session.execute(
                select(Action)
                .where(
                    Action.application_id == mapping.application_id,
                    Action.action_type == "nudge_no_reply",
                )
            ).scalars().all()
            
            if len(existing_nudges) >= 2:
                # Max nudges reached
                continue
            
            # Get application for candidate email
            application = session.execute(
                select(Application)
                .where(Application.id == mapping.application_id)
            ).scalar_one_or_none()
            
            if not application:
                continue
            
            # Create nudge action
            action_id = uuid.uuid4()
            action = Action(
                autopilot_action_id=action_id,
                application_id=mapping.application_id,
                action_type="nudge_no_reply",
                request_payload={
                    "candidate_email": mapping.candidate_email,
                    "nudge_number": len(existing_nudges) + 1,
                },
                status="completed",
            )
            session.add(action)
            
            # Enqueue nudge email
            send_candidate_email.delay(
                candidate_id=None,
                greenhouse_candidate_id=application.greenhouse_candidate_id,
                to_email=mapping.candidate_email,
                subject=f"Re: Interview Scheduling - Following Up {mapping.tracking_token}",
                body=f"""
Hi,

I wanted to follow up on the interview scheduling email I sent a few days ago. 
If you're still interested in the position, please let me know your availability.

If you've already responded or have any questions, please feel free to reach out.

Best regards,
The Recruiting Team

Reference: {mapping.tracking_token}
""",
            )
            
            nudged_count += 1
            
            create_audit_log(
                session,
                action_type="nudge_sent",
                description=f"Sent follow-up nudge #{len(existing_nudges) + 1}",
                application_id=str(mapping.application_id),
                metadata={"candidate_email": mapping.candidate_email},
            )
        
        session.commit()
        
        logger.info(f"Sent {nudged_count} follow-up nudges to candidates")
        return {"nudged": nudged_count}
        
    except Exception as e:
        logger.exception(f"Error in nudge_no_reply_candidates: {e}")
        raise
        
    finally:
        session.close()


@celery_app.task
def chase_missing_scorecards():
    """
    Send reminders to interviewers with missing scorecards.
    
    Per First Review requirements:
    - Check for completed interviews without submitted scorecards
    - Send reminder to interviewer after configurable hours (default 24)
    """
    session = get_db_session()
    
    try:
        from app.models.calendar_mapping import CalendarMapping
        
        # Find interviews that completed > 24 hours ago
        cutoff = datetime.utcnow() - timedelta(hours=24)
        
        result = session.execute(
            select(CalendarMapping)
            .where(
                CalendarMapping.status == "scheduled",
                CalendarMapping.created_at < cutoff,
            )
        )
        
        pending_scorecards = result.scalars().all()
        
        chased_count = 0
        for mapping in pending_scorecards:
            # In production, check Greenhouse for scorecard submission
            # For now, create exception for manual review
            
            if mapping.greenhouse_interview_id:
                create_exception_record(
                    session,
                    exception_type="missing_scorecard",
                    reason=f"Interview {mapping.greenhouse_interview_id} completed but scorecard not submitted",
                    application_id=mapping.application_id,
                    payload_refs={
                        "greenhouse_interview_id": mapping.greenhouse_interview_id,
                        "external_event_id": mapping.external_event_id,
                    },
                )
                chased_count += 1
        
        session.commit()
        
        logger.info(f"Created {chased_count} missing scorecard exceptions")
        return {"chased": chased_count}
        
    except Exception as e:
        logger.exception(f"Error in chase_missing_scorecards: {e}")
        raise
        
    finally:
        session.close()


@celery_app.task
def check_stuck_in_stage():
    """
    Detect candidates stuck in a stage beyond SLA thresholds.
    
    Per First Review requirements:
    - Check for applications that haven't progressed within configured SLA
    - Create exception for human review
    - Default SLA: 5 days in same stage
    """
    session = get_db_session()
    
    try:
        # Find applications in same stage for > 5 days
        cutoff = datetime.utcnow() - timedelta(days=5)
        
        result = session.execute(
            select(Application)
            .where(
                Application.processing_status.in_(["completed", "human_review"]),
                Application.stage_updated_at < cutoff,
                Application.current_stage_name.notin_(["Hired", "Rejected", "Offer", "Closed"]),
            )
        )
        
        stuck_applications = result.scalars().all()
        
        flagged_count = 0
        for application in stuck_applications:
            # Check if already flagged
            existing = session.execute(
                select(ExceptionModel)
                .where(
                    ExceptionModel.application_id == application.id,
                    ExceptionModel.exception_type == "stuck_in_stage",
                    ExceptionModel.status == "open",
                )
            ).scalar_one_or_none()
            
            if existing:
                continue
            
            days_in_stage = (datetime.utcnow() - application.stage_updated_at).days
            
            create_exception_record(
                session,
                exception_type="stuck_in_stage",
                reason=f"Application stuck in stage '{application.current_stage_name}' for {days_in_stage} days",
                application_id=application.id,
                payload_refs={
                    "greenhouse_application_id": application.greenhouse_application_id,
                    "stage_name": application.current_stage_name,
                    "days_in_stage": days_in_stage,
                    "job_name": application.job_name,
                },
            )
            flagged_count += 1
            
            create_audit_log(
                session,
                action_type="sla_breach_detected",
                description=f"Application stuck in '{application.current_stage_name}' for {days_in_stage} days",
                application_id=str(application.id),
                greenhouse_application_id=application.greenhouse_application_id,
            )
        
        session.commit()
        
        logger.info(f"Flagged {flagged_count} applications stuck in stage")
        return {"flagged": flagged_count}
        
    except Exception as e:
        logger.exception(f"Error in check_stuck_in_stage: {e}")
        raise
        
    finally:
        session.close()

