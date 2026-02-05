"""
ORCID Profile Tool Implementation.

Fetches researcher profile information from ORCID.
"""

from typing import Any

import httpx

from app.constants import TIMEOUT_SHORT
from app.tools.registry import ToolOutput, http_error_output

# API Configuration
ORCID_BASE_URL = "https://pub.orcid.org/v3.0"
ORCID_HEADERS = {"Accept": "application/vnd.orcid+json"}


def _safe_get(data: dict | None, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts, returning default if any key is missing."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _extract_date(date_obj: dict | None) -> str | None:
    """Extract a readable date string from ORCID date format."""
    if not date_obj:
        return None
    
    year_obj = date_obj.get("year")
    month_obj = date_obj.get("month")
    day_obj = date_obj.get("day")
    
    year = year_obj.get("value") if year_obj else None
    month = month_obj.get("value") if month_obj else None
    day = day_obj.get("value") if day_obj else None
    
    parts = [p for p in [year, month, day] if p]
    return "-".join(parts) if parts else None


def _fetch_orcid_endpoint(orcid_id: str, endpoint: str) -> dict[str, Any]:
    """Fetch data from a specific ORCID API endpoint."""
    url = f"{ORCID_BASE_URL}/{orcid_id}/{endpoint}"
    response = httpx.get(url, headers=ORCID_HEADERS, timeout=TIMEOUT_SHORT)
    response.raise_for_status()
    return response.json()


def _parse_person(data: dict) -> dict:
    """Parse person data from ORCID API response."""
    result = {
        "given_name": _safe_get(data, "name", "given-names", "value"),
        "family_name": _safe_get(data, "name", "family-name", "value"),
        "credit_name": _safe_get(data, "name", "credit-name", "value"),
        "biography": _safe_get(data, "biography", "content"),
    }

    keywords = _safe_get(data, "keywords", "keyword", default=[]) or []
    result["keywords"] = [kw.get("content") for kw in keywords if kw.get("content")]

    emails = _safe_get(data, "emails", "email", default=[]) or []
    result["emails"] = [e.get("email") for e in emails if e.get("email")]

    ext_ids = _safe_get(data, "external-identifiers", "external-identifier", default=[]) or []
    result["external_ids"] = [
        {
            "type": eid.get("external-id-type"),
            "value": eid.get("external-id-value"),
            "url": _safe_get(eid, "external-id-url", "value"),
        }
        for eid in ext_ids
    ]

    urls = _safe_get(data, "researcher-urls", "researcher-url", default=[]) or []
    result["urls"] = [
        {
            "name": u.get("url-name"),
            "url": _safe_get(u, "url", "value"),
        }
        for u in urls
    ]

    return result


def _parse_affiliations(data: dict, affiliation_type: str) -> list[dict]:
    """Parse education or employment affiliations from ORCID API response."""
    affiliations = []
    
    for group in data.get("affiliation-group", []) or []:
        for summary in group.get("summaries", []) or []:
            summary_key = f"{affiliation_type}-summary"
            aff_data = summary.get(summary_key, {})
            
            if not aff_data:
                continue
                
            org = aff_data.get("organization", {}) or {}
            org_address = org.get("address", {}) or {}
            
            affiliations.append({
                "organization": org.get("name"),
                "department": aff_data.get("department-name"),
                "role": aff_data.get("role-title"),
                "city": org_address.get("city"),
                "country": org_address.get("country"),
                "start_date": _extract_date(aff_data.get("start-date")),
                "end_date": _extract_date(aff_data.get("end-date")),
            })
    
    return affiliations


def _parse_works(data: dict) -> list[dict]:
    """Parse works/publications from ORCID API response."""
    works = []

    for group in data.get("group", []) or []:
        work_summaries = group.get("work-summary", []) or []
        if not work_summaries:
            continue

        work = work_summaries[0]
        ext_id_list = _safe_get(group, "external-ids", "external-id", default=[]) or []

        works.append({
            "title": _safe_get(work, "title", "title", "value"),
            "type": work.get("type"),
            "publication_date": _extract_date(work.get("publication-date")),
            "journal": _safe_get(work, "journal-title", "value"),
            "url": _safe_get(work, "url", "value"),
            "identifiers": [
                {"type": eid.get("external-id-type"), "value": eid.get("external-id-value")}
                for eid in ext_id_list
            ],
        })

    return works


MAX_WORKS_IN_PROFILE = 5


def get_orcid_profile(orcid_id: str) -> ToolOutput:
    """
    Fetch complete ORCID profile for a researcher.

    Args:
        orcid_id: The ORCID identifier (e.g., '0000-0002-1825-0097').

    Returns:
        ToolOutput with profile information (single item).
    """
    try:
        person_data = _fetch_orcid_endpoint(orcid_id, "person")
        works_data = _fetch_orcid_endpoint(orcid_id, "works")
        education_data = _fetch_orcid_endpoint(orcid_id, "educations")
        employment_data = _fetch_orcid_endpoint(orcid_id, "employments")

        all_works = _parse_works(works_data)
        total_works = len(all_works)

        profile = {
            "orcid_id": orcid_id,
            "orcid_url": f"https://orcid.org/{orcid_id}",
            **_parse_person(person_data),
            "education": _parse_affiliations(education_data, "education"),
            "employment": _parse_affiliations(employment_data, "employment"),
            "total_works_count": total_works,
            "works": all_works[:MAX_WORKS_IN_PROFILE],
        }

        if total_works > MAX_WORKS_IN_PROFILE:
            profile["works_note"] = (
                f"Showing {MAX_WORKS_IN_PROFILE} of {total_works} works. "
                f"Use search_orcid_works to search all publications by keyword."
            )

        return ToolOutput(items=[profile])

    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        return http_error_output(e, not_found_message=f"ORCID ID not found: {orcid_id}")


def search_orcid_works(orcid_id: str, keywords: list[str]) -> ToolOutput:
    """
    Search publications for a researcher by keywords.

    Args:
        orcid_id: The ORCID identifier (e.g., '0000-0002-1825-0097').
        keywords: List of keywords to search for in publication metadata.

    Returns:
        ToolOutput with matching publications.
    """
    try:
        works_data = _fetch_orcid_endpoint(orcid_id, "works")
        all_works = _parse_works(works_data)

        # Normalize keywords for case-insensitive matching
        keywords_lower = [kw.lower() for kw in keywords]

        matching_works = []
        for work in all_works:
            # Build searchable text from available metadata
            searchable_parts = []
            if work.get("title"):
                searchable_parts.append(work["title"])
            if work.get("journal"):
                searchable_parts.append(work["journal"])
            if work.get("type"):
                searchable_parts.append(work["type"])

            searchable_text = " ".join(searchable_parts).lower()

            # Check if any keyword matches
            if any(kw in searchable_text for kw in keywords_lower):
                matching_works.append(work)

        return ToolOutput(
            items=matching_works,
            metadata={
                "orcid_id": orcid_id,
                "keywords": keywords,
                "total_works": len(all_works),
            },
        )

    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        return http_error_output(e, not_found_message=f"ORCID ID not found: {orcid_id}")