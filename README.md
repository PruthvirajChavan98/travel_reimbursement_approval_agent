# Travel Reimbursement Approval Agent — Monorepo

An agentic system that reviews employee travel‑expense claims against policy and returns a structured
recommendation — **Approve / Partially Approve / Reject / Manual Review** — with approved amount,
deductions, missing documents, policy references, confidence, and an explanation. It pauses for a human
approver on the uncertain cases (human‑in‑the‑loop).

```
.
├── backend/    FastAPI + LangGraph agent (gpt-oss on Azure) · MCP tools · Postgres checkpointer ·
│               Langfuse v2 tracing · DeepEval · deterministic policy guardrail. See backend/README.md.
└── frontend/   React + TypeScript + Vite + Tailwind v4 reviewer console (TanStack Query, react-router,
                zustand). Talks to the backend over /api. See frontend/README.md.
```

The LLM is **advisory**; a deterministic core is **authoritative** — every money figure and the final
outcome are recomputed deterministically, so decisions are reproducible and auditable.

## Quickstart

### Option A — local dev (two terminals)
```bash
# 1) Backend (mock mode if no Azure key; live if backend/.env has one)
cd backend && uv sync && uv run uvicorn app.api:app --reload --port 8000

# 2) Frontend (Vite dev server; proxies /api → http://localhost:8000)
cd frontend && npm install && npm run dev          # http://localhost:5173
```
Frontend‑only demo with no backend: `cd frontend && VITE_USE_MOCKS=1 npm run dev`.

### Option B — full stack in Docker
```bash
cp backend/.env.example backend/.env               # add AZURE_OPENAI_API_KEY for live mode (optional)
docker compose up -d                               # postgres + langfuse v2 + api + web
```
- Web UI: http://localhost:8081  ·  API: http://localhost:8000  ·  Langfuse: http://localhost:3000
- The `web` container (nginx) serves the built frontend and proxies `/api` → the `api` service.

## Make targets
```bash
make install     # uv sync (backend) + npm install (frontend)
make dev-api     # run the API
make dev-web     # run the frontend dev server
make test        # backend test suite (45 tests)
make up / down   # docker compose up -d / down
```

## How the pieces connect
- The frontend calls `/api/{healthz,adjudicate,resume}`. In dev, the **Vite proxy** forwards `/api` →
  `VITE_API_BASE_URL` (default `http://localhost:8000`). In Docker, **nginx** proxies `/api` → `api:8000`.
- The backend also enables **CORS** (`CORS_ORIGINS`, default `http://localhost:5173`) for direct
  browser→API calls.
- Modes: with an Azure key the backend runs the real **gpt-oss** agent (live, with HITL interrupts);
  without one it runs the **deterministic mock** pipeline — both return the same response shape.

See **backend/README.md** and **frontend/README.md** for details.
