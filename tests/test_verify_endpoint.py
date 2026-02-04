"""End-to-end tests for the /verify endpoint with mocked external APIs."""

import json

import pytest

from tests.conftest import (
    build_background_work_response,
    build_openrouter_chat_reply,
    build_openrouter_responses_reply,
    build_verification_determination_response,
    build_verification_evidence_response,
)


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
class TestVerifyEndpointStructure:
    """Tests for /verify endpoint response structure."""

    def test_verify_returns_expected_structure(
        self, httpx_mock, test_client, sample_kyc_request, mock_tavily
    ):
        """Test that /verify returns the expected response structure."""
        # Mock OpenRouter /responses API - verification prompt
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/responses",
            json=build_openrouter_responses_reply(
                "## Verification completed.\n\nAll criteria verified successfully."
            ),
        )
        # Mock OpenRouter /responses API - work prompt (since order_description provided)
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/responses",
            json=build_openrouter_responses_reply(
                "## Work Analysis completed.\n\nRelevant research found."
            ),
        )

        # Mock OpenRouter /chat/completions API (extraction calls)
        # All chat completion calls can return the appropriate responses
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
        # Summary generation
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            json=build_openrouter_chat_reply(
                "Verified MIT professor with relevant research experience."
            ),
        )

        response = test_client.post("/verify", json=sample_kyc_request)

        assert response.status_code == 200
        data = response.json()

        # Check top-level structure
        assert "decision" in data
        assert "checks" in data
        assert "audit" in data

        # Check decision structure
        assert data["decision"]["status"] in ["PASS", "FLAG", "REVIEW"]
        assert "flags_count" in data["decision"]
        assert "summary" in data["decision"]

        # Check checks structure
        assert len(data["checks"]) == 4
        for check in data["checks"]:
            assert "criterion" in check
            assert "status" in check
            assert "evidence" in check
            assert "sources" in check

        # Check audit structure
        assert "tool_calls" in data["audit"]
        assert "raw" in data["audit"]

    def test_verify_pass_status(
        self, httpx_mock, test_client, sample_kyc_request, mock_tavily
    ):
        """Test that all NO FLAG determinations result in PASS status."""
        # Verification prompt
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/responses",
            json=build_openrouter_responses_reply("## Verification completed."),
        )
        # Work prompt
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/responses",
            json=build_openrouter_responses_reply("## Work completed."),
        )

        # All NO FLAG determinations
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
            json=build_openrouter_chat_reply("All clear."),
        )

        response = test_client.post("/verify", json=sample_kyc_request)

        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["status"] == "PASS"
        assert data["decision"]["flags_count"] == 0


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
class TestVerifyEndpointMinimal:
    """Tests for /verify with minimal request (no order_description)."""

    def test_verify_without_order_description(
        self, httpx_mock, test_client, sample_kyc_request_minimal, mock_tavily
    ):
        """Test that /verify works without order_description."""
        # Only verification prompt (no work prompt)
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/responses",
            json=build_openrouter_responses_reply("## Verification completed."),
        )

        # Only evidence and determination extractions (no work extraction)
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
        # Summary
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            json=build_openrouter_chat_reply("Verified."),
        )

        response = test_client.post("/verify", json=sample_kyc_request_minimal)

        assert response.status_code == 200
        data = response.json()

        # Should not have background_work when no order_description
        assert data.get("background_work") is None


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_healthy(self, test_client):
        """Test that /health endpoint returns healthy status."""
        response = test_client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_health_no_auth_required(self, test_client):
        """Test that /health doesn't require authentication (for future auth tests)."""
        # This test will be more meaningful after auth is implemented
        response = test_client.get("/health")
        assert response.status_code == 200
