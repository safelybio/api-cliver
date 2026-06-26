"""Tests for the async verification job endpoints."""

from unittest.mock import AsyncMock, patch

from app.models import (
    Audit,
    Decision,
    KYCResponse,
    RawOutput,
)


def _fake_response() -> KYCResponse:
    """Build a minimal valid KYCResponse for the mocked worker."""
    return KYCResponse(
        decision=Decision(status="PASS", flags_count=0, summary="All clear."),
        checks=[],
        background_work=None,
        audit=Audit(
            tool_calls=[],
            raw=RawOutput(verification="## Verified.", work=None),
        ),
    )


class TestAsyncVerifyJobs:
    """Tests for POST /verify/async and GET /verify/jobs/{id}."""

    def test_async_requires_api_key(self, test_client, sample_kyc_request):
        """POST /verify/async without API key returns 401."""
        response = test_client.post("/verify/async", json=sample_kyc_request)
        assert response.status_code == 401

    def test_jobs_requires_api_key(self, test_client):
        """GET /verify/jobs/{id} without API key returns 401."""
        response = test_client.get("/verify/jobs/some-id")
        assert response.status_code == 401

    def test_unknown_job_returns_404(self, test_client):
        """GET on an unknown job_id returns 404."""
        response = test_client.get(
            "/verify/jobs/does-not-exist",
            headers={"X-API-Key": "test-api-key"},
        )
        assert response.status_code == 404

    def test_async_returns_job_id_and_completes(
        self, test_client, sample_kyc_request
    ):
        """POST /verify/async returns a job_id; polling yields a completed result."""
        with patch(
            "app.main._run_verification",
            new=AsyncMock(return_value=_fake_response()),
        ):
            response = test_client.post(
                "/verify/async",
                json=sample_kyc_request,
                headers={"X-API-Key": "test-api-key"},
            )
            assert response.status_code == 200
            body = response.json()
            assert "job_id" in body
            assert body["status_url"] == f"/verify/jobs/{body['job_id']}"
            assert "estimated_seconds" in body

            job_id = body["job_id"]

            # The background task runs on the test client's event loop; by the
            # time this synchronous GET returns, the mocked worker has finished.
            status_response = test_client.get(
                f"/verify/jobs/{job_id}",
                headers={"X-API-Key": "test-api-key"},
            )
            assert status_response.status_code == 200
            status_body = status_response.json()
            assert status_body["job_id"] == job_id
            # The TestClient drains the background task before the next request,
            # so the job has completed by the time we poll.
            assert status_body["status"] == "completed"
            assert status_body["result"]["decision"]["status"] == "PASS"
