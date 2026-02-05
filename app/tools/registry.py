"""Simplified tool registry for KYC API."""

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml
from tavily import TavilyClient  # type: ignore[import-untyped]

_CACHE: dict[str, Any] = {}


def http_error_output(
    error: httpx.HTTPStatusError | httpx.RequestError,
    context: dict[str, Any] | None = None,
    not_found_message: str | None = None,
) -> "ToolOutput":
    """
    Convert an HTTP error to a ToolOutput with error metadata.

    Args:
        error: The httpx error to convert.
        context: Additional metadata to include in the error output.
        not_found_message: Custom message for 404 errors (if None, uses default).

    Returns:
        ToolOutput with error=True and error message.
    """
    error_context = context or {}

    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code == 404 and not_found_message:
            message = not_found_message
        else:
            message = f"API error: {error.response.status_code} - {error!s}"
    else:
        message = f"Request failed: {error!s}"

    return ToolOutput(
        items=[],
        metadata={
            "error": True,
            "message": message,
            **error_context,
        },
    )


@dataclass
class ToolOutput:
    """Standard return format for all tools."""

    items: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


def _load_definitions() -> dict[str, Any]:
    """Load and cache tool definitions from YAML."""
    if "definitions" not in _CACHE:
        path = Path(__file__).parent / "definitions.yaml"
        with open(path, encoding="utf-8") as f:
            _CACHE["definitions"] = yaml.safe_load(f)
    return _CACHE["definitions"]


def _build_parameters(params: dict[str, Any]) -> dict[str, Any]:
    """Convert YAML parameter definitions to JSON Schema format."""
    properties = {}
    required = []

    for name, spec in params.items():
        prop: dict[str, Any] = {"type": spec["type"]}

        if "description" in spec:
            prop["description"] = spec["description"].strip()
        if "enum" in spec:
            prop["enum"] = spec["enum"]
        if "items" in spec:
            prop["items"] = spec["items"]

        properties[name] = prop

        if spec.get("required", False):
            required.append(name)

    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required

    return result


def get_responses_tools(tool_names: list[str] | None = None) -> list[dict[str, Any]]:
    """Get tools in OpenRouter Responses API format."""
    tools_def = _load_definitions().get("tools", {})
    tools = []

    for name, spec in tools_def.items():
        if tool_names and name not in tool_names:
            continue
        tools.append(
            {
                "type": "function",
                "name": name,
                "description": spec["description"].strip(),
                "parameters": _build_parameters(spec.get("parameters", {})),
            }
        )

    return tools


def get_implementation(tool_name: str) -> Callable[..., Any]:
    """Get the implementation function for a tool."""
    tools_def = _load_definitions().get("tools", {})

    if tool_name not in tools_def:
        raise ValueError(f"Unknown tool: {tool_name}")

    impl_path = tools_def[tool_name]["implementation"]
    module_path, func_name = impl_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    tavily_client: TavilyClient,
) -> ToolOutput:
    """Execute a tool and return structured ToolOutput."""
    impl = get_implementation(tool_name)

    if tool_name == "search_web":
        return impl(arguments.get("query", ""), tavily_client=tavily_client)

    # Filter arguments to only include non-empty values for optional params
    filtered_args = {k: v for k, v in arguments.items() if v not in (None, "", [])}
    return impl(**filtered_args)
