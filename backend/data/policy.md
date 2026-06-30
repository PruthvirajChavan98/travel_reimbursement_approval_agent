# Travel & Expense Reimbursement Policy

> Prose policy for grounding. **All numeric limits are defined authoritatively in
> `config/policy.yaml`** (referenced by the rule IDs below) — this document never
> restates figures, to avoid drift. All amounts are in **USD**.

## POL-LODGING — Lodging (per diem)
Hotel lodging is reimbursed up to a per-night cap, applied per night of the trip.
High-cost destinations have locality overrides. Amounts above the applicable cap
are deducted; the remainder is still reimbursable.

## POL-MEALS — Meals & Incidental Expenses (M&IE, per diem)
Meals and incidentals are reimbursed up to a daily cap, applied per day of travel.
Overages are deducted.

## POL-AIRFARE / POL-GROUND / POL-OTHER — Category limits
Airfare, ground transportation, and miscellaneous expenses are each reimbursed up
to a flat per-line cap. Overages are deducted.

## POL-MILEAGE — Personal-vehicle mileage
Mileage is reimbursed at the standard rate per mile times the miles driven. A claim
exceeding `miles × rate` is reduced to the allowed amount.

## POL-NONREIMB — Non-reimbursable expenses
Personal expenses are never reimbursable and are rejected in full.

## POL-RECEIPT — Receipt substantiation
Any line item above the receipt threshold requires an attached receipt. A missing
required receipt makes the claim incomplete and routes it to **Manual Review**
(per IRS accountable-plan substantiation: amount, time, place, business purpose).

## POL-APPROVAL — Approval authority
Claims within the auto-approval limit may be approved automatically. Claims above
that limit require a higher-level human approver and are routed to **Manual Review**.

## POL-DUPLICATE — Duplicate detection
An expense matching a prior claim (same employee, near-equal amount, same/adjacent
date, same vendor) — or repeated within the same claim — is a suspected duplicate
and is routed to **Manual Review**.

## POL-CONFIDENCE — Uncertainty handling
When the decision is uncertain — missing documents, an expense with no matching
policy rule, conflicting signals, or low confidence — the claim is routed to
**Manual Review** rather than forcing an automated decision.
