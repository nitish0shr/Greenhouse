# =============================================================================
# Microsoft Graph Webhook Receiver
# =============================================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session

logger = logging.getLogger(__name__)
router = APIRouter()


# -----------------------------------------------------------------------------
# Graph Notification Endpoint
# -----------------------------------------------------------------------------

@router.post("/notifications", status_code=status.HTTP_202_ACCEPTED)
async def graph_notifications(
    request: Request,
    validation_token: Optional[str] = Query(None, alias="validationToken"),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Receive Microsoft Graph change notifications.
    
    This endpoint handles:
    1. Subscription validation (returns validationToken)
    2. Change notifications (processes email/calendar changes)
    """
    # Handle subscription validation
    if validation_token:
        logger.info("Received Graph subscription validation request")
        return Response(
            content=validation_token,
            media_type="text/plain",
            status_code=status.HTTP_200_OK,
        )
    
    # Parse notification payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse Graph notification JSON: {e}")
        return {"status": "error", "message": "Invalid JSON"}
    
    # Process each notification
    notifications = payload.get("value", [])
    
    for notification in notifications:
        await process_graph_notification(notification, session)
    
    return {"status": "accepted", "count": len(notifications)}


async def process_graph_notification(
    notification: dict,
    session: AsyncSession,
):
    """
    Process a single Graph change notification.
    
    Args:
        notification: Notification data from Graph
        session: Database session
    """
    resource = notification.get("resource", "")
    change_type = notification.get("changeType", "")
    client_state = notification.get("clientState", "")
    
    logger.info(f"Processing Graph notification: {change_type} on {resource}")
    
    # Validate client state if configured
    # if client_state != settings.graph_client_state:
    #     logger.warning("Invalid client state in Graph notification")
    #     return
    
    # Determine resource type and handle accordingly
    if "/messages" in resource:
        await handle_email_notification(notification, session)
    elif "/events" in resource:
        await handle_calendar_notification(notification, session)
    else:
        logger.info(f"Unhandled Graph resource type: {resource}")


async def handle_email_notification(
    notification: dict,
    session: AsyncSession,
):
    """
    Handle email-related notifications (new replies, etc.)
    
    Per First Review requirements:
    - Track candidate replies to automated emails
    - Correlate replies to applications via conversationId or tracking_token
    - Log reply to Greenhouse activity feed
    - Create exception if correlation fails
    """
    from app.workers.tasks import process_email_reply
    
    resource = notification.get("resource", "")
    change_type = notification.get("changeType", "")
    resource_data = notification.get("resourceData", {})
    
    message_id = resource_data.get("id")
    
    if change_type == "created" and message_id:
        logger.info(f"New email received, enqueuing for processing: {message_id}")
        
        # Enqueue to Celery worker for processing
        # This keeps the webhook handler fast and idempotent
        try:
            process_email_reply.delay(
                message_id=message_id,
                resource=resource,
            )
        except Exception as e:
            logger.error(f"Failed to enqueue email processing: {e}", exc_info=True)
            # Don't fail the webhook - we received the notification
    
    elif change_type == "updated":
        logger.info(f"Email updated: {message_id}")
        # Updates are typically read receipts or flag changes - no action needed




async def handle_calendar_notification(
    notification: dict,
    session: AsyncSession,
):
    """
    Handle calendar-related notifications (event changes, etc.)
    
    This can be used to:
    - Sync Outlook calendar changes back to Greenhouse
    - Handle interview rescheduling/cancellations
    """
    resource = notification.get("resource", "")
    change_type = notification.get("changeType", "")
    resource_data = notification.get("resourceData", {})
    
    event_id = resource_data.get("id")
    
    if change_type == "updated":
        logger.info(f"Calendar event updated: {event_id}")
        # TODO: Fetch event details and update Greenhouse
        # - Use external_event_id to find corresponding interview
        # - Update interview time if changed
    
    elif change_type == "deleted":
        logger.info(f"Calendar event deleted: {event_id}")
        # TODO: Handle interview cancellation


# -----------------------------------------------------------------------------
# Subscription Management Endpoints
# -----------------------------------------------------------------------------

@router.post("/subscriptions/email")
async def create_email_subscription(
    mailbox: Optional[str] = None,
):
    """
    Create a subscription for email notifications.
    
    This sets up webhooks for incoming emails to the recruiting mailbox.
    """
    from app.services.microsoft_graph import graph_client
    
    mailbox = mailbox or settings.ms_mailbox
    resource = f"users/{mailbox}/messages"
    
    # TODO: Use actual notification URL
    notification_url = "https://your-domain.com/api/graph/notifications"
    
    try:
        result = await graph_client.create_subscription(
            resource=resource,
            notification_url=notification_url,
            change_types=["created"],
            client_state="recruiter-autopilot",
        )
        
        return {
            "status": "created",
            "subscription_id": result.get("id"),
            "expiration": result.get("expirationDateTime"),
        }
    
    except Exception as e:
        logger.error(f"Failed to create email subscription: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/subscriptions/calendar")
async def create_calendar_subscription(
    mailbox: Optional[str] = None,
):
    """
    Create a subscription for calendar notifications.
    
    This sets up webhooks for calendar changes (interview scheduling).
    """
    from app.services.microsoft_graph import graph_client
    
    mailbox = mailbox or settings.ms_mailbox
    resource = f"users/{mailbox}/events"
    
    # TODO: Use actual notification URL
    notification_url = "https://your-domain.com/api/graph/notifications"
    
    try:
        result = await graph_client.create_subscription(
            resource=resource,
            notification_url=notification_url,
            change_types=["created", "updated", "deleted"],
            client_state="recruiter-autopilot",
        )
        
        return {
            "status": "created",
            "subscription_id": result.get("id"),
            "expiration": result.get("expirationDateTime"),
        }
    
    except Exception as e:
        logger.error(f"Failed to create calendar subscription: {e}")
        return {"status": "error", "message": str(e)}
