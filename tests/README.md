# Testing Guide

## Overview

This directory contains tests for the Recruiting Autopilot system. Tests are organized by type:

- `test_security.py` - Security utilities (HMAC, sanitization, injection detection)
- `test_scoring_engine.py` - Scoring engine functionality
- `test_webhooks.py` - Webhook endpoints (Greenhouse, Graph)

## Running Tests

### Run All Tests
```bash
pytest
```

### Run Specific Test File
```bash
pytest tests/test_security.py
```

### Run with Coverage
```bash
pytest --cov=app --cov-report=html
```

### Run by Marker
```bash
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
pytest -m e2e          # End-to-end tests only
```

## Test Structure

### Fixtures (conftest.py)

- `db_session` - Database session for tests (in-memory SQLite)
- `mock_greenhouse_client` - Mock Greenhouse API client
- `mock_graph_client` - Mock Graph API client
- `sample_resume_text` - Sample resume text for testing
- `sample_scoring_output` - Sample scoring output

### Writing New Tests

1. Import necessary fixtures from `conftest.py`
2. Use `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.e2e` markers
3. Follow naming convention: `test_*.py` for files, `test_*` for functions
4. Use async fixtures for async tests with `pytest-asyncio`

Example:
```python
import pytest
from app.services.scoring_engine import ScoringEngine

@pytest.mark.unit
def test_scoring_engine_basic(db_session, sample_resume_text):
    engine = ScoringEngine()
    result = engine.score(sample_resume_text)
    assert result["weighted_score"] >= 0
```

## Mock Mode

Tests use mock clients (`MockGreenhouseClient`, `MockGraphClient`) to avoid making real API calls. These are defined in:

- `app/services/mock_greenhouse.py`
- `app/services/mock_graph.py`

To use mock mode in development, set environment variable:
```bash
MOCK_MODE=true
```

## Continuous Integration

Tests should run automatically in CI/CD pipeline. Ensure all tests pass before merging.
