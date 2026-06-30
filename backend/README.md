# Travel Reimbursement Approval Agent

An agentic system that reviews an employee travel‑expense claim against policy and returns a
structured recommendation — **Approve / Partially Approve / Reject / Manual Review** — with the
approved amount, itemized deductions, missing documents, policy references, confidence, and an
explanation.

It is built on **LangGraph** (durable Postgres checkpointer + human‑in‑the‑loop), tools served over
**MCP**, observability via self‑hosted **Langfuse v2**, and evaluation via **DeepEval**. The LLM is
**`gpt-oss-120b`** on an **Azure AI Foundry OpenAI‑compatible** endpoint.

> **Design thesis:** the LLM is *advisory*; a deterministic core is *authoritative*. The LLM drives the
> agentic tool loop and the qualitative judgement, but a deterministic guardrail recomputes every
> money figure and outcome. This is deliberate — `gpt-oss` can hallucinate numbers and its tool‑calling
> can be flaky, so money decisions must be reproducible and auditable.

---

## Architecture

```
POST /adjudicate (claim)        FastAPI lifespan owns: MCP stdio client + checkpointer (Postgres/in‑memory) + compiled graph
        │
        ▼      ┌──────────────────── LangGraph StateGraph (checkpointed by thread_id = claim_id) ────────────────────┐
   intake ───▶ │ validate claim + pre‑compute deterministic facts, seed them into the prompt (grounding)             │
        │      │ agent: gpt-oss (ChatOpenAI) bound to MCP fact‑tools + submit_decision                                │
        │      │   ├─ tool calls → ToolNode → MCP server (stdio): lookup_policy, check_per_diem_or_limit,             │
        │      │   │                check_receipt_completeness, detect_duplicates, check_approval_threshold (ADVISORY)│
        │      │   └─ submit_decision (qualitative Proposal) → reconcile = gather_facts()+decide()  (AUTHORITATIVE)   │
        │      │         └─ if MANUAL_REVIEW → interrupt() for a human approver (durable pause)                       │
        ▼      └──────────────────────────────────────────────────────────────────────────────────────────────────┘
   POST /resume (approve/reject) ─▶ same thread_id ─▶ finalize (human sets the outcome; amounts stay deterministic)

   Langfuse v2 records a trace per adjudication (manual spans).   DeepEval scores decisions offline.
   No Azure key → MOCK mode: the deterministic pipeline runs with no network (cold‑clone runnable).
```

**Who owns what**

| Concern | Owner |
|---|---|
| Tool orchestration, qualitative judgement (business purpose, "looks personal?"), explanation | **LLM** (advisory; may only *escalate* to Manual Review, never loosen) |
| Money math, caps, deductions, duplicate keys, required‑doc presence, final outcome, rule IDs | **Deterministic core** (`decide()` — authoritative) |
| Human approve/reject on Manual Review (outcome only; amounts unchanged) | **Human**, via the durable interrupt/resume |

If the LLM errors or returns an invalid proposal, `decide(..., llm_failed=True)` routes the claim to
**Manual Review** — the system never auto‑approves on failure.

---

## Quickstart

