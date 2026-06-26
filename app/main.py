"""FastAPI application for KYC verification."""

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Load environment variables from .env file
load_dotenv()

# Configure logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s | %(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from app.constants import TOOL_CONTEXT_TRUNCATION
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
    title="DNA Synthesis KYC API",
    description="AI Customer Screening for Nucleic Acid Providers",
    version="1.0.0",
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add request ID to each request for logging correlation."""
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    start_time = time.time()

    response = await call_next(request)

    duration_ms = int((time.time() - start_time) * 1000)
    response.headers["X-Request-ID"] = request_id

    # Log request completion (no PII)
    logger.info(
        f"request_id={request_id} | "
        f"method={request.method} | "
        f"path={request.url.path} | "
        f"status={response.status_code} | "
        f"duration_ms={duration_ms}"
    )

    return response


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
MAIN_MODEL = "google/gemini-3-flash-preview"
EXTRACTION_MODEL = "google/gemini-3-flash-preview"

# Sanctions criterion name
SANCTIONS_CRITERION = "Sanctions and Export Control Screening"

# API Key authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Verify the API key from the X-API-Key header."""
    expected_key = os.environ.get("CLIVER_API_KEY")
    if not expected_key or api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


# Rate limiting - 60 requests per minute per API key (or IP if no key)
def _get_rate_limit_key(request: Request) -> str:
    """Rate limit by API key if present, else by IP address."""
    api_key = request.headers.get("X-API-Key")
    return api_key if api_key else get_remote_address(request)


limiter = Limiter(key_func=_get_rate_limit_key)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Handle rate limit exceeded errors."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.warning(f"request_id={request_id} | rate_limit_exceeded")
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
        headers={"Retry-After": "60", "X-Request-ID": request_id},
    )


def _format_tool_context(tool_calls: list[RawToolCall]) -> str:
    """Format tool calls as context for extraction prompts."""
    if not tool_calls:
        return ""

    lines = ["\n\n=== Tool Outputs Reference ==="]
    for tc in tool_calls:
        lines.append(f"\n[{tc.tool_name}]:")
        # Truncate long results for context
        result_preview = (
            tc.model_output[:TOOL_CONTEXT_TRUNCATION]
            if len(tc.model_output) > TOOL_CONTEXT_TRUNCATION
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


@dataclass
class PromptResults:
    """Results from running verification and work prompts."""

    verification: CompletionResult
    work: CompletionResult | None
    id_counters: dict[str, int]


@dataclass
class ExtractionResults:
    """Results from structured extraction."""

    evidence: list[VerificationEvidence]
    determinations: list[VerificationDetermination]
    background_work: list[BackgroundWork] | None


async def _run_prompts(
    client: OpenRouterClient,
    customer_info: str,
    has_order: bool,
    request_id: str,
) -> PromptResults:
    """Run verification and optional work prompts with tools."""
    id_counters: dict[str, int] = {}

    verification_prompt = VERIFICATION_PROMPT.replace("{{customer_info}}", customer_info)
    try:
        verification_result = await client.complete_with_tools(
            verification_prompt,
            model=MAIN_MODEL,
            id_counters=id_counters,
        )
    except Exception as e:
        logger.error(
            f"request_id={request_id} | verification_prompt_failed | error={e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=502, detail="Verification service temporarily unavailable"
        ) from e

    work_result: CompletionResult | None = None
    if has_order:
        work_prompt = WORK_PROMPT.replace("{{customer_info}}", customer_info)
        try:
            work_result = await client.complete_with_tools(
                work_prompt,
                model=MAIN_MODEL,
                id_counters=id_counters,
            )
        except Exception as e:
            logger.error(
                f"request_id={request_id} | work_prompt_failed | error={e}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=502, detail="Verification service temporarily unavailable"
            ) from e

    return PromptResults(
        verification=verification_result,
        work=work_result,
        id_counters=id_counters,
    )


async def _run_extractions(
    client: OpenRouterClient,
    prompt_results: PromptResults,
    request_id: str,
) -> ExtractionResults:
    """Run structured extractions on prompt results."""
    verification_context = prompt_results.verification.text
    verification_context += _format_tool_context(prompt_results.verification.tool_calls)

    work_context = None
    if prompt_results.work:
        work_context = prompt_results.work.text
        work_context += _format_tool_context(prompt_results.work.tool_calls)

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
        logger.error(
            f"request_id={request_id} | extraction_failed | error={e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=502, detail="Verification service temporarily unavailable"
        ) from e

    evidence_list = [VerificationEvidence(**row) for row in evidence_data["rows"]]
    determinations = [
        VerificationDetermination(**row) for row in determinations_data["rows"]
    ]

    background_work: list[BackgroundWork] | None = None
    if work_data:
        work_rows = [BackgroundWorkRow(**row) for row in work_data["rows"]]
        background_work = _convert_background_work(work_rows)

    return ExtractionResults(
        evidence=evidence_list,
        determinations=determinations,
        background_work=background_work,
    )


async def _generate_summary(
    client: OpenRouterClient,
    customer_info: str,
    prompt_results: PromptResults,
    status: str,
    request_id: str,
) -> str:
    """Generate decision summary using LLM with fallback."""
    try:
        summary_prompt = _build_summary_prompt(
            customer_info,
            prompt_results.verification.text,
            prompt_results.work.text if prompt_results.work else None,
        )
        summary = await client.generate_text_async(summary_prompt, model=EXTRACTION_MODEL)
        return summary.strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"request_id={request_id} | summary_generation_failed | error={e}")
        if status == "PASS":
            return "All verification criteria passed."
        elif status == "FLAG":
            return "Sanctions screening flagged - requires immediate review."
        else:
            return "Some criteria require manual review."


