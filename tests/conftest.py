"""Shared test fixtures for KYC API tests."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Load mock response fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture
def mock_env():
    """Mock environment variables for testing."""
    env_vars = {
        "OPENROUTER_API_KEY": "test-openrouter-key",
        "TAVILY_API_KEY": "test-tavily-key",
        "SCREENING_LIST_API_KEY": "test-screening-key",
        "CLIVER_API_KEY": "test-api-key",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest.fixture
def test_client(mock_env):
    """FastAPI test client with mocked environment."""
    from app.main import app

    return TestClient(app)


@pytest.fixture
def mock_tavily():
    """Mock TavilyClient for web search.

    This patches TavilyClient at the location where it's used (app.openrouter)
    so that when OpenRouterClient is instantiated, it gets the mock.
    """
    mock_client = MagicMock()
    mock_client.search.return_value = {
        "results": [
            {
                "url": "https://biology.mit.edu/staff/jane-smith",
                "title": "Jane Smith - MIT Biology",
                "content": "Dr. Jane Smith is an Associate Professor in the Department of Biology at MIT, specializing in molecular biology and virology research.",
            }
        ]
    }

    with patch("app.openrouter.TavilyClient", return_value=mock_client):
        yield mock_client


@pytest.fixture
def sample_kyc_request():
    """Standard test customer data."""
    return {
        "customer_name": "Jane Smith",
        "email": "jsmith@mit.edu",
        "institution": "MIT",
        "order_description": "SARS-CoV-2 spike protein for vaccine research",
    }


@pytest.fixture
def sample_kyc_request_minimal():
    """Minimal valid request (no order_description)."""
    return {
        "customer_name": "Test User",
        "email": "test@example.edu",
        "institution": "Example University",
    }


@pytest.fixture
def mock_openrouter_responses():
    """Load mock OpenRouter responses from fixture."""
    return load_fixture("openrouter_responses.json")


@pytest.fixture
def mock_tool_responses():
    """Load mock tool responses from fixture."""
    return load_fixture("tool_responses.json")


# Mock response builders for pytest-httpx
def build_openrouter_responses_reply(text: str, tool_calls: list | None = None):
    """Build a mock OpenRouter /responses API reply."""
    content = [{"type": "output_text", "text": text}]

    output = []
    if tool_calls:
        output.extend(tool_calls)

    output.append({"type": "message", "content": content})

    return {"output": output}


def build_openrouter_chat_reply(content: str):
    """Build a mock OpenRouter /chat/completions API reply."""
    return {"choices": [{"message": {"content": content}}]}


def build_verification_evidence_response():
    """Build a mock verification evidence extraction response."""
    return {
        "rows": [
            {
                "criterion": "Customer Institutional Affiliation",
                "sources": ["web1"],
                "evidence_summary": "Jane Smith confirmed as Associate Professor at MIT Biology department.",
            },
            {
                "criterion": "Institution Type and Biomedical Focus",
                "sources": ["web1"],
                "evidence_summary": "MIT is a major research university with established biomedical research programs.",
            },
            {
                "criterion": "Email Domain Verification",
                "sources": ["web1"],
                "evidence_summary": "Email domain mit.edu matches the stated institution.",
            },
            {
                "criterion": "Sanctions and Export Control Screening",
                "sources": ["screen1"],
                "evidence_summary": "No matches found in consolidated screening list.",
            },
        ]
    }


def build_verification_determination_response():
    """Build a mock verification determination extraction response."""
    return {
        "rows": [
            {"criterion": "Customer Institutional Affiliation", "flag": "NO FLAG"},
            {"criterion": "Institution Type and Biomedical Focus", "flag": "NO FLAG"},
            {"criterion": "Email Domain Verification", "flag": "NO FLAG"},
            {"criterion": "Sanctions and Export Control Screening", "flag": "NO FLAG"},
        ]
    }


def build_background_work_response():
    """Build a mock background work extraction response."""
    return {
        "rows": [
            {
                "relevance_level": 5,
                "organism": "SARS-CoV-2",
                "sources": ["epmc1"],
                "work_summary": "Published research on coronavirus spike protein structure.",
            }
        ]
    }
