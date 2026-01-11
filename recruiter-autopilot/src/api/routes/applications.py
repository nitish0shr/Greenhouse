"""Application management API endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.database import get_session
from src.models.application import Application, ApplicationState, ApplicationTier
from src.models.candidate import Candidate
from src.models.exception_queue import ExceptionQueueItem
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class ApplicationResponse(BaseModel):
    """Application response schema."""

    id: int
    greenhouse_id: int
    candidate_id: int
    job_id: int
    state: str
    tier: str | None
    score: float | None
    confidence: float | None
    needs_human_review: bool
    human_reviewed: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApplicationListResponse(BaseModel):
    """Paginated application list response."""

    items: list[ApplicationResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ApplicationDetailResponse(BaseModel):
    """Detailed application response with candidate info."""

    id: int
    greenhouse_id: int
    state: str
    tier: str | None
    score: float | None
    confidence: float | None
    rubric_version: str | None
    needs_human_review: bool
    human_reviewed: bool
    human_reviewed_at: datetime | None
    human_reviewed_by: str | None
    emails_sent_count: int
    last_email_sent_at: datetime | None
    last_reply_at: datetime | None
    last_reply_intent: str | None
    scheduled_interview_at: datetime | None
    rejected: bool
    rejection_reason: str | None
    outcome: str | None
    error_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    # Candidate info (safe fields only)
    candidate_display_name: str
    candidate_greenhouse_id: int

    class Config:
        from_attributes = True


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    state: ApplicationState | None = None,
    tier: ApplicationTier | None = None,
    needs_review: bool | None = None,
    job_id: int | None = None,
) -> ApplicationListResponse:
    """
    List applications with optional filters.

    - Pagination support
    - Filter by state, tier, needs_review, job_id
    """
    # Build query
    query = select(Application)

    if state:
        query = query.where(Application.state == state)
    if tier:
        query = query.where(Application.tier == tier)
    if needs_review is not None:
        query = query.where(Application.needs_human_review == needs_review)
    if job_id:
        query = query.where(Application.job_id == job_id)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(Application.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    applications = result.scalars().all()

    return ApplicationListResponse(
        items=[ApplicationResponse.model_validate(app) for app in applications],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/review-queue")
async def get_review_queue(
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    """
    Get applications needing human review.

    Returns applications flagged for review with context.
    """
    query = (
        select(Application)
        .where(
            Application.needs_human_review == True,
            Application.human_reviewed == False,
        )
        .options(selectinload(Application.candidate))
        .order_by(Application.created_at.asc())  # Oldest first
    )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    applications = result.scalars().all()

    items = []
    for app in applications:
        # Get associated exception queue items
        exceptions = await session.execute(
            select(ExceptionQueueItem)
            .where(
                ExceptionQueueItem.application_id == app.id,
                ExceptionQueueItem.resolved == False,
            )
            .order_by(ExceptionQueueItem.created_at.desc())
            .limit(5)
        )

        items.append({
            "application": {
                "id": app.id,
                "greenhouse_id": app.greenhouse_id,
                "state": app.state.value,
                "tier": app.tier.value if app.tier else None,
                "score": app.score,
                "confidence": app.confidence,
                "created_at": app.created_at.isoformat(),
            },
            "candidate": {
                "display_name": app.candidate.display_name if app.candidate else "Unknown",
                "greenhouse_id": app.candidate.greenhouse_id if app.candidate else None,
            },
            "exceptions": [
                {
                    "id": exc.id,
                    "type": exc.exception_type.value,
                    "priority": exc.priority.value,
                    "title": exc.title,
                    "created_at": exc.created_at.isoformat(),
                }
                for exc in exceptions.scalars().all()
            ],
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
async def get_application(
    application_id: int,
    session: AsyncSession = Depends(get_session),
) -> ApplicationDetailResponse:
    """Get detailed application information."""
    result = await session.execute(
        select(Application)
        .where(Application.id == application_id)
        .options(selectinload(Application.candidate))
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    return ApplicationDetailResponse(
        id=application.id,
        greenhouse_id=application.greenhouse_id,
        state=application.state.value,
        tier=application.tier.value if application.tier else None,
        score=application.score,
        confidence=application.confidence,
        rubric_version=application.rubric_version,
        needs_human_review=application.needs_human_review,
        human_reviewed=application.human_reviewed,
        human_reviewed_at=application.human_reviewed_at,
        human_reviewed_by=application.human_reviewed_by,
        emails_sent_count=application.emails_sent_count,
        last_email_sent_at=application.last_email_sent_at,
        last_reply_at=application.last_reply_at,
        last_reply_intent=application.last_reply_intent,
        scheduled_interview_at=application.scheduled_interview_at,
        rejected=application.rejected,
        rejection_reason=application.rejection_reason,
        outcome=application.outcome,
        error_count=application.error_count,
        last_error=application.last_error,
        created_at=application.created_at,
        updated_at=application.updated_at,
        candidate_display_name=application.candidate.display_name if application.candidate else "Unknown",
        candidate_greenhouse_id=application.candidate.greenhouse_id if application.candidate else 0,
    )


@router.get("/{application_id}/timeline")
async def get_application_timeline(
    application_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Get the automation timeline for an application.

    Returns state transitions, emails, scoring events, etc.
    """
    result = await session.execute(
        select(Application)
        .where(Application.id == application_id)
        .options(
            selectinload(Application.state_transitions),
            selectinload(Application.scoring_results),
        )
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    # Build timeline from various sources
    timeline = []

    # State transitions
    for transition in application.state_transitions:
        timeline.append({
            "type": "state_transition",
            "timestamp": transition.created_at.isoformat(),
            "data": {
                "from_state": transition.from_state.value,
                "to_state": transition.to_state.value,
                "trigger": transition.trigger,
                "reason": transition.reason,
            },
        })

    # Scoring results
    for scoring in application.scoring_results:
        timeline.append({
            "type": "scoring",
            "timestamp": scoring.created_at.isoformat(),
            "data": {
                "tier": scoring.tier.value,
                "score": scoring.total_score,
                "max_score": scoring.max_score,
                "percentage": scoring.percentage,
                "confidence": scoring.confidence,
                "needs_review": scoring.needs_human_review,
            },
        })

    # Sort by timestamp
    timeline.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "application_id": application_id,
        "greenhouse_id": application.greenhouse_id,
        "current_state": application.state.value,
        "timeline": timeline,
    }


