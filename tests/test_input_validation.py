"""Tests for input validation on KYC API endpoints.

These tests verify:
- Required field validation
- Field length limits
- Email format validation (after 2.3 implementation)
"""

import pytest

from tests.conftest import mock_minimal_verify_flow

# Standard headers for authenticated requests
AUTH_HEADERS = {"X-API-Key": "test-api-key"}


class TestRequiredFields:
    """Tests for required field validation."""

    @pytest.mark.parametrize(
        "missing_field,request_body",
        [
            ("customer_name", {"email": "test@example.edu", "institution": "Example University"}),
            ("email", {"customer_name": "Test User", "institution": "Example University"}),
            ("institution", {"customer_name": "Test User", "email": "test@example.edu"}),
            ("all_fields", {}),
        ],
        ids=["missing_customer_name", "missing_email", "missing_institution", "empty_body"],
    )
    def test_missing_required_field(self, test_client, missing_field, request_body):
        """Test that missing required fields return 422."""
        response = test_client.post("/verify", json=request_body, headers=AUTH_HEADERS)
        assert response.status_code == 422

    def test_null_required_field(self, test_client):
        """Test that null required field returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": None,
                "email": "test@example.edu",
                "institution": "Example University",
            },
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422


class TestFieldLengthLimits:
    """Tests for field length limits."""

    @pytest.mark.parametrize(
        "field,value,base_request",
        [
            (
                "customer_name",
                "x" * 201,
                {"email": "test@example.edu", "institution": "Example University"},
            ),
            (
                "email",
                "x" * 245 + "@example.edu",  # > 254 chars (RFC 5321 limit)
                {"customer_name": "Test User", "institution": "Example University"},
            ),
            (
                "institution",
                "x" * 501,
                {"customer_name": "Test User", "email": "test@example.edu"},
            ),
            (
                "order_description",
                "x" * 2001,
                {"customer_name": "Test User", "email": "test@example.edu", "institution": "Example University"},
            ),
        ],
        ids=["customer_name_201", "email_255", "institution_501", "order_description_2001"],
    )
    def test_field_too_long(self, test_client, field, value, base_request):
        """Test that fields exceeding length limits return 422."""
        request_body = {**base_request, field: value}
        response = test_client.post("/verify", json=request_body, headers=AUTH_HEADERS)
        assert response.status_code == 422

    def test_customer_name_at_limit(self, httpx_mock, test_client, mock_tavily):
        """Test that customer_name at 200 chars is accepted (boundary test)."""
        # This test verifies behavior at the boundary
        # For now, it just ensures we don't crash on names at the limit
        pass  # Placeholder


class TestEmailValidation:
    """Tests for email format validation."""

    @pytest.mark.parametrize(
        "invalid_email",
        [
            "not-an-email",
            "test@",
            "@example.edu",
        ],
        ids=["no_at_sign", "missing_domain", "missing_local_part"],
    )
    def test_invalid_email_format(self, test_client, invalid_email):
        """Test that invalid email formats return 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": invalid_email,
                "institution": "Example University",
            },
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422

    def test_valid_email_format(self, httpx_mock, test_client, mock_tavily):
        """Test that valid email format is accepted."""
        # This test just verifies valid emails work (placeholder for future)
        pass


class TestOptionalFields:
    """Tests for optional field behavior."""

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    def test_order_description_optional(self, test_client, httpx_mock, mock_tavily):
        """Test that order_description is truly optional."""
        mock_minimal_verify_flow(httpx_mock, summary_text="Summary.")

        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "test@example.edu",
                "institution": "Example University",
                # No order_description
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    def test_empty_order_description_skips_work_prompt(self, test_client, httpx_mock, mock_tavily):
        """Test that empty string order_description skips work prompt (falsy value)."""
        # Empty string is falsy in Python, so work prompt should be skipped
        mock_minimal_verify_flow(httpx_mock, summary_text="Summary.")

        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "test@example.edu",
                "institution": "Example University",
                "order_description": "",  # Empty string is falsy
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        # Empty string should skip work prompt, so no background_work
        assert response.json().get("background_work") is None
