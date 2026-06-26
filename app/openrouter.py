"""Simplified OpenRouter client for KYC API."""

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from tavily import TavilyClient  # type: ignore[import-untyped]

from app.constants import (
    MAX_COMPLETION_TOKENS,
    SNIPPET_PREVIEW_LENGTH,
    TIMEOUT_LONG,
    TIMEOUT_MEDIUM,
)
from app.models import ToolResult
from app.tools.registry import ToolOutput, execute_tool, get_chat_tools

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# Tool prefix mapping for result IDs
TOOL_PREFIXES = {
    "search_web": "web",
    "search_screening_list": "screen",
    "search_epmc": "epmc",
    "get_orcid_profile": "orcid",
    "search_orcid_works": "orcworks",
}


@dataclass
class RawToolCall:
    """Represents a raw tool call with its result (internal use)."""

    tool_name: str
    arguments: dict[str, Any]
    output: ToolOutput
    model_output: str  # JSON string sent to model (with IDs)


def _format_for_model(
    tool_name: str, output: ToolOutput, counters: dict[str, int]
) -> str:
    """Assign per-result IDs and format output for model consumption."""
    prefix = TOOL_PREFIXES.get(tool_name, tool_name[:4])

    if not output.items:
        # No results case (e.g., screening with no matches, or errors)
        counters[prefix] = counters.get(prefix, 0) + 1
        return json.dumps(
            {
                "instruction": "Cite using [id] format (e.g., [screen1]).",
                "id": f"{prefix}{counters[prefix]}",
                **output.metadata,
            },
            indent=2,
        )

    # Assign per-result IDs
    annotated = []
    for item in output.items:
        counters[prefix] = counters.get(prefix, 0) + 1
        annotated.append({"id": f"{prefix}{counters[prefix]}", **item})

    return json.dumps(
        {
            "instruction": "Cite using [id] format (e.g., [web1], [epmc2]).",
            "results": annotated,
            **output.metadata,
        },
        indent=2,
    )


@dataclass
class CompletionResult:
    """Result from a completion with tools."""

    text: str
    tool_calls: list[RawToolCall]


def _build_query(tool_name: str, args: dict[str, Any]) -> str:
    """Build a human-readable query string from tool arguments."""
    if tool_name == "search_epmc":
        parts = []
        if args.get("author"):
            parts.append(args["author"])
        if args.get("affiliation"):
            parts.append(f"at {args['affiliation']}")
        if args.get("keyword"):
            parts.append(f"about {args['keyword']}")
        return " ".join(parts) if parts else "EPMC search"

    if tool_name == "search_web":
        return args.get("query", "web search")

    if tool_name == "search_screening_list":
        queries = args.get("queries", [])
        return ", ".join(queries) if queries else "screening list search"

    if tool_name == "get_orcid_profile":
        return args.get("orcid_id", "ORCID profile")

    if tool_name == "search_orcid_works":
        return args.get("orcid_id", "ORCID works")

    return str(args)


