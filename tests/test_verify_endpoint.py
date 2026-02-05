"""End-to-end tests for the /verify endpoint with mocked external APIs."""

import pytest

from tests.conftest import mock_full_verify_flow, mock_minimal_verify_flow


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
class TestVerifyEndpointStructure:
    """Tests for /verify endpoint response structure."""

    def test_verify_returns_expected_structure(
        self, httpx_mock, test_client, sample_kyc_request, mock_tavily
    ):
        """Test that /verify returns the expected response structure."""
        mock_full_verify_flow(
            httpx_mock,
            verification_text="## Verification completed.\n\nAll criteria verified successfully.",
            work_text="## Work Analysis completed.\n\nRelevant research found.",
            summary_text="Verified MIT professor with relevant research experience.",
        )

        response = test_client.post(
            "/verify",
            json=sample_kyc_request,
            headers={"X-API-Key": "test-api-key"},
        )

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
        mock_full_verify_flow(httpx_mock, summary_text="All clear.")

        response = test_client.post(
            "/verify",
            json=sample_kyc_request,
            headers={"X-API-Key": "test-api-key"},
        )

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
        mock_minimal_verify_flow(httpx_mock)

        response = test_client.post(
            "/verify",
            json=sample_kyc_request_minimal,
            headers={"X-API-Key": "test-api-key"},
        )

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
