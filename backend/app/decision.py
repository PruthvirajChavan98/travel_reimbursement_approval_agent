"""The deterministic decision authority.

This module owns the final outcome and ALL money math. It is used three ways:
* **mock mode** — no LLM available (no API key / ``--mock``);
* **fallback** — the agent loop failed or returned invalid output;
* **reconciliation** — validate/merge an LLM ``Proposal`` against the facts.

Ownership split (deliberate, see README): the deterministic layer owns money,
hard caps, duplicates, required-doc presence and the *amounts*. The LLM owns
qualitative judgment and may only **escalate** to MANUAL_REVIEW (or surface a
REJECT the rules missed) — it can never loosen a decision or alter the math.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config
from .config import load_policy
from .models import Claim, Decision, Deduction, EvaluationResult, Outcome, Proposal, ToolResults, Trace
from .tools import gather_facts


def load_prior_claims(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else config.PRIOR_CLAIMS
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _deterministic_confidence(facts: ToolResults) -> float:
    """Confidence = how *sure* we are of the decision (uncertainty lowers it).

    Clean over-cap deductions and clear non-reimbursable lines are confident
    decisions and incur no penalty; only genuine uncertainty does.
    """
    conf = 1.0
    if facts.missing_documents:
        conf -= 0.4
    if facts.has_suspected_duplicate:
        conf -= 0.3
    if facts.unmatched_categories:
        conf -= 0.4
    if not facts.within_auto_approve:
        conf -= 0.2
    return round(max(0.0, conf), 2)


def _base_outcome(facts: ToolResults, claimed: float, approved: float, confidence: float, policy: dict, llm_failed: bool):
    """Apply the manual-review-first precedence; return (outcome, reasons)."""
    th = policy["thresholds"]
    reasons: list[str] = []

    if llm_failed:
        reasons.append("LLM adjudication failed or returned invalid output; routed to human review.")
    if facts.missing_documents:
        reasons.append("Missing required receipt(s): " + "; ".join(facts.missing_documents))
    if facts.has_suspected_duplicate:
        reasons.append("Suspected duplicate expense: " + "; ".join(facts.duplicate_flags))
    if facts.unmatched_categories:
        reasons.append("Expense category with no matching policy rule: " + ", ".join(sorted(set(facts.unmatched_categories))))
    if not facts.within_auto_approve:
        reasons.append(f"Claim total ${claimed:.2f} exceeds the auto-approval limit; requires {facts.required_approver_role} approval.")
    if confidence < th["manual_review_confidence"]:
        reasons.append(f"Confidence {confidence} is below the manual-review threshold {th['manual_review_confidence']}.")

    if reasons:
        return Outcome.MANUAL_REVIEW, reasons
    if approved <= th["reject_floor"]:
        return Outcome.REJECT, reasons
    if approved < claimed:
        return Outcome.PARTIAL_APPROVE, reasons
    return Outcome.APPROVE, reasons


def _explain(outcome: Outcome, claimed: float, approved: float, rejected: float, deductions: list[Deduction], reasons: list[str]) -> str:
    if outcome is Outcome.APPROVE:
        return f"All line items comply with policy. Approved in full: ${approved:.2f}."
    if outcome is Outcome.PARTIAL_APPROVE:
        detail = "; ".join(f"{d.line_item_id} -${d.amount:.2f} ({d.reason})" for d in deductions)
        return f"Approved ${approved:.2f} of ${claimed:.2f}; ${rejected:.2f} deducted for policy overages: {detail}."
    if outcome is Outcome.REJECT:
        return f"Rejected: approved amount is ${approved:.2f} after applying policy (claimed ${claimed:.2f})."
    return "Routed to manual review: " + "; ".join(reasons)


def decide(facts: ToolResults, policy: dict, proposal: Proposal | None = None, llm_failed: bool = False) -> Decision:
    """Build the authoritative Decision from deterministic facts (+ optional LLM proposal)."""
    claimed = round(facts.claimed_total, 2)
    approved = round(facts.allowed_total, 2)
    rejected = round(claimed - approved, 2)

    deductions = [
        Deduction(
            line_item_id=lc.line_item_id,
            amount=lc.deduction,
            reason=f"{lc.category.value} over cap ({lc.note})" if lc.cap is not None else lc.note,
            policy_ref=lc.rule_id,
        )
        for lc in facts.line_checks
        if lc.deduction > 0
    ]

    det_conf = _deterministic_confidence(facts)
    confidence = det_conf if proposal is None else round(min(det_conf, proposal.confidence), 2)

    outcome, reasons = _base_outcome(facts, claimed, approved, confidence, policy, llm_failed)

    # Reconcile with the LLM: it may only escalate, never loosen.
    if proposal is not None and not llm_failed:
        if proposal.decision is Outcome.MANUAL_REVIEW and outcome is not Outcome.MANUAL_REVIEW:
            outcome = Outcome.MANUAL_REVIEW
            reasons.append(f"LLM flagged this claim for manual review: {proposal.reasoning_summary or proposal.explanation}")
        elif proposal.decision is Outcome.REJECT and outcome in (Outcome.APPROVE, Outcome.PARTIAL_APPROVE):
            outcome = Outcome.MANUAL_REVIEW
            reasons.append("Conflict: LLM recommended REJECT but the policy engine found the expense within policy; routed to manual review.")

    det_expl = _explain(outcome, claimed, approved, rejected, deductions, reasons)
    if proposal is None or llm_failed:
        explanation = det_expl
    elif proposal.decision is outcome:
        explanation = proposal.explanation.strip() or det_expl
    else:
        explanation = f"{det_expl} (LLM view: {proposal.explanation.strip()})"

    return Decision(
        decision=outcome,
        claimed_amount=claimed,
        approved_amount=approved,
        rejected_amount=rejected,
        deductions=deductions,
        missing_documents=facts.missing_documents,
        policy_references=facts.policy_references,
        confidence=confidence,
        explanation=explanation,
        manual_review_reasons=reasons if outcome is Outcome.MANUAL_REVIEW else [],
    )


def evaluate_deterministic(
    claim: Claim,
    policy: dict | None = None,
    prior_claims: list[dict] | None = None,
    mode: str = "mock",
    trace: Trace | None = None,
) -> EvaluationResult:
    """Full no-LLM decision path (mock mode and the agent's fallback)."""
    policy = policy or load_policy()
    prior_claims = prior_claims if prior_claims is not None else load_prior_claims()
    if trace is None:
        trace = Trace(mode=mode)

    facts = gather_facts(claim, policy, prior_claims)
    trace.add(
        "tool_call",
        "Gathered deterministic facts (policy lookup, caps, receipts, duplicates, approval tier)",
        {
            "policy_references": facts.policy_references,
            "line_checks": [lc.model_dump() for lc in facts.line_checks],
            "missing_documents": facts.missing_documents,
            "duplicate_flags": facts.duplicate_flags,
            "approval": {"required_role": facts.required_approver_role, "auto_approve": facts.within_auto_approve},
            "claimed_total": facts.claimed_total,
            "allowed_total": facts.allowed_total,
        },
    )

    decision = decide(facts, policy)
    trace.add(
        "guardrail",
        f"Deterministic decision: {decision.decision.value}",
        {
            "approved_amount": decision.approved_amount,
            "rejected_amount": decision.rejected_amount,
            "confidence": decision.confidence,
            "manual_review_reasons": decision.manual_review_reasons,
        },
    )
    return EvaluationResult(decision=decision, trace=trace)
