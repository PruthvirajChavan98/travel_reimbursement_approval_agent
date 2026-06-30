# Travel Reimbursement Approval Agent

An agentic system that reviews employee **travel‑expense claims** against company policy and returns a
structured, auditable recommendation — **Approve / Partially Approve / Reject / Manual Review** — with the
approved amount, itemized deductions, missing documents, policy references, a confidence score, and a plain
explanation. Uncertain or exception cases are **not forced** to a decision: they pause for a human approver
(human‑in‑the‑loop) and resume exactly where they left off.

> **Design thesis — the LLM is advisory, the deterministic core is authoritative.**
> A large language model (`gpt-oss-120b`) orchestrates tools and judges *qualitative* questions ("is the
> business purpose adequate? does this look personal? is anything ambiguous?"). It can **only escalate** to
> Manual Review — it can never loosen an outcome or compute a number. A deterministic engine recomputes
> **every** money figure, deduction, policy reference, and the final outcome. So decisions are
> **reproducible, auditable, and safe even when the model misbehaves**.

This repository is a **monorepo**: a Python **FastAPI + LangGraph** agent backend and a React **reviewer
console** frontend.

```
.
├── backend/    FastAPI + LangGraph agent · MCP tools · deterministic policy guardrail ·
│               Postgres checkpointer · Langfuse v2 tracing · DeepEval. See backend/README.md.
└── frontend/   React 19 + Vite + Tailwind v4 reviewer console ("Departure Board" UI) —
                TanStack Query · react-router · zustand. Talks to the backend over /api. See frontend/README.md.
```

---

## Table of contents

- [What it does](#what-it-does)
- [How it works (architecture)](#how-it-works-architecture)
- [The decision output](#the-decision-output)
- [The policy engine](#the-policy-engine)
- [Tools (MCP)](#tools-mcp)
- [Receipt scanning (VLM)](#receipt-scanning-vlm)
- [The reviewer console (frontend)](#the-reviewer-console-frontend)
- [Tech stack](#tech-stack)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [CLI & API usage](#cli--api-usage)
- [Testing & evaluation](#testing--evaluation)
- [Observability](#observability)
- [Modes & graceful degradation](#modes--graceful-degradation)
- [Sample scenarios](#sample-scenarios)
- [How it maps to the assignment](#how-it-maps-to-the-assignment)
- [Design choices, trade‑offs & limitations](#design-choices-trade-offs--limitations)
- [Repository layout](#repository-layout)

---

## What it does

1. **Intake** a claim (JSON via API/CLI, or the web form). A claim is an employee + a list of line items
   (lodging, meals, airfare, ground transport, mileage, other, personal), each with an amount, date,
   optional vendor/location/quantity, and a `has_receipt` flag.
2. **Ground** the claim in policy: per‑diem caps, receipt rules, duplicate detection, and approval tiers.
3. **Reason** over it with an agent that calls fact tools and forms a qualitative recommendation.
4. **Decide** deterministically: the engine recomputes the authoritative amounts and outcome.
5. **Escalate** to a human when the claim is incomplete, over an approval threshold, a suspected duplicate,
   uses an unknown category, or is low‑confidence — and **resume** once the human approves or rejects.
6. **Explain & trace** every step (structured output + a reasoning trace + optional Langfuse traces).

---

## How it works (architecture)

Adjudication is a **LangGraph state machine** (`backend/app/graph.py`). The LLM lives inside an agentic
tool loop; a deterministic `reconcile` node is the final authority.

```
                 ┌──────────────────────── the agentic loop ───────────────────────┐
                 │                                                                  │
 START ─▶ intake ─▶ agent ──(LLM calls fact tools)──▶ tools (ToolNode) ─────────────┘
   │       │          │                                   (loops back to agent)
   │       │          └──(LLM calls submit_decision, or stops)──▶ reconcile ─▶ END
   │       │                                                          │
   │       │  intake: validate claim + pre-compute facts              │ reconcile (DETERMINISTIC AUTHORITY):
   │       │           (gather_facts) + seed the prompt               │  recompute facts → decide()
   │       │                                                          │  • if MANUAL_REVIEW → interrupt()
   │       └─ LLM is bound to 5 MCP fact-tools + submit_decision       │      ⏸  pause for a human approver
   │          (advisory: judges quality, never computes money)         │      ▶  resume via Command(resume=…)
   │                                                                   │  • else APPROVE / PARTIAL / REJECT
   └─ checkpointer (Postgres or in-memory) persists state at the interrupt for durable HITL
```

**Who owns what**

| Actor | Responsibility | Can it change money / outcome? |
|---|---|---|
| **LLM** (`gpt-oss-120b`, advisory) | Tool orchestration; qualitative judgment; the explanation. | **No** — it may only *escalate* to Manual Review. |
| **Deterministic core** (`decision.py` + `tools.py`) | All caps, allowed/deducted amounts, duplicate keys, receipt presence, approval tier, final outcome, rule IDs. | **Yes** — it is the single source of truth. |
| **Human** (durable interrupt/resume) | Approve or reject a Manual‑Review claim. | Outcome only — **amounts are never edited**. |

If the LLM errors or returns an invalid proposal, the engine runs with `llm_failed=True` and routes to
**Manual Review** — it never auto‑approves on failure.

The agent path is wired in `runner.py` (`live_graph`): it launches the MCP tool server over **stdio**,
builds a plain `ChatOpenAI` against the OpenAI‑compatible endpoint, and compiles the graph with a
checkpointer. A separate `run_mock` path runs the same deterministic engine with **no network** so a fresh
clone works out of the box.

---

## The decision output

Every adjudication returns the same structured `Decision` (the assignment's required fields):

| Field | Meaning |
|---|---|
| `decision` | `APPROVE` · `PARTIAL_APPROVE` · `REJECT` · `MANUAL_REVIEW` |
| `claimed_amount` | Total claimed (USD) |
| `approved_amount` | Total approved after caps |
| `rejected_amount` | Claimed − approved |
| `deductions[]` | Per‑line `{line_item_id, amount, reason, policy_ref}` |
| `missing_documents[]` | Receipts required but absent (over the $75 threshold) |
| `policy_references[]` | The `POL-*` rules applied |
| `confidence` | 0.0–1.0 (deterministic, only ever *lowered* by the LLM) |
| `explanation` | Short human‑readable rationale |
| `manual_review_reasons[]` | Why it was escalated (populated only for Manual Review) |

**Outcome logic** (deterministic, manual‑review‑first):

1. **Any** escalation reason → `MANUAL_REVIEW` — missing receipt > $75, suspected duplicate, unknown
   category, total over the auto‑approval limit, final confidence < `0.6`, or an LLM failure/escalation/
   reject‑conflict.
2. else `approved_amount ≤ 0` → `REJECT`
3. else `approved_amount < claimed_amount` → `PARTIAL_APPROVE`
4. else → `APPROVE`

**Confidence** starts at `1.0` and is penalized: −0.4 missing documents, −0.3 suspected duplicate, −0.4
unknown category, −0.2 over the auto‑approval limit (clamped to `[0,1]`); the LLM's confidence can only
pull it **down** (`min`).

---

## The policy engine

All numbers live in one place — `backend/config/policy.yaml` (version `2026-06-29`, USD) — each tagged with
a `POL-*` rule ID. The prose mirror is `backend/data/policy.md`.

| Category | Cap | Rule |
|---|---|---|
| Lodging | **$110 / night** (locality overrides: New York $300, San Francisco $270, Washington $250) | `POL-LODGING` |
| Meals (M&IE) | **$68 / day** | `POL-MEALS` |
| Airfare | **$1,500 / line** | `POL-AIRFARE` |
| Ground transport | **$200 / line** | `POL-GROUND` |
| Other | **$100 / line** | `POL-OTHER` |
| Mileage | **$0.725 / mile** | `POL-MILEAGE` |
| Personal | **$0** (non‑reimbursable) | `POL-NONREIMB` |

- **Receipts** are required for any line item **strictly above $75** (`POL-RECEIPT`) — missing ones route to
  Manual Review, not auto‑reject.
- **Approval tiers** (`POL-APPROVAL`): ≤ **$2,500** → *manager* (auto‑approve); ≤ **$10,000** → *director*;
  above → *vp*. Anything above auto‑approve routes to Manual Review.
- **Duplicates** (`POL-DUPLICATE`): same employee + vendor, amount within **$0.01**, dates within **±1 day**
  (vs. prior claims and within the claim) → Manual Review.
- **Confidence floor** (`POL-CONFIDENCE`): final confidence below **0.6** → Manual Review; approved ≤ `0.0`
  → Reject.
- An **unknown category** (no matching rule) does *not* deduct — it forces Manual Review (a policy gap a
  human should resolve).

Tuning the policy means editing YAML — no code changes.

---

## Tools (MCP)

Five **read‑only fact tools** are served over the **Model Context Protocol** (FastMCP, `stdio`,
`backend/app/mcp_server.py`, server name `travel-tools`) and consumed via `langchain-mcp-adapters`:

| Tool | Purpose |
|---|---|
| `lookup_policy` | Return the rule + cap for a category |
| `check_per_diem_or_limit` | Cap / allowed / deduction for one line (nights, days, miles, locality) |
| `check_receipt_completeness` | List line items missing a required receipt |
| `detect_duplicates` | Flag suspected duplicates vs. prior + within the claim |
| `check_approval_threshold` | Required approver role + whether the total auto‑approves |

The LLM also calls a local `submit_decision` "tool" (a sentinel, not executed) to hand in its qualitative
proposal. **None of these are trusted for the final math** — the `reconcile` node recomputes ground truth.

---

## Receipt scanning (VLM)

`POST /receipts/extract` turns an uploaded bill into pre‑filled claim fields. Routing is deterministic
(PyMuPDF): a **parsable PDF** (text layer ≥ 15 chars) goes to the **text LLM** (`gpt-oss-120b`); an **image
or scanned PDF** is sent to a **vision model** (`Kimi-K2.6`), rasterizing the page and stepping the DPI down
(200→150→110→80) to stay under the per‑image limit. Uploads are capped at **20 MB** (413 over the cap, 415
for unsupported types); any model/transport failure degrades to `source="unavailable"` instead of erroring.

---

## The reviewer console (frontend)

A single‑page React app with a deliberate **"Departure Board"** visual identity (it's a *travel* desk):

- **Claims Queue** — a dark split‑flap **departures board**; each claim is a row with a flight‑status verdict
  chip (Cleared / Partial / Denied / At gate); the one awaiting a human pulses amber.
- **Decision detail** — the claim rendered as a **boarding pass** with a rotated rubber **stamp** of the
  verdict, a confidence gauge, the deductions table, and a collapsible reasoning trace.
- **Held at the gate (HITL)** — a reviewer enters their name and approves/rejects an escalated claim
  (disabled with a tooltip if the backend is in mock mode, which never interrupts).
- **Submit / check‑in** — a validated claim form with a dynamic line‑item editor, "Load sample" fixtures,
  and a **scan‑a‑bill** drop zone wired to `/receipts/extract`.

It calls the backend through a `/api` proxy, or runs **fully offline** with `VITE_USE_MOCKS=1` (a mock
adapter reproduces all four outcomes and the resume flow). The client `zustand` store *is* the queue — there
is no server‑side list endpoint.

---

## Tech stack

**Backend** — Python 3.12 · FastAPI · **LangGraph** (`1.2.6`, Postgres/in‑memory checkpointer) · LangChain
1.x + `langchain-openai` · **MCP** (FastMCP + `langchain-mcp-adapters`) · Pydantic v2 · PyMuPDF · Langfuse
v2 · DeepEval · packaged with **uv**.

**Frontend** — React 19 · Vite 6 · Tailwind v4 (CSS‑first) · shadcn/ui (Radix) · TanStack Query ·
react‑router 7 · zustand (+persist) · react‑hook‑form + zod · sonner.

**Infra** — Docker Compose (postgres · langfuse · api · web/nginx · cloudflared) · Cloudflare Tunnel.

---

## Quickstart

### Option A — local dev (two terminals)

```bash
# 1) Backend — mock mode with no key; live if backend/.env has AZURE_OPENAI_API_KEY
cd backend && uv sync && uv run uvicorn app.api:app --reload --port 8000

# 2) Frontend — Vite dev server, proxies /api → http://localhost:8000
cd frontend && npm install && npm run dev          # http://localhost:5173
```

Frontend‑only demo, **no backend needed**: `cd frontend && VITE_USE_MOCKS=1 npm run dev`.

### Option B — full stack in Docker

```bash
cp backend/.env.example backend/.env               # optional: add AZURE_OPENAI_* for live mode
docker compose up -d                               # postgres + langfuse v2 + api + web + cloudflared
```

> **Note on ports:** the compose stack publishes **no host ports** — it is fronted by a **Cloudflare
> Tunnel** (`cloudflared`), so the only public entrypoint is the tunnel (routes are configured in the
> Cloudflare dashboard → in‑network `web:80`). To browse locally instead, either use **Option A** (dev
> servers on `:5173` / `:8000`) or add a `ports:` mapping to compose (e.g. `8081:80` on `web`,
> `3000:3000` on `langfuse`). Leave `TUNNEL_TOKEN` blank to disable the tunnel.

### Make targets

```bash
make install     # uv sync (backend) + npm install (frontend)
make dev-api     # run the API (uvicorn app.api:app --reload --port 8000)
make dev-web     # run the frontend dev server (Vite)
make test        # backend test suite (60 tests)
make build       # build the frontend production bundle
make up / down   # docker compose up -d / down
```

---

## Configuration

All backend config is environment‑driven (`backend/.env`, gitignored; template in `backend/.env.example`).
Everything degrades gracefully when unset.

| Variable | Default | Effect |
|---|---|---|
| `AZURE_OPENAI_BASE_URL` | — | OpenAI‑compatible endpoint (`…/openai/v1`). **Required for live mode.** |
| `AZURE_OPENAI_API_KEY` | — | API key. **Blank ⇒ deterministic mock mode** (no network). |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-oss-120b` | Text model name |
| `AZURE_OPENAI_REASONING_EFFORT` | `high` | `low` \| `medium` \| `high` |
| `DATABASE_URL` | — | Set ⇒ durable **Postgres** checkpointer; blank ⇒ **in‑memory** (state lost on restart) |
| `VLM_MODEL` | `Kimi-K2.6` | Vision model for receipt images |
| `VLM_BASE_URL` / `VLM_API_KEY` | — | Reuse the Azure host/key when blank |
| `MAX_UPLOAD_MB` | `20` | Receipt upload cap |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | — | Both keys set ⇒ tracing on; else no‑op |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` | Allowed browser origins |
| `RUN_LLM_JUDGE` | — | `1` ⇒ run the opt‑in LLM‑judge eval (needs live creds) |
| `TUNNEL_TOKEN` | — | Cloudflare Tunnel token (blank disables the tunnel) |

Frontend: `VITE_USE_MOCKS=1` (offline mock adapter) · `VITE_API_BASE_URL` (default `http://localhost:8000`).

---

## CLI & API usage

**CLI** (`backend/main.py`):

```bash
cd backend
uv run python main.py evaluate data/claims/02_partial.json            # live if creds, else mock
uv run python main.py evaluate data/claims/04_manual_review.json --resume-as approve   # auto-resume HITL
uv run python main.py evaluate data/claims/01_approve.json --mock      # force deterministic
uv run python main.py batch                                            # all data/claims/*.json → outputs/*.decision.json
```

**HTTP API** (FastAPI, default `:8000`; behind the frontend it's under `/api`):

| Method & path | Body | Returns |
|---|---|---|
| `GET /healthz` | — | `{ status, mode }` (`mode` = `live` \| `mock`) |
| `POST /adjudicate` | `{ "claim": { … } }` | `{ decision, interrupt, trace, mode }` |
| `POST /resume` | `{ claim_id, approved, approver?, note? }` | `{ decision, mode }` (live only) |
| `POST /receipts/extract` | multipart `file` (PNG/JPG/PDF) | `ReceiptExtraction` |

```bash
curl -s localhost:8000/adjudicate -H 'content-type: application/json' \
  -d '{"claim": '"$(cat backend/data/claims/02_partial.json)"'}' | jq
# resume a Manual-Review claim (live mode):
curl -s localhost:8000/resume -H 'content-type: application/json' \
  -d '{"claim_id":"CLM-2026-0004","approved":true,"approver":"manager_jane"}' | jq
```

---

## Testing & evaluation

```bash
cd backend && uv run pytest          # 60 tests across 8 files; runs fully offline
```

The suite is layered: deterministic business logic (`test_tools` 16, `test_decision` 11), the MCP server
(`test_mcp` 4, an in‑process stdio subprocess), the LangGraph graph with a scripted fake LLM + in‑memory
checkpointer (`test_graph` 6), the FastAPI endpoints in mock mode (`test_api` 4), receipt routing/extraction
with a fake client (`test_receipts` 7, `test_receipts_api` 7), and the DeepEval suite (`test_eval` 5).

**Evaluation (DeepEval)** has two tiers:

- **Deterministic gate (default, offline, no keys):** a custom `DecisionMatch` metric asserts the exact
  decision + approved/rejected amounts for the four sample claims against `backend/data/golden/*.json`.
- **Opt‑in LLM judge (`RUN_LLM_JUDGE=1` + live creds):** scores explanation *groundedness* with `gpt-oss`
  as judge. Because gpt‑oss is a weak structured‑output judge, it runs at low reasoning effort with lenient
  parsing and **skips with a reason** rather than failing — the deterministic metrics stay authoritative.

```bash
cd backend && uv run deepeval test run tests/test_eval.py    # or: uv run pytest tests/test_eval.py
```

---

## Observability

When `LANGFUSE_*` keys are present, each adjudication is recorded as a **Langfuse v2** trace
(`backend/app/tracing.py`) via manual low‑level spans — chosen because the Langfuse v2 LangChain
`CallbackHandler` imports a module removed in LangChain v1. Tracing is wrapped so it can **never break
adjudication**, and no‑ops cleanly when keys are absent. The Docker stack self‑hosts Langfuse v2 (one
container + Postgres) with a seeded demo org/project.

---

## Modes & graceful degradation

The system is built to run with **zero setup** and add capability as you provide credentials:

| Missing | Behavior |
|---|---|
| `AZURE_OPENAI_API_KEY` | **Mock mode** — the deterministic pipeline runs with no network (cold‑clone runnable). |
| `DATABASE_URL` | In‑memory checkpointer (HITL works in‑process; state is lost on restart). |
| `LANGFUSE_*` | Tracing disabled (no‑op). |
| `TUNNEL_TOKEN` | Cloudflare tunnel disabled. |

Mock and live modes return the **same response shape**, so the frontend and tests don't care which is on.

---

## Sample scenarios

Four sample claims (`backend/data/claims/`), one per outcome, with expected results in
`backend/data/golden/`:

| Claim | Scenario | Outcome | Amounts |
|---|---|---|---|
| `01_approve` | 2 nights lodging + 3 days meals + rideshare, all in policy | **APPROVE** | $420 approved |
| `02_partial` | Lodging $150/night over the $110 cap | **PARTIAL_APPROVE** | $340 approved, $80 deducted (`POL-LODGING`) |
| `03_reject` | A personal (minibar/entertainment) expense | **REJECT** | $0 approved, $90 rejected (`POL-NONREIMB`) |
| `04_manual_review` | $450 airfare with no receipt (> $75) | **MANUAL_REVIEW** | $570 if a manager approves (`POL-RECEIPT`) |

---

## How it maps to the assignment

| Requirement | Where |
|---|---|
| Claim intake (JSON / form / API) | CLI, `POST /adjudicate`, the web form |
| Context grounding before deciding | `gather_facts` + the five policy fact tools |
| ≥ 2 meaningful tools | **Five** MCP tools (policy lookup, per‑diem, receipt check, duplicate detector, approval threshold) |
| Agentic GenAI workflow | LangGraph agent loop — the LLM decides when to call tools and combines results |
| Structured output | The `Decision` schema (decision, amounts, deductions, missing docs, policy refs, confidence, explanation) |
| Manual‑review handling | `interrupt()`/`resume` HITL; uncertain/incomplete/exception cases route to a human |
| *Optional:* UI | The React reviewer console |
| *Optional:* audit trail | Reasoning trace + Langfuse traces |
| *Optional:* tests / eval | 60‑test pytest suite + DeepEval golden gate |
| *Optional:* confidence / reason codes | `confidence` + `manual_review_reasons` |
| *Optional:* MCP integration | The FastMCP `travel-tools` server |

---

## Design choices, trade‑offs & limitations

- **Deterministic authority over LLM convenience.** Money is too important to trust to a model that can
  hallucinate numbers and call tools flakily — so the LLM is boxed into a qualitative, escalate‑only role.
- **Fail safe, not silent.** LLM failure, low confidence, unknown categories, and missing receipts all route
  to a human rather than guessing.
- **USD‑only, mock data.** No multi‑currency/FX; all policy/claims/receipts are sample data (no real
  employee/company data), per the assignment scope.
- **Receipts.** `has_receipt` is metadata; the bill‑scan VLM extraction pre‑fills the form but the human
  still owns the call.
- **Duplicate detection** is deterministic near‑key matching (no fuzzy/embedding similarity).
- **In‑memory checkpointer** is demo‑grade (single process, non‑durable); set `DATABASE_URL` for Postgres.
- **Next steps:** richer receipt OCR, per‑country policy/VAT, a fuller approver UI on `/resume`.

See **`backend/README.md`** (deep architecture, ownership model, observability/eval rationale, sample
outputs) and **`frontend/README.md`** (the reviewer console) for more.
