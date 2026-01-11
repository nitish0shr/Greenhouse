# =============================================================================
# Pytest Configuration and Fixtures
# =============================================================================

import pytest
from typing import Generator
from unittest.mock import Mock, AsyncMock, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.database import Base
from app.config import settings

# Test database URL (use in-memory SQLite for tests)
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Create a test database session."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def mock_greenhouse_client() -> Mock:
    """Mock Greenhouse client."""
    client = Mock()
    client.get_candidate.return_value = {
        "id": 12345,
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@example.com",
        "attachments": [],
    }
    client.get_application.return_value = {
        "id": 67890,
        "candidate_id": 12345,
        "job_id": 100,
        "current_stage": {"id": 1, "name": "Application Review"},
    }
    client.download_attachment = AsyncMock(return_value=b"fake resume content")
    client.add_note_to_candidate = AsyncMock(return_value={"id": 1})
    client.add_tag = AsyncMock(return_value={"id": 1})
    return client


@pytest.fixture
def mock_graph_client() -> Mock:
    """Mock Graph client."""
    client = Mock()
    client.send_mail = AsyncMock(return_value={"id": "msg-123"})
    client.create_calendar_event = AsyncMock(return_value={"id": "event-123"})
    client.get_message = AsyncMock(return_value={
        "id": "msg-123",
        "conversationId": "conv-123",
        "subject": "Test",
        "from": {"emailAddress": {"address": "candidate@example.com"}},
    })
    client.get_free_busy = AsyncMock(return_value={
        "value": [{
            "scheduleId": "user@example.com",
            "availabilityView": "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000
        }],
    })
    client.create_subscription = AsyncMock(return_value={
        "id": "sub-123",
        "expirationDateTime": "2026-01-13T12:00:00Z",
    })
    return client


@pytest.fixture
def sample_resume_text() -> str:
    """Sample resume text for testing."""
    return """
    John Doe
    Software Engineer
    
    Experience:
    - 5 years of Python development using Django and FastAPI
    - Strong background in PostgreSQL and SQL
    - Experience with AWS cloud platforms
    - CI/CD pipelines with GitHub Actions
    
    Education:
    - Bachelor of Science in Computer Science
    """


@pytest.fixture
def sample_scoring_output() -> dict:
    """Sample scoring output for testing."""
    return {
        "hard_reject": False,
        "hard_reject_reasons": [],
        "dimension_scores": {
            "technical_skills": {
                "score": 85,
                "evidence": [
                    {"snippet": "5 years of Python development", "source": "resume"}
                ],
            },
        },
        "weighted_score": 85,
        "tier": "A",
        "confidence": 0.9,
        "needs_human_review": False,
        "needs_human_review_reasons": [],
        "evidence_snippets": [],
        "missing_info_questions": [],
        "rubric_version": "1.0.0",
    }
