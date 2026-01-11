# =============================================================================
# Admin Endpoints - Kill Switches, Replay, Exception Management
# =============================================================================

import logging
from datetime import datetime, timedelta
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_

from app.database import get_async_session, SyncSessionLocal
from app.models.job_config import JobConfig
from app.models.exception import Exception as ExceptionModel
from app.models.event import Event
from app.models.application import Application
from app.models.feature_flag import FeatureFlag, FeatureFlags
from app.services.feature_flags import FeatureFlagService
from app.workers.tasks import process_greenhouse_event

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class KillSwitchRequest(BaseModel):
    enabled: bool


class FeatureFlagRequest(BaseModel):
    enabled: bool
    description: Optional[str] = None


class ReplayRequest(BaseModel):
    force: bool = False  # Force replay even if already processed


# -----------------------------------------------------------------------------
# Kill Switch Endpoints
# -----------------------------------------------------------------------------

@router.post("/kill-switch/global", status_code=status.HTTP_200_OK)
async def set_global_kill_switch(
    request: KillSwitchRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Set global kill switch (disable/enable all automation).

    When disabled, all automation stops but webhooks are still received and stored.
    """
    # Update or create the feature flag
    result = await session.execute(
        select(FeatureFlag).where(
            and_(
                FeatureFlag.name == FeatureFlags.ENABLE_AUTOPILOT_GLOBAL,
                FeatureFlag.scope == "global",
            )
        )
    )
    flag = result.scalar_one_or_none()

    if flag:
        flag.enabled = request.enabled
    else:
        flag = FeatureFlag(
            name=FeatureFlags.ENABLE_AUTOPILOT_GLOBAL,
            enabled=request.enabled,
            scope="global",
            description="Global autopilot kill switch",
        )
        session.add(flag)

    await session.commit()

    action = "ENABLED" if request.enabled else "DISABLED"
    logger.warning(f"Global autopilot kill switch {action}")

    return {
        "status": "ok",
        "flag": FeatureFlags.ENABLE_AUTOPILOT_GLOBAL,
        "enabled": request.enabled,
        "message": f"Global autopilot {action.lower()}",
    }


@router.post("/kill-switch/job/{job_id}", status_code=status.HTTP_200_OK)
async def set_job_kill_switch(
    job_id: int,
    request: KillSwitchRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Set kill switch for a specific job.

    Args:
        job_id: Greenhouse job ID
        enabled: Whether automation is enabled for this job
    """
    # Update or create JobConfig
    result = await session.execute(
        select(JobConfig).where(JobConfig.greenhouse_job_id == job_id)
    )
    config = result.scalar_one_or_none()

    if config:
        config.enabled = request.enabled
    else:
        config = JobConfig(
            greenhouse_job_id=job_id,
            enabled=request.enabled,
        )
        session.add(config)

    await session.commit()

    action = "ENABLED" if request.enabled else "DISABLED"
    logger.info(f"Job {job_id} autopilot {action}")

    return {
        "status": "ok",
        "job_id": job_id,
        "enabled": request.enabled,
        "message": f"Job {job_id} autopilot {action.lower()}",
    }


@router.get("/kill-switch/status", status_code=status.HTTP_200_OK)
async def get_kill_switch_status(
    session: AsyncSession = Depends(get_async_session),
):
    """Get current status of all kill switches."""
    # Get global flag
    global_result = await session.execute(
        select(FeatureFlag).where(
            and_(
                FeatureFlag.name == FeatureFlags.ENABLE_AUTOPILOT_GLOBAL,
                FeatureFlag.scope == "global",
            )
        )
    )
    global_flag = global_result.scalar_one_or_none()
    global_enabled = global_flag.enabled if global_flag else True

    # Get job-level flags
    job_result = await session.execute(
        select(JobConfig).order_by(JobConfig.greenhouse_job_id)
    )
    job_configs = job_result.scalars().all()

    return {
        "global_enabled": global_enabled,
        "jobs": [
            {
                "job_id": config.greenhouse_job_id,
                "enabled": config.enabled,
            }
            for config in job_configs
        ],
    }


# -----------------------------------------------------------------------------
# Feature Flag Endpoints
# -----------------------------------------------------------------------------

@router.get("/feature-flags", status_code=status.HTTP_200_OK)
async def list_feature_flags(
    session: AsyncSession = Depends(get_async_session),
):
    """List all feature flags."""
    result = await session.execute(
        select(FeatureFlag).order_by(FeatureFlag.scope, FeatureFlag.name)
    )
    flags = result.scalars().all()

    return {
        "flags": [
            {
                "id": str(flag.id),
                "name": flag.name,
                "enabled": flag.enabled,
                "scope": flag.scope,
                "scope_id": flag.scope_id,
                "description": flag.description,
            }
            for flag in flags
        ]
    }


@router.post("/feature-flags/{flag_name}", status_code=status.HTTP_200_OK)
async def set_feature_flag(
    flag_name: str,
    request: FeatureFlagRequest,
    scope: str = Query("global"),
    scope_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_async_session),
):
    """Set a feature flag value."""
    # Find or create flag
    query = select(FeatureFlag).where(
        and_(
            FeatureFlag.name == flag_name,
            FeatureFlag.scope == scope,
        )
    )
    if scope_id:
        query = query.where(FeatureFlag.scope_id == scope_id)
    else:
        query = query.where(FeatureFlag.scope_id.is_(None))

    result = await session.execute(query)
    flag = result.scalar_one_or_none()

    if flag:
        flag.enabled = request.enabled
        if request.description:
            flag.description = request.description
    else:
        flag = FeatureFlag(
            name=flag_name,
            enabled=request.enabled,
            scope=scope,
            scope_id=scope_id,
            description=request.description,
        )
        session.add(flag)

    await session.commit()
    logger.info(f"Feature flag {flag_name} ({scope}) set to {request.enabled}")

    return {
        "status": "ok",
        "flag": flag_name,
        "enabled": request.enabled,
        "scope": scope,
        "scope_id": scope_id,
    }


