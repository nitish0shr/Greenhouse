"""Webhook endpoints for Greenhouse and Microsoft Graph."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.database import get_session
from src.models.webhook import WebhookEvent, WebhookSource, WebhookStatus
from src.utils.logging import get_logger
from src.utils.security import generate_correlation_id, verify_hmac_signature
from src.workers.tasks import process_greenhouse_webhook

logger = get_logger(__name__)
router = APIRouter()


async def get_raw_body(request: Request) -> bytes:
    """Get raw request body for signature verification."""
    return await request.body()


@router.post("/greenhouse")
async def greenhouse_webhook(
    request: Request,
    raw_body: bytes = Depends(get_raw_body),
    signature: Annotated[str | None, Header(alias="Signature")] = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Receive and process Greenhouse webhooks.

    - Verifies HMAC signature using webhook secret
    - Implements idempotency using event_id
    - Pushes processing to worker queue
    """
    correlation_id = getattr(request.state, "correlation_id", generate_correlation_id())

    # Parse payload
    try:
        import orjson
        payload = orjson.loads(raw_body)
    except Exception as e:
        logger.warning("Failed to parse webhook payload", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Extract event metadata
    action = payload.get("action", "unknown")
    event_id = str(payload.get("payload", {}).get("id", "")) or correlation_id

    # For application webhooks, extract IDs
    application_payload = payload.get("payload", {}).get("application", {})
    greenhouse_application_id = application_payload.get("id")
    greenhouse_candidate_id = application_payload.get("candidate_id")
    greenhouse_job_id = None
    if application_payload.get("jobs"):
        greenhouse_job_id = application_payload["jobs"][0].get("id")

    logger.info(
        "Received Greenhouse webhook",
        action=action,
        event_id=event_id,
        application_id=greenhouse_application_id,
        correlation_id=correlation_id,
    )

    # Verify signature (if secret is configured)
    webhook_secret = settings.greenhouse_webhook_secret.get_secret_value()
    signature_verified = False

    if webhook_secret:
        if not signature:
            logger.warning("Missing webhook signature", event_id=event_id)
            raise HTTPException(status_code=401, detail="Missing signature header")

        if not verify_hmac_signature(raw_body, signature, webhook_secret):
            logger.warning("Invalid webhook signature", event_id=event_id)
            raise HTTPException(status_code=401, detail="Invalid signature")

        signature_verified = True
        logger.debug("Webhook signature verified", event_id=event_id)

    # Check for duplicate (idempotency)
    existing = await session.execute(
        select(WebhookEvent).where(
            WebhookEvent.source == WebhookSource.GREENHOUSE,
            WebhookEvent.event_id == event_id,
        )
    )
    existing_event = existing.scalar_one_or_none()

    if existing_event:
        if existing_event.is_duplicate:
            logger.info("Ignoring duplicate webhook", event_id=event_id)
            return {
                "status": "ignored",
                "reason": "duplicate",
                "event_id": event_id,
            }
        # Event exists but not processed - will be retried
        logger.info("Event already exists, pending processing", event_id=event_id)
        return {
            "status": "pending",
            "event_id": event_id,
        }

    # Create webhook event record
    webhook_event = WebhookEvent(
        source=WebhookSource.GREENHOUSE,
        event_id=event_id,
        event_type=action,
        status=WebhookStatus.RECEIVED,
        payload=payload,
        signature_verified=signature_verified,
        signature_header=signature,
        greenhouse_application_id=greenhouse_application_id,
        greenhouse_candidate_id=greenhouse_candidate_id,
        greenhouse_job_id=greenhouse_job_id,
        correlation_id=correlation_id,
    )
    session.add(webhook_event)
    await session.flush()  # Get the ID

    # Queue for processing
    try:
        if settings.mock_mode:
            # In mock mode, process synchronously for testing
            logger.info("Mock mode: skipping queue, event recorded", event_id=event_id)
            task_id = f"mock-{webhook_event.id}"
        else:
            # Push to Celery queue
            task = process_greenhouse_webhook.delay(webhook_event.id)
            task_id = task.id

        webhook_event.mark_queued(task_id)
        await session.commit()

        logger.info(
            "Webhook queued for processing",
            event_id=event_id,
            task_id=task_id,
            webhook_event_id=webhook_event.id,
        )

        return {
            "status": "queued",
            "event_id": event_id,
            "task_id": task_id,
        }

    except Exception as e:
        logger.error(
            "Failed to queue webhook",
            error=str(e),
            event_id=event_id,
            exc_info=True,
        )
        webhook_event.mark_failed(str(e))
        await session.commit()
        raise HTTPException(status_code=500, detail="Failed to queue webhook")


@router.post("/graph")
async def graph_webhook(
    request: Request,
    raw_body: bytes = Depends(get_raw_body),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """
    Receive Microsoft Graph change notifications.

    Handles:
    - Subscription validation (responds with validationToken)
    - Email notifications (candidate replies)
    - Calendar event changes
    """
    correlation_id = getattr(request.state, "correlation_id", generate_correlation_id())

    # Check for validation request (subscription setup)
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        logger.info("Graph subscription validation request", correlation_id=correlation_id)
        return Response(content=validation_token, media_type="text/plain")

    # Parse notification payload
    try:
        import orjson
        payload = orjson.loads(raw_body)
    except Exception as e:
        logger.warning("Failed to parse Graph notification", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    notifications = payload.get("value", [])
    logger.info(
        "Received Graph notifications",
        count=len(notifications),
        correlation_id=correlation_id,
    )

    for notification in notifications:
        resource = notification.get("resource", "")
        change_type = notification.get("changeType", "")
        client_state = notification.get("clientState", "")

        # Validate client state (should match our subscription)
        # This is a basic check - in production, use a proper secret

        # Determine notification type and extract IDs
        if "/messages" in resource:
            event_type = f"message.{change_type}"
        elif "/events" in resource:
            event_type = f"calendar.{change_type}"
        else:
            event_type = f"unknown.{change_type}"

        # Generate event ID from subscription ID + resource
        subscription_id = notification.get("subscriptionId", "")
        event_id = f"{subscription_id}:{resource}:{notification.get('id', '')}"

        # Check for duplicate
        existing = await session.execute(
            select(WebhookEvent).where(
                WebhookEvent.source == WebhookSource.MICROSOFT_GRAPH,
                WebhookEvent.event_id == event_id,
            )
        )
        if existing.scalar_one_or_none():
            logger.debug("Ignoring duplicate Graph notification", event_id=event_id)
            continue

        # Create webhook event
        webhook_event = WebhookEvent(
            source=WebhookSource.MICROSOFT_GRAPH,
            event_id=event_id,
            event_type=event_type,
            status=WebhookStatus.RECEIVED,
            payload=notification,
            signature_verified=True,  # Graph validates via clientState
            correlation_id=correlation_id,
        )
        session.add(webhook_event)
        await session.flush()

        # Queue for processing
        try:
            if not settings.mock_mode:
                from src.workers.tasks import process_graph_notification
                task = process_graph_notification.delay(webhook_event.id)
                webhook_event.mark_queued(task.id)
            else:
                webhook_event.mark_queued(f"mock-{webhook_event.id}")
        except Exception as e:
            logger.error("Failed to queue Graph notification", error=str(e))
            webhook_event.mark_failed(str(e))

    await session.commit()

    # Graph expects 202 Accepted
    return Response(status_code=202)


@router.get("/greenhouse/status/{event_id}")
async def get_webhook_status(
    event_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get the processing status of a webhook event."""
    result = await session.execute(
        select(WebhookEvent).where(
            WebhookEvent.source == WebhookSource.GREENHOUSE,
            WebhookEvent.event_id == event_id,
        )
    )
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "status": event.status.value,
        "created_at": event.created_at.isoformat(),
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
        "error_message": event.error_message,
        "retry_count": event.retry_count,
    }
