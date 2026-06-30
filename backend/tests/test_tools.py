"""Business-correctness tests for the deterministic tools (money math + checks)."""
import copy

from app.models import Category
from app.tools import (
    check_approval_threshold,
    check_receipt_completeness,
    compute_line,
    detect_duplicates,
    gather_facts,
)
from factories import line, make_claim


# --------------------------- per-line cap math ----------------------------- #
def test_lodging_within_cap(policy):
    r = compute_line("lodging", 200.0, quantity=2, location=None, policy=policy)
    assert r["cap"] == 220.0 and r["allowed"] == 200.0 and r["deduction"] == 0.0


def test_lodging_over_cap(policy):
    r = compute_line("lodging", 300.0, quantity=2, location=None, policy=policy)
    assert r["cap"] == 220.0 and r["allowed"] == 220.0 and r["deduction"] == 80.0


def test_lodging_locality_override(policy):
    r = compute_line("lodging", 500.0, quantity=2, location="New York", policy=policy)
    assert r["cap"] == 600.0 and r["deduction"] == 0.0  # 300/night * 2


def test_meals_per_day(policy):
    assert compute_line("meals", 180.0, 3, None, policy)["cap"] == 204.0  # 68 * 3


def test_mileage_rate(policy):
    r = compute_line("mileage", 80.0, quantity=100, location=None, policy=policy)
    assert r["cap"] == 72.5 and r["allowed"] == 72.5 and r["deduction"] == 7.5


def test_airfare_flat_cap(policy):
    assert compute_line("airfare", 1600.0, None, None, policy)["deduction"] == 100.0


def test_personal_non_reimbursable(policy):
    r = compute_line("personal", 90.0, None, None, policy)
    assert r["cap"] == 0.0 and r["allowed"] == 0.0 and r["deduction"] == 90.0


def test_unmatched_category_is_policy_gap(policy):
    trimmed = copy.deepcopy(policy)
    del trimmed["category_limits"]["other"]
    r = compute_line("other", 50.0, None, None, trimmed)
    assert r["cap"] is None and r["rule_id"] is None


# --------------------------- receipts -------------------------------------- #
def test_receipt_required_above_threshold(policy):
    claim = make_claim([line(amount=100.0, has_receipt=False)])
    assert len(check_receipt_completeness(claim, policy)) == 1


def test_receipt_not_required_below_threshold(policy):
    claim = make_claim([line(amount=50.0, has_receipt=False)])
    assert check_receipt_completeness(claim, policy) == []


def test_receipt_present_is_complete(policy):
    claim = make_claim([line(amount=100.0, has_receipt=True)])
    assert check_receipt_completeness(claim, policy) == []


# --------------------------- duplicates ------------------------------------ #
def test_duplicate_vs_prior(policy, prior):
    claim = make_claim(
        [line(category=Category.lodging, amount=220.0, date="2026-05-10", vendor="Hilton Garden Inn")],
        employee_id="E-1001",
    )
    flags, suspected = detect_duplicates(claim, prior, policy)
    assert suspected and any("prior claim" in f for f in flags)


def test_intra_claim_duplicate(policy):
    li = dict(category=Category.airfare, amount=300.0, date="2026-06-10", vendor="United")
    claim = make_claim([line(id="L1", **li), line(id="L2", **li)])
    flags, suspected = detect_duplicates(claim, [], policy)
    assert suspected and any("within the same claim" in f for f in flags)


def test_no_duplicate(policy, prior):
    claim = make_claim([line(amount=42.0, vendor="Cafe", date="2026-06-10")])
    assert detect_duplicates(claim, prior, policy) == ([], False)


# --------------------------- approval threshold ---------------------------- #
def test_threshold_tiers(policy):
    assert check_approval_threshold(2500.0, policy)[1] is True   # boundary, auto
    assert check_approval_threshold(2501.0, policy)[1] is False  # director
    assert check_approval_threshold(20000.0, policy)[0] == "vp"


# --------------------------- gather_facts ---------------------------------- #
def test_gather_facts_clean_sample(policy, prior, load_sample):
    facts = gather_facts(load_sample("01_approve.json"), policy, prior)
    assert facts.allowed_total == 420.0
    assert facts.missing_documents == [] and facts.has_suspected_duplicate is False
    assert facts.within_auto_approve is True
    assert "POL-LODGING" in facts.policy_references and "POL-APPROVAL" in facts.policy_references