# -----------------------------------------------------------------------------
# Re-run Scoring
# -----------------------------------------------------------------------------

@router.post("/admin/applications/{application_id}/rescore", status_code=status.HTTP_200_OK)
async def rescore_application(
    application_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Re-run scoring for an application.
    
    Fetches application, downloads attachments, re-scores, and updates results.
    """
    # Get application
    app_result = await session.execute(
        select(Application).where(Application.id == application_id)
    )
    application = app_result.scalar_one_or_none()
    
    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    
    # TODO: Implement re-scoring logic
    # This would:
    # 1. Fetch application from Greenhouse
    # 2. Download attachments
    # 3. Parse resume
    # 4. Run scoring engine
    # 5. Run decision engine
    # 6. Update results
    
    logger.info(f"Re-scoring requested for application {application_id}")
    return {"status": "accepted", "application_id": str(application_id)}


# -----------------------------------------------------------------------------
# DLQ Replay
# -----------------------------------------------------------------------------

@router.post("/dlq/replay/{exception_id}", status_code=status.HTTP_200_OK)
async def replay_dlq_exception(
    exception_id: uuid.UUID,
    request: ReplayRequest = ReplayRequest(),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Replay an exception from DLQ.

    Resets retry count and re-enqueues for processing.
    """
    exception = await session.get(ExceptionModel, exception_id)

    if not exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exception not found",
        )

    # Check if already resolved
    if exception.status == "resolved" and not request.force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Exception already resolved. Use force=true to replay anyway.",
        )

    # Reset for retry
    exception.retry_count = 0
    exception.status = "retrying"
    exception.next_retry_at = datetime.utcnow()
    await session.commit()

    # If we have a greenhouse_event_id, re-enqueue the event
    greenhouse_event_id = exception.payload_refs.get("greenhouse_event_id")
    if greenhouse_event_id:
        # Get the original event
        event_result = await session.execute(
            select(Event).where(Event.greenhouse_event_id == greenhouse_event_id)
        )
        event = event_result.scalar_one_or_none()

        if event:
            # Re-enqueue
            process_greenhouse_event.delay(
                greenhouse_event_id=event.greenhouse_event_id,
                event_type=event.event_type,
                payload=event.raw_body_json,
            )
            logger.info(f"Re-enqueued event {greenhouse_event_id} for exception {exception_id}")

    logger.info(f"Replay triggered for exception {exception_id}")
    return {
        "status": "ok",
        "exception_id": str(exception_id),
        "greenhouse_event_id": greenhouse_event_id,
    }


