# =============================================================================
# Recruiter Autopilot - FastAPI Application
# =============================================================================

from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import close_db, init_db

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Lifespan Context Manager
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle events."""
    # Startup
    logger.info("Starting Recruiter Autopilot...")
    logger.info(f"Environment: {settings.environment}")
    
    if settings.debug:
        logger.warning("Debug mode is enabled - do not use in production!")
    
    # Initialize database (for development only - use migrations in production)
    # Skip database initialization in production (use Alembic migrations instead)
    # Also skip if database is not available (for demo/testing)
    if settings.environment == "development" and not settings.is_production:
        try:
            # Only initialize if DATABASE_URL points to localhost (development)
            if "localhost" in settings.database_url or "127.0.0.1" in settings.database_url:
                await init_db()
                logger.info("Database tables initialized")
            else:
                logger.info("Skipping database initialization (non-local database, use migrations)")
        except Exception as e:
            logger.warning(f"Database initialization skipped: {e}")
    else:
        logger.info("Skipping database initialization (production mode - use migrations)")
    
    logger.info("Startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await close_db()
    logger.info("Shutdown complete")


# -----------------------------------------------------------------------------
# FastAPI Application
# -----------------------------------------------------------------------------
app = FastAPI(
    title="Recruiter Autopilot",
    description="Automated applicant processing for Greenhouse with Outlook integration",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)


# -----------------------------------------------------------------------------
# Middleware
# -----------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Static Files & Templates
# -----------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# -----------------------------------------------------------------------------
# Exception Handlers
# -----------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal error occurred",
            "type": type(exc).__name__,
        },
    )


# -----------------------------------------------------------------------------
# Health Check Endpoints
# -----------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "environment": settings.environment,
    }


@app.get("/health/ready", tags=["Health"])
async def readiness_check():
    """Readiness check - verifies all dependencies are available."""
    checks = {
        "database": False,
        "redis": False,
        "greenhouse": settings.greenhouse_configured,
        "graph": settings.graph_configured,
    }
    
    # Check database connection
    try:
        from app.database import async_engine
        async with async_engine.connect() as conn:
            await conn.execute("SELECT 1")
        checks["database"] = True
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
    
    # Check Redis connection
    try:
        import redis.asyncio as redis
        r = redis.from_url(settings.redis_url)
        await r.ping()
        await r.close()
        checks["redis"] = True
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
    
    all_healthy = all(checks.values())
    
    return JSONResponse(
        status_code=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
        },
    )


# -----------------------------------------------------------------------------
# API Routers
# -----------------------------------------------------------------------------
from app.api import webhooks, admin, graph_webhooks, admin_endpoints

app.include_router(webhooks.router, prefix="/api", tags=["Webhooks"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(admin_endpoints.router, prefix="/api/admin", tags=["Admin API"])
app.include_router(graph_webhooks.router, prefix="/api/graph", tags=["Graph Webhooks"])


# -----------------------------------------------------------------------------
# Root Endpoint - Landing Page
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, tags=["Root"])
async def root(request: Request):
    """Landing page with system overview and quick actions."""
    # Default stats (used if database isn't available)
    stats = {
        "total_applications": 0,
        "avg_processing_time": "< 30s",
        "active_jobs": 0,
        "pending_reviews": 0,
    }
    
    # Default health status
    health = {
        "api": True,
        "database": False,
        "redis": False,
        "workers": False,
        "worker_count": 0,
    }
    
    # Try to get database stats (gracefully handle if DB not available)
    try:
        from sqlalchemy import func, select
        from app.database import AsyncSessionLocal
        from app.models.application import Application
        from app.models.human_review import HumanReviewQueue
        from app.models.job_config import JobConfig
        
        async with AsyncSessionLocal() as session:
            stats["total_applications"] = await session.scalar(
                select(func.count(Application.id))
            ) or 0
            stats["active_jobs"] = await session.scalar(
                select(func.count(JobConfig.id)).where(JobConfig.is_active == True)
            ) or 0
            stats["pending_reviews"] = await session.scalar(
                select(func.count(HumanReviewQueue.id))
                .where(HumanReviewQueue.status == "pending")
            ) or 0
            health["database"] = True
    except Exception as db_error:
        logger.debug(f"Database not available: {db_error}")
    
    # Try to check Redis (gracefully handle if not available)
    try:
        import redis.asyncio as redis_client
        r = redis_client.from_url(settings.redis_url)
        await r.ping()
        health["redis"] = True
        health["workers"] = True
        health["worker_count"] = 1
        await r.close()
    except Exception as redis_error:
        logger.debug(f"Redis not available: {redis_error}")
    
    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "stats": stats,
            "health": health,
        },
    )


@app.get("/api", tags=["API"])
async def api_info():
    """Root API endpoint with API information (JSON)."""
    return {
        "name": "Recruiter Autopilot",
        "version": "1.0.0",
        "docs": "/docs" if settings.debug else None,
        "health": "/health",
        "admin": "/admin",
    }

