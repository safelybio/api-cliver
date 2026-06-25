"""Tests for API key authentication."""

import json

import pytest

from tests.conftest import (
    build_background_work_response,
    build_openrouter_chat_reply,
    build_verification_determination_response,
    build_verification_evidence_response,
)


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

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    def test_verify_with_valid_api_key(
        self, test_client, sample_kyc_request, httpx_mock, mock_tavily
    ):
        """Test that /verify with valid API key succeeds."""
        # Set up mocks for verification prompt
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            json=build_openrouter_chat_reply("Verification completed."),
        )
        # Work prompt (since sample_kyc_request includes order_description)
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            json=build_openrouter_chat_reply("Work completed."),
        )
        # Extraction calls
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

        # Use the API key from mock_env fixture (test-api-key)
        response = test_client.post(
            "/verify",
            json=sample_kyc_request,
            headers={"X-API-Key": "test-api-key"},
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
