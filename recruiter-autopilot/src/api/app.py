"""FastAPI application factory."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings
from src.models.database import close_db, init_db
from src.utils.logging import get_logger, setup_logging
from src.utils.security import generate_correlation_id

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    setup_logging(
        log_level=settings.log_level,
        json_logs=settings.is_production,
    )
    logger.info(
        "Starting Recruiter Autopilot",
        env=settings.app_env,
        mock_mode=settings.mock_mode,
    )

    if settings.is_development:
        await init_db()
        logger.info("Database initialized")

    yield

    # Shutdown
    await close_db()
    logger.info("Recruiter Autopilot shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Production-grade Recruiter Autopilot for Greenhouse + Outlook",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Correlation ID middleware
    @app.middleware("http")
    async def add_correlation_id(request: Request, call_next):
        """Add correlation ID to each request."""
        correlation_id = request.headers.get("X-Correlation-ID") or generate_correlation_id()
        request.state.correlation_id = correlation_id

        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler."""
        correlation_id = getattr(request.state, "correlation_id", "unknown")
        logger.error(
            "Unhandled exception",
            error=str(exc),
            correlation_id=correlation_id,
            path=request.url.path,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "correlation_id": correlation_id,
            },
        )

    # Health check
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": settings.app_name,
            "version": "1.0.0",
            "environment": settings.app_env,
        }

    # Readiness check
    @app.get("/ready")
    async def readiness_check():
        """Readiness check endpoint."""
        # Could add DB/Redis connectivity checks here
        return {"status": "ready"}

    # Import and register routers
    from src.api.routes.webhooks import router as webhooks_router
    from src.api.routes.applications import router as applications_router
    from src.api.routes.jobs import router as jobs_router
    from src.api.routes.admin import router as admin_router

    app.include_router(webhooks_router, prefix="/webhooks", tags=["Webhooks"])
    app.include_router(applications_router, prefix="/api/applications", tags=["Applications"])
    app.include_router(jobs_router, prefix="/api/jobs", tags=["Jobs"])

    if settings.admin_enabled:
        app.include_router(admin_router, prefix="/admin", tags=["Admin"])

    return app
