# =============================================================================
# Greenhouse Webhook Receiver - First Review Implementation
# =============================================================================

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models.event import Event
from app.utils.security import verify_greenhouse_signature
from app.workers.tasks import process_greenhouse_event

logger = logging.getLogger(__name__)
router = APIRouter()


# -----------------------------------------------------------------------------
# Webhook Endpoint - POST /webhooks/greenhouse
# -----------------------------------------------------------------------------

@router.post("/webhooks/greenhouse", status_code=status.HTTP_200_OK)
async def greenhouse_webhook(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    signature: Optional[str] = Header(None, alias="Signature"),
    event_id: Optional[str] = Header(None, alias="Greenhouse-Event-ID"),
):
    """
    Receive and process Greenhouse webhooks.
    
    Per First Review requirements:
    1. Verify HMAC-SHA256 signature (raw bytes, constant-time compare)
    2. Check idempotency via Greenhouse-Event-ID (UNIQUE constraint)
    3. Store event in events table with signature_valid flag
    4. Enqueue to Celery worker (fast response < 100ms)
    5. Return HTTP 200 quickly
    
    Args:
        request: FastAPI Request object
        session: Database session
        signature: Signature header (HMAC-SHA256)
        event_id: Greenhouse-Event-ID header (for idempotency)
    
    Returns:
        200 OK with status (even if duplicate/idempotent)
        401 Unauthorized if signature invalid
    """
    # Get raw body bytes BEFORE any JSON parsing (critical for signature verification)
    body_bytes = await request.body()
    
    # Verify signature (must use raw bytes)
    signature_valid = False
    if signature:
        signature_valid = verify_greenhouse_signature(body_bytes, signature)
        if not signature_valid:
            logger.warning(f"Invalid webhook signature for event {event_id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature",
            )
    else:
        logger.warning("Webhook received without signature header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing signature header",
        )
    
    # Parse JSON payload (after signature verification)
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )
    
    # Extract event type
    event_type = payload.get("action", "unknown")
    
    # Check idempotency - have we already processed this event?
    if not event_id:
        logger.warning("Webhook received without Greenhouse-Event-ID header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Greenhouse-Event-ID header",
        )
    
    # Check for duplicate event (idempotency)
    existing = await session.execute(
        select(Event).where(Event.greenhouse_event_id == event_id)
    )
    if existing.scalar_one_or_none():
        logger.info(f"Ignoring duplicate webhook event (idempotent): {event_id}")
        # Return 200 OK - Greenhouse expects 200 for idempotent duplicates
        return {"status": "duplicate", "event_id": event_id}
    
    # Create event record
    event = Event(
        greenhouse_event_id=event_id,
        event_type=event_type,
        raw_body_json=payload,  # Store parsed JSON (matches First Review schema)
        signature_valid=signature_valid,
        status="pending",
        received_at=datetime.utcnow(),
    )
    session.add(event)
    
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to store event {event_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store event",
        )
    
    # Enqueue to Celery worker (async, non-blocking)
    try:
        process_greenhouse_event.delay(
            greenhouse_event_id=event_id,
            event_type=event_type,
            payload=payload,
        )
        logger.info(f"Enqueued webhook event: {event_id} ({event_type})")
    except Exception as e:
        logger.error(f"Failed to enqueue event {event_id}: {e}", exc_info=True)
        # Don't fail the request - event is stored, can retry later
    
    # Return 200 OK quickly (per First Review: fast response)
    return {
        "status": "accepted",
        "event_id": event_id,
        "event_type": event_type,
    }


# -----------------------------------------------------------------------------
# Webhook Status Endpoint (for debugging/monitoring)
# -----------------------------------------------------------------------------

@router.get("/webhooks/greenhouse/status/{event_id}")
async def get_webhook_status(
    event_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Check the processing status of a webhook event.
    
    Useful for debugging and monitoring.
    """
    result = await session.execute(
        select(Event).where(Event.greenhouse_event_id == event_id)
    )
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook event not found",
        )
    
    return {
        "event_id": event.greenhouse_event_id,
        "event_type": event.event_type,
        "signature_valid": event.signature_valid,
        "status": event.status,
        "received_at": event.received_at.isoformat(),
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
        "error_message": event.error_message,
    }
