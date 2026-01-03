# Cliver API User Guide

This API performs automated know-your-customer (KYC) verification for life science customers, checking their institutional affiliation, email legitimacy, and sanctions compliance.

**Interactive API documentation**: [cliver-api.fly.dev/docs#/default/verify_customer_verify_post](cliver-api.fly.dev/docs#/default/verify_customer_verify_post)

## Making a Request

Send a POST request to `/verify` with customer information:

```json
{
  "customer_name": "Jane Smith",
  "email": "jsmith@mit.edu",
  "institution": "Massachusetts Institute of Technology",
  "order_description": "SARS-CoV-2 spike protein DNA"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `customer_name` | Yes | Customer's full name |
| `email` | Yes | Customer's email address |
| `institution` | Yes | The institution they claim to work at |
| `order_description` | No | What they're ordering (enables background work search) |

## Understanding the Response

### Decision

```json
{
  "decision": {
    "status": "PASS",
    "flags_count": 0,
    "summary": "Researcher at MIT verified with relevant coronavirus publications."
  }
}
```

**Status values:**

| Status | Meaning | Action |
|--------|---------|--------|
| `PASS` | All checks passed | Safe to proceed |
| `REVIEW` | Some checks need attention | Manual review required |
| `FLAG` | Sanctions match found | Do not proceed without compliance review |

The `flags_count` shows how many of the 4 checks raised concerns. The `summary` is a brief explanation of the overall result.

### Checks

The API verifies 4 criteria:

```json
{
  "checks": [
    {
      "criterion": "Customer Institutional Affiliation",
      "status": "NO FLAG",
      "evidence": "Listed as Associate Professor on MIT Biology website.",
      "sources": ["web1"]
    },
    {
      "criterion": "Institution Type and Biomedical Focus",
      "status": "NO FLAG",
      "evidence": "MIT is a recognized research university with biology programs.",
      "sources": ["web2"]
    },
    {
      "criterion": "Email Domain Verification",
      "status": "NO FLAG",
      "evidence": "mit.edu is MIT's official email domain.",
      "sources": ["web3"]
    },
    {
      "criterion": "Sanctions and Export Control Screening",
      "status": "NO FLAG",
      "evidence": "No matches in US Consolidated Screening List.",
      "sources": ["screen1"]
    }
  ]
}
```

**Check status values:**
- `NO FLAG` - Verified successfully
- `FLAG` - Problem found
- `UNDETERMINED` - Could not verify (insufficient sources)

The `sources` field references the specific search results that support the evidence. You can find the full details of each source in the audit section.

### Background Work

If you include `order_description`, the API searches for the customer's relevant research:

```json
{
  "background_work": [
    {
      "relevance": 5,
      "organism": "SARS-CoV-2",
      "summary": "Published research on coronavirus spike protein binding mechanisms.",
      "sources": ["epmc1", "epmc2"]
    }
  ]
}
```

**Relevance scale:**
- 5 = Customer has published work on the same organism
- 4 = Customer has published work on related organisms
- 3 = Customer has published biological/molecular work
- 2 = Their institution works on the same organism
- 1 = Their institution works on related organisms

If no relevant work is found, `background_work` will be `null` or empty.

### Audit Trail

The `audit` section contains complete details of every search performed:

```json
{
  "audit": {
    "tool_calls": [
      {
        "tool": "search_web",
        "query": "Jane Smith MIT biology",
        "result_count": 10,
        "results": [
          {
            "id": "web1",
            "title": "Jane Smith - MIT Biology",
            "url": "https://biology.mit.edu/people/jane-smith",
            "snippet": "Associate Professor of Biology..."
          }
        ]
      },
      {
        "tool": "search_screening_list",
        "query": "Massachusetts Institute Technology",
        "result_count": 0,
        "results": []
      }
    ],
    "raw": {
      "verification": "Full verification analysis text...",
      "work": "Full background work search text..."
    }
  }
}
```

Each source ID (like `web1`, `epmc2`, `screen1`) in the checks refers to a specific result in this list. The `raw` section contains the complete AI analysis text for full transparency.

## Example: Complete Response

```json
{
  "decision": {
    "status": "PASS",
    "flags_count": 0,
    "summary": "MIT researcher verified with coronavirus publications."
  },
  "checks": [
    {
      "criterion": "Customer Institutional Affiliation",
      "status": "NO FLAG",
      "evidence": "Jane Smith is listed as Associate Professor on MIT Biology website.",
      "sources": ["web1"]
    },
    {
      "criterion": "Institution Type and Biomedical Focus",
      "status": "NO FLAG",
      "evidence": "MIT is a leading research university with extensive life sciences programs.",
      "sources": ["web2"]
    },
    {
      "criterion": "Email Domain Verification",
      "status": "NO FLAG",
      "evidence": "The domain mit.edu is MIT's official institutional email system.",
      "sources": ["web3"]
    },
    {
      "criterion": "Sanctions and Export Control Screening",
      "status": "NO FLAG",
      "evidence": "No matches found for customer or institution in US screening lists.",
      "sources": ["screen1"]
    }
  ],
  "background_work": [
    {
      "relevance": 5,
      "organism": "SARS-CoV-2",
      "summary": "First author on Nature paper studying spike protein mutations.",
      "sources": ["epmc1"]
    },
    {
      "relevance": 4,
      "organism": "MERS-CoV",
      "summary": "Co-authored review of coronavirus entry mechanisms.",
      "sources": ["epmc2"]
    }
  ],
  "audit": {
    "tool_calls": [
      {
        "tool": "search_web",
        "query": "Jane Smith MIT biology",
        "result_count": 8,
        "results": [
          {
            "id": "web1",
            "title": "Jane Smith - MIT Biology",
            "url": "https://biology.mit.edu/people/jane-smith",
            "snippet": "Associate Professor of Biology, studying viral entry mechanisms..."
          },
          {
            "id": "web2",
            "title": "MIT Biology Department",
            "url": "https://biology.mit.edu",
            "snippet": "Research areas include infectious disease, molecular biology..."
          }
        ]
      },
      {
        "tool": "search_epmc",
        "query": "Jane Smith coronavirus spike",
        "result_count": 12,
        "results": [
          {
            "id": "epmc1",
            "title": "SARS-CoV-2 spike mutations affecting receptor binding",
            "url": "https://doi.org/10.1038/...",
            "authors": ["Jane Smith", "John Doe"],
            "year": 2023
          }
        ]
      },
      {
        "tool": "search_screening_list",
        "query": "Massachusetts Institute Technology",
        "result_count": 0,
        "results": []
      }
    ],
    "raw": {
      "verification": "## Verification Analysis...",
      "work": "## Background Work Search..."
    }
  }
}
```

## What the API Searches

The API uses multiple data sources:

| Source | What it checks |
|--------|----------------|
| Web search | Institution websites, staff directories, news |
| Europe PMC | Scientific publications and author affiliations |
| ORCID | Researcher profiles and publication history |
| US Screening List | Sanctions and export control compliance |