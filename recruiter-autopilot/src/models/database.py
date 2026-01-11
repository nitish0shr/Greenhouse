"""Database connection and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.config import settings
from src.models.base import Base

# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=settings.database_pool_size if not settings.is_development else 5,
    max_overflow=settings.database_max_overflow if not settings.is_development else 2,
    pool_pre_ping=True,  # Enable connection health checks
)

# Create session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI to get a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for getting a database session (for use outside FastAPI)."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database (create tables if they don't exist)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()


# For Celery workers (sync operations) - use a separate engine
def get_sync_engine():
    """Get synchronous engine for Celery workers."""
    from sqlalchemy import create_engine

    return create_engine(
        settings.sync_database_url,
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
    )


def get_sync_session():
    """Get synchronous session for Celery workers."""
    from sqlalchemy.orm import sessionmaker

    sync_engine = get_sync_engine()
    SessionLocal = sessionmaker(bind=sync_engine, autoflush=False, autocommit=False)
    return SessionLocal()
