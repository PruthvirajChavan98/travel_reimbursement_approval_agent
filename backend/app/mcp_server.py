"""MCP server exposing the deterministic reimbursement tools (stdio transport).

These are READ-ONLY fact tools the LLM uses for grounding/transparency — they are
NOT trusted for the final money math (the in-graph `reconcile` node recomputes
ground truth via gather_facts/decide). Policy and prior claims are loaded
server-side; claim-scoped tools take the claim as a JSON string (the MCP client is
stateless and cannot close over the current claim).

Run:  python -m app.mcp_server   (stdio)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow being launched directly by path (`python app/mcp_server.py`) too.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app import tools as T  # noqa: E402
from app.config import load_policy  # noqa: E402
from app.decision import load_prior_claims  # noqa: E402
from app.models import Claim  # noqa: E402

mcp = FastMCP("travel-tools")
POLICY = load_policy()
PRIORS = load_prior_claims()


@mcp.tool()
def lookup_policy(category: str) -> dict:
    """Look up the reimbursement policy rule and cap for an expense category
    (one of: lodging, meals, airfare, ground_transport, mileage, other, personal)."""
    return T.lookup_policy(category, POLICY)


@mcp.tool()
def check_per_diem_or_limit(
    category: str, amount: float, quantity: float | None = None, location: str | None = None
) -> dict:
    """Compute the policy cap, allowed amount, and deduction for ONE expense line.
    quantity = nights (lodging), days (meals), or miles (mileage); location enables
    lodging locality overrides."""
    return T.compute_line(category, amount, quantity, location, POLICY)


@mcp.tool()
def check_approval_threshold(total: float) -> dict:
    """Return the required approver role and whether a claim total is auto-approvable."""
    role, auto_approve, rule_id = T.check_approval_threshold(total, POLICY)
    return {"total": total, "required_approver_role": role, "auto_approve": auto_approve, "rule_id": rule_id}


@mcp.tool()
def check_receipt_completeness(claim_json: str) -> dict:
    """List line items missing a required receipt. Pass the full claim as a JSON string."""
    claim = Claim.model_validate_json(claim_json)
    return {"missing_documents": T.check_receipt_completeness(claim, POLICY)}


@mcp.tool()
def detect_duplicates(claim_json: str) -> dict:
    """Detect suspected duplicate expenses vs prior claims and within the claim.
    Pass the full claim as a JSON string."""
    claim = Claim.model_validate_json(claim_json)
    flags, suspected = T.detect_duplicates(claim, PRIORS, POLICY)
    return {"duplicate_flags": flags, "has_suspected_duplicate": suspected}


if __name__ == "__main__":
    mcp.run()  # stdio transport
