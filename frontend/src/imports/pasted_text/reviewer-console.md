# Frontend Engineering Brief — Travel Reimbursement Approval Agent (Reviewer Console)

## 1. Your role & mission
You are a senior frontend engineer. Build a polished, production-feeling **web console** for an
AI travel-reimbursement approval agent. A finance reviewer uses it to submit an expense claim,
see the agent's structured recommendation, act on claims the agent escalates for human review
(approve/reject), and inspect *why* the agent decided what it did.

**Build the frontend only. Do not modify the backend.** Treat the API below as a fixed contract.

## 2. Product context (what the backend does)
The backend adjudicates a travel-expense **claim** against policy and returns one of four outcomes:
- `APPROVE` — fully within policy.
- `PARTIAL_APPROVE` — some line items over caps; the over-cap amount is deducted, remainder approved.
- `REJECT` — e.g. a non-reimbursable (personal) expense; nothing approved.
- `MANUAL_REVIEW` — uncertain/incomplete (missing receipt, suspected duplicate, exceeds auto-approval
  limit, low confidence). The agent **pauses and waits for a human** — this is the human-in-the-loop
  (HITL) flow you must surface.

All money math is deterministic and authoritative; the LLM is advisory. **Never let the UI imply the
user can change computed amounts** — a human reviewer only **confirms (approve)** or **overrides (reject)**
the *outcome* of a Manual-Review claim; the amounts stay as computed.

The backend runs in **`live`** mode (real LLM) or **`mock`** mode (deterministic, no secrets). Show the
current mode as a badge. In mock mode, `/adjudicate` never returns an interrupt (no HITL).

## 3. API contract (fixed — build against this exactly)

Base URL via env: `VITE_API_BASE_URL` (default `http://localhost:8000`). In dev, use a **Vite proxy**
(`/api` → backend) to avoid CORS, since the backend does not set CORS headers. Document this.

### `GET /healthz`
→ `200 { "status": "ok", "mode": "live" | "mock" }`

### `POST /adjudicate`
Request:
```json
{ "claim": <Claim>  /* see §4 */ }
```
Response (mock mode):
```json
{ "decision": <Decision>, "interrupt": null, "trace": <Trace>, "mode": "mock" }
```
Response (live mode, auto-decided):
```json
{ "decision": <Decision>, "interrupt": null, "mode": "live" }
```
Response (live mode, **needs a human** — Manual Review):
```json
{
  "decision": null,
  "interrupt": {
    "claim_id": "CLM-2026-0004",
    "proposed_decision": "MANUAL_REVIEW",
    "approved_amount": 570.0,
    "manual_review_reasons": ["Missing required receipt(s): L1 (airfare): receipt required for $450.0 (>75) [POL-RECEIPT]"],
    "required_approver_role": "manager"
  },
  "mode": "live"
}
```

### `POST /resume` (finalize a Manual-Review claim; live mode only)
Request:
```json
{ "claim_id": "CLM-2026-0004", "approved": true, "approver": "manager_jane", "note": "Receipt provided offline" }
```
Response: `{ "decision": <Decision>, "interrupt": null, "mode": "live" }`
- `approved: true`  → outcome becomes `APPROVE` (or `PARTIAL_APPROVE` if there were deductions); amounts unchanged.
- `approved: false` → outcome becomes `REJECT`, `approved_amount` 0.
- In mock mode `/resume` returns `{ "error": "..." }` — handle gracefully (resume is disabled).

**There is no list/history endpoint.** The UI must keep its own list of submitted claims + their
results in client state (persist to `localStorage`). Use `claim.claim_id` as the key/thread id;
`/resume` must reuse the same `claim_id`.

## 4. Data models (mirror these with Zod for form validation + typing)

**Claim (input):**
```ts
type Category = "lodging" | "meals" | "airfare" | "ground_transport" | "mileage" | "other" | "personal";
interface LineItem {
  id: string;                 // e.g. "L1"
  category: Category;
  description: string;
  amount: number;             // USD, >= 0
  date: string;               // ISO date "YYYY-MM-DD"
  vendor?: string | null;
  location?: string | null;   // city, for lodging locality overrides
  quantity?: number | null;   // nights (lodging) / days (meals) / miles (mileage)
  has_receipt?: boolean;      // default false
  receipt_text?: string | null;
}
interface Claim {
  claim_id: string;
  employee_id: string;
  employee_role?: string;     // default "employee" (affects approval tier)
  trip_purpose?: string;      // business justification (qualitative; the LLM judges adequacy)
  destination?: string | null;
  start_date?: string | null; // ISO date
  end_date?: string | null;
  currency?: string;          // "USD" only (assumption)
  line_items: LineItem[];
}
```

**Decision (output):**
```ts
type Outcome = "APPROVE" | "PARTIAL_APPROVE" | "REJECT" | "MANUAL_REVIEW";
interface Deduction { line_item_id: string; amount: number; reason: string; policy_ref?: string | null; }
interface Decision {
  decision: Outcome;
  claimed_amount: number;
  approved_amount: number;
  rejected_amount: number;
  deductions: Deduction[];
  missing_documents: string[];
  policy_references: string[];   // e.g. ["POL-LODGING","POL-APPROVAL"]
  confidence: number;            // 0..1
  explanation: string;
  manual_review_reasons: string[];
}
```

**Trace (present in mock responses; render if available):**
```ts
interface TraceStep { kind: string; /* policy|tool_call|llm|guardrail|fallback */ summary: string; detail?: Record<string, unknown> | null; }
interface Trace { mode: string; steps: TraceStep[]; }
```

