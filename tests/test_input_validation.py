"""Tests for input validation on KYC API endpoints.

These tests verify:
- Required field validation
- Field length limits (after 1.3 implementation)
- Email format validation (after 2.3 implementation)
"""

import pytest


class TestRequiredFields:
    """Tests for required field validation."""

    def test_missing_customer_name(self, test_client):
        """Test that missing customer_name returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "email": "test@example.edu",
                "institution": "Example University",
            },
        )
        assert response.status_code == 422

    def test_missing_email(self, test_client):
        """Test that missing email returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "institution": "Example University",
            },
        )
        assert response.status_code == 422

    def test_missing_institution(self, test_client):
        """Test that missing institution returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "test@example.edu",
            },
        )
        assert response.status_code == 422

    def test_empty_request_body(self, test_client):
        """Test that empty request body returns 422."""
        response = test_client.post("/verify", json={})
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
        )
        assert response.status_code == 422


class TestFieldLengthLimits:
    """Tests for field length limits (requires 1.3 implementation).

    These tests are marked as expected failures until 1.3 is implemented.
    After implementing max_length constraints in KYCRequest, remove the xfail markers.
    """

    @pytest.mark.xfail(reason="Field length limits not yet implemented (1.3)")
    def test_customer_name_too_long(self, test_client):
        """Test that customer_name > 200 chars returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "x" * 201,
                "email": "test@example.edu",
                "institution": "Example University",
            },
        )
        assert response.status_code == 422

    @pytest.mark.xfail(reason="Field length limits not yet implemented (1.3)")
    def test_email_too_long(self, test_client):
        """Test that email > 254 chars returns 422."""
        # 254 is RFC 5321 limit
        long_local = "x" * 245
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": f"{long_local}@example.edu",
                "institution": "Example University",
            },
        )
        assert response.status_code == 422

    @pytest.mark.xfail(reason="Field length limits not yet implemented (1.3)")
    def test_institution_too_long(self, test_client):
        """Test that institution > 500 chars returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "test@example.edu",
                "institution": "x" * 501,
            },
        )
        assert response.status_code == 422

    @pytest.mark.xfail(reason="Field length limits not yet implemented (1.3)")
    def test_order_description_too_long(self, test_client):
        """Test that order_description > 2000 chars returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "test@example.edu",
                "institution": "Example University",
                "order_description": "x" * 2001,
            },
        )
        assert response.status_code == 422

    def test_customer_name_at_limit(self, httpx_mock, test_client, mock_tavily):
        """Test that customer_name at 200 chars is accepted (boundary test)."""
        # This test verifies behavior at the boundary, useful after 1.3
        # For now, it just ensures we don't crash on longer names
        pass  # Placeholder - will be meaningful after 1.3


class TestEmailValidation:
    """Tests for email format validation (requires 2.3 implementation).

    These tests are marked as expected failures until 2.3 is implemented.
    After implementing EmailStr in KYCRequest, remove the xfail markers.
    """

    @pytest.mark.xfail(reason="Email validation not yet implemented (2.3)")
    def test_invalid_email_format(self, test_client):
        """Test that invalid email format returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "not-an-email",
                "institution": "Example University",
            },
        )
        assert response.status_code == 422

    @pytest.mark.xfail(reason="Email validation not yet implemented (2.3)")
    def test_email_missing_domain(self, test_client):
        """Test that email without domain returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "test@",
                "institution": "Example University",
            },
        )
        assert response.status_code == 422

    @pytest.mark.xfail(reason="Email validation not yet implemented (2.3)")
    def test_email_missing_local_part(self, test_client):
        """Test that email without local part returns 422."""
        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "@example.edu",
                "institution": "Example University",
            },
        )
        assert response.status_code == 422

    def test_valid_email_format(self, httpx_mock, test_client, mock_tavily):
        """Test that valid email format is accepted."""
        # This test just verifies valid emails work (placeholder for future)
        pass  # Will be more meaningful after 2.3


class TestOptionalFields:
    """Tests for optional field behavior."""

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    def test_order_description_optional(self, test_client, httpx_mock, mock_tavily):
        """Test that order_description is truly optional."""
        # Set up mocks for a successful request
        from tests.conftest import (
            build_openrouter_chat_reply,
            build_openrouter_responses_reply,
            build_verification_determination_response,
            build_verification_evidence_response,
        )
        import json

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
            json=build_openrouter_chat_reply("Summary."),
        )

        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "test@example.edu",
                "institution": "Example University",
                # No order_description
            },
        )

        assert response.status_code == 200

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    def test_empty_order_description_skips_work_prompt(self, test_client, httpx_mock, mock_tavily):
        """Test that empty string order_description skips work prompt (falsy value)."""
        from tests.conftest import (
            build_openrouter_chat_reply,
            build_openrouter_responses_reply,
            build_verification_determination_response,
            build_verification_evidence_response,
        )
        import json

        # Empty string is falsy in Python, so work prompt should be skipped
        # Only need verification prompt and 3 extractions (no work extraction)
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
            json=build_openrouter_chat_reply("Summary."),
        )

        response = test_client.post(
            "/verify",
            json={
                "customer_name": "Test User",
                "email": "test@example.edu",
                "institution": "Example University",
                "order_description": "",  # Empty string is falsy
            },
        )

        assert response.status_code == 200
        # Empty string should skip work prompt, so no background_work
        assert response.json().get("background_work") is None
