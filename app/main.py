# =============================================================================
# Recruiter Autopilot - FastAPI Application
# =============================================================================

from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    if settings.environment == "development":
        await init_db()
        logger.info("Database tables initialized")
    
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
# Root Endpoint
# -----------------------------------------------------------------------------
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Recruiter Autopilot",
        "version": "1.0.0",
        "docs": "/docs" if settings.debug else None,
        "health": "/health",
        "admin": "/admin",
    }
