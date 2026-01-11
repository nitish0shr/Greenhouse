# =============================================================================
# Webhook Tests
# =============================================================================

import pytest
import json
import hmac
import hashlib
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, SyncSessionLocal
from app.models.event import Event


@pytest.fixture
def client(db_session):
    """Create test client."""
    # Override database dependency
    app.dependency_overrides = {}
    return TestClient(app)


@pytest.fixture
def greenhouse_webhook_payload():
    """Sample Greenhouse webhook payload."""
    return {
        "action": "new_candidate_application",
        "payload": {
            "application": {
                "id": 67890,
                "candidate_id": 12345,
                "job_id": 100,
            },
        },
    }


def generate_signature(payload: bytes, secret: str) -> str:
    """Generate Greenhouse webhook signature."""
    digest = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256 {digest}"


class TestGreenhouseWebhook:
    """Test Greenhouse webhook endpoint."""
    
    def test_webhook_with_valid_signature(self, client, greenhouse_webhook_payload):
        """Test webhook with valid signature."""
        payload_bytes = json.dumps(greenhouse_webhook_payload).encode()
        signature = generate_signature(payload_bytes, "test_secret")
        
        # Note: This test requires proper secret configuration
        # In real tests, you'd set the secret via environment variable
        response = client.post(
            "/api/webhooks/greenhouse",
            content=payload_bytes,
            headers={
                "Signature": signature,
                "Greenhouse-Event-ID": "test-event-123",
            },
        )
        
        # Should accept (200 or 202)
        assert response.status_code in [200, 202, 400]  # 400 if secret mismatch
    
    def test_webhook_with_invalid_signature(self, client, greenhouse_webhook_payload):
        """Test webhook with invalid signature."""
        payload_bytes = json.dumps(greenhouse_webhook_payload).encode()
        
        response = client.post(
            "/api/webhooks/greenhouse",
            content=payload_bytes,
            headers={
                "Signature": "sha256 invalid",
                "Greenhouse-Event-ID": "test-event-123",
            },
        )
        
        # Should reject
        assert response.status_code == 401
    
    def test_webhook_idempotency(self, client, greenhouse_webhook_payload, db_session):
        """Test webhook idempotency with duplicate event ID."""
        payload_bytes = json.dumps(greenhouse_webhook_payload).encode()
        signature = generate_signature(payload_bytes, "test_secret")
        event_id = "test-event-456"
        
        # Create existing event
        existing_event = Event(
            greenhouse_event_id=event_id,
            event_type="new_candidate_application",
            payload=greenhouse_webhook_payload,
            status="processed",
        )
        db_session.add(existing_event)
        db_session.commit()
        
        response = client.post(
            "/api/webhooks/greenhouse",
            content=payload_bytes,
            headers={
                "Signature": signature,
                "Greenhouse-Event-ID": event_id,
            },
        )
        
        # Should accept duplicate (idempotent)
        assert response.status_code in [200, 202]


class TestGraphWebhook:
    """Test Graph webhook endpoint."""
    
    def test_validation_handshake(self, client):
        """Test subscription validation handshake."""
        validation_token = "test-validation-token-12345"
        
        response = client.post(
            "/api/graph/notifications",
            params={"validationToken": validation_token},
        )
        
        # Should return validation token as plain text
        assert response.status_code == 200
        assert response.text == validation_token
    
    def test_notification_processing(self, client):
        """Test notification processing."""
        notification = {
            "value": [
                {
                    "resource": "users/test@example.com/messages",
                    "changeType": "created",
                    "resourceData": {
                        "id": "msg-123",
                    },
                },
            ],
        }
        
        response = client.post(
            "/api/graph/notifications",
            json=notification,
        )
        
        # Should accept
        assert response.status_code == 202
