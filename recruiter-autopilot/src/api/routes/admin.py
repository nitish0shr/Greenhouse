"""Admin API endpoints and lightweight HTMX UI."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession
import secrets

from src.config import settings
from src.models.database import get_session
from src.models.application import Application, ApplicationState
from src.models.exception_queue import ExceptionQueueItem, ExceptionPriority
from src.models.job import Job, KillSwitch
from src.models.audit import AuditLog
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()
security = HTTPBasic()


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Verify admin credentials."""
    correct_username = secrets.compare_digest(
        credentials.username.encode("utf8"),
        settings.admin_username.encode("utf8"),
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"),
        settings.admin_password.get_secret_value().encode("utf8"),
    )

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


# HTML Template helpers
def render_base(content: str, title: str = "Recruiter Autopilot Admin") -> str:
    """Render base HTML template."""
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <script src="https://unpkg.com/htmx.org@1.9.10"></script>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   background: #f5f5f5; color: #333; line-height: 1.6; }}
            .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
            nav {{ background: #2563eb; color: white; padding: 15px 20px; margin-bottom: 20px; }}
            nav a {{ color: white; text-decoration: none; margin-right: 20px; }}
            nav a:hover {{ text-decoration: underline; }}
            .card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            .card h2 {{ margin-bottom: 15px; color: #1f2937; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
            th {{ background: #f9fafb; font-weight: 600; }}
            tr:hover {{ background: #f9fafb; }}
            .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }}
            .badge-green {{ background: #dcfce7; color: #166534; }}
            .badge-yellow {{ background: #fef3c7; color: #92400e; }}
            .badge-red {{ background: #fee2e2; color: #991b1b; }}
            .badge-blue {{ background: #dbeafe; color: #1e40af; }}
            .badge-gray {{ background: #f3f4f6; color: #374151; }}
            .btn {{ padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer;
                   font-size: 14px; font-weight: 500; }}
            .btn-primary {{ background: #2563eb; color: white; }}
            .btn-danger {{ background: #dc2626; color: white; }}
            .btn-sm {{ padding: 4px 8px; font-size: 12px; }}
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                     gap: 20px; margin-bottom: 20px; }}
            .stat-card {{ background: white; padding: 20px; border-radius: 8px;
                         box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            .stat-value {{ font-size: 32px; font-weight: 700; color: #1f2937; }}
            .stat-label {{ color: #6b7280; font-size: 14px; }}
            .htmx-indicator {{ display: none; }}
            .htmx-request .htmx-indicator {{ display: inline; }}
            .loading {{ opacity: 0.5; }}
        </style>
    </head>
    <body>
        <nav>
            <a href="/admin"><strong>Recruiter Autopilot</strong></a>
            <a href="/admin">Dashboard</a>
            <a href="/admin/review-queue">Review Queue</a>
            <a href="/admin/exceptions">Exceptions</a>
            <a href="/admin/jobs">Jobs</a>
            <a href="/admin/audit">Audit Log</a>
        </nav>
        <div class="container">
            {content}
        </div>
    </body>
    </html>
    """


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    admin: str = Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Admin dashboard with key metrics."""
    # Get stats
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Applications today
    apps_today = await session.execute(
        select(func.count(Application.id))
        .where(Application.created_at >= today)
    )
    apps_today_count = apps_today.scalar() or 0

    # Needs review count
    needs_review = await session.execute(
        select(func.count(Application.id))
        .where(
            Application.needs_human_review == True,
            Application.human_reviewed == False,
        )
    )
    needs_review_count = needs_review.scalar() or 0

    # Unresolved exceptions
    exceptions = await session.execute(
        select(func.count(ExceptionQueueItem.id))
        .where(ExceptionQueueItem.resolved == False)
    )
    exception_count = exceptions.scalar() or 0

    # Active kill switches
    kill_switches = await session.execute(
        select(func.count(KillSwitch.id))
        .where(KillSwitch.is_active == True)
    )
    kill_switch_count = kill_switches.scalar() or 0

    # By state counts
    state_counts = await session.execute(
        select(Application.state, func.count(Application.id))
        .group_by(Application.state)
    )
    by_state = {row[0].value: row[1] for row in state_counts.fetchall()}

    content = f"""
    <h1>Dashboard</h1>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{apps_today_count}</div>
            <div class="stat-label">Applications Today</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: {'#dc2626' if needs_review_count > 0 else '#166534'}">
                {needs_review_count}
            </div>
            <div class="stat-label">Needs Review</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: {'#dc2626' if exception_count > 0 else '#166534'}">
                {exception_count}
            </div>
            <div class="stat-label">Unresolved Exceptions</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: {'#dc2626' if kill_switch_count > 0 else '#166534'}">
                {kill_switch_count}
            </div>
            <div class="stat-label">Active Kill Switches</div>
        </div>
    </div>

    <div class="card">
        <h2>Applications by State</h2>
        <table>
            <thead>
                <tr>
                    <th>State</th>
                    <th>Count</th>
                </tr>
            </thead>
            <tbody>
                {''.join(f'<tr><td>{state}</td><td>{count}</td></tr>' for state, count in sorted(by_state.items()))}
            </tbody>
        </table>
    </div>

    <div class="card">
        <h2>Quick Actions</h2>
        <p>
            <a href="/admin/review-queue" class="btn btn-primary">Review Queue ({needs_review_count})</a>
            <a href="/admin/exceptions" class="btn btn-primary" style="margin-left: 10px;">
                Exceptions ({exception_count})
            </a>
        </p>
    </div>
    """

    return HTMLResponse(render_base(content, "Dashboard - Recruiter Autopilot"))


@router.get("/review-queue", response_class=HTMLResponse)
async def admin_review_queue(
    admin: str = Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """Review queue UI."""
    page_size = 20

    # Get applications needing review
    query = (
        select(Application)
        .where(
            Application.needs_human_review == True,
            Application.human_reviewed == False,
        )
        .order_by(Application.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(query)
    applications = result.scalars().all()

    # Count total
    count_result = await session.execute(
        select(func.count(Application.id))
        .where(
            Application.needs_human_review == True,
            Application.human_reviewed == False,
        )
    )
    total = count_result.scalar() or 0
    pages = (total + page_size - 1) // page_size

    rows = ""
    for app in applications:
        tier_badge = ""
        if app.tier:
            color = {"A": "green", "B": "yellow", "C": "yellow", "REJECT": "red"}.get(
                app.tier.value, "gray"
            )
            tier_badge = f'<span class="badge badge-{color}">{app.tier.value}</span>'

        rows += f"""
        <tr>
            <td>{app.greenhouse_id}</td>
            <td><span class="badge badge-blue">{app.state.value}</span></td>
            <td>{tier_badge}</td>
            <td>{app.score:.1f if app.score else 'N/A'}</td>
            <td>{app.confidence:.0%if app.confidence else 'N/A'}</td>
            <td>{app.created_at.strftime('%Y-%m-%d %H:%M')}</td>
            <td>
                <button class="btn btn-sm btn-primary"
                        hx-post="/admin/api/applications/{app.id}/mark-reviewed"
                        hx-swap="outerHTML"
                        hx-target="closest tr">
                    Mark Reviewed
                </button>
            </td>
        </tr>
        """

    pagination = ""
    if pages > 1:
        pagination = '<div style="margin-top: 20px;">'
        for p in range(1, pages + 1):
            active = "btn-primary" if p == page else ""
            pagination += f'<a href="/admin/review-queue?page={p}" class="btn btn-sm {active}">{p}</a> '
        pagination += "</div>"

    content = f"""
    <h1>Review Queue ({total})</h1>

    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>GH Application ID</th>
                    <th>State</th>
                    <th>Tier</th>
                    <th>Score</th>
                    <th>Confidence</th>
                    <th>Created</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {rows if rows else '<tr><td colspan="7" style="text-align: center; color: #6b7280;">No applications need review</td></tr>'}
            </tbody>
        </table>
        {pagination}
    </div>
    """

    return HTMLResponse(render_base(content, "Review Queue - Recruiter Autopilot"))


@router.get("/exceptions", response_class=HTMLResponse)
async def admin_exceptions(
    admin: str = Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """Exceptions queue UI."""
    page_size = 20

    query = (
        select(ExceptionQueueItem)
        .where(ExceptionQueueItem.resolved == False)
        .order_by(
            ExceptionQueueItem.priority.desc(),
            ExceptionQueueItem.created_at.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(query)
    exceptions = result.scalars().all()

    count_result = await session.execute(
        select(func.count(ExceptionQueueItem.id))
        .where(ExceptionQueueItem.resolved == False)
    )
    total = count_result.scalar() or 0
    pages = (total + page_size - 1) // page_size

    rows = ""
    for exc in exceptions:
        priority_color = {
            "low": "gray",
            "medium": "blue",
            "high": "yellow",
            "urgent": "red",
        }.get(exc.priority.value, "gray")

        rows += f"""
        <tr>
            <td><span class="badge badge-{priority_color}">{exc.priority.value.upper()}</span></td>
            <td>{exc.exception_type.value}</td>
            <td>{exc.title[:50]}{'...' if len(exc.title) > 50 else ''}</td>
            <td>{exc.greenhouse_application_id or 'N/A'}</td>
            <td>{exc.created_at.strftime('%Y-%m-%d %H:%M')}</td>
            <td>
                <button class="btn btn-sm btn-primary"
                        hx-post="/admin/api/exceptions/{exc.id}/resolve"
                        hx-swap="outerHTML"
                        hx-target="closest tr">
                    Resolve
                </button>
            </td>
        </tr>
        """

    pagination = ""
    if pages > 1:
        pagination = '<div style="margin-top: 20px;">'
        for p in range(1, pages + 1):
            active = "btn-primary" if p == page else ""
            pagination += f'<a href="/admin/exceptions?page={p}" class="btn btn-sm {active}">{p}</a> '
        pagination += "</div>"

    content = f"""
    <h1>Exception Queue ({total})</h1>

    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>Priority</th>
                    <th>Type</th>
                    <th>Title</th>
                    <th>Application ID</th>
                    <th>Created</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {rows if rows else '<tr><td colspan="6" style="text-align: center; color: #6b7280;">No unresolved exceptions</td></tr>'}
            </tbody>
        </table>
        {pagination}
    </div>
    """

    return HTMLResponse(render_base(content, "Exceptions - Recruiter Autopilot"))


@router.get("/jobs", response_class=HTMLResponse)
async def admin_jobs(
    admin: str = Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Jobs management UI."""
    result = await session.execute(
        select(Job).order_by(Job.name)
    )
    jobs = result.scalars().all()

    rows = ""
    for job in jobs:
        automation_badge = (
            '<span class="badge badge-green">ON</span>'
            if job.automation_enabled
            else '<span class="badge badge-red">OFF</span>'
        )

        # Check for active kill switches
        ks_result = await session.execute(
            select(func.count(KillSwitch.id))
            .where(KillSwitch.job_id == job.id, KillSwitch.is_active == True)
        )
        ks_count = ks_result.scalar() or 0
        ks_badge = (
            f'<span class="badge badge-red">{ks_count} KILL SWITCH</span>'
            if ks_count > 0
            else ""
        )

        rows += f"""
        <tr>
            <td>{job.greenhouse_id}</td>
            <td>{job.name[:40]}{'...' if len(job.name) > 40 else ''}</td>
            <td>{job.status}</td>
            <td>{automation_badge} {ks_badge}</td>
            <td>
                <button class="btn btn-sm {'btn-danger' if job.automation_enabled else 'btn-primary'}"
                        hx-post="/admin/api/jobs/{job.id}/toggle-automation"
                        hx-swap="innerHTML"
                        hx-target="closest td">
                    {'Disable' if job.automation_enabled else 'Enable'}
                </button>
            </td>
        </tr>
        """

    content = f"""
    <h1>Jobs</h1>

    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>GH Job ID</th>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Automation</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {rows if rows else '<tr><td colspan="5" style="text-align: center; color: #6b7280;">No jobs configured</td></tr>'}
            </tbody>
        </table>
    </div>
    """

    return HTMLResponse(render_base(content, "Jobs - Recruiter Autopilot"))


# API endpoints for HTMX actions
@router.post("/api/applications/{application_id}/mark-reviewed")
async def api_mark_reviewed(
    application_id: int,
    admin: str = Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """HTMX endpoint to mark application as reviewed."""
    result = await session.execute(
        select(Application).where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()

    if not app:
        return HTMLResponse('<td colspan="7">Not found</td>')

    app.human_reviewed = True
    app.human_reviewed_at = datetime.utcnow()
    app.human_reviewed_by = admin
    app.needs_human_review = False
    await session.commit()

    return HTMLResponse(
        f'<td colspan="7" style="color: #166534; text-align: center;">✓ Marked as reviewed by {admin}</td>'
    )


@router.post("/api/exceptions/{exception_id}/resolve")
async def api_resolve_exception(
    exception_id: int,
    admin: str = Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """HTMX endpoint to resolve an exception."""
    result = await session.execute(
        select(ExceptionQueueItem).where(ExceptionQueueItem.id == exception_id)
    )
    exc = result.scalar_one_or_none()

    if not exc:
        return HTMLResponse('<td colspan="6">Not found</td>')

    exc.mark_resolved(admin, "manual_fix", "Resolved via admin UI")
    await session.commit()

    return HTMLResponse(
        f'<td colspan="6" style="color: #166534; text-align: center;">✓ Resolved by {admin}</td>'
    )


@router.post("/api/jobs/{job_id}/toggle-automation")
async def api_toggle_automation(
    job_id: int,
    admin: str = Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """HTMX endpoint to toggle job automation."""
    result = await session.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        return HTMLResponse("Not found")

    job.automation_enabled = not job.automation_enabled
    await session.commit()

    btn_class = "btn-danger" if job.automation_enabled else "btn-primary"
    btn_text = "Disable" if job.automation_enabled else "Enable"
    badge = (
        '<span class="badge badge-green">ON</span>'
        if job.automation_enabled
        else '<span class="badge badge-red">OFF</span>'
    )

    return HTMLResponse(f"""
        {badge}
        <button class="btn btn-sm {btn_class}"
                hx-post="/admin/api/jobs/{job.id}/toggle-automation"
                hx-swap="innerHTML"
                hx-target="closest td"
                style="margin-left: 10px;">
            {btn_text}
        </button>
    """)
