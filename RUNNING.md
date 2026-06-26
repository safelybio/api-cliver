# Running the (fixed) Cliver API

`safelybio`'s fork of [`alejoacelas/api-cliver`](https://github.com/alejoacelas/api-cliver) — an LLM-based KYC verification API for DNA-synthesis customers. **We fixed it:** upstream was returning 502 on every `/verify` because OpenRouter no longer serves the `/responses` endpoint the verification loop relied on.

## The fix
Branch `fix/openrouter-chat-completions` (merged into this `master`; that branch is kept clean for the upstream PR in `PR_DRAFT.md`).
- `app/openrouter.py` — ported `complete_with_tools` from the Responses API (`/responses`, now 404 on OpenRouter) to **Chat Completions** (`/chat/completions`); reads tool calls from `choices[0].message.tool_calls`; appends results as `role:"tool"` messages and re-calls to the cap. Tool schema added via `get_chat_tools` in `app/tools/registry.py`.
- `app/main.py` — `MAIN_MODEL = "google/gemini-3.1-pro-preview"` (a valid OpenRouter slug; the old `google/gemini-3-pro-preview` 404s).
- `app/constants.py` — `MAX_COMPLETION_TOKENS = 8000`.
- `pytest` → **31 passed**.

## Speed + async (on `master`, deployed)
A second round of work, merged to **`master`** from `perf/cliver-speed-async`; the live `cliver-api` is deployed from it:
- **Parallel tool execution (the big win).** `complete_with_tools` is now `async`; a turn's tool calls run **concurrently** via `asyncio.gather` + `run_in_executor` — they used to run one-at-a-time, which was the dominant latency. Plus `MAIN_MODEL` → `google/gemini-3-flash-preview`, tool-loop cap 20 → 10, `MAX_COMPLETION_TOKENS` 8000 → 4000.
- **Async endpoints (no more 60 s edge timeout).** `POST /verify/async` returns a `job_id` immediately; poll `GET /verify/jobs/{job_id}` → `{status: pending|completed|failed, result?}`. In-memory job store (single-process only; use Redis for multi-worker). Sync `POST /verify` is unchanged; shared helper `_run_verification` runs the flow for both.
- **Result, measured live:** a 46-tool-call screen dropped from >60 s (edge-timeout territory) to **~22 s** (no order) / **~68 s** (with an order — runs a second research loop). Because submit and each poll are individually fast, async screens complete cleanly regardless of total duration.
- `uv run pytest` → **35 passed**.
- ⚠️ Sanity-check the flash slug `google/gemini-3-flash-preview` is live on the OpenRouter account (it's now both `MAIN_MODEL` and `EXTRACTION_MODEL`).

## What it is
One endpoint, `POST /verify`, gated by header `X-API-Key`. It runs an LLM tool-loop (OpenRouter → Gemini) with web search (Tavily) + ORCID / Europe PMC, and returns a `decision` (status **PASS/REVIEW/FLAG** + one-line summary), exactly **4 criteria** (each FLAG / NO FLAG / UNDETERMINED + an evidence paragraph + cited sources), optional `background_work` on the order, and a sources list. `GET /health` is open (no key). **Paid:** roughly **5–15¢ per call**. **Latency:** ~20 s (no order) to ~70 s (with an order) on the `perf/cliver-speed-async` branch — was ~30–90 s on a Gemini-pro serial-tool loop; see **Speed + async** below.

## Request / response
```
POST /verify
X-API-Key: <CLIVER_API_KEY>
Content-Type: application/json

{ "customer_name": "Dr Maria Lopez", "email": "m.lopez@stanford.edu",
  "institution": "Stanford University", "order_description": "GFP" }   # order_description optional
```
Returns `{ decision:{status, flags_count, summary}, checks:[{criterion, status, evidence, sources}], background_work?, audit }`. Verdict vocabulary (PASS/REVIEW/FLAG) matches Safely Verify's — so verdicts compare cleanly, but Cliver emits 4 coarse LLM-judged criteria (vs our ~21 deterministic checks) and can't stream → it's verdict-comparable, not tile-comparable.

## Env vars — values are NOT in this repo
| Var | For | Required? |
|---|---|---|
| `OPENROUTER_API_KEY` | every LLM call | yes (hard startup blocker) |
| `TAVILY_API_KEY` | web-search tool | yes (hard startup blocker) |
| `CLIVER_API_KEY` | the `X-API-Key` gate | yes (you set it) |
| `SCREENING_LIST_API_KEY` | sanctions (US CSL) | optional — degrades to UNDETERMINED without |

For the team's deployment, all three live in the Railway `cliver-api` service env — pull with `railway variables -s cliver-api --kv` (never commit the values; this is a public fork).

## ⚠️ Blocker — OpenRouter credits
The deployed instance returns **402 Payment Required** until the OpenRouter account has purchased credits (it reserves a model's full token budget up front). Fund at <https://openrouter.ai/settings/credits>; after that `/verify` returns 200 with no code change.

## Run locally
```bash
git clone https://github.com/safelybio/api-cliver && cd api-cliver
uv sync                      # or: pip install .
export OPENROUTER_API_KEY=… TAVILY_API_KEY=… CLIVER_API_KEY=…
uvicorn app.main:app --port 8080
curl -s -X POST localhost:8080/verify \
  -H "X-API-Key: $CLIVER_API_KEY" -H 'Content-Type: application/json' \
  -d '{"customer_name":"Dr Maria Lopez","email":"m.lopez@stanford.edu","institution":"Stanford University"}'
```

## Team deployment (Railway + Vercel)
- **Railway** — service `cliver-api` (its own project), built from the `Dockerfile`. Live at **<https://cliver-api-production.up.railway.app>** (`/health` → 200). Redeploy with `railway up` from a clone linked to that project (`railway link` / `railway init` already done on the original clone). The Dockerfile binds port 8080; Railway routes to it via `EXPOSE`.
- **Playground (easiest way to try it)** — live at **<https://try-cliver-production.up.railway.app>** (Railway service `try-cliver`, project `try-cliver`; source at `~/projects/cliver-playground/main.py`, redeploy `railway up -s try-cliver`). It's a `stdlib`-only Python server that serves a form and proxies the **async** flow (`POST /verify/async` → poll `GET /verify/jobs/{id}`), injecting `X-API-Key` server-side. Because it uses async + is a long-running server (not a 60 s serverless function), it has no timeout. Its only env var is `CLIVER_API_KEY`. *(Supersedes the old Vercel `…/cliver.html` proxy, which hit the Vercel Hobby 60 s function cap.)*

## Upstream contribution
`PR_DRAFT.md` is the ready-to-send pull request back to `alejoacelas/api-cliver` (the fix makes their hosted API work again). Submit with `gh pr create --repo alejoacelas/api-cliver --base master --head safelybio:fix/openrouter-chat-completions --body-file PR_DRAFT.md` once it's been reviewed.
