# Running the (fixed) Cliver API

`safelybio`'s fork of [`alejoacelas/api-cliver`](https://github.com/alejoacelas/api-cliver) — an LLM-based KYC verification API for DNA-synthesis customers. **We fixed it:** upstream was returning 502 on every `/verify` because OpenRouter no longer serves the `/responses` endpoint the verification loop relied on.

## The fix
Branch `fix/openrouter-chat-completions` (merged into this `master`; that branch is kept clean for the upstream PR in `PR_DRAFT.md`).
- `app/openrouter.py` — ported `complete_with_tools` from the Responses API (`/responses`, now 404 on OpenRouter) to **Chat Completions** (`/chat/completions`); reads tool calls from `choices[0].message.tool_calls`; appends results as `role:"tool"` messages and re-calls to the cap. Tool schema added via `get_chat_tools` in `app/tools/registry.py`.
- `app/main.py` — `MAIN_MODEL = "google/gemini-3.1-pro-preview"` (a valid OpenRouter slug; the old `google/gemini-3-pro-preview` 404s).
- `app/constants.py` — `MAX_COMPLETION_TOKENS = 8000`.
- `pytest` → **31 passed**.

## What it is
One endpoint, `POST /verify`, gated by header `X-API-Key`. It runs an LLM tool-loop (OpenRouter → Gemini) with web search (Tavily) + ORCID / Europe PMC, and returns a `decision` (status **PASS/REVIEW/FLAG** + one-line summary), exactly **4 criteria** (each FLAG / NO FLAG / UNDETERMINED + an evidence paragraph + cited sources), optional `background_work` on the order, and a sources list. `GET /health` is open (no key). **Slow + paid:** ~30–90 s and roughly **10–20¢ per call** (a Gemini-pro tool loop).

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
- **Playground (easiest way to try it)** — a hosted form at the Safely Verify demo (`…/cliver.html`) posts to a Vercel serverless proxy that injects the `X-API-Key` server-side, so a link works without exposing the key. ⚠️ Vercel Hobby caps serverless functions at **60 s**, and Cliver runs often exceed that — for a reliable shareable URL, host the proxy on Railway instead. A standalone local playground (`cliver-playground.py`, served on `:8099`) has no timeout.

## Upstream contribution
`PR_DRAFT.md` is the ready-to-send pull request back to `alejoacelas/api-cliver` (the fix makes their hosted API work again). Submit with `gh pr create --repo alejoacelas/api-cliver --base master --head safelybio:fix/openrouter-chat-completions --body-file PR_DRAFT.md` once it's been reviewed.
