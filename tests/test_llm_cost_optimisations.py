"""Tests for the LLM cost optimisations: sticky session_id, usage tracking,
compact tool JSON, and the trimmed extraction context."""

import json

import pytest

from app.openrouter import _format_for_model
from app.tools.registry import ToolOutput
from tests.conftest import mock_full_verify_flow


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
class TestPromptCachingPayload:
    """Every LLM call for a screen must request usage and pin a session_id."""

    def test_usage_include_and_session_id_on_all_calls(
        self, httpx_mock, test_client, sample_kyc_request, mock_tavily
    ):
        mock_full_verify_flow(httpx_mock)

        response = test_client.post(
            "/verify",
            json=sample_kyc_request,
            headers={"X-API-Key": "test-api-key"},
        )
        assert response.status_code == 200

        requests = [
            r
            for r in httpx_mock.get_requests()
            if str(r.url) == "https://openrouter.ai/api/v1/chat/completions"
        ]
        # Verification + work + 3 extractions + summary = 6 OpenRouter calls.
        assert len(requests) == 6

        session_ids = set()
        for req in requests:
            body = json.loads(req.content)
            # Usage tracking is always on.
            assert body["usage"] == {"include": True}
            # session_id pins every call to one provider to keep the cache warm.
            assert "session_id" in body
            session_ids.add(body["session_id"])

        # All calls for one screen share a single session_id.
        assert len(session_ids) == 1


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
class TestExtractionContextTrimmed:
    """Extraction calls receive only the report text, not the tool dump."""

    def test_extraction_context_has_no_tool_dump(
        self, httpx_mock, test_client, sample_kyc_request, mock_tavily
    ):
        verification_text = (
            "## Report\n\n| Criterion | Sources |\n|---|---|\n| X | [web1] |"
        )
        mock_full_verify_flow(httpx_mock, verification_text=verification_text)

        response = test_client.post(
            "/verify",
            json=sample_kyc_request,
            headers={"X-API-Key": "test-api-key"},
        )
        assert response.status_code == 200

        requests = [
            r
            for r in httpx_mock.get_requests()
            if str(r.url) == "https://openrouter.ai/api/v1/chat/completions"
        ]
        # Extraction requests are those carrying a response_format (json_schema).
        extraction_requests = [
            json.loads(r.content)
            for r in requests
            if "response_format" in json.loads(r.content)
        ]
        assert extraction_requests, "expected at least one extraction call"

        for body in extraction_requests:
            content = body["messages"][0]["content"]
            # The report text is parsed directly.
            assert verification_text in content or "[web1]" in content
            # The raw tool-output reference block must no longer be appended.
            assert "=== Tool Outputs Reference ===" not in content


class TestCompactToolJson:
    """Tool outputs are serialised as compact JSON (no pretty-print indent)."""

    def test_results_payload_is_compact(self):
        output = ToolOutput(
            items=[{"title": "Example", "url": "https://example.com"}]
        )
        result = _format_for_model("search_web", output, {})

        # Compact separators: no key/value ": " spacing, no newline indentation.
        # (A literal ", " can legitimately appear inside string values, so we
        # only assert on the unambiguous structural separators.)
        assert '": ' not in result
        assert "\n" not in result
        # The compact form matches json.dumps with compact separators exactly.
        parsed = json.loads(result)
        assert result == json.dumps(parsed, separators=(",", ":"))
        assert parsed["results"][0]["id"] == "web1"

    def test_empty_payload_is_compact(self):
        output = ToolOutput(items=[], metadata={"message": "No results"})
        result = _format_for_model("search_screening_list", output, {})

        assert "\n" not in result
        assert '": ' not in result
        parsed = json.loads(result)
        assert result == json.dumps(parsed, separators=(",", ":"))
        assert parsed["id"] == "screen1"