class MarkReviewedRequest(BaseModel):
    """Request to mark an application as reviewed."""

    reviewed_by: str
    notes: str | None = None
    action: str | None = None  # "approve", "reject", "rescore"


@router.post("/{application_id}/mark-reviewed")
async def mark_application_reviewed(
    application_id: int,
    request: MarkReviewedRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Mark an application as human reviewed.

    Clears the needs_human_review flag.
    """
    result = await session.execute(
        select(Application).where(Application.id == application_id)
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    application.human_reviewed = True
    application.human_reviewed_at = datetime.utcnow()
    application.human_reviewed_by = request.reviewed_by
    application.needs_human_review = False

    # Add review note to automation notes
    if application.automation_notes is None:
        application.automation_notes = []

    application.automation_notes.append({
        "type": "human_review",
        "timestamp": datetime.utcnow().isoformat(),
        "reviewed_by": request.reviewed_by,
        "notes": request.notes,
        "action": request.action,
    })

    await session.commit()

    logger.info(
        "Application marked as reviewed",
        application_id=application_id,
        reviewed_by=request.reviewed_by,
        action=request.action,
    )

    return {
        "status": "success",
        "application_id": application_id,
        "reviewed_by": request.reviewed_by,
        "action": request.action,
    }


@router.post("/{application_id}/rescore")
async def rescore_application(
    application_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Trigger re-scoring for an application.

    Useful after rubric updates or when reviewing flagged applications.
    """
    from src.workers.tasks import rescore_application_task

    result = await session.execute(
        select(Application).where(Application.id == application_id)
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    # Queue re-scoring
    task = rescore_application_task.delay(application_id)

    logger.info(
        "Re-scoring queued",
        application_id=application_id,
        task_id=task.id,
    )

    return {
        "status": "queued",
        "application_id": application_id,
        "task_id": task.id,
    }
