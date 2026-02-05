"""
EPMC (Europe PubMed Central) Search Tool Implementation.

Searches for scientific articles in Europe PubMed Central.
"""

import re
from typing import Literal

import httpx

from app.constants import TIMEOUT_SHORT
from app.tools.registry import ToolOutput, http_error_output

# API Configuration
EPMC_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
EPMC_HEADERS = {"Accept": "application/json"}


def _clean_field(value: str) -> str:
    """Clean a field value for use in a search query."""
    return re.sub(r'["\',.]', '', value)


def _build_query(
    orcid: str | None = None,
    author: str | None = None,
    affiliation: str | None = None,
    topic: str | None = None
) -> str:
    """Build EPMC search query from parameters."""
    query_parts = []
    
    if orcid:
        query_parts.append(f'AUTHORID:("{_clean_field(orcid)}")')
    
    if author:
        query_parts.append(f'AUTHOR:("{_clean_field(author)}")')
    
    if affiliation:
        query_parts.append(f'AFF:({_clean_field(affiliation)})')
    
    if topic:
        query_parts.append(f'({_clean_field(topic)})')
    
    return " AND ".join(query_parts) if query_parts else "*"


def _author_name_matches(author_search: str | None, author_data: dict) -> bool:
    """Check if any word in author_search matches the author's names."""
    if not author_search:
        return False
    
    first_name = (author_data.get("firstName") or "").lower().strip()
    last_name = (author_data.get("lastName") or "").lower().strip()
    full_name = (author_data.get("fullName") or "").lower().strip()
    
    search_words = [w.lower().strip() for w in author_search.split() if w.strip()]
    
    for word in search_words:
        if word and (word == first_name or word == last_name or word == full_name):
            return True
    
    return False


def _author_orcid_matches(orcid_search: str | None, author_data: dict) -> bool:
    """Check if the author has a matching ORCID."""
    if not orcid_search:
        return False
    
    author_id = author_data.get("authorId")
    if author_id and author_id.get("type") == "ORCID":
        return author_id.get("value") == orcid_search
    
    return False


def _get_author_affiliations(author_data: dict) -> list[str]:
    """Extract affiliations from author data."""
    aff_details = author_data.get("authorAffiliationDetailsList", {}) or {}
    affiliations = aff_details.get("authorAffiliation", []) or []
    return [aff.get("affiliation") for aff in affiliations if aff.get("affiliation")]


def _parse_article_lite(
    article: dict,
    orcid_search: str | None = None,
    author_search: str | None = None
) -> dict:
    """Parse article in lite mode - title, author string, and matching authors only."""
    author_list = article.get("authorList", {}) or {}
    authors = author_list.get("author", []) or []
    
    matching_authors = []
    for auth in authors:
        orcid_match = _author_orcid_matches(orcid_search, auth)
        name_match = _author_name_matches(author_search, auth)
        
        if orcid_match or name_match:
            author_info = {
                "first_name": auth.get("firstName"),
                "last_name": auth.get("lastName"),
                "affiliations": _get_author_affiliations(auth)
            }
            author_id = auth.get("authorId")
            if author_id and author_id.get("type") == "ORCID":
                author_info["orcid"] = author_id.get("value")
            
            matching_authors.append(author_info)
    
    return {
        "title": article.get("title"),
        "author_string": article.get("authorString"),
        "matching_authors": matching_authors if matching_authors else "Unclear match"
    }


def _parse_article_full(article: dict) -> dict:
    """Parse article in full mode - complete metadata."""
    author_list = article.get("authorList", {}) or {}
    authors = author_list.get("author", []) or []
    
    parsed_authors = []
    for auth in authors:
        author_info = {
            "name": auth.get("fullName"),
            "first_name": auth.get("firstName"),
            "last_name": auth.get("lastName"),
        }
        
        author_id = auth.get("authorId")
        if author_id and author_id.get("type") == "ORCID":
            author_info["orcid"] = author_id.get("value")
        
        author_info["affiliations"] = _get_author_affiliations(auth)
        parsed_authors.append(author_info)
    
    journal_info = article.get("journalInfo", {}) or {}
    journal = journal_info.get("journal", {}) or {}
    
    return {
        "doi": article.get("doi"),
        "title": article.get("title"),
        "authors": parsed_authors,
        "author_string": article.get("authorString"),
        "journal": journal.get("title"),
        "pub_year": article.get("pubYear"),
        "abstract": article.get("abstractText"),
        "cited_by_count": article.get("citedByCount")
    }


def search_epmc(
    orcid: str | None = None,
    author: str | None = None,
    affiliation: str | None = None,
    topic: str | None = None,
    mode: Literal["lite", "full"] = "lite",
) -> ToolOutput:
    """
    Search Europe PubMed Central for scientific articles.

    Args:
        orcid: Author's ORCID identifier.
        author: Author name to search for.
        affiliation: Institution/affiliation to search for.
        topic: Topic or keywords to search for.
        mode: 'lite' (25 results, minimal) or 'full' (5 results, complete).

    Returns:
        ToolOutput with search results.
    """
    if not any([orcid, author, affiliation, topic]):
        return ToolOutput(
            items=[],
            metadata={
                "error": True,
                "message": "At least one search parameter is required",
            },
        )

    max_results = 25 if mode == "lite" else 5
    query = _build_query(orcid=orcid, author=author, affiliation=affiliation, topic=topic)

    params: dict[str, str | int] = {
        "query": query,
        "resultType": "core",
        "pageSize": max_results,
        "format": "json",
    }

    try:
        response = httpx.get(
            f"{EPMC_BASE_URL}/search",
            params=params,
            headers=EPMC_HEADERS,
            timeout=TIMEOUT_SHORT,
        )
        response.raise_for_status()
        data = response.json()

        hit_count = data.get("hitCount", 0)
        result_list = data.get("resultList", {}) or {}
        results = result_list.get("result", []) or []

        if mode == "lite":
            parsed_results = [
                _parse_article_lite(article, orcid_search=orcid, author_search=author)
                for article in results
            ]
        else:
            parsed_results = [_parse_article_full(article) for article in results]

        return ToolOutput(
            items=parsed_results,
            metadata={
                "query": query,
                "mode": mode,
                "hit_count": hit_count,
            },
        )

    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        return http_error_output(e, {"query": query})