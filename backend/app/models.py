"""Pydantic domain models — the typed contracts shared across the system.

Two decision-shaped models, deliberately distinct:

* ``Proposal`` is what the LLM returns via the ``submit_decision`` tool. It is
  *qualitative only* (outcome, confidence, explanation, noticed gaps) — the LLM
  never does money math, because gpt-oss can hallucinate numerics.
* ``Decision`` is the final, authoritative output. All amounts are computed by
  the deterministic guardrail in ``decision.py``; the LLM's explanation is kept,
  its outcome may be overridden, and its confidence is only ever downgraded.
"""
from __future__ import annotations

import datetime
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Category(str, Enum):
    lodging = "lodging"
    meals = "meals"
    airfare = "airfare"
    ground_transport = "ground_transport"
    mileage = "mileage"
    other = "other"
    personal = "personal"  # non-reimbursable


class Outcome(str, Enum):
    APPROVE = "APPROVE"
    PARTIAL_APPROVE = "PARTIAL_APPROVE"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


# --------------------------------------------------------------------------- #
# Input                                                                       #
# --------------------------------------------------------------------------- #
class LineItem(BaseModel):
    id: str
    category: Category
    description: str
    amount: float = Field(ge=0, description="Claimed amount in USD")
    date: date
    vendor: str | None = None
    location: str | None = Field(default=None, description="City, for per-diem locality overrides")
    quantity: float | None = Field(
        default=None,
        description="Nights (lodging), days (meals), or miles (mileage). Defaults to 1 where relevant.",
    )
    has_receipt: bool = False
    receipt_text: str | None = None


class Claim(BaseModel):
    claim_id: str
    employee_id: str
    employee_role: str = "employee"
    trip_purpose: str = ""
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    currency: str = "USD"
    line_items: list[LineItem]

    @property
    def claimed_total(self) -> float:
        return round(sum(li.amount for li in self.line_items), 2)


# --------------------------------------------------------------------------- #
# Deterministic tool facts                                                    #
# --------------------------------------------------------------------------- #
class LineCheck(BaseModel):
    line_item_id: str
    category: Category
    claimed: float
    cap: float | None  # None => no cap defined for this category
    allowed: float
    deduction: float
    rule_id: str | None
    note: str = ""


class ToolResults(BaseModel):
    """Consolidated deterministic facts for a claim (the ground truth)."""

    line_checks: list[LineCheck]
    missing_documents: list[str] = []
    duplicate_flags: list[str] = []
    has_suspected_duplicate: bool = False
    required_approver_role: str = "manager"
    within_auto_approve: bool = True
    unmatched_categories: list[str] = []  # categories with no policy rule (policy gap)
    policy_references: list[str] = []
    claimed_total: float = 0.0
    allowed_total: float = 0.0


# --------------------------------------------------------------------------- #
# Output                                                                       #
# --------------------------------------------------------------------------- #
class Deduction(BaseModel):
    line_item_id: str
    amount: float
    reason: str
    policy_ref: str | None = None


class Proposal(BaseModel):
    """Arguments of the ``submit_decision`` tool — the LLM's qualitative call."""

    decision: Outcome
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    missing_documents: list[str] = []
    reasoning_summary: str = ""


class Decision(BaseModel):
    """The final, authoritative structured recommendation."""

    decision: Outcome
    claimed_amount: float
    approved_amount: float
    rejected_amount: float
    deductions: list[Deduction] = []
    missing_documents: list[str] = []
    policy_references: list[str] = []
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    manual_review_reasons: list[str] = []


# --------------------------------------------------------------------------- #
# Trace (proves the agentic workflow; doubles as demo evidence)               #
# --------------------------------------------------------------------------- #
class TraceStep(BaseModel):
    kind: str  # policy | tool_call | llm | guardrail | fallback
    summary: str
    detail: dict | None = None


class Trace(BaseModel):
    mode: str  # live | mock | fallback
    steps: list[TraceStep] = []

    def add(self, kind: str, summary: str, detail: dict | None = None) -> None:
        self.steps.append(TraceStep(kind=kind, summary=summary, detail=detail))


class EvaluationResult(BaseModel):
    """What the CLI/API return: the decision plus its full reasoning trace."""

    decision: Decision
    trace: Trace


# --------------------------------------------------------------------------- #
# Receipt extraction (bill upload → prefill the claim form)                   #
# --------------------------------------------------------------------------- #
class ReceiptLineItem(BaseModel):
    description: str = ""
    amount: float = Field(default=0.0, ge=0)
    quantity: float | None = None
    category: Category | None = None


class ReceiptExtraction(BaseModel):
    """Structured fields extracted from an uploaded bill, used to prefill a claim.

    `source` records which path produced it: text LLM (parsable), VLM (image),
    a deterministic mock (offline), or `unavailable` when extraction failed and
    the user must enter the bill manually.
    """

    vendor: str | None = None
    # Qualified as datetime.date: a field named `date` with a default shadows the bare
    # `date` type during forward-ref evaluation (-> None | None).
    date: datetime.date | None = None
    total: float | None = Field(default=None, ge=0)
    suggested_category: Category = Category.other
    line_items: list[ReceiptLineItem] = []
    raw_text: str = ""
    source: str = ""  # text | vlm | mock | unavailable
