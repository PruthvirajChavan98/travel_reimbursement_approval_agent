"""Deterministic tools — the system's ground truth.

These functions own ALL money math and policy lookups. They are pure and
deterministic (same inputs -> same outputs), which is exactly why the LLM is not
allowed to do arithmetic: gpt-oss can hallucinate numerics.

Each tool is exposed two ways:
* as plain Python functions + ``gather_facts`` (used by ``decision.py`` and the
  deterministic fallback / mock mode), and
* as OpenAI function-tool schemas + a per-claim dispatch table (used by the agent
  loop so the LLM can call them).
"""
from __future__ import annotations

import json
from datetime import date

from .models import Category, Claim, LineCheck, LineItem, Outcome, ToolResults


def _money(x: float) -> float:
    return round(float(x), 2)


# --------------------------------------------------------------------------- #
# Core deterministic checks                                                   #
# --------------------------------------------------------------------------- #
def lookup_policy(category: str, policy: dict) -> dict:
    """Return the policy rule(s) and caps that apply to an expense category."""
    cat = str(category)
    if cat == Category.lodging.value:
        node = policy["per_diem"]["lodging"]
        return {
            "category": cat,
            "rule_id": node["rule_id"],
            "basis": "per-night lodging cap",
            "daily_cap": node["daily_cap"],
            "locality_overrides": node.get("locality_overrides", {}),
        }
    if cat == Category.meals.value:
        node = policy["per_diem"]["meals"]
        return {"category": cat, "rule_id": node["rule_id"], "basis": "per-day M&IE cap", "daily_cap": node["daily_cap"]}
    if cat == Category.mileage.value:
        node = policy["mileage"]
        return {"category": cat, "rule_id": node["rule_id"], "basis": "rate per mile", "rate_per_mile": node["rate_per_mile"]}
    if cat == Category.personal.value:
        node = policy["non_reimbursable"]
        return {"category": cat, "rule_id": node["rule_id"], "basis": "non-reimbursable", "cap": 0}
    limits = policy.get("category_limits", {})
    if cat in limits:
        return {"category": cat, "rule_id": limits[cat]["rule_id"], "basis": "flat category cap", "cap": limits[cat]["cap"]}
    return {"category": cat, "rule_id": None, "basis": "no matching policy rule", "cap": None}


def compute_line(category: str, amount: float, quantity: float | None, location: str | None, policy: dict) -> dict:
    """Compute cap / allowed / deduction for one expense line (the money math)."""
    cat = str(category)
    claimed = _money(amount)
    cap: float | None
    rule_id: str | None
    note = ""

    if cat == Category.personal.value:
        cap, rule_id, note = 0.0, policy["non_reimbursable"]["rule_id"], "non-reimbursable expense"
    elif cat == Category.lodging.value:
        node = policy["per_diem"]["lodging"]
        nights = quantity if quantity else 1
        daily = node.get("locality_overrides", {}).get(location or "", node["daily_cap"])
        cap, rule_id = _money(daily * nights), node["rule_id"]
        note = f"{daily}/night x {nights} night(s)"
    elif cat == Category.meals.value:
        node = policy["per_diem"]["meals"]
        days = quantity if quantity else 1
        cap, rule_id = _money(node["daily_cap"] * days), node["rule_id"]
        note = f"{node['daily_cap']}/day x {days} day(s)"
    elif cat == Category.mileage.value:
        node = policy["mileage"]
        miles = quantity or 0
        cap, rule_id = _money(node["rate_per_mile"] * miles), node["rule_id"]
        note = f"{node['rate_per_mile']}/mile x {miles} mile(s)"
    else:
        limits = policy.get("category_limits", {})
        if cat in limits:
            cap, rule_id = _money(limits[cat]["cap"]), limits[cat]["rule_id"]
            note = "flat category cap"
        else:
            cap, rule_id, note = None, None, "no matching policy rule"

    if cap is None:  # policy gap -> can't bound it; flag for review, deduct nothing
        return {"category": cat, "claimed": claimed, "cap": None, "allowed": claimed, "deduction": 0.0, "rule_id": None, "note": note}

    allowed = _money(min(claimed, cap))
    deduction = _money(max(0.0, claimed - cap))
    return {"category": cat, "claimed": claimed, "cap": cap, "allowed": allowed, "deduction": deduction, "rule_id": rule_id, "note": note}


