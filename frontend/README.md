# TravelDesk — Travel Reimbursement Approval Console

A production-quality frontend for an AI travel-expense adjudication agent. Finance reviewers submit claims, inspect AI decisions, and handle escalated Manual Review cases (human-in-the-loop).

## Quick Start

### Mock mode (no backend required)

```bash
VITE_USE_MOCKS=1 npm run dev
```

All four outcomes work without a backend: `APPROVE`, `PARTIAL_APPROVE`, `REJECT`, and the full `MANUAL_REVIEW → human review → finalized` flow. Use **Load sample** on the New Claim form to try each fixture.

### Live mode (real backend)

```bash
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

Requests to `/api` are proxied to the backend URL, avoiding CORS issues (the backend does not set CORS headers). The proxy is configured in `vite.config.ts`.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `VITE_USE_MOCKS` | — | Set to `1` to use the frontend mock adapter (no backend needed) |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend URL for the Vite proxy target |

## Architecture

```
src/lib/
  types.ts       TypeScript interfaces mirroring the API contract
  schemas.ts     Zod schemas for form validation (mirrors §4 of the spec)
  fixtures.ts    Sample claims + deterministic mock responses for all 4 outcomes
  mock.ts        Frontend mock adapter — intercepts API calls when VITE_USE_MOCKS=1
  api.ts         API client (real fetch or mock, single source of truth)
  store.ts       Zustand store + localStorage persistence for submitted claims

src/app/
  routes.ts      React Router v7 route config
  App.tsx        QueryClientProvider + RouterProvider + Toaster

src/app/components/
  AppShell.tsx       Header, mode badge (live/mock from /healthz), nav
  ClaimsList.tsx     Claims queue — filterable list of all submitted claims
  SubmitClaim.tsx    Claim form with dynamic line items, Zod validation, sample loader
  DecisionDetail.tsx Decision view: amounts, deductions, policy refs, confidence meter
  HitlPanel.tsx      Human-in-the-loop review panel (approve / reject a Manual Review claim)
  ReasoningTrace.tsx Collapsible agent trace timeline (policy, tool_call, llm, guardrail, fallback)
  OutcomeBadge.tsx   Semantic outcome badge (APPROVE / PARTIAL_APPROVE / REJECT / MANUAL_REVIEW)
```

**Data flow**: Form submit → `POST /adjudicate` → response stored in Zustand/localStorage → navigate to decision detail. If the response has an `interrupt` (Manual Review), the HITL panel is shown. Approving/rejecting calls `POST /resume`, which replaces the decision in the store.

## Notes on Mock vs Live Backend Mode

- **VITE_USE_MOCKS=1** — no backend. Mock healthz reports `mode: "live"` so the HITL panel is enabled for demo purposes.
- **Real backend in mock mode** (`/healthz` → `mode: "mock"`) — `/adjudicate` never returns an interrupt; the HITL panel is shown but disabled with an explanatory tooltip.
- **Real backend in live mode** — full flow including interrupt/resume.