def _parse_year(value: str | int | None) -> int | None:
    """Parse a year from a string or int, returning None if invalid."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).split("-")[0])
    except (ValueError, TypeError, IndexError):
        return None


def _extract_web_fields(item: dict) -> dict[str, Any]:
    """Extract fields for search_web results."""
    content = item.get("content", "")
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "snippet": content[:SNIPPET_PREVIEW_LENGTH] if content else None,
    }


def _extract_epmc_fields(item: dict) -> dict[str, Any]:
    """Extract fields for search_epmc results."""
    doi = item.get("doi", "")
    authors = item.get("authors", [])
    author_names = [a.get("name", "") for a in authors] if isinstance(authors, list) else None
    return {
        "title": item.get("title", ""),
        "url": f"https://doi.org/{doi}" if doi else "",
        "authors": author_names if author_names else None,
        "year": _parse_year(item.get("pub_year")),
    }


def _extract_screening_fields(item: dict) -> dict[str, Any]:
    """Extract fields for search_screening_list results."""
    return {
        "title": item.get("name", ""),
        "url": "",
        "programs": item.get("programs"),
    }


def _extract_orcid_profile_fields(item: dict) -> dict[str, Any]:
    """Extract fields for get_orcid_profile results."""
    name = (
        item.get("credit_name")
        or f"{item.get('given_name', '')} {item.get('family_name', '')}".strip()
        or "Unknown"
    )
    return {
        "title": name,
        "url": item.get("orcid_url", ""),
    }


def _extract_orcid_works_fields(item: dict) -> dict[str, Any]:
    """Extract fields for search_orcid_works results."""
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "year": _parse_year(item.get("publication_date")),
    }


def _extract_generic_fields(item: dict) -> dict[str, Any]:
    """Extract fields for unknown tool types (fallback)."""
    return {
        "title": item.get("title", str(item)),
        "url": item.get("url", ""),
    }


# Tool-specific field extractors
_TOOL_FIELD_EXTRACTORS: dict[str, Any] = {
    "search_web": _extract_web_fields,
    "search_epmc": _extract_epmc_fields,
    "search_screening_list": _extract_screening_fields,
    "get_orcid_profile": _extract_orcid_profile_fields,
    "search_orcid_works": _extract_orcid_works_fields,
}


def normalize_tool_calls(raw_calls: list[RawToolCall]) -> list[ToolResult]:
    """Convert raw tool calls to flat list of results for audit section.

    Each result includes the tool name and query for easy iteration.
    IDs are already assigned in model_output, so we just extract them.
    """
    results: list[ToolResult] = []

    for tc in raw_calls:
        try:
            data = json.loads(tc.model_output)
        except json.JSONDecodeError:
            data = {}

        query = _build_query(tc.tool_name, tc.arguments)
        items = data.get("results", [])
        extractor = _TOOL_FIELD_EXTRACTORS.get(tc.tool_name, _extract_generic_fields)

        # Handle no-results case (single item with id at top level)
        if not items and data.get("id"):
            results.append(
                ToolResult(
                    tool=tc.tool_name,
                    query=query,
                    id=data["id"],
                    title=data.get("message", "No results"),
                    url="",
                )
            )
        else:
            for item in items:
                fields = extractor(item)
                results.append(
                    ToolResult(
                        tool=tc.tool_name,
                        query=query,
                        id=item.get("id", ""),
                        **fields,
                    )
                )

    return results


class OpenRouterClient:
    """Client for OpenRouter API with tool calling and structured output support."""

    def __init__(self) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")

        tavily_key = os.environ.get("TAVILY_API_KEY")
        if not tavily_key:
            raise ValueError("TAVILY_API_KEY environment variable is required")

        self.tavily_client = TavilyClient(tavily_key)
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", "https://cliver.example.com"),
            "X-Title": os.environ.get("OPENROUTER_TITLE", "Cliver KYC API"),
        }

    async def complete_with_tools(
        self,
        prompt: str,
        model: str = "google/gemini-3-flash-preview",
        tool_names: list[str] | None = None,
        max_iterations: int = 10,
        id_counters: dict[str, int] | None = None,
    ) -> CompletionResult:
        """
        Run a prompt with tool calling loop.

        Args:
            prompt: The user prompt to send.
            model: OpenRouter model name.
            tool_names: List of tool names to enable, or None for all.
            max_iterations: Maximum tool calling iterations.
            id_counters: Persistent ID counters across multiple calls.

        Returns:
            CompletionResult with final text and all tool calls made.
        """
        tools = get_chat_tools(tool_names)
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        tool_calls: list[RawToolCall] = []
        if id_counters is None:
            id_counters = {}  # Per-result ID counters

        message: dict[str, Any] = {}
        loop = asyncio.get_running_loop()

        for _ in range(max_iterations):
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": MAX_COMPLETION_TOKENS,
            }

            async with httpx.AsyncClient(timeout=TIMEOUT_LONG) as client:
                response = await client.post(
                    OPENROUTER_CHAT_URL,
                    headers=self.headers,
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()

            message = data["choices"][0]["message"]
            requested_calls = message.get("tool_calls") or []

            if not requested_calls:
                break

            # Echo the assistant's tool-call turn back into the conversation.
            messages.append(message)

            # Parse each requested call, then run the (blocking) tool
            # implementations concurrently in the default executor.
            parsed_calls = []
            for tc in requested_calls:
                func = tc.get("function", {})
                func_name = func.get("name", "")
                call_id = tc.get("id", "")
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                parsed_calls.append((func_name, call_id, args))

            outputs = await asyncio.gather(
                *[
                    loop.run_in_executor(
                        None, execute_tool, func_name, args, self.tavily_client
                    )
                    for func_name, _call_id, args in parsed_calls
                ]
            )

            # Format and record results in the original call order so that
            # per-result IDs and message ordering stay deterministic.
            for (func_name, call_id, args), output in zip(parsed_calls, outputs):
                model_output = _format_for_model(func_name, output, id_counters)

                tool_calls.append(
                    RawToolCall(
                        tool_name=func_name,
                        arguments=args,
                        output=output,
                        model_output=model_output,
                    )
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": model_output,
                    }
                )

        final_text = self._extract_text(message)
        return CompletionResult(text=final_text, tool_calls=tool_calls)

    def extract_structured(
        self,
        text: str,
        extraction_prompt: str,
        response_format: dict[str, Any],
        model: str = "google/gemini-2.5-flash",
    ) -> dict[str, Any]:
        """
        Extract structured data from text using json_schema response_format.

        Args:
            text: The text to extract data from.
            extraction_prompt: Instructions for extraction.
            response_format: OpenRouter json_schema response format.
            model: Model to use for extraction.

        Returns:
            Parsed JSON response matching the schema.
        """
        with httpx.Client(timeout=TIMEOUT_MEDIUM) as client:
            response = client.post(
                OPENROUTER_CHAT_URL,
                headers=self.headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": f"{extraction_prompt}\n\n{text}"}
                    ],
                    "response_format": response_format,
                },
            )
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    async def extract_structured_async(
        self,
        text: str,
        extraction_prompt: str,
        response_format: dict[str, Any],
        model: str = "google/gemini-2.5-flash",
    ) -> dict[str, Any]:
        """Async version of extract_structured."""
        async with httpx.AsyncClient(timeout=TIMEOUT_MEDIUM) as client:
            response = await client.post(
                OPENROUTER_CHAT_URL,
                headers=self.headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": f"{extraction_prompt}\n\n{text}"}
                    ],
                    "response_format": response_format,
                },
            )
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    async def generate_text_async(
        self,
        prompt: str,
        model: str = "google/gemini-2.5-flash",
    ) -> str:
        """Generate text response (no structured output)."""
        async with httpx.AsyncClient(timeout=TIMEOUT_MEDIUM) as client:
            response = await client.post(
                OPENROUTER_CHAT_URL,
                headers=self.headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _extract_text(self, message: dict[str, Any]) -> str:
        """Extract text content from a Chat Completions message."""
        content = message.get("content")
        if isinstance(content, str):
            return content

        # Some providers return content as a list of parts.
        if isinstance(content, list):
            text_types = ("text", "output_text")
            return "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in text_types
            )

        return ""