def check_line(line: LineItem, policy: dict) -> LineCheck:
    d = compute_line(line.category.value, line.amount, line.quantity, line.location, policy)
    return LineCheck(line_item_id=line.id, **d)


def check_receipt_completeness(claim: Claim, policy: dict) -> list[str]:
    """Line items strictly above the receipt threshold must have a receipt."""
    threshold = policy["receipts"]["required_above"]
    rule_id = policy["receipts"]["rule_id"]
    missing = []
    for li in claim.line_items:
        if li.amount > threshold and not li.has_receipt:
            missing.append(f"{li.id} ({li.category.value}): receipt required for ${_money(li.amount)} (>{threshold}) [{rule_id}]")
    return missing


def _same_vendor(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip().lower() == b.strip().lower())


def detect_duplicates(claim: Claim, prior_claims: list[dict], policy: dict) -> tuple[list[str], bool]:
    """Exact/near-key duplicate detection vs prior claims and within the claim."""
    cfg = policy["duplicates"]
    tol = cfg["amount_tolerance"]
    window = cfg["date_window_days"]
    rule_id = cfg["rule_id"]
    flags: list[str] = []

    for li in claim.line_items:
        for p in prior_claims:
            if (
                p.get("employee_id") == claim.employee_id
                and _same_vendor(li.vendor, p.get("vendor"))
                and abs(li.amount - float(p.get("amount", -1))) <= tol
                and abs((li.date - date.fromisoformat(p["date"])).days) <= window
            ):
                flags.append(
                    f"{li.id} matches prior claim {p.get('claim_id')} "
                    f"({p.get('vendor')} ${p.get('amount')} on {p.get('date')}) [{rule_id}]"
                )

    seen: dict[tuple, str] = {}
    for li in claim.line_items:
        key = (li.category.value, _money(li.amount), li.date.isoformat(), (li.vendor or "").lower())
        if key in seen:
            flags.append(f"{li.id} duplicates {seen[key]} within the same claim [{rule_id}]")
        else:
            seen[key] = li.id
    return flags, bool(flags)


def check_approval_threshold(total: float, policy: dict) -> tuple[str, bool, str]:
    """Return (required_approver_role, auto_approve, rule_id) for a claim total."""
    matrix = policy["approval_matrix"]
    for tier in matrix["tiers"]:
        if tier["max_amount"] is None or total <= tier["max_amount"]:
            return tier["approver_role"], bool(tier["auto_approve"]), matrix["rule_id"]
    last = matrix["tiers"][-1]
    return last["approver_role"], bool(last["auto_approve"]), matrix["rule_id"]


def gather_facts(claim: Claim, policy: dict, prior_claims: list[dict]) -> ToolResults:
    """Run every deterministic check and consolidate the ground-truth facts."""
    line_checks = [check_line(li, policy) for li in claim.line_items]
    missing = check_receipt_completeness(claim, policy)
    dup_flags, has_dup = detect_duplicates(claim, prior_claims, policy)
    claimed_total = claim.claimed_total
    role, auto_approve, approval_rule = check_approval_threshold(claimed_total, policy)
    unmatched = [lc.category.value for lc in line_checks if lc.cap is None]

    refs: set[str] = {lc.rule_id for lc in line_checks if lc.rule_id}
    refs.add(approval_rule)
    if missing:
        refs.add(policy["receipts"]["rule_id"])
    if has_dup:
        refs.add(policy["duplicates"]["rule_id"])

    return ToolResults(
        line_checks=line_checks,
        missing_documents=missing,
        duplicate_flags=dup_flags,
        has_suspected_duplicate=has_dup,
        required_approver_role=role,
        within_auto_approve=auto_approve,
        unmatched_categories=unmatched,
        policy_references=sorted(refs),
        claimed_total=claimed_total,
        allowed_total=_money(sum(lc.allowed for lc in line_checks)),
    )