Requirements: Python 3.12, [`uv`](https://docs.astral.sh/uv/), and (for the live/full stack) Docker.

### 1. Mock mode — runs on a cold clone, no secrets, no Docker
```bash
uv sync
uv run python main.py batch          # adjudicates the 4 sample claims → outputs/*.decision.json
uv run pytest                         # 45 tests, fully offline
```

### 2. Live mode (gpt-oss) + self‑hosted infra
```bash
cp .env.example .env                  # fill in AZURE_OPENAI_API_KEY (+ base_url); .env is gitignored
docker compose up -d postgres langfuse        # Postgres (checkpointer) + Langfuse v2  (~30s to healthy)
uv run uvicorn app.api:app --port 8000        # API in live mode
# …or one claim via the CLI:
uv run python main.py evaluate data/claims/01_approve.json
```

### 3. Everything in Docker
```bash
docker compose up -d                  # postgres + langfuse v2 + the app (port 8000)
```

Langfuse UI: <http://localhost:3000> (seeded login `demo@example.com` / `demopassword123`).

---

## Usage

**CLI**
```bash
python main.py evaluate <claim.json>                 # live if Azure key set, else mock
python main.py evaluate <claim.json> --mock          # force deterministic
python main.py evaluate data/claims/04_manual_review.json --resume-as approve   # HITL end‑to‑end
python main.py batch                                 # deterministic; writes outputs/
```

**API**
```bash
curl -s localhost:8000/healthz
curl -s -X POST localhost:8000/adjudicate -H 'Content-Type: application/json' \
     -d "{\"claim\": $(cat data/claims/04_manual_review.json)}"
# → returns {"interrupt": {...}, ...} when a human is needed; then:
curl -s -X POST localhost:8000/resume -H 'Content-Type: application/json' \
     -d '{"claim_id":"CLM-2026-0004","approved":true,"approver":"manager_jane"}'
```

---

## Policy & data (all mock; USD)

`config/policy.yaml` is the **single source of truth for every number** (per‑diem caps, mileage rate,
receipt threshold, category limits, approval tiers, confidence/reject thresholds), seeded from public
standards (GSA FY2026 lodging $110/night & M&IE $68/day; IRS 2026 mileage $0.725/mi; $75 receipt
threshold). `data/policy.md` is prose that references rule IDs (`POL-LODGING`, …) without restating
numbers, so the two cannot drift. `data/claims/*.json` are the four sample claims (one per outcome);
`data/prior_claims.json` backs duplicate detection; `data/golden/*.json` are the eval expectations.

---

## Observability — Langfuse v2 (manual instrumentation)

Each adjudication is recorded as a Langfuse trace. **Note:** the langfuse **v2** SDK ships a LangChain
`CallbackHandler` that imports `langchain.callbacks` — a module removed in **langchain v1** (which this
project is pinned to via `langchain-mcp-adapters`). So instead of the callback we instrument **manually**
with the v2 low‑level client (`app/tracing.py`), which is decoupled from the LangChain version. Tracing
**no‑ops cleanly** when `LANGFUSE_*` keys are absent, so it never blocks a run.

---

## Evaluation — DeepEval (`tests/test_eval.py`)

- **Deterministic gate (default, offline, no keys):** a custom `DecisionMatch` metric asserts the exact
  decision and approved/rejected amounts against `data/golden/*.json`. This is the metric that matters
  for a money decision — it runs with no LLM and no network.
- **Opt‑in qualitative judge:** set `RUN_LLM_JUDGE=1` to score explanation groundedness with `gpt-oss`
  as the judge (`tests/eval_judge.py`). **Caveat (a real finding):** `gpt-oss` is a weak *structured‑output*
  judge — under heavy reasoning it leaks its answer into the harmony reasoning channel — so the judge runs
  at low reasoning effort with lenient parsing, and *skips with a clear reason* rather than failing if it
  still can't produce a score. Deterministic metrics remain authoritative.

```bash
uv run deepeval test run tests/test_eval.py          # or: uv run pytest tests/test_eval.py
RUN_LLM_JUDGE=1 uv run pytest tests/test_eval.py::test_explanation_is_grounded
```

---

## Testing

`uv run pytest` → **45 tests** (1 opt‑in judge skipped), fully offline:
`test_tools` (money‑math boundaries), `test_decision` (4 outcomes + manual‑review triggers + LLM
reconciliation), `test_mcp` (the MCP server over stdio), `test_graph` (the graph with a **mocked LLM** +
in‑memory checkpointer: happy path, agentic tool loop, interrupt→resume approve/reject, invalid‑proposal
fallback), `test_api` (FastAPI in mock mode), `test_eval` (DeepEval).

---

## Project structure

```
app/
  models.py       # Pydantic contracts: Claim, LineItem, Proposal, Decision, ToolResults, Trace
  config.py       # env settings + policy loader
  tools.py        # deterministic money math + checks (the ground truth)
  decision.py     # decide(): the authoritative guardrail + reconciliation + mock/fallback engine
  mcp_server.py   # FastMCP stdio server exposing the fact tools
  llm.py          # ChatOpenAI → gpt-oss
  checkpoint.py   # AsyncPostgresSaver (DATABASE_URL) or InMemorySaver fallback
  graph.py        # the LangGraph StateGraph (intake → agent → tools → reconcile + HITL interrupt)
  runner.py       # shared orchestration for API & CLI (+ mock path)
  tracing.py      # Langfuse v2 manual spans (no‑op without keys)
  api.py          # FastAPI: /adjudicate, /resume, /healthz
main.py           # CLI: evaluate / batch
config/policy.yaml · data/{policy.md,claims,prior_claims.json,golden} · tests/ · docker-compose.yml · Dockerfile
```

---

## Design choices & trade‑offs

- **LangGraph over a hand‑rolled loop** — gives a durable, resumable state machine; the Postgres
  checkpointer makes human‑in‑the‑loop *interrupt → resume* survive restarts (thread = `claim_id`).
- **MCP fact tools, but a deterministic reconcile node** — the LLM uses MCP tools for grounding and
  transparency, yet the final amounts come from `gather_facts()`/`decide()` in‑process, so a dropped or
  malformed tool call can never corrupt a money decision.
- **gpt-oss tool‑calling is real but not guaranteed** — verified working on this Azure deployment, but
  the deterministic fallback (→ Manual Review) covers the documented harmony/parsing failure modes.
- **Langfuse v2, self‑hosted** — lightweight (one container + Postgres) vs v3's ClickHouse/Redis/S3
  footprint; manual instrumentation sidesteps the v2‑SDK/langchain‑v1 incompatibility.
- **Graceful degradation everywhere** — no Azure key → mock mode; no `DATABASE_URL` → in‑memory
  checkpointer; no Langfuse keys → tracing off. A cold clone runs and is testable with zero setup.

## Assumptions & limitations

- All amounts are **USD** (no multi‑currency/FX — explicitly out of scope).
- Receipts are represented as **metadata** on line items (`has_receipt`); no image/OCR extraction.
- Duplicate detection is deterministic exact/near‑key matching (no fuzzy/embedding matching).
- In‑memory checkpointer loses state on restart and can't back multi‑worker deployments (demo‑only).
- `gpt-oss` is a capable adjudicator but a weak structured‑output *judge* (see Evaluation).
- **Next steps:** real receipt extraction, per‑country policy/VAT, a richer approver UI on top of `/resume`.

## Sample outputs

`outputs/` contains a generated decision per sample claim (`*.decision.json`, including the reasoning
trace) plus a human‑in‑the‑loop transcript — regenerate with `python main.py batch`.
