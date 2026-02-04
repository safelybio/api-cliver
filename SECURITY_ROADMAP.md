# Cliver Security Roadmap

**Purpose:** Prioritized security improvements for Cliver, with implementation guidance.

---

## Priority 1: Critical (Address Before Production Use)

### 1.1 Add Authentication Middleware

**Current state:** API endpoints are publicly accessible with no authentication.

**Risk:** Anyone who discovers the endpoint can use it, incurring your API costs and potentially abusing the service.

**Change:**
- Add API key authentication middleware to FastAPI
- Require `X-API-Key` header on `/verify` endpoint
- Keep `/health` unauthenticated for monitoring

**Implementation sketch:**
```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != os.getenv("CLIVER_API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key

@app.post("/verify")
async def verify(request: KYCRequest, api_key: str = Security(verify_api_key)):
    ...
```

---

### 1.2 Add Rate Limiting

**Current state:** No request throttling.

**Risk:** Cost attacks, denial of service, abuse of external API quotas.

**Change:**
- Add `slowapi` for rate limiting
- Limit by API key (or IP if unauthenticated)
- Suggested limit: 60 requests/minute per key

**Implementation:**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/verify")
@limiter.limit("60/minute")
async def verify(request: Request, ...):
    ...
```

---

### 1.3 Add Input Length Limits

**Current state:** No limits on input field sizes.

**Risk:** Oversized inputs could cause high LLM costs, slow responses, or unexpected behavior.

**Change:**
- Add `max_length` constraints to Pydantic model
- Suggested limits:
  - `customer_name`: 200 characters
  - `email`: 254 characters (RFC 5321)
  - `institution`: 500 characters
  - `order_description`: 2000 characters

**Implementation:**
```python
from pydantic import Field

class KYCRequest(BaseModel):
    customer_name: str = Field(..., max_length=200)
    email: str = Field(..., max_length=254)
    institution: str = Field(..., max_length=500)
    order_description: str | None = Field(None, max_length=2000)
```

---

## Priority 2: High (Address Soon)

### 2.1 Add Basic Logging

**Current state:** No logging. No visibility into requests, errors, or usage.

**Risk:** Cannot detect abuse, debug issues, or maintain audit trail.

**Change:**
- Add structured logging with Python `logging` module
- Log: request received (no PII), request completed, errors
- Use request IDs for correlation
- Configure log level via environment variable

**What to log:**
```
INFO  | request_id=abc123 | endpoint=/verify | status=started
INFO  | request_id=abc123 | endpoint=/verify | status=completed | duration_ms=2341
ERROR | request_id=abc123 | endpoint=/verify | error="OpenRouter timeout"
```

**What NOT to log:**
- Customer names, emails, institutions
- Order descriptions
- Full request/response bodies


---

### 2.2 Sanitize Error Responses

**Current state:** Exception messages passed directly to HTTP responses.

**Risk:** Internal error details (stack traces, API errors) exposed to clients.

**Change:**
- Return generic error messages to clients
- Log detailed errors server-side
- Map known errors to user-friendly messages

**Example:**
```python
# Before
raise HTTPException(status_code=502, detail=f"Verification prompt failed: {e}")

# After
logger.error(f"Verification prompt failed: {e}", exc_info=True)
raise HTTPException(status_code=502, detail="Verification service temporarily unavailable")
```

---

### 2.3 Add Email Format Validation

**Current state:** Email field accepts any string.

**Risk:** Malformed input, potential for injection or unexpected behavior.

**Change:**
- Add email validation to Pydantic model

**Implementation:**
```python
from pydantic import EmailStr

class KYCRequest(BaseModel):
    email: EmailStr
```

---

## Priority 3: Medium (Recommended)

### 3.1 Configure Dependency Scanning

**Current state:** No automated vulnerability scanning for dependencies.

**Risk:** Known vulnerabilities in dependencies go undetected.

**Change:**
- Add `.github/dependabot.yml` for automated PRs
- Consider adding `pip-audit` to CI

**Implementation:**
```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

---

### 3.2 Add Request ID Tracking

**Current state:** No correlation between requests and external API calls.

**Risk:** Difficult to debug issues or trace requests through the system.

**Change:**
- Generate UUID for each request
- Pass through to all logging
- Include in response headers (`X-Request-ID`)
- Optionally include in external API calls for tracing

---

### 3.3 Document Prompt Injection Mitigations

**Current state:** User input interpolated directly into LLM prompts.

**Risk:** Malicious input could influence verification results.

**Mitigation options:**
1. **Documentation:** Emphasize human review requirement (low effort)
2. **Input escaping:** Wrap user input in clear delimiters (medium effort)
3. **Structured output validation:** Validate LLM outputs against expected schema (already partially done)

**Recommended approach:** Document the risk clearly and emphasize that Cliver is decision-support, not automated decision-making. Add a note about this in the Security Overview.

---

### 3.4 Remove Hardcoded Referer Header

**Current state:** `app/openrouter.py` contains hardcoded `HTTP-Referer: https://kyc-api.fly.dev`

**Risk:** Minor—cosmetic issue, but could confuse self-hosters.

**Change:**
- Remove the header, or
- Make it configurable via environment variable

---

## Priority 4: Lower (Nice to Have)

### 4.1 Add CORS Configuration

**Current state:** No CORS headers configured.

**Impact:** Only relevant if browser-based clients will call the API directly.

**Change:**
- Add `fastapi.middleware.cors.CORSMiddleware`
- Configure allowed origins based on deployment

---

### 4.2 Add OpenAPI Security Definitions

**Current state:** Auto-generated OpenAPI docs don't reflect authentication requirements.

**Change:**
- Add security scheme definitions to FastAPI app
- Document API key requirement in OpenAPI spec

---

### 4.3 Create Security Headers Middleware

**Current state:** No security headers set by the application.

**Change:**
- Add middleware for security headers (can also be done at proxy level):
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Cache-Control: no-store` (for API responses)

---

## Implementation Order

For a team preparing Cliver for production:

| Week | Tasks |
|------|-------|
| 1 | 1.1 Authentication, 1.2 Rate limiting, 1.3 Input limits |
| 2 | 2.1 Logging, 2.2 Error sanitization, 2.3 Email validation |
| 3 | 3.1 Dependabot, 3.2 Request IDs, 3.4 Remove hardcoded header |
| Ongoing | 3.3 Prompt injection documentation, Priority 4 items |

---

## Tracking

| ID | Task | Status | Completed |
|----|------|--------|-----------|
| 1.1 | Authentication | ☐ Not started | |
| 1.2 | Rate limiting | ☐ Not started | |
| 1.3 | Input length limits | ☐ Not started | |
| 2.1 | Logging | ☐ Not started | |
| 2.2 | Error sanitization | ☐ Not started | |
| 2.3 | Email validation | ☐ Not started | |
| 3.1 | Dependency scanning | ☐ Not started | |
| 3.2 | Request ID tracking | ☐ Not started | |
| 3.3 | Prompt injection docs | ☐ Not started | |
| 3.4 | Remove hardcoded header | ☐ Not started | |