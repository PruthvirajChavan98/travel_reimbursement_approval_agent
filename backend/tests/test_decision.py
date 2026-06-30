"""Reliability tests: the 4 outcomes, manual-review triggers, and LLM reconciliation."""
from app.decision import decide, evaluate_deterministic
from app.models import Category, Outcome, Proposal
from app.tools import gather_facts
from factories import line, make_claim


# --------------------- the four outcomes on the four samples --------------- #
def test_sample_approve(policy, prior, load_sample):
    d = evaluate_deterministic(load_sample("01_approve.json"), policy, prior).decision
    assert d.decision is Outcome.APPROVE
    assert d.approved_amount == 420.0 and d.rejected_amount == 0.0 and d.deductions == []
    assert d.confidence == 1.0


def test_sample_partial(policy, prior, load_sample):
    d = evaluate_deterministic(load_sample("02_partial.json"), policy, prior).decision
    assert d.decision is Outcome.PARTIAL_APPROVE
    assert d.approved_amount == 340.0 and d.rejected_amount == 80.0
    assert len(d.deductions) == 1 and d.deductions[0].line_item_id == "L1"


def test_sample_reject(policy, prior, load_sample):
    d = evaluate_deterministic(load_sample("03_reject.json"), policy, prior).decision
    assert d.decision is Outcome.REJECT
    assert d.approved_amount == 0.0 and d.rejected_amount == 90.0


def test_sample_manual_review(policy, prior, load_sample):
    d = evaluate_deterministic(load_sample("04_manual_review.json"), policy, prior).decision
    assert d.decision is Outcome.MANUAL_REVIEW
    assert d.missing_documents and d.manual_review_reasons


# --------------------- other manual-review triggers ------------------------ #
def test_exceeds_auto_approval_limit(policy, prior):
    # Clean (within caps, receipts present) but total > 2500 -> needs higher approver.
    claim = make_claim([
        line(id="L1", category=Category.lodging, amount=1320.0, quantity=12, has_receipt=True),
        line(id="L2", category=Category.airfare, amount=1300.0, has_receipt=True),
    ])
    d = evaluate_deterministic(claim, policy, prior).decision
    assert d.decision is Outcome.MANUAL_REVIEW
    assert any("auto-approval" in r for r in d.manual_review_reasons)


def test_duplicate_routes_to_manual(policy, prior):
    claim = make_claim(
        [line(category=Category.lodging, amount=220.0, date="2026-05-10", vendor="Hilton Garden Inn", has_receipt=True)],
        employee_id="E-1001",
    )
    d = evaluate_deterministic(claim, policy, prior).decision
    assert d.decision is Outcome.MANUAL_REVIEW
    assert any("duplicate" in r.lower() for r in d.manual_review_reasons)


# --------------------- LLM reconciliation (decide) ------------------------- #
def _clean_facts(policy):
    claim = make_claim([line(category=Category.meals, amount=60.0, quantity=1, has_receipt=True)])
    return gather_facts(claim, policy, [])


def test_llm_can_escalate_to_manual(policy):
    facts = _clean_facts(policy)
    proposal = Proposal(decision=Outcome.MANUAL_REVIEW, confidence=0.9, explanation="Purpose unclear", reasoning_summary="vague justification")
    d = decide(facts, policy, proposal=proposal)
    assert d.decision is Outcome.MANUAL_REVIEW and d.manual_review_reasons


def test_llm_reject_conflict_routes_to_manual(policy):
    facts = _clean_facts(policy)
    proposal = Proposal(decision=Outcome.REJECT, confidence=0.9, explanation="Looks personal")
    d = decide(facts, policy, proposal=proposal)
    assert d.decision is Outcome.MANUAL_REVIEW
    assert any("Conflict" in r for r in d.manual_review_reasons)


def test_low_llm_confidence_forces_manual(policy):
    facts = _clean_facts(policy)
    proposal = Proposal(decision=Outcome.APPROVE, confidence=0.3, explanation="Maybe ok")
    d = decide(facts, policy, proposal=proposal)
    assert d.confidence == 0.3 and d.decision is Outcome.MANUAL_REVIEW


def test_llm_cannot_loosen_partial(policy):
    # deterministic says PARTIAL (over-cap); LLM says APPROVE -> stays PARTIAL, amounts deterministic.
    claim = make_claim([line(category=Category.lodging, amount=300.0, quantity=2, has_receipt=True)])
    facts = gather_facts(claim, policy, [])
    proposal = Proposal(decision=Outcome.APPROVE, confidence=0.95, explanation="fine")
    d = decide(facts, policy, proposal=proposal)
    assert d.decision is Outcome.PARTIAL_APPROVE and d.approved_amount == 220.0


def test_llm_failure_forces_manual(policy):
    facts = _clean_facts(policy)
    d = decide(facts, policy, proposal=None, llm_failed=True)
    assert d.decision is Outcome.MANUAL_REVIEW
    assert any("failed" in r for r in d.manual_review_reasons)
