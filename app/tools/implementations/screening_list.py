"""
Consolidated Screening List Tool Implementation.

Searches the US Government's Consolidated Screening List for sanctioned
entities, denied parties, and other restricted persons/organizations.
"""

import os

import httpx

from app.tools.registry import ToolOutput

# API Configuration
SCREENING_LIST_BASE_URL = "https://data.trade.gov/consolidated_screening_list/v1"
TIMEOUT = 30


def _get_api_key() -> str:
    """Get the API key from environment variable."""
    api_key = os.environ.get("SCREENING_LIST_API_KEY")
    if not api_key:
        raise ValueError("SCREENING_LIST_API_KEY environment variable is required")
    return api_key


def _parse_entity(entity: dict) -> dict:
    """Parse a screening entity from the API response."""
    programs_raw = entity.get("programs")
    if isinstance(programs_raw, str):
        programs = [programs_raw] if programs_raw else []
    elif isinstance(programs_raw, list):
        programs = programs_raw
    else:
        programs = []

    return {
        "name": entity.get("name"),
        "programs": programs,
        "source": entity.get("source"),
    }


def _search_single(client: httpx.Client, api_key: str, query: str) -> list[dict]:
    """Execute a single search query."""
    params = {
        "subscription-key": api_key,
        "name": query,
        "fuzzy_name": "true",
    }

    response = client.get(
        f"{SCREENING_LIST_BASE_URL}/search",
        params=params,
        headers={"Accept": "application/json", "User-Agent": "KYC-API/1.0"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    data = response.json()
    return data.get("results") or []


def search_screening_list(queries: list[str]) -> ToolOutput:
    """
    Search the Consolidated Screening List with multiple keyword combinations.

    Args:
        queries: List of keyword combinations to search for.

    Returns:
        ToolOutput with matching entities.
    """
    if not queries:
        return ToolOutput(
            items=[],
            metadata={
                "status": "no_queries",
                "message": "No search queries provided.",
                "queries_searched": queries,
            },
        )

    try:
        api_key = _get_api_key()

        with httpx.Client() as client:
            all_results = []
            for query in queries:
                try:
                    results = _search_single(client, api_key, query)
                    all_results.extend(results)
                except httpx.HTTPStatusError:
                    continue
                except httpx.RequestError:
                    continue

        # Deduplicate results by name
        seen_names: set[str] = set()
        unique_results: list[dict] = []

        for entity in all_results:
            name = entity.get("name")
            if name and name not in seen_names:
                seen_names.add(name)
                unique_results.append(_parse_entity(entity))

        if not unique_results:
            return ToolOutput(
                items=[],
                metadata={
                    "status": "no_matches",
                    "message": "No matches found in the US Consolidated Screening List.",
                    "queries_searched": queries,
                },
            )

        return ToolOutput(
            items=unique_results,
            metadata={
                "status": "matches_found",
                "total": len(unique_results),
                "queries_searched": queries,
            },
        )

    except ValueError as e:
        return ToolOutput(
            items=[],
            metadata={"error": True, "message": str(e), "queries_searched": queries},
        )
    except httpx.HTTPStatusError as e:
        return ToolOutput(
            items=[],
            metadata={
                "error": True,
                "message": f"API error: {e.response.status_code}",
                "queries_searched": queries,
            },
        )
    except httpx.RequestError as e:
        return ToolOutput(
            items=[],
            metadata={
                "error": True,
                "message": f"Request failed: {str(e)}",
                "queries_searched": queries,
            },
        )
