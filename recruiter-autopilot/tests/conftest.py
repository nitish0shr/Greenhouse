"""Pytest configuration and fixtures."""

import asyncio
from datetime import datetime
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.config import Settings
from src.models.base import Base
from src.models.database import get_session
from src.api.app import create_app


# Test database URL (SQLite in memory for fast tests)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
TEST_SYNC_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Create test settings."""
    return Settings(
        app_env="development",
        debug=True,
        mock_mode=True,
        database_url=TEST_DATABASE_URL,
        admin_password="test-password",
    )


@pytest_asyncio.fixture
async def async_engine():
    """Create async database engine for tests."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create async database session for tests."""
    async_session_factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        yield session


@pytest.fixture
def sync_engine():
    """Create sync database engine for tests."""
    engine = create_engine(
        TEST_SYNC_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def sync_session(sync_engine) -> Generator[Session, None, None]:
    """Create sync database session for tests."""
    SessionLocal = sessionmaker(bind=sync_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest_asyncio.fixture
async def client(async_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client."""
    app = create_app()

    # Override database session dependency
    async def override_get_session():
        yield async_session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def sample_resume_text() -> str:
    """Sample resume text for testing."""
    return """
JANE DOE
Senior Software Engineer
jane.doe@email.com | (555) 123-4567 | San Francisco, CA
linkedin.com/in/janedoe | github.com/janedoe

SUMMARY
Experienced software engineer with 7+ years building scalable backend systems.
Strong expertise in Python, distributed systems, and cloud infrastructure.
Led teams of 5-8 engineers on critical platform initiatives.

EXPERIENCE

Senior Software Engineer | TechCorp Inc. | 2020 - Present
- Designed and implemented microservices architecture serving 10M+ requests/day
- Led migration from monolith to microservices, reducing deployment time by 80%
- Mentored 5 junior engineers, conducting code reviews and technical guidance
- Technologies: Python, Go, Kubernetes, PostgreSQL, Redis, AWS

Software Engineer | StartupXYZ | 2017 - 2020
- Built real-time data pipeline processing 1TB+ daily using Apache Kafka
- Developed REST APIs handling 50K concurrent users
- Improved system reliability from 99.5% to 99.99% uptime
- Technologies: Python, Django, Kafka, Docker, GCP

EDUCATION
M.S. Computer Science | Stanford University | 2017
B.S. Computer Science | UC Berkeley | 2015

SKILLS
Languages: Python (expert), Go, JavaScript, SQL
Frameworks: FastAPI, Django, React
Infrastructure: AWS, GCP, Kubernetes, Docker, Terraform
Databases: PostgreSQL, Redis, MongoDB

CERTIFICATIONS
- AWS Solutions Architect Professional
"""


@pytest.fixture
def sample_rubric() -> dict:
    """Sample rubric for testing."""
    return {
        "name": "Test Rubric",
        "version": "1.0",
        "description": "Test rubric for unit tests",
        "dimensions": {
            "experience": {
                "weight": 0.40,
                "description": "Years of experience",
                "scoring": {
                    "0-2_years": 3,
                    "2-5_years": 6,
                    "5-10_years": 8,
                    "10+_years": 10,
                },
            },
            "skills": {
                "weight": 0.40,
                "description": "Technical skills",
                "required_any": ["python", "java", "go"],
                "preferred": ["kubernetes", "aws"],
            },
            "education": {
                "weight": 0.20,
                "description": "Education",
            },
        },
        "hard_constraints": [
            {
                "name": "min_experience",
                "type": "years",
                "min": 1,
                "reject_message": "Less than 1 year experience",
            },
        ],
        "tier_thresholds": {
            "A": 0.80,
            "B": 0.65,
            "C": 0.45,
        },
        "confidence_settings": {
            "threshold": 0.7,
            "low_confidence_triggers_review": True,
        },
    }


@pytest.fixture
def sample_webhook_payload() -> dict:
    """Sample Greenhouse webhook payload."""
    return {
        "action": "new_candidate_application",
        "payload": {
            "application": {
                "id": 12345,
                "candidate_id": 54321,
                "applied_at": "2024-01-15T10:00:00Z",
                "source": {"public_name": "LinkedIn"},
                "current_stage": {"id": 1001, "name": "Application Review"},
                "jobs": [{"id": 99999, "name": "Software Engineer"}],
                "attachments": [
                    {
                        "filename": "resume.pdf",
                        "url": "https://example.com/resume.pdf",
                        "type": "resume",
                    }
                ],
            },
        },
    }


@pytest.fixture
def sample_candidate_data() -> dict:
    """Sample candidate data from Greenhouse."""
    return {
        "id": 54321,
        "first_name": "Jane",
        "last_name": "Doe",
        "company": "TechCorp Inc.",
        "title": "Senior Software Engineer",
        "email_addresses": [{"value": "jane.doe@email.com", "type": "personal"}],
        "phone_numbers": [{"value": "+1-555-123-4567", "type": "mobile"}],
        "tags": ["python", "backend"],
    }


@pytest.fixture
def sample_job_data() -> dict:
    """Sample job data from Greenhouse."""
    return {
        "id": 99999,
        "name": "Software Engineer",
        "status": "open",
        "departments": [{"id": 1, "name": "Engineering"}],
        "offices": [{"id": 1, "name": "San Francisco"}],
    }
