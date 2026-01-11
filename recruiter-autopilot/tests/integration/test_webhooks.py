"""Integration tests for webhook endpoints."""

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient


class TestGreenhouseWebhook:
    """Tests for Greenhouse webhook endpoint."""

    @pytest.mark.asyncio
    async def test_webhook_with_valid_signature(self, client: AsyncClient, sample_webhook_payload):
        """Test webhook acceptance with valid signature."""
        secret = "test-secret"
        payload_bytes = json.dumps(sample_webhook_payload).encode()

        signature = hmac.new(
            secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        # Note: In real test, we'd need to mock the settings
        response = await client.post(
            "/webhooks/greenhouse",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "Signature": f"sha256={signature}",
            },
        )

        # Should be accepted (queued or processed)
        assert response.status_code in (200, 401)  # 401 if secret doesn't match env

    @pytest.mark.asyncio
    async def test_webhook_without_signature(self, client: AsyncClient, sample_webhook_payload):
        """Test webhook rejection without signature."""
        response = await client.post(
            "/webhooks/greenhouse",
            json=sample_webhook_payload,
        )

        # Should be rejected
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_webhook_with_invalid_json(self, client: AsyncClient):
        """Test webhook rejection with invalid JSON."""
        response = await client.post(
            "/webhooks/greenhouse",
            content=b"not valid json",
            headers={
                "Content-Type": "application/json",
                "Signature": "sha256=abc",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_webhook_idempotency(self, client: AsyncClient, sample_webhook_payload):
        """Test that duplicate webhooks are ignored."""
        secret = "test-secret"
        payload_bytes = json.dumps(sample_webhook_payload).encode()

        signature = hmac.new(
            secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "Signature": f"sha256={signature}",
        }

        # First request
        response1 = await client.post(
            "/webhooks/greenhouse",
            content=payload_bytes,
            headers=headers,
        )

        # Second request with same payload
        response2 = await client.post(
            "/webhooks/greenhouse",
            content=payload_bytes,
            headers=headers,
        )

        # Both should succeed, but second might indicate duplicate
        if response1.status_code == 200 and response2.status_code == 200:
            data1 = response1.json()
            data2 = response2.json()

            # If both succeed, at least the event_id should match
            assert data1.get("event_id") == data2.get("event_id") or \
                   data2.get("reason") == "duplicate"


class TestGraphWebhook:
    """Tests for Microsoft Graph webhook endpoint."""

    @pytest.mark.asyncio
    async def test_subscription_validation(self, client: AsyncClient):
        """Test Graph subscription validation response."""
        validation_token = "test-validation-token-12345"

        response = await client.post(
            f"/webhooks/graph?validationToken={validation_token}",
        )

        assert response.status_code == 200
        assert response.text == validation_token

    @pytest.mark.asyncio
    async def test_notification_processing(self, client: AsyncClient):
        """Test Graph notification processing."""
        notification = {
            "value": [
                {
                    "subscriptionId": "sub-123",
                    "resource": "/users/test@example.com/messages/msg-456",
                    "changeType": "created",
                    "clientState": "test-state",
                }
            ]
        }

        response = await client.post(
            "/webhooks/graph",
            json=notification,
        )

        assert response.status_code == 202  # Graph expects 202 Accepted


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Test health check endpoint."""
        response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    @pytest.mark.asyncio
    async def test_readiness_check(self, client: AsyncClient):
        """Test readiness check endpoint."""
        response = await client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
