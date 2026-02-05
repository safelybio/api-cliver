# Cliver Security Overview

**Version:** 2.0  
**Last Updated:** February 2026

---

## What is Cliver?

Cliver is an open-source API that assists know-your-customer (KYC) verification for DNA synthesis providers. It uses an LLM to orchestrate checks against public databases (publications, researcher profiles) and screening lists (US sanctions/export controls), returning structured verification results with evidence.

**Deployment model:** Self-hosted. You run Cliver on your own infrastructure with your own API keys. Cliver maintainers have no access to your data during normal operation.

---

## Architecture

### Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────────┐
│   Client    │────▶│   Cliver    │────▶│   External Services  │
│  (Your App) │◀────│    API      │◀────│  (LLM, Search, etc.) │
└─────────────┘     └─────────────┘     └──────────────────────┘
                          │
                          ▼
                    No persistence
                    (stateless)
```

### Key Design Principles

| Principle | Implementation |
| :---- | :---- |
| **Stateless** | No data persisted between requests. No database, cache, or file storage. |
| **Self-hosted** | You control infrastructure, network, and access policies. |
| **Transparent** | Open-source code. Full audit trail returned with each response. |

---

## Data Security

### What Data is Processed

All input fields are sent to the LLM, which orchestrates verification by querying external services. The LLM determines what information to include in each query based on context.

| Data Type | Example | Verification Purpose |
| ----- | ----- | ----- |
| Customer name | "Jane Smith" | Identity verification, publication matching, sanctions screening |
| Email | "jane@university.edu" | Domain legitimacy, institutional affiliation |
| Institution | "MIT" | Affiliation verification, sanctions screening |
| Order description | "CRISPR guide RNA" | Search for related customer work |

### Data Persistence

**Cliver stores nothing.** Each API request is processed and discarded. There is no:

- Database  
- Request logging  
- File storage  
- Caching of customer data

Audit trails are returned in the API response for you to store according to your retention policies.

### Data Sent to External Services

| Service | Data Sent | Purpose |
| :---- | :---- | :---- |
| OpenRouter → LLM | All input fields | Orchestration and analysis |
| Tavily | All input fields | Web search for public customer information |
| Europe PMC | Name, institution, order description | Publication search |
| ORCID | Name or ORCID ID | Researcher profile lookup |
| US Consolidated Screening List | Name, institution | Sanctions/export control check |

---

## Third-Party Services

### LLM Provider (via OpenRouter)

- **Zero Data Retention:** You must configure this in your OpenRouter account settings; not automatic  
- **No training on inputs:** Commercial API terms prohibit training on your data  
- **Provider options:** Anthropic, OpenAI, Google (you choose the model)  
- **Security documentation:** [openrouter.ai/privacy](https://openrouter.ai/privacy)

### Screening & Publication APIs

| Service | Operator | Security Posture |
| :---- | :---- | :---- |
| US Consolidated Screening List | US Dept. of Commerce | Government API, HTTPS |
| Europe PMC | EMBL-EBI | Public research database, HTTPS |
| ORCID | ORCID Inc. | Public researcher profiles, HTTPS |
| Tavily | Tavily Inc. | Commercial search API, HTTPS |

All external calls use HTTPS. No sensitive data is sent to services that don't require it.

---

## Application Security

### Current State

| Area | Status | Notes |
| :---- | :---- | :---- |
| Authentication | ✓ Implemented | API key required via `X-API-Key` header |
| Rate limiting | ✓ Implemented | 60 requests/minute, keyed by API key (falls back to IP if header missing) |
| Input validation | ✓ Implemented | customer_name ≤200, email ≤254 (RFC 5321), institution ≤500, order_description ≤2000 chars; Pydantic EmailStr validation |
| Logging | ✓ Implemented | 8-char request IDs (returned in `X-Request-ID` header), timing in ms; no PII logged |
| Secrets management | ✓ Environment variables | API keys never in code |
| HTTPS | ✓ Enforced at deployment | Via reverse proxy |
| Dependency scanning | ✓ Configured | Dependabot for weekly vulnerability scans |

### Security Considerations

**Prompt injection:** User input is passed to the LLM. While Cliver is a verification tool (not an autonomous agent), malicious input could potentially influence LLM outputs. Mitigations include input validation, structured output parsing (decisions constrained to PASS/FLAG/REVIEW enum), and full audit trails. Human review of results is recommended.

**Cost exposure:** Authentication and rate limiting prevent unauthorized use and API cost abuse.

### HTTP Status Codes

| Code | Condition |
| :---- | :---- |
| 200 | Successful verification |
| 401 | Missing or invalid API key |
| 422 | Input validation failure |
| 429 | Rate limit exceeded |
| 502 | Upstream service error |

---

## Deployment Security

### Secrets Required

| Variable | Purpose | Required |
| :---- | :---- | :---- |
| `CLIVER_API_KEY` | API authentication | Yes |
| `OPENROUTER_API_KEY` | LLM access | Yes |
| `TAVILY_API_KEY` | Web search | Yes |
| `SCREENING_LIST_API_KEY` | Sanctions list | Yes |
| `OPENROUTER_REFERER` | HTTP-Referer header for OpenRouter | No (default: `https://cliver.example.com`) |
| `OPENROUTER_TITLE` | X-Title header for OpenRouter | No (default: `Cliver KYC API`) |
| `LOG_LEVEL` | Logging verbosity | No (default: `INFO`) |