async def _run_verification(kyc_request: KYCRequest, request_id: str) -> KYCResponse:
    """Run the full KYC verification flow and build the response.

    Shared by the synchronous ``/verify`` endpoint and the async job worker.
    """
    has_order = bool(kyc_request.order_description)
    logger.info(f"request_id={request_id} | verify_started | has_order={has_order}")

    try:
        client = OpenRouterClient()
    except ValueError as e:
        logger.error(f"request_id={request_id} | client_init_failed | error={e}")
        raise HTTPException(
            status_code=500, detail="Service configuration error"
        ) from e

    # Build customer info string for prompt templates
    customer_info = f"""Name: {kyc_request.customer_name}
Institution: {kyc_request.institution}
Email: {kyc_request.email}"""
    if kyc_request.order_description:
        customer_info += f"\nOrder: {kyc_request.order_description}"

    # Run prompts and extractions
    prompt_results = await _run_prompts(client, customer_info, has_order, request_id)
    extraction_results = await _run_extractions(client, prompt_results, request_id)

    # Build response
    checks = _merge_checks(extraction_results.evidence, extraction_results.determinations)
    status, flags_count = _compute_decision_status(extraction_results.determinations)
    summary = await _generate_summary(client, customer_info, prompt_results, status, request_id)

    # Combine all tool calls for audit
    all_tool_calls = list(prompt_results.verification.tool_calls)
    if prompt_results.work:
        all_tool_calls.extend(prompt_results.work.tool_calls)

    logger.info(
        f"request_id={request_id} | verify_completed | "
        f"status={status} | flags_count={flags_count}"
    )

    return KYCResponse(
        decision=Decision(status=status, flags_count=flags_count, summary=summary),
        checks=checks,
        background_work=extraction_results.background_work,
        audit=Audit(
            tool_calls=normalize_tool_calls(all_tool_calls),
            raw=RawOutput(
                verification=prompt_results.verification.text,
                work=prompt_results.work.text if prompt_results.work else None,
            ),
        ),
    )


@app.post("/verify", response_model=KYCResponse)
@limiter.limit("60/minute")
async def verify_customer(
    request: Request,
    kyc_request: KYCRequest,
    api_key: str = Security(verify_api_key),
) -> KYCResponse:
    """
    Run know-your-customer checks on a life-science customer.

    This endpoint:
    1. Checks affiliation, web domain, institution legitimacy, and sanctions screening
    2. Finds relevant work from the customer/their institution if provided details on the order
    3. Returns summary of findings with full audit trail

    Requires X-API-Key header for authentication.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    return await _run_verification(kyc_request, request_id)


# =============================================================================
# Async job endpoints
# =============================================================================

# In-memory job store. Suitable for a single-process deployment; a multi-worker
# or multi-instance setup would need a shared store (e.g. Redis).
_JOBS: dict[str, dict[str, Any]] = {}

# Rough client-side hint for how long a verification typically takes.
ESTIMATED_VERIFY_SECONDS = 60


async def _run_verification_job(
    job_id: str, kyc_request: KYCRequest, request_id: str
) -> None:
    """Background worker: run verification and store the result on the job."""
    try:
        result = await _run_verification(kyc_request, request_id)
        job = _JOBS.get(job_id)
        if job is not None:
            job["status"] = "completed"
            job["result"] = result
            job["completed_at"] = time.time()
    except Exception as e:  # noqa: BLE001 - record any failure on the job
        logger.error(
            f"request_id={request_id} | job_id={job_id} | "
            f"async_verify_failed | error={e}",
            exc_info=True,
        )
        job = _JOBS.get(job_id)
        if job is not None:
            job["status"] = "failed"
            job["error"] = "Verification failed"
            job["completed_at"] = time.time()


@app.post("/verify/async")
@limiter.limit("60/minute")
async def verify_customer_async(
    request: Request,
    kyc_request: KYCRequest,
    api_key: str = Security(verify_api_key),
) -> dict[str, Any]:
    """
    Start a verification as a background job and return immediately.

    Returns a ``job_id`` to poll via ``GET /verify/jobs/{job_id}``. Use this for
    long verifications that would otherwise exceed an edge/proxy timeout.

    Requires X-API-Key header for authentication.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    job_id = str(uuid.uuid4())
    _JOBS[job_id] = {
        "status": "pending",
        "created_at": time.time(),
        "completed_at": None,
        "result": None,
        "error": None,
    }

    logger.info(f"request_id={request_id} | job_id={job_id} | async_verify_queued")
    asyncio.create_task(_run_verification_job(job_id, kyc_request, request_id))

    return {
        "job_id": job_id,
        "status_url": f"/verify/jobs/{job_id}",
        "estimated_seconds": ESTIMATED_VERIFY_SECONDS,
    }


@app.get("/verify/jobs/{job_id}")
async def get_verify_job(
    job_id: str,
    api_key: str = Security(verify_api_key),
) -> dict[str, Any]:
    """Return the status (and result, once complete) of an async verify job."""
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    response: dict[str, Any] = {
        "job_id": job_id,
        "status": job["status"],
        "created_at": job["created_at"],
        "completed_at": job["completed_at"],
    }
    if job["status"] == "completed":
        response["result"] = job["result"]
    elif job["status"] == "failed":
        response["error"] = job["error"]
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
