"""FastAPI application for KYC verification."""

import asyncio
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

# Load environment variables from .env file
load_dotenv()

from app.models import (
    BACKGROUND_WORK_SCHEMA,
    VERIFICATION_DETERMINATION_SCHEMA,
    VERIFICATION_EVIDENCE_SCHEMA,
    Audit,
    BackgroundWork,
    BackgroundWorkRow,
    Check,
    Decision,
    KYCRequest,
    KYCResponse,
    RawOutput,
    VerificationDetermination,
    VerificationEvidence,
)
from app.openrouter import (
    CompletionResult,
    OpenRouterClient,
    RawToolCall,
    normalize_tool_calls,
)

app = FastAPI(
    title="KYC Verification API",
    description="API for KYC verification using AI-powered research tools",
    version="1.0.0",
)

# Load prompts at startup
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
VERIFICATION_PROMPT = (PROMPTS_DIR / "verification.txt").read_text()
WORK_PROMPT = (PROMPTS_DIR / "work.txt").read_text()
EXTRACTION_PROMPT_EVIDENCE = (PROMPTS_DIR / "extraction_evidence.txt").read_text()
EXTRACTION_PROMPT_DETERMINATIONS = (
    PROMPTS_DIR / "extraction_determinations.txt"
).read_text()
EXTRACTION_PROMPT_WORK = (PROMPTS_DIR / "extraction_work.txt").read_text()
SUMMARY_PROMPT = (PROMPTS_DIR / "summary.txt").read_text()

# Model configuration
MAIN_MODEL = "google/gemini-3-pro-preview"
EXTRACTION_MODEL = "google/gemini-3-flash-preview"

# Sanctions criterion name
SANCTIONS_CRITERION = "Sanctions and Export Control Screening"


def _format_tool_context(tool_calls: list[RawToolCall]) -> str:
    """Format tool calls as context for extraction prompts."""
    if not tool_calls:
        return ""

    lines = ["\n\n=== Tool Outputs Reference ==="]
    for tc in tool_calls:
        lines.append(f"\n[{tc.tool_name}]:")
        # Truncate long results for context
        result_preview = (
            tc.model_output[:2000]
            if len(tc.model_output) > 2000
            else tc.model_output
        )
        lines.append(result_preview)
    return "\n".join(lines)


def _compute_decision_status(
    determinations: list[VerificationDetermination],
) -> tuple[str, int]:
    """
    Compute decision status from determinations.

    Logic:
    - FLAG: Only if Sanctions criterion has FLAG
    - REVIEW: If any other criterion has FLAG or UNDETERMINED
    - PASS: All criteria are NO FLAG
    """
    sanctions_flag = False
    other_issues = []

    for d in determinations:
        if d.criterion == SANCTIONS_CRITERION:
            if d.flag == "FLAG":
                sanctions_flag = True
        else:
            if d.flag in ("FLAG", "UNDETERMINED"):
                other_issues.append(d)

    if sanctions_flag:
        return "FLAG", 1
    elif other_issues:
        return "REVIEW", len(other_issues)
    else:
        return "PASS", 0


def _merge_checks(
    evidence_list: list[VerificationEvidence],
    determinations: list[VerificationDetermination],
) -> list[Check]:
    """Merge evidence and determinations into unified Check objects."""
    evidence_by_criterion = {e.criterion: e for e in evidence_list}
    determination_by_criterion = {d.criterion: d for d in determinations}

    checks = []
    for criterion in evidence_by_criterion:
        evidence = evidence_by_criterion.get(criterion)
        determination = determination_by_criterion.get(criterion)

        if evidence and determination:
            checks.append(
                Check(
                    criterion=criterion,
                    status=determination.flag,
                    evidence=evidence.evidence_summary,
                    sources=evidence.sources,
                )
            )

    return checks


def _convert_background_work(rows: list[BackgroundWorkRow]) -> list[BackgroundWork]:
    """Convert internal BackgroundWorkRow to output BackgroundWork format."""
    return [
        BackgroundWork(
            relevance=row.relevance_level,
            organism=row.organism,
            summary=row.work_summary,
            sources=row.sources,
        )
        for row in rows
    ]


def _build_summary_prompt(
    customer_info: str,
    verification_raw: str,
    work_raw: str | None,
) -> str:
    """Build the prompt for generating the decision summary."""
    return (
        SUMMARY_PROMPT.replace("{{customer_info}}", customer_info)
        .replace("{{verification_raw}}", verification_raw)
        .replace("{{work_raw}}", work_raw or "No order details provided.")
    )