### Deployment Checklist

- [x] API key authentication (built-in)  
- [x] Rate limiting (built-in)  
- [x] Request logging with correlation IDs (built-in)  
- [ ] Deploy behind reverse proxy with HTTPS termination  
- [ ] Store secrets in environment variables or secrets manager  
- [ ] Configure network isolation (restrict egress to required APIs only)  
- [ ] Set up monitoring and alerting

---

## Incident Response

### Reporting Security Issues in Cliver

If you discover a vulnerability in Cliver itself:

- **Email:** \[security contact placeholder\]  
- **Response time:** We aim to acknowledge within 7 days  
- **Disclosure:** We coordinate disclosure after a fix is available

### Your Incident Response

As a self-hosted deployment, you are responsible for:

- Monitoring for security incidents  
- Notifying affected parties if customer data is compromised  
- GDPR breach notification (72 hours to supervisory authority, if applicable)

---

## Provider Responsibilities

Since Cliver is self-hosted, security responsibilities are shared:

| Responsibility | Cliver Provides | You Provide |
| :---- | :---- | :---- |
| Code security | Open-source, auditable code | Code review, updates |
| Authentication | ✓ API key authentication | Secure key generation and storage |
| Rate limiting | ✓ 60 req/min per key | Additional limits if needed |
| HTTPS | App ready for TLS termination | Certificate and proxy setup |
| Logging | ✓ Request logging (no PII) | Log aggregation and monitoring |
| Access control | — | Network policies, firewall rules |
| Secrets management | Env var loading | Secure secret storage |
| Incident response | Vulnerability fixes | Detection, notification, remediation |

---

## Summary

Cliver's security model relies on:

1. **Stateless design** — No data retention reduces breach impact  
2. **Self-hosting** — You control the security perimeter  
3. **Transparency** — Open-source code, full audit trails  

For compliance guidance (GDPR, data processing), see the Cliver Compliance Guide (coming soon).

---

## Appendix: Areas for Additional Detail

This document can be expanded with:

- **Detailed threat model** — STRIDE analysis, attack trees  
- **Penetration test results** — When conducted  
- **SOC 2 / ISO 27001 mapping** — If providers require compliance mapping  
- **Network diagram** — Detailed deployment architecture  
- **API security headers** — Recommended headers (CSP, HSTS, etc.)  
- **Dependency SBOM** — Full software bill of materials

---

*This document describes Cliver's security posture as of February 2026\. Security is a shared responsibility between Cliver maintainers (code security) and deploying organizations (operational security). For questions, contact \[email\].*  