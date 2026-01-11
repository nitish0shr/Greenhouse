# =============================================================================
# Recruiter Autopilot - Database Configuration
# =============================================================================

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


# -----------------------------------------------------------------------------
# Base Model
# -----------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# -----------------------------------------------------------------------------
# Async Engine & Session (for FastAPI)
# -----------------------------------------------------------------------------
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI endpoints."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_async_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for use outside of FastAPI dependencies."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Sync Engine & Session (for Celery workers)
# -----------------------------------------------------------------------------
sync_engine = create_engine(
    settings.database_url_sync,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)


def get_sync_session():
    """Get a synchronous session for Celery workers."""
    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.close()


# -----------------------------------------------------------------------------
# Database Utilities
# -----------------------------------------------------------------------------
async def init_db():
    """Initialize database tables (for development only)."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections."""
    await async_engine.dispose()