@app.post("/verify", response_model=KYCResponse)
async def verify_customer(request: KYCRequest) -> KYCResponse:
    """
    Run know-your-customer checks on a life-science customer.

    This endpoint:
    1. Checks affiliation, web domain, institution legitimacy, and sanctions screening
    2. Finds relevant work from the customer/their institution if provided details on the order
    3. Returns summary of findings with full audit trail
    """
    try:
        client = OpenRouterClient()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Build customer info string for prompt templates
    customer_info = f"""Name: {request.customer_name}
Institution: {request.institution}
Email: {request.email}"""

    if request.order_description:
        customer_info += f"\nOrder: {request.order_description}"

    # Shared ID counters for consistent IDs across both prompts
    id_counters: dict[str, int] = {}

    # Run verification prompt with tools
    verification_prompt = VERIFICATION_PROMPT.replace(
        "{{customer_info}}", customer_info
    )
    try:
        verification_result = client.complete_with_tools(
            verification_prompt,
            model=MAIN_MODEL,
            id_counters=id_counters,
        )
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Verification prompt failed: {e}"
        ) from e

    # Run work prompt with tools only if order_description provided
    work_result: CompletionResult | None = None
    if request.order_description:
        work_prompt = WORK_PROMPT.replace("{{customer_info}}", customer_info)
        try:
            work_result = client.complete_with_tools(
                work_prompt,
                model=MAIN_MODEL,
                id_counters=id_counters,  # Use same counters
            )
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"Work prompt failed: {e}"
            ) from e

    # Build extraction contexts
    verification_context = verification_result.text
    verification_context += _format_tool_context(verification_result.tool_calls)

    work_context = None
    if work_result:
        work_context = work_result.text
        work_context += _format_tool_context(work_result.tool_calls)

    # Run extractions in parallel
    try:
        extraction_tasks = [
            client.extract_structured_async(
                verification_context,
                EXTRACTION_PROMPT_EVIDENCE,
                VERIFICATION_EVIDENCE_SCHEMA,
                model=EXTRACTION_MODEL,
            ),
            client.extract_structured_async(
                verification_context,
                EXTRACTION_PROMPT_DETERMINATIONS,
                VERIFICATION_DETERMINATION_SCHEMA,
                model=EXTRACTION_MODEL,
            ),
        ]

        # Add work extraction if applicable
        if work_context:
            extraction_tasks.append(
                client.extract_structured_async(
                    work_context,
                    EXTRACTION_PROMPT_WORK,
                    BACKGROUND_WORK_SCHEMA,
                    model=EXTRACTION_MODEL,
                )
            )

        results = await asyncio.gather(*extraction_tasks)

        evidence_data = results[0]
        determinations_data = results[1]
        work_data = results[2] if len(results) > 2 else None

    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Extraction failed: {e}"
        ) from e

    # Parse extracted data
    evidence_list = [VerificationEvidence(**row) for row in evidence_data["rows"]]
    determinations = [
        VerificationDetermination(**row) for row in determinations_data["rows"]
    ]

    # Convert background work
    background_work: list[BackgroundWork] | None = None
    if work_data:
        work_rows = [BackgroundWorkRow(**row) for row in work_data["rows"]]
        background_work = _convert_background_work(work_rows)

    # Build checks
    checks = _merge_checks(evidence_list, determinations)

    # Compute decision status
    status, flags_count = _compute_decision_status(determinations)

    # Generate summary with LLM
    try:
        summary_prompt = _build_summary_prompt(
            customer_info,
            verification_result.text,
            work_result.text if work_result else None,
        )
        summary = await client.generate_text_async(summary_prompt, model=EXTRACTION_MODEL)
        # Clean up summary (remove quotes, word counts, etc.)
        summary = summary.strip().strip('"').strip("'")
    except Exception:
        # Fallback to simple summary if LLM fails
        if status == "PASS":
            summary = "All verification criteria passed."
        elif status == "FLAG":
            summary = "Sanctions screening flagged - requires immediate review."
        else:
            summary = "Some criteria require manual review."

    decision = Decision(
        status=status,
        flags_count=flags_count,
        summary=summary,
    )

    # Combine all tool calls for audit
    all_tool_calls = list(verification_result.tool_calls)
    if work_result:
        all_tool_calls.extend(work_result.tool_calls)

    audit = Audit(
        tool_calls=normalize_tool_calls(all_tool_calls),
        raw=RawOutput(
            verification=verification_result.text,
            work=work_result.text if work_result else None,
        ),
    )

    return KYCResponse(
        decision=decision,
        checks=checks,
        background_work=background_work,
        audit=audit,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