@router.post("/dlq/replay/by-event/{greenhouse_event_id}", status_code=status.HTTP_200_OK)
async def replay_by_event_id(
    greenhouse_event_id: str,
    request: ReplayRequest = ReplayRequest(),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Replay a specific Greenhouse event by ID.

    Re-fetches the event and re-enqueues for processing.
    """
    # Find the event
    result = await session.execute(
        select(Event).where(Event.greenhouse_event_id == greenhouse_event_id)
    )
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event not found: {greenhouse_event_id}",
        )

    # Check if already processed successfully
    if event.status == "processed" and not request.force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event already processed. Use force=true to replay anyway.",
        )

    # Reset event status
    event.status = "pending"
    event.error_message = None
    await session.commit()

    # Re-enqueue
    process_greenhouse_event.delay(
        greenhouse_event_id=event.greenhouse_event_id,
        event_type=event.event_type,
        payload=event.raw_body_json,
    )

    logger.info(f"Replayed event: {greenhouse_event_id}")
    return {
        "status": "ok",
        "greenhouse_event_id": greenhouse_event_id,
        "event_type": event.event_type,
    }


@router.post("/dlq/replay/by-application/{application_id}", status_code=status.HTTP_200_OK)
async def replay_by_application_id(
    application_id: uuid.UUID,
    request: ReplayRequest = ReplayRequest(),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Replay all events related to an application.

    Finds all events for the application and re-enqueues them.
    """
    # Get the application
    app_result = await session.execute(
        select(Application).where(Application.id == application_id)
    )
    application = app_result.scalar_one_or_none()

    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    # Find events containing this application ID
    # Note: This searches the JSONB payload for the application ID
    events_result = await session.execute(
        select(Event).where(
            Event.raw_body_json["application"]["id"].as_integer() == application.greenhouse_application_id
        )
    )
    events = events_result.scalars().all()

    replayed = []
    for event in events:
        if event.status == "processed" and not request.force:
            continue

        event.status = "pending"
        event.error_message = None

        process_greenhouse_event.delay(
            greenhouse_event_id=event.greenhouse_event_id,
            event_type=event.event_type,
            payload=event.raw_body_json,
        )
        replayed.append(event.greenhouse_event_id)

    await session.commit()

    logger.info(f"Replayed {len(replayed)} events for application {application_id}")
    return {
        "status": "ok",
        "application_id": str(application_id),
        "replayed_events": replayed,
        "count": len(replayed),
    }


@router.post("/dlq/replay/by-time-window", status_code=status.HTTP_200_OK)
async def replay_by_time_window(
    start_time: datetime = Query(..., description="Start of time window (ISO format)"),
    end_time: datetime = Query(..., description="End of time window (ISO format)"),
    status_filter: Optional[str] = Query(None, description="Filter by status (failed, pending)"),
    request: ReplayRequest = ReplayRequest(),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Replay all events within a time window.

    Useful for recovering from outages or retrying failed batches.
    """
    # Build query
    query = select(Event).where(
        and_(
            Event.received_at >= start_time,
            Event.received_at <= end_time,
        )
    )

    if status_filter:
        query = query.where(Event.status == status_filter)
    elif not request.force:
        # Default: only replay failed events
        query = query.where(Event.status.in_(["failed", "pending"]))

    result = await session.execute(query.order_by(Event.received_at))
    events = result.scalars().all()

    replayed = []
    for event in events:
        event.status = "pending"
        event.error_message = None

        process_greenhouse_event.delay(
            greenhouse_event_id=event.greenhouse_event_id,
            event_type=event.event_type,
            payload=event.raw_body_json,
        )
        replayed.append(event.greenhouse_event_id)

    await session.commit()

    logger.info(f"Replayed {len(replayed)} events from {start_time} to {end_time}")
    return {
        "status": "ok",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "replayed_events": replayed[:100],  # Limit response size
        "count": len(replayed),
    }


@router.get("/dlq/stats", status_code=status.HTTP_200_OK)
async def get_dlq_stats(
    session: AsyncSession = Depends(get_async_session),
):
    """Get DLQ statistics."""
    # Count exceptions by status
    open_count = await session.execute(
        select(ExceptionModel).where(ExceptionModel.status == "open")
    )
    retrying_count = await session.execute(
        select(ExceptionModel).where(ExceptionModel.status == "retrying")
    )
    resolved_count = await session.execute(
        select(ExceptionModel).where(ExceptionModel.status == "resolved")
    )

    # Count events by status
    failed_events = await session.execute(
        select(Event).where(Event.status == "failed")
    )
    pending_events = await session.execute(
        select(Event).where(Event.status == "pending")
    )

    return {
        "exceptions": {
            "open": len(list(open_count.scalars().all())),
            "retrying": len(list(retrying_count.scalars().all())),
            "resolved": len(list(resolved_count.scalars().all())),
        },
        "events": {
            "failed": len(list(failed_events.scalars().all())),
            "pending": len(list(pending_events.scalars().all())),
        },
    }


# -----------------------------------------------------------------------------
# Exception Management
# -----------------------------------------------------------------------------

@router.get("/admin/exceptions", status_code=status.HTTP_200_OK)
async def list_exceptions(
    status_filter: Optional[str] = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_async_session),
):
    """
    List exceptions with optional filtering.
    
    Args:
        status_filter: Filter by status ('open', 'resolved', 'retrying')
        limit: Maximum number of results
    """
    query = select(ExceptionModel)
    
    if status_filter:
        query = query.where(ExceptionModel.status == status_filter)
    
    query = query.order_by(ExceptionModel.created_at.desc()).limit(limit)
    
    result = await session.execute(query)
    exceptions = result.scalars().all()
    
    return {
        "exceptions": [
            {
                "id": str(exc.id),
                "exception_type": exc.exception_type,
                "reason": exc.reason,
                "status": exc.status,
                "retry_count": exc.retry_count,
                "created_at": exc.created_at.isoformat(),
            }
            for exc in exceptions
        ]
    }


@router.get("/admin/exceptions/{exception_id}", status_code=status.HTTP_200_OK)
async def get_exception(
    exception_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get exception details.
    """
    exception = await session.get(ExceptionModel, exception_id)
    
    if not exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exception not found",
        )
    
    return {
        "id": str(exception.id),
        "exception_type": exception.exception_type,
        "reason": exception.reason,
        "status": exception.status,
        "retry_count": exception.retry_count,
        "next_retry_at": exception.next_retry_at.isoformat() if exception.next_retry_at else None,
        "last_error": exception.last_error,
        "payload_refs": exception.payload_refs,
        "created_at": exception.created_at.isoformat(),
        "resolved_at": exception.resolved_at.isoformat() if exception.resolved_at else None,
    }


@router.post("/admin/exceptions/{exception_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve_exception(
    exception_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Mark exception as resolved.
    """
    exception = await session.get(ExceptionModel, exception_id)
    
    if not exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exception not found",
        )
    
    exception.status = "resolved"
    exception.resolved_at = datetime.utcnow()
    await session.commit()
    
    return {"status": "ok", "exception_id": str(exception_id)}


@router.post("/admin/exceptions/{exception_id}/retry", status_code=status.HTTP_200_OK)
async def retry_exception(
    exception_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Manually retry an exception.
    """
    exception = await session.get(ExceptionModel, exception_id)
    
    if not exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exception not found",
        )
    
    # Reset retry count and status
    exception.retry_count = 0
    exception.status = "open"
    exception.next_retry_at = None
    await session.commit()
    
    return {"status": "ok", "exception_id": str(exception_id)}
