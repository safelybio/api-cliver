"""Tests for authentication (requires 1.1 implementation).

These tests verify API key authentication once implemented.
All tests are marked as expected failures until 1.1 is implemented.
"""

import pytest


@pytest.mark.xfail(reason="Authentication not yet implemented (1.1)")
class TestAPIKeyAuthentication:
    """Tests for API key authentication."""

    def test_verify_without_api_key(self, test_client, sample_kyc_request):
        """Test that /verify without API key returns 401."""
        response = test_client.post("/verify", json=sample_kyc_request)
        assert response.status_code == 401

    def test_verify_with_invalid_api_key(self, test_client, sample_kyc_request):
        """Test that /verify with invalid API key returns 401."""
        response = test_client.post(
            "/verify",
            json=sample_kyc_request,
            headers={"X-API-Key": "invalid-key"},
        )
        assert response.status_code == 401

    def test_verify_with_empty_api_key(self, test_client, sample_kyc_request):
        """Test that /verify with empty API key returns 401."""
        response = test_client.post(
            "/verify",
            json=sample_kyc_request,
            headers={"X-API-Key": ""},
        )
        assert response.status_code == 401

    def test_verify_with_valid_api_key(
        self, test_client, sample_kyc_request, httpx_mock, mock_tavily
    ):
        """Test that /verify with valid API key succeeds."""
        from tests.conftest import (
            build_openrouter_chat_reply,
            build_openrouter_responses_reply,
            build_verification_determination_response,
            build_verification_evidence_response,
            build_background_work_response,
        )
        import json

        # Set up mocks
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/responses",
            json=build_openrouter_responses_reply("Verification completed."),
        )
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            json=build_openrouter_chat_reply(
                json.dumps(build_verification_evidence_response())
            ),
        )
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            json=build_openrouter_chat_reply(
                json.dumps(build_verification_determination_response())
            ),
        )
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            json=build_openrouter_chat_reply(
                json.dumps(build_background_work_response())
            ),
        )
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            json=build_openrouter_chat_reply("Summary."),
        )

        # This test will need the actual valid key from environment
        # For now, we use a placeholder that should match CLIVER_API_KEY
        response = test_client.post(
            "/verify",
            json=sample_kyc_request,
            headers={"X-API-Key": "valid-test-key"},
        )
        assert response.status_code == 200


class TestHealthNoAuth:
    """Tests that /health doesn't require authentication."""

    def test_health_no_auth_required(self, test_client):
        """Test that /health endpoint works without authentication."""
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_health_with_api_key_still_works(self, test_client):
        """Test that /health endpoint works with API key (doesn't break)."""
        response = test_client.get(
            "/health",
            headers={"X-API-Key": "any-key"},
        )
        assert response.status_code == 200