## 5. Tech stack & conventions
- **React 18 + TypeScript + Vite**.
- **Tailwind CSS + shadcn/ui** for components; **lucide-react** icons.
- **TanStack Query** for all API calls (mutations for adjudicate/resume; query for healthz with light polling).
- **React Hook Form + Zod** for the claim form, schema mirroring §4.
- A typed **API client module** (`src/lib/api.ts`) — single source for endpoints, types, base URL/proxy.
- A **mock adapter** (e.g. MSW or a `VITE_USE_MOCKS=1` switch) implementing the contract with the §8
  fixtures, so the UI is fully developable/demoable **without the backend running**. This mirrors the
  backend's own mock philosophy.
- State: TanStack Query cache + a small client store (Zustand or context) + `localStorage` for the
  submitted-claims list.

## 6. Views to build
1. **App shell** — header with product name, a **mode badge** (live/mock from `/healthz`, polled), nav.
2. **Claims list / queue** (home) — client-side list of submitted claims with: claim id, employee,
   total, outcome badge, and a clear **"Action needed"** state for claims awaiting human resume.
   Filter/sort by outcome. Empty state with a CTA to submit one.
3. **Submit claim** — form for the Claim + a dynamic line-items editor (add/remove rows; category,
   amount, date, quantity, vendor, receipt toggle). Zod validation. Offer a **"load a sample claim"**
   helper using the §8 fixtures. On submit → `POST /adjudicate` → route to the detail view.
4. **Decision detail** — the heart of the app:
   - Prominent **outcome badge** with semantic color (see §7) and the one-line `explanation`.
   - **Amounts**: claimed → approved → rejected (a clear visual, e.g. a stacked bar / summary cards).
   - **Deductions table**: line item, amount deducted, reason, `policy_ref` chip.
   - **Missing documents** list (warning style) and **policy references** as chips.
   - **Confidence** as a labeled meter (e.g. 0.99 → "High").
   - **HITL panel** (only when the response had an `interrupt`, i.e. Manual Review pending): show
     `proposed_decision`, `manual_review_reasons`, `required_approver_role`; inputs for approver name +
     optional note; **Approve** and **Reject** buttons → `POST /resume` → replace with the finalized
     Decision and update the list. Disable this panel in mock mode with an explanatory tooltip.
   - **Reasoning trace** (collapsible) — render `trace.steps` as a vertical timeline; expand a step to
     see `detail` (pretty-printed). This is the "why" view; make it genuinely useful, not raw JSON dump.
5. **Error / loading / empty** states everywhere: request in flight, network error (with retry),
   `/resume` error in mock mode, validation errors inline on the form.

## 7. Design direction
Enterprise **fintech / approvals** tool: trustworthy, dense-but-calm, scannable. Make intentional,
distinctive choices — **do not ship a generic AI-template look**. Establish a real type scale, spacing
rhythm, and one confident accent. Outcome semantics (use consistently, with text labels + icons, not
color alone — accessibility):
- APPROVE → green/success · PARTIAL_APPROVE → amber/warning · REJECT → red/destructive ·
  MANUAL_REVIEW → blue or violet/"needs attention".
Requirements: responsive (usable down to ~768px), keyboard-accessible, WCAG-AA contrast, focus states,
sensible loading skeletons. Money formatted as USD; dates human-readable.

## 8. Fixtures (use for the mock adapter and the "load sample" helper)
Provide four sample claims and their expected results so the UI demonstrates all four outcomes + the
HITL flow. Concretely:
- `01_approve` → APPROVE, claimed 420, approved 420, no deductions.
- `02_partial` → PARTIAL_APPROVE, claimed 420, approved 340, one deduction of 80 on line "L1"
  (lodging over the per-night cap), policy_ref `POL-LODGING`.
- `03_reject` → REJECT, claimed 90, approved 0 (a `personal` line item — non-reimbursable, `POL-NONREIMB`).
- `04_manual_review` → in **live** mode returns an `interrupt` (missing airfare receipt > $75,
  `POL-RECEIPT`, approver `manager`); resuming with `approved:true` finalizes to APPROVE, approved 570.
(Build the sample Claim JSON to match these, following §4. If the real backend is available, you can
also fetch real responses to refine fixtures — but the mock adapter must stand alone.)

## 9. Out of scope (do not build)
Auth/login, multi-user/roles enforcement, real persistence/DB, receipt image upload/OCR, multi-currency,
editing the policy, and any backend changes. (You may scaffold a Vite proxy config; that's it on the
server side.)

## 10. Definition of done (acceptance criteria — verify before declaring done)
- `npm install && npm run dev` runs; `npm run build` and `tsc --noEmit` (typecheck) and lint pass clean.
- With `VITE_USE_MOCKS=1` (no backend), every view works and all **four outcomes render**, plus the
  **submit → interrupt → resume → finalized** HITL flow using the mock adapter.
- Pointed at a real backend (`VITE_API_BASE_URL` via the dev proxy): submitting each of the four sample
  claims produces the matching outcome; a Manual-Review claim shows the HITL panel and resume works.
- Mode badge reflects `/healthz`. Errors, loading, and empty states are handled (no unhandled rejections,
  no crash on `decision: null`).
- A short `README.md`: how to run (mock + live), env vars, the Vite proxy/CORS note, and a 4-line
  architecture overview.
- Provide a brief plain-language walkthrough of the main components and data flow on completion.

## 11. Working method
State your assumptions and the component/route map before coding. Build the API client + types + mock
adapter first, then the Decision-detail view (the core), then the form and list. Keep components small
and typed; reuse shadcn primitives. Match the contract in §3–§4 exactly — if anything there seems wrong,
flag it rather than diverging.