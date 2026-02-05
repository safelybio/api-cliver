"""Simplified OpenRouter client for KYC API."""

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from tavily import TavilyClient  # type: ignore[import-untyped]

from app.constants import SNIPPET_PREVIEW_LENGTH, TIMEOUT_LONG, TIMEOUT_MEDIUM
from app.models import ToolResult
from app.tools.registry import ToolOutput, execute_tool, get_responses_tools

OPENROUTER_RESPONSES_URL = "https://openrouter.ai/api/v1/responses"
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

    def complete_with_tools(
        self,
        prompt: str,
        model: str = "google/gemini-2.5-pro-preview",
        tool_names: list[str] | None = None,
        max_iterations: int = 20,
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
        tools = get_responses_tools(tool_names)
        input_items: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        tool_calls: list[RawToolCall] = []
        if id_counters is None:
            id_counters = {}  # Per-result ID counters

        output_items: list[dict[str, Any]] = []
        data: dict[str, Any] = {}

        for _ in range(max_iterations):
            payload: dict[str, Any] = {
                "model": model,
                "input": input_items,
                "tools": tools,
                "tool_choice": "auto",
            }

            with httpx.Client(timeout=TIMEOUT_LONG) as client:
                response = client.post(
                    OPENROUTER_RESPONSES_URL,
                    headers=self.headers,
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()

            output_items = data.get("output", [])
            function_calls = [
                item for item in output_items if item.get("type") == "function_call"
            ]

            if not function_calls:
                break

            for fc in function_calls:
                func_name = fc.get("name", "")
                call_id = fc.get("call_id", "")

                try:
                    args = json.loads(fc.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                # Execute tool and get structured output
                output = execute_tool(func_name, args, self.tavily_client)

                # Format for model with per-result IDs
                model_output = _format_for_model(func_name, output, id_counters)

                # Store tool call
                tool_calls.append(
                    RawToolCall(
                        tool_name=func_name,
                        arguments=args,
                        output=output,
                        model_output=model_output,
                    )
                )

                # Add to conversation for next iteration
                input_items.append(
                    {
                        "type": "function_call",
                        "id": fc.get("id", call_id),
                        "call_id": call_id,
                        "name": func_name,
                        "arguments": fc.get("arguments", "{}"),
                        "status": "completed",
                    }
                )
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": model_output,
                    }
                )

        final_text = self._extract_text(output_items, data)
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

    def _extract_text(
        self, output_items: list[dict[str, Any]], data: dict[str, Any]
    ) -> str:
        """Extract text content from response output items."""
        for item in output_items:
            if item.get("type") == "message":
                content_items = item.get("content", [])
                text_parts = []
                for content in content_items:
                    if content.get("type") == "output_text":
                        text_parts.append(content.get("text", ""))
                return "".join(text_parts)

        # Fallback to top-level output_text
        return data.get("output_text", "")
