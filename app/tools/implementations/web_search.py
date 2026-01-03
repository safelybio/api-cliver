"""Web Search Tool Implementation using Tavily API."""

from tavily import TavilyClient  # type: ignore[import-untyped]
from tavily.errors import BadRequestError  # type: ignore[import-untyped]

from app.tools.registry import ToolOutput


def search_web(query: str, tavily_client: TavilyClient) -> ToolOutput:
    """
    Search the web using Tavily API.

    Args:
        query: The search query string.
        tavily_client: Initialized TavilyClient instance.

    Returns:
        ToolOutput with search results.
    """
    try:
        response = tavily_client.search(
            query=query,
            search_depth="advanced",
            max_results=10,
            chunks_per_source=5,
        )
    except BadRequestError as e:
        return ToolOutput(items=[], metadata={"error": str(e)})
    except Exception as e:
        return ToolOutput(items=[], metadata={"error": f"Search failed: {str(e)}"})

    results = []
    for item in response.get("results", []):
        if item.get("url"):
            results.append({
                "url": item.get("url"),
                "title": item.get("title", ""),
                "content": item.get("content", ""),
            })

    return ToolOutput(items=results)