# --------------------------------------------------------------------------- #
# OpenAI function-tool schemas + per-claim dispatch (used by the agent loop)  #
# --------------------------------------------------------------------------- #
_CATEGORY_ENUM = [c.value for c in Category]

SUBMIT_DECISION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_decision",
        "description": (
            "Return your FINAL qualitative recommendation. Call this exactly once after gathering facts. "
            "Do NOT compute money amounts — the system computes all amounts, deductions, and rule references "
            "deterministically from policy. Judge the QUALITATIVE aspects: is the business purpose adequate, "
            "does any expense look non-business/personal, is anything ambiguous or conflicting? If uncertain or "
            "incomplete, choose MANUAL_REVIEW."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision": {"type": "string", "enum": [o.value for o in Outcome]},
                "confidence": {"type": "number", "description": "0.0 to 1.0"},
                "explanation": {"type": "string"},
                "missing_documents": {"type": "array", "items": {"type": "string"}},
                "reasoning_summary": {"type": "string"},
            },
            "required": ["decision", "confidence", "explanation", "missing_documents", "reasoning_summary"],
        },
    },
}

DATA_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_policy",
            "description": "Look up the reimbursement policy rule and cap for an expense category.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"category": {"type": "string", "enum": _CATEGORY_ENUM}},
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_per_diem_or_limit",
            "description": "Compute the policy cap, allowed amount, and deduction for one expense line.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "category": {"type": "string", "enum": _CATEGORY_ENUM},
                    "amount": {"type": "number"},
                    "quantity": {"type": "number", "description": "nights (lodging), days (meals), or miles (mileage)"},
                    "location": {"type": "string"},
                },
                "required": ["category", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_receipt_completeness",
            "description": "List line items that are missing a required receipt for this claim.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_duplicates",
            "description": "Detect suspected duplicate expenses (vs prior claims and within this claim).",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_approval_threshold",
            "description": "Return the required approver role and whether the claim total is auto-approvable.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"total": {"type": "number"}},
            },
        },
    },
]


def tool_schemas() -> list[dict]:
    """All function-tool schemas exposed to the LLM (data tools + submit_decision)."""
    return [*DATA_TOOL_SCHEMAS, SUBMIT_DECISION_SCHEMA]


def build_dispatch(claim: Claim, policy: dict, prior_claims: list[dict]) -> dict:
    """Map tool name -> callable(**kwargs) -> JSON-serializable result, bound to a claim."""

    def _lookup_policy(category: str) -> dict:
        return lookup_policy(category, policy)

    def _check_per_diem_or_limit(category: str, amount: float, quantity: float | None = None, location: str | None = None) -> dict:
        return compute_line(category, amount, quantity, location, policy)

    def _check_receipt_completeness() -> dict:
        return {"missing_documents": check_receipt_completeness(claim, policy)}

    def _detect_duplicates() -> dict:
        flags, suspected = detect_duplicates(claim, prior_claims, policy)
        return {"duplicate_flags": flags, "has_suspected_duplicate": suspected}

    def _check_approval_threshold(total: float | None = None) -> dict:
        t = claim.claimed_total if total is None else total
        role, auto, rule_id = check_approval_threshold(t, policy)
        return {"total": t, "required_approver_role": role, "auto_approve": auto, "rule_id": rule_id}

    return {
        "lookup_policy": _lookup_policy,
        "check_per_diem_or_limit": _check_per_diem_or_limit,
        "check_receipt_completeness": _check_receipt_completeness,
        "detect_duplicates": _detect_duplicates,
        "check_approval_threshold": _check_approval_threshold,
    }


def dumps(obj) -> str:
    """Compact JSON for tool-result messages."""
    return json.dumps(obj, default=str)
