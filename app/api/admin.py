# =============================================================================
# Admin API & Dashboard
# =============================================================================

import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.human_review import HumanReviewQueue
from app.models.webhook_event import WebhookEvent

router = APIRouter()
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")


# -----------------------------------------------------------------------------
# Authentication
# -----------------------------------------------------------------------------

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials using constant-time comparison."""
    correct_username = secrets.compare_digest(
        credentials.username.encode("utf8"),
        settings.admin_username.encode("utf8"),
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"),
        settings.admin_password.encode("utf8"),
    )
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    return credentials.username


# -----------------------------------------------------------------------------
# Dashboard Views
# -----------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin: str = Depends(verify_admin),
):
    """Main admin dashboard with statistics."""
    # Default stats (used if database isn't available)
    stats = {
        "total_applications": 0,
        "pending": 0,
        "completed": 0,
        "review_queue": 0,
        "avg_score": 0,
        "min_score": 0,
        "max_score": 0,
    }
    recent_apps = []
    db_available = False

    # Try to get database stats (gracefully handle if DB not available)
    try:
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            # Get queue statistics
            total_apps = await session.scalar(select(func.count(Application.id)))
            pending_apps = await session.scalar(
                select(func.count(Application.id))
                .where(Application.processing_status == "pending")
            )
            completed_apps = await session.scalar(
                select(func.count(Application.id))
                .where(Application.processing_status == "completed")
            )
            review_queue = await session.scalar(
                select(func.count(HumanReviewQueue.id))
                .where(HumanReviewQueue.status == "pending")
            )

            # Get recent applications
            recent_result = await session.execute(
                select(Application)
                .order_by(desc(Application.created_at))
                .limit(10)
            )
            recent_apps = recent_result.scalars().all()

            # Get score distribution
            score_stats = await session.execute(
                select(
                    func.avg(Application.score).label("avg"),
                    func.min(Application.score).label("min"),
                    func.max(Application.score).label("max"),
                )
                .where(Application.score.isnot(None))
            )
            score_row = score_stats.one()

            stats = {
                "total_applications": total_apps or 0,
                "pending": pending_apps or 0,
                "completed": completed_apps or 0,
                "review_queue": review_queue or 0,
                "avg_score": round(score_row.avg or 0, 1),
                "min_score": round(score_row.min or 0, 1),
                "max_score": round(score_row.max or 0, 1),
            }
            db_available = True
    except Exception as e:
        # Database not available - use default stats
        import logging
        logging.getLogger(__name__).warning(f"Database not available for admin dashboard: {e}")

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin_user": admin,
            "stats": stats,
            "recent_applications": recent_apps,
            "db_available": db_available,
        },
    )


@router.get("/queue", response_class=HTMLResponse)
async def queue_status(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: str = Depends(verify_admin),
):
    """View Celery queue status and pending tasks."""
    # Get pending webhook events
    pending_webhooks = await session.execute(
        select(WebhookEvent)
        .where(WebhookEvent.status.in_(["received", "processing"]))
        .order_by(desc(WebhookEvent.received_at))
        .limit(50)
    )
    
    # Get failed events
    failed_webhooks = await session.execute(
        select(WebhookEvent)
        .where(WebhookEvent.status == "failed")
        .order_by(desc(WebhookEvent.received_at))
        .limit(20)
    )
    
    return templates.TemplateResponse(
        "queue.html",
        {
            "request": request,
            "admin_user": admin,
            "pending_webhooks": pending_webhooks.scalars().all(),
            "failed_webhooks": failed_webhooks.scalars().all(),
        },
    )


@router.get("/review", response_class=HTMLResponse)
async def review_queue(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: str = Depends(verify_admin),
    status_filter: Optional[str] = Query(None, alias="status"),
    job_id: Optional[int] = Query(None),
):
    """View human review queue."""
    query = select(HumanReviewQueue)
    
    if status_filter:
        query = query.where(HumanReviewQueue.status == status_filter)
    else:
        query = query.where(HumanReviewQueue.status == "pending")
    
    if job_id:
        query = query.where(HumanReviewQueue.job_id == job_id)
    
    query = query.order_by(
        HumanReviewQueue.priority,
        desc(HumanReviewQueue.created_at),
    ).limit(50)
    
    result = await session.execute(query)
    items = result.scalars().all()
    
    # Get unique jobs for filter dropdown
    jobs_result = await session.execute(
        select(
            HumanReviewQueue.job_id,
            HumanReviewQueue.job_name,
        ).distinct()
    )
    jobs = jobs_result.all()
    
    return templates.TemplateResponse(
        "review_queue.html",
        {
            "request": request,
            "admin_user": admin,
            "items": items,
            "jobs": jobs,
            "current_status": status_filter or "pending",
            "current_job_id": job_id,
        },
    )


@router.get("/candidates/{candidate_id}", response_class=HTMLResponse)
async def candidate_detail(
    request: Request,
    candidate_id: str,
    session: AsyncSession = Depends(get_async_session),
    admin: str = Depends(verify_admin),
):
    """View candidate details and audit log."""
    # Get candidate
    result = await session.execute(
        select(Candidate).where(Candidate.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()
    
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    
    # Get applications
    apps_result = await session.execute(
        select(Application)
        .where(Application.candidate_id == candidate_id)
        .order_by(desc(Application.created_at))
    )
    applications = apps_result.scalars().all()
    
    # Get audit logs
    logs_result = await session.execute(
        select(AuditLog)
        .where(AuditLog.candidate_id == candidate_id)
        .order_by(desc(AuditLog.created_at))
        .limit(100)
    )
    audit_logs = logs_result.scalars().all()
    
    return templates.TemplateResponse(
        "candidate_detail.html",
        {
            "request": request,
            "admin_user": admin,
            "candidate": candidate,
            "applications": applications,
            "audit_logs": audit_logs,
        },
    )


# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------

@router.get("/api/stats")
async def get_stats(
    session: AsyncSession = Depends(get_async_session),
    admin: str = Depends(verify_admin),
):
    """Get dashboard statistics as JSON."""
    total_apps = await session.scalar(select(func.count(Application.id)))
    pending_apps = await session.scalar(
        select(func.count(Application.id))
        .where(Application.processing_status == "pending")
    )
    completed_apps = await session.scalar(
        select(func.count(Application.id))
        .where(Application.processing_status == "completed")
    )
    failed_apps = await session.scalar(
        select(func.count(Application.id))
        .where(Application.processing_status == "failed")
    )
    review_queue = await session.scalar(
        select(func.count(HumanReviewQueue.id))
        .where(HumanReviewQueue.status == "pending")
    )
    
    return {
        "total_applications": total_apps or 0,
        "pending": pending_apps or 0,
        "completed": completed_apps or 0,
        "failed": failed_apps or 0,
        "review_queue": review_queue or 0,
    }


@router.post("/api/candidates/{candidate_id}/rescore")
async def rescore_candidate(
    candidate_id: str,
    session: AsyncSession = Depends(get_async_session),
    admin: str = Depends(verify_admin),
):
    """Re-run scoring for a candidate's latest application."""
    from app.workers.tasks import process_new_application
    
    # Get candidate
    result = await session.execute(
        select(Candidate).where(Candidate.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()
    
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    
    # Get latest application
    app_result = await session.execute(
        select(Application)
        .where(Application.candidate_id == candidate_id)
        .order_by(desc(Application.created_at))
        .limit(1)
    )
    application = app_result.scalar_one_or_none()
    
    if not application:
        raise HTTPException(status_code=404, detail="No application found")
    
    # Queue for re-processing
    process_new_application.delay(
        application_id=application.greenhouse_id,
        webhook_event_id=None,
        payload={},
    )
    
    # Create audit log
    from app.models.audit_log import AuditLog
    log = AuditLog(
        action_type="rescore_requested",
        description=f"Re-scoring requested by {admin}",
        candidate_id=candidate_id,
        application_id=str(application.id),
        greenhouse_application_id=application.greenhouse_id,
        triggered_by=f"admin:{admin}",
    )
    session.add(log)
    await session.commit()
    
    return {
        "status": "queued",
        "application_id": application.greenhouse_id,
        "message": "Application queued for re-scoring",
    }


@router.post("/api/review/{review_id}/approve")
async def approve_review_item(
    review_id: str,
    session: AsyncSession = Depends(get_async_session),
    admin: str = Depends(verify_admin),
):
    """Approve a human review item and advance the application."""
    from app.services.greenhouse import GreenhouseClient
    import asyncio
    
    result = await session.execute(
        select(HumanReviewQueue).where(HumanReviewQueue.id == review_id)
    )
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    
    # Advance in Greenhouse
    greenhouse = GreenhouseClient()
    try:
        await greenhouse.advance_application(item.greenhouse_application_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to advance: {e}")
    
    # Update review item
    item.status = "approved"
    item.reviewed_by = admin
    item.reviewed_at = datetime.utcnow()
    item.decision = "approve"
    
    # Create audit log
    log = AuditLog(
        action_type="manual_approval",
        description=f"Manually approved by {admin}",
        greenhouse_application_id=item.greenhouse_application_id,
        triggered_by=f"admin:{admin}",
    )
    session.add(log)
    await session.commit()
    
    return {"status": "approved", "application_id": item.greenhouse_application_id}


@router.post("/api/review/{review_id}/reject")
async def reject_review_item(
    review_id: str,
    reason_id: Optional[int] = None,
    notes: Optional[str] = None,
    session: AsyncSession = Depends(get_async_session),
    admin: str = Depends(verify_admin),
):
    """Reject a human review item."""
    from app.services.greenhouse import GreenhouseClient
    
    result = await session.execute(
        select(HumanReviewQueue).where(HumanReviewQueue.id == review_id)
    )
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    
    # Reject in Greenhouse
    greenhouse = GreenhouseClient()
    try:
        await greenhouse.reject_application(
            item.greenhouse_application_id,
            rejection_reason_id=reason_id,
            notes=notes or f"Rejected by {admin}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject: {e}")
    
    # Update review item
    item.status = "rejected"
    item.reviewed_by = admin
    item.reviewed_at = datetime.utcnow()
    item.decision = "reject"
    item.decision_notes = notes
    
    # Create audit log
    log = AuditLog(
        action_type="manual_rejection",
        description=f"Manually rejected by {admin}",
        greenhouse_application_id=item.greenhouse_application_id,
        triggered_by=f"admin:{admin}",
        metadata={"reason_id": reason_id, "notes": notes},
    )
    session.add(log)
    await session.commit()
    
    return {"status": "rejected", "application_id": item.greenhouse_application_id}


@router.get("/api/audit-log/{candidate_id}")
async def get_candidate_audit_log(
    candidate_id: str,
    limit: int = Query(100, le=500),
    session: AsyncSession = Depends(get_async_session),
    admin: str = Depends(verify_admin),
):
    """Get audit log for a candidate."""
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.candidate_id == candidate_id)
        .order_by(desc(AuditLog.created_at))
        .limit(limit)
    )
    logs = result.scalars().all()
    
    return [
        {
            "id": str(log.id),
            "action_type": log.action_type,
            "description": log.description,
            "triggered_by": log.triggered_by,
            "status": log.status,
            "created_at": log.created_at.isoformat(),
            "metadata": log.metadata_json,
        }
        for log in logs
    ]
