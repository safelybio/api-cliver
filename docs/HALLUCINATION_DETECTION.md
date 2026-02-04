# Hallucination Detection Issues

This document describes reliability issues observed in API responses where the AI generates evidence or conclusions that don't match the actual tool outputs.

---

## Observed Issues

### Issue 1: Fabricated Source Citations

**Problem:** The AI cites source IDs (e.g., `[web1]`, `[web2]`, `[web3]`) that don't exist in the tool call results.

**Example from `tests/failure_case_0.txt`:**
- Tool calls returned `result_count: 0` for all three web searches
- AI cited `[web1]`, `[web2]`, `[web3]` with detailed fabricated evidence:
  - "A 2022 peer-reviewed article in Nature Scientific Reports..."
  - "A verified Google Scholar profile..."
  - "Research/professional profiles (ScienceHR)..."

**Deterministic Check:**
```python
def validate_source_citations(response: KYCResponse) -> list[str]:
    """
    Extract all citation IDs from checks and verify they exist in tool_calls.
    Returns list of warnings for invalid citations.
    """
    import re

    # Build set of valid source IDs from tool calls
    valid_ids = set()
    for tool_call in response.audit.tool_calls:
        for result in tool_call.results:
            valid_ids.add(result.id)

    warnings = []

    # Check each criterion's sources
    for check in response.checks:
        for source_id in check.sources:
            if source_id not in valid_ids:
                warnings.append(
                    f"Citation '{source_id}' in '{check.criterion}' not found in tool results"
                )

    # Also scan evidence text for [id] patterns
    for check in response.checks:
        cited_ids = re.findall(r'\[(\w+\d+)\]', check.evidence)
        for cited_id in cited_ids:
            if cited_id not in valid_ids:
                warnings.append(
                    f"Inline citation '[{cited_id}]' in evidence not found in tool results"
                )

    return warnings
```

---

### Issue 2: Empty Search Results Treated as Positive Evidence

**Problem:** When web searches return zero results, the AI should report "no evidence found" rather than fabricating findings.

**Example:**
- `search_web` returned `{"result_count": 0, "results": []}`
- AI wrote: "A 2022 peer-reviewed article in Nature Scientific Reports lists..."

**Deterministic Check:**
```python
def validate_evidence_against_results(response: KYCResponse) -> list[str]:
    """
    Check that criteria with cited sources actually have results from those tools.
    Returns list of warnings.
    """
    warnings = []

    # Map tool call IDs to their result counts
    tool_results = {}
    for tool_call in response.audit.tool_calls:
        tool_results[tool_call.tool] = tool_call.result_count

    for check in response.checks:
        if check.status == "NO FLAG" and check.sources:
            # Check if cited sources have actual results
            web_sources = [s for s in check.sources if s.startswith("web")]
            if web_sources and tool_results.get("search_web", 0) == 0:
                warnings.append(
                    f"'{check.criterion}' cites web sources but all web searches returned 0 results"
                )

    return warnings
```

---

### Issue 3: Screening List Mismatch

**Problem:** The sanctions screening returned an unrelated person, but the AI concluded "no matches."

**Example:**
- Search query: "Shuvankar Dey, Indian Institute of Technology Kanpur"
- Result returned: "AL-DIN, Haroun Mansour Yaqoub Nasser" (unrelated)
- AI conclusion: "no matches indicating sanctions or restricted status"

**Deterministic Check:**
```python
def validate_screening_relevance(
    response: KYCResponse,
    customer_name: str,
    institution: str
) -> list[str]:
    """
    Verify that screening results are relevant to the customer being checked.
    Returns list of warnings.
    """
    warnings = []

    for tool_call in response.audit.tool_calls:
        if tool_call.tool == "search_screening_list":
            for result in tool_call.results:
                # Check if result name bears any resemblance to customer
                result_name = result.title.lower()
                customer_lower = customer_name.lower()

                # Simple check: do any words match?
                customer_words = set(customer_lower.split())
                result_words = set(result_name.split())

                if not customer_words & result_words:
                    warnings.append(
                        f"Screening result '{result.title}' doesn't match customer '{customer_name}'"
                    )

    return warnings
```

---

### Issue 4: Invalid Email Format Accepted

**Problem:** The email field contained a description ("Verified email at iitk.ac.in") instead of an actual email address.

**Example:**
- Input: `"email": "Verified email at iitk.ac.in"`
- Expected: Validation error (422)
- Actual: Request processed with PASS status

**Fix:** Implement Priority 2.3 (Email Validation with `EmailStr`)

```python
from pydantic import EmailStr

class KYCRequest(BaseModel):
    email: EmailStr  # Will reject invalid email formats
```

---

## Implementation Recommendations

### Phase 1: Add Warning System

Add a `warnings` field to the response that contains any detected issues:

```python
class KYCResponse(BaseModel):
    decision: Decision
    checks: list[Check]
    background_work: list[BackgroundWork] | None = None
    audit: Audit
    warnings: list[str] | None = None  # NEW: Deterministic validation warnings
```

### Phase 2: Post-Processing Validation

After extraction, run deterministic checks:

```python
def validate_response(response: KYCResponse, request: KYCRequest) -> list[str]:
    """Run all deterministic validation checks."""
    warnings = []
    warnings.extend(validate_source_citations(response))
    warnings.extend(validate_evidence_against_results(response))
    warnings.extend(validate_screening_relevance(
        response,
        request.customer_name,
        request.institution
    ))
    return warnings
```

### Phase 3: Consider Auto-Escalation

If warnings are detected, consider:
- Automatically changing status to `REVIEW` instead of `PASS`
- Flagging the response for human review
- Adding a confidence score based on warning count

---

## Tracking

| Issue | Check Type | Status |
|-------|-----------|--------|
| Fabricated citations | Source ID validation | ☐ Not implemented |
| Empty results as evidence | Result count validation | ☐ Not implemented |
| Screening mismatch | Name relevance check | ☐ Not implemented |
| Invalid email format | Pydantic EmailStr | ☐ Priority 2.3 |
