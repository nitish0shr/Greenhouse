"""Job management API endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.database import get_session
from src.models.job import Job, KillSwitch
from src.models.application import Application, ApplicationState
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class JobResponse(BaseModel):
    """Job response schema."""

    id: int
    greenhouse_id: int
    name: str
    status: str
    department: str | None
    office: str | None
    automation_enabled: bool
    auto_advance_enabled: bool
    auto_reject_enabled: bool
    auto_email_enabled: bool
    auto_schedule_enabled: bool
    rubric_id: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class JobStatsResponse(BaseModel):
    """Job statistics response."""

    job_id: int
    total_applications: int
    by_state: dict[str, int]
    by_tier: dict[str, int]
    needs_review_count: int
    exception_count: int


class KillSwitchRequest(BaseModel):
    """Request to toggle kill switch."""

    stage_id: int | None = None
    stage_name: str | None = None
    reason: str
    activated_by: str


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    session: AsyncSession = Depends(get_session),
    status: str | None = None,
    automation_enabled: bool | None = None,
) -> list[JobResponse]:
    """
    List all jobs with optional filters.
    """
    query = select(Job)

    if status:
        query = query.where(Job.status == status)
    if automation_enabled is not None:
        query = query.where(Job.automation_enabled == automation_enabled)

    query = query.order_by(Job.name)

    result = await session.execute(query)
    jobs = result.scalars().all()

    return [JobResponse.model_validate(job) for job in jobs]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    """Get job details."""
    result = await session.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse.model_validate(job)


@router.get("/{job_id}/stats", response_model=JobStatsResponse)
async def get_job_stats(
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> JobStatsResponse:
    """
    Get statistics for a job's applications.
    """
    # Verify job exists
    result = await session.execute(
        select(Job).where(Job.id == job_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job not found")

    # Get counts by state
    state_counts = await session.execute(
        select(Application.state, func.count(Application.id))
        .where(Application.job_id == job_id)
        .group_by(Application.state)
    )
    by_state = {row[0].value: row[1] for row in state_counts.fetchall()}

    # Get counts by tier
    tier_counts = await session.execute(
        select(Application.tier, func.count(Application.id))
        .where(Application.job_id == job_id, Application.tier.isnot(None))
        .group_by(Application.tier)
    )
    by_tier = {row[0].value if row[0] else "unscored": row[1] for row in tier_counts.fetchall()}

    # Get needs review count
    needs_review = await session.execute(
        select(func.count(Application.id))
        .where(
            Application.job_id == job_id,
            Application.needs_human_review == True,
            Application.human_reviewed == False,
        )
    )
    needs_review_count = needs_review.scalar() or 0

    # Get exception count
    from src.models.exception_queue import ExceptionQueueItem
    exception_count_result = await session.execute(
        select(func.count(ExceptionQueueItem.id))
        .where(
            ExceptionQueueItem.job_id == job_id,
            ExceptionQueueItem.resolved == False,
        )
    )
    exception_count = exception_count_result.scalar() or 0

    # Total applications
    total = sum(by_state.values())

    return JobStatsResponse(
        job_id=job_id,
        total_applications=total,
        by_state=by_state,
        by_tier=by_tier,
        needs_review_count=needs_review_count,
        exception_count=exception_count,
    )


@router.get("/{job_id}/kill-switches")
async def get_kill_switches(
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """
    Get active kill switches for a job.
    """
    result = await session.execute(
        select(KillSwitch)
        .where(KillSwitch.job_id == job_id, KillSwitch.is_active == True)
        .order_by(KillSwitch.activated_at.desc())
    )
    switches = result.scalars().all()

    return [
        {
            "id": ks.id,
            "stage_id": ks.stage_id,
            "stage_name": ks.stage_name,
            "is_active": ks.is_active,
            "reason": ks.reason,
            "activated_by": ks.activated_by,
            "activated_at": ks.activated_at.isoformat(),
        }
        for ks in switches
    ]


@router.post("/{job_id}/kill-switch/activate")
async def activate_kill_switch(
    job_id: int,
    request: KillSwitchRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Activate a kill switch for a job or specific stage.

    This stops all automation for the specified scope.
    """
    # Verify job exists
    result = await session.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check for existing active switch at same scope
    existing = await session.execute(
        select(KillSwitch)
        .where(
            KillSwitch.job_id == job_id,
            KillSwitch.stage_id == request.stage_id,
            KillSwitch.is_active == True,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Kill switch already active for this scope",
        )

    # Create kill switch
    kill_switch = KillSwitch(
        job_id=job_id,
        stage_id=request.stage_id,
        stage_name=request.stage_name,
        is_active=True,
        reason=request.reason,
        activated_by=request.activated_by,
    )
    session.add(kill_switch)
    await session.commit()

    logger.warning(
        "Kill switch activated",
        job_id=job_id,
        stage_id=request.stage_id,
        reason=request.reason,
        activated_by=request.activated_by,
    )

    return {
        "status": "activated",
        "kill_switch_id": kill_switch.id,
        "job_id": job_id,
        "stage_id": request.stage_id,
    }


class DeactivateKillSwitchRequest(BaseModel):
    """Request to deactivate kill switch."""

    deactivated_by: str


@router.post("/{job_id}/kill-switch/{kill_switch_id}/deactivate")
async def deactivate_kill_switch(
    job_id: int,
    kill_switch_id: int,
    request: DeactivateKillSwitchRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Deactivate a kill switch.

    Resumes automation for the affected scope.
    """
    result = await session.execute(
        select(KillSwitch)
        .where(
            KillSwitch.id == kill_switch_id,
            KillSwitch.job_id == job_id,
        )
    )
    kill_switch = result.scalar_one_or_none()

    if not kill_switch:
        raise HTTPException(status_code=404, detail="Kill switch not found")

    if not kill_switch.is_active:
        raise HTTPException(status_code=400, detail="Kill switch already inactive")

    kill_switch.deactivate(request.deactivated_by)
    await session.commit()

    logger.info(
        "Kill switch deactivated",
        kill_switch_id=kill_switch_id,
        job_id=job_id,
        deactivated_by=request.deactivated_by,
    )

    return {
        "status": "deactivated",
        "kill_switch_id": kill_switch_id,
        "job_id": job_id,
    }


class UpdateAutomationRequest(BaseModel):
    """Request to update job automation settings."""

    automation_enabled: bool | None = None
    auto_advance_enabled: bool | None = None
    auto_reject_enabled: bool | None = None
    auto_email_enabled: bool | None = None
    auto_schedule_enabled: bool | None = None


@router.patch("/{job_id}/automation")
async def update_job_automation(
    job_id: int,
    request: UpdateAutomationRequest,
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    """
    Update automation settings for a job.
    """
    result = await session.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Update only provided fields
    if request.automation_enabled is not None:
        job.automation_enabled = request.automation_enabled
    if request.auto_advance_enabled is not None:
        job.auto_advance_enabled = request.auto_advance_enabled
    if request.auto_reject_enabled is not None:
        job.auto_reject_enabled = request.auto_reject_enabled
    if request.auto_email_enabled is not None:
        job.auto_email_enabled = request.auto_email_enabled
    if request.auto_schedule_enabled is not None:
        job.auto_schedule_enabled = request.auto_schedule_enabled

    await session.commit()

    logger.info(
        "Job automation settings updated",
        job_id=job_id,
        changes=request.model_dump(exclude_none=True),
    )

    return JobResponse.model_validate(job)
