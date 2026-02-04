"""Pydantic models and JSON schemas for KYC API."""

from typing import Any, Literal

from pydantic import BaseModel, Field

# Criteria names matching the verification prompt
VERIFICATION_CRITERIA = [
    "Customer Institutional Affiliation",
    "Institution Type and Biomedical Focus",
    "Email Domain Verification",
    "Sanctions and Export Control Screening",
]


# =============================================================================
# Request Model
# =============================================================================


class KYCRequest(BaseModel):
    """Request model for KYC verification."""

    customer_name: str = Field(..., max_length=200)
    email: str = Field(..., max_length=254)  # RFC 5321 limit
    institution: str = Field(..., max_length=500)
    order_description: str | None = Field(None, max_length=2000)


# =============================================================================
# Response Models (Decision-First Format)
# =============================================================================


class Decision(BaseModel):
    """Top-level decision summary."""

    status: Literal["PASS", "FLAG", "REVIEW"]
    flags_count: int
    summary: str


class Check(BaseModel):
    """A unified verification check with status and evidence."""

    criterion: Literal[
        "Customer Institutional Affiliation",
        "Institution Type and Biomedical Focus",
        "Email Domain Verification",
        "Sanctions and Export Control Screening",
    ]
    status: Literal["FLAG", "NO FLAG", "UNDETERMINED"]
    evidence: str
    sources: list[str]  # Tool citation IDs like ["web1", "epmc1"]


class BackgroundWork(BaseModel):
    """Background work item from research."""

    relevance: int  # 5=customer/same, 4=customer/related, etc.
    organism: str
    summary: str
    sources: list[str]  # Tool citation IDs


class ToolResult(BaseModel):
    """A single result from a tool call, flattened for easy iteration."""

    tool: str  # Tool name (e.g., "search_web", "search_epmc")
    query: str  # Human-readable search query
    id: str  # Citation ID (e.g., "epmc1", "web1", "screen1")
    title: str
    url: str
    snippet: str | None = None
    # Tool-specific fields (optional)
    authors: list[str] | None = None
    year: int | None = None
    affiliations: list[str] | None = None
    programs: list[str] | None = None


class RawOutput(BaseModel):
    """Raw AI-generated markdown outputs."""

    verification: str
    work: str | None = None


class Audit(BaseModel):
    """Audit section with tool results and raw outputs."""

    tool_calls: list[ToolResult]  # Flat list of results with tool/query embedded
    raw: RawOutput


class KYCResponse(BaseModel):
    """Response model for KYC verification (Decision-First format)."""

    decision: Decision
    checks: list[Check]
    background_work: list[BackgroundWork] | None = None
    audit: Audit


# =============================================================================
# Internal Models (for extraction)
# =============================================================================


class VerificationEvidence(BaseModel):
    """Evidence row from verification (Table 1) - internal use."""

    criterion: Literal[
        "Customer Institutional Affiliation",
        "Institution Type and Biomedical Focus",
        "Email Domain Verification",
        "Sanctions and Export Control Screening",
    ]
    sources: list[str]
    evidence_summary: str


class VerificationDetermination(BaseModel):
    """Determination row from verification (Table 2) - internal use."""

    criterion: Literal[
        "Customer Institutional Affiliation",
        "Institution Type and Biomedical Focus",
        "Email Domain Verification",
        "Sanctions and Export Control Screening",
    ]
    flag: Literal["FLAG", "NO FLAG", "UNDETERMINED"]


class BackgroundWorkRow(BaseModel):
    """A row from the background work table - internal use."""

    relevance_level: int
    organism: str
    sources: list[str]
    work_summary: str


class RawToolCall(BaseModel):
    """Raw tool call data from OpenRouter - internal use."""

    tool_id: str
    tool_name: str
    arguments: dict[str, Any]
    result: str


# =============================================================================
# JSON Schemas for OpenRouter Structured Outputs
# =============================================================================

VERIFICATION_EVIDENCE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "verification_evidence",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion": {
                                "type": "string",
                                "enum": VERIFICATION_CRITERIA,
                            },
                            "sources": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Tool citation IDs like web1, screen1",
                            },
                            "evidence_summary": {"type": "string"},
                        },
                        "required": ["criterion", "sources", "evidence_summary"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["rows"],
            "additionalProperties": False,
        },
    },
}

VERIFICATION_DETERMINATION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "verification_determinations",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion": {
                                "type": "string",
                                "enum": VERIFICATION_CRITERIA,
                            },
                            "flag": {
                                "type": "string",
                                "enum": ["FLAG", "NO FLAG", "UNDETERMINED"],
                            },
                        },
                        "required": ["criterion", "flag"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["rows"],
            "additionalProperties": False,
        },
    },
}

BACKGROUND_WORK_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "background_work_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "relevance_level": {
                                "type": "integer",
                                "description": "5=customer/same organism, 4=customer/related, 3=customer/any, 2=institution/same, 1=institution/related",
                            },
                            "organism": {"type": "string"},
                            "sources": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "work_summary": {"type": "string"},
                        },
                        "required": [
                            "relevance_level",
                            "organism",
                            "sources",
                            "work_summary",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["rows"],
            "additionalProperties": False,
        },
    },
}
