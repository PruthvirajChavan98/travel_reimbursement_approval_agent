"""The LangGraph adjudication graph.

Flow:  START → intake (validate + pre-compute deterministic facts, seed the prompt)
            → agent (LLM bound to MCP fact-tools + submit_decision)
                ├─ data tool calls → tools (ToolNode) → agent   (the agentic loop)
                └─ submit_decision / done → reconcile (deterministic authority)
                       └─ if MANUAL_REVIEW → interrupt() for a human approver → finalize

The LLM is ADVISORY: `reconcile` recomputes ground truth with gather_facts()+decide(),
so all amounts/outcomes are deterministic. Everything above interrupt() is pure, so the
node can safely re-run on resume.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from pydantic import ValidationError

from app.decision import decide, gather_facts
from app.models import Claim, Outcome, Proposal, ToolResults
from app.tools import SUBMIT_DECISION_SCHEMA

SYSTEM_PROMPT = (
    "You are a travel & expense reimbursement adjudicator. You will be given a claim and "
    "pre-computed policy facts. You may call the fact tools (lookup_policy, "
    "check_per_diem_or_limit, check_receipt_completeness, detect_duplicates, "
    "check_approval_threshold) to verify or explore details. Do NOT compute money amounts — "
    "the system computes all amounts, deductions, and policy references deterministically. "
    "Judge the QUALITATIVE aspects: is the business purpose adequate, does any expense look "
    "personal/non-business, is anything ambiguous or conflicting? When ready, call "
    "submit_decision EXACTLY ONCE with one of APPROVE / PARTIAL_APPROVE / REJECT / "
    "MANUAL_REVIEW, a confidence 0-1, and a short explanation. If uncertain or the claim is "
    "incomplete, choose MANUAL_REVIEW."
)


class State(TypedDict):
    messages: Annotated[list, add_messages]
    claim: dict
    facts: dict | None
    decision: dict | None


def _facts_summary(facts: ToolResults) -> str:
    lines = [
        f"- {lc.line_item_id} {lc.category.value}: claimed ${lc.claimed} cap "
        f"{'n/a' if lc.cap is None else f'${lc.cap}'} → allowed ${lc.allowed} "
        f"(deduction ${lc.deduction}) [{lc.rule_id}]"
        for lc in facts.line_checks
    ]
    return (
        "Pre-computed deterministic facts:\n"
        + "\n".join(lines)
        + f"\nMissing documents: {facts.missing_documents or 'none'}"
        + f"\nDuplicate flags: {facts.duplicate_flags or 'none'}"
        + f"\nApproval: total ${facts.claimed_total} → role {facts.required_approver_role}, "
        + f"auto_approve={facts.within_auto_approve}"
        + f"\nAllowed total ${facts.allowed_total} of claimed ${facts.claimed_total}."
    )


def _user_prompt(claim: Claim, facts: ToolResults) -> str:
    return (
        f"Adjudicate this travel reimbursement claim.\n\nClaim JSON:\n{claim.model_dump_json(indent=2)}"
        f"\n\n{_facts_summary(facts)}\n\nUse tools if helpful, then call submit_decision."
    )


def _extract_proposal_args(messages: list) -> dict | None:
    for m in reversed(messages):
        for call in getattr(m, "tool_calls", None) or []:
            if call["name"] == "submit_decision":
                return call["args"]
    return None


def _apply_human(dec, human: dict | None, claim: Claim):
    human = human or {}
    approver = human.get("approver", "human")
    note = human.get("note", "")
    if human.get("approved") is False:
        return dec.model_copy(update={
            "decision": Outcome.REJECT,
            "approved_amount": 0.0,
            "rejected_amount": dec.claimed_amount,
            "explanation": f"Rejected by {approver} on manual review. {note}".strip(),
            "manual_review_reasons": dec.manual_review_reasons + [f"Human reject by {approver}. {note}".strip()],
        })
    outcome = Outcome.PARTIAL_APPROVE if dec.deductions else Outcome.APPROVE
    return dec.model_copy(update={
        "decision": outcome,
        "explanation": f"Approved by {approver} on manual review. {dec.explanation} {note}".strip(),
        "manual_review_reasons": [],
    })


def build_graph(model, tools, policy: dict, prior_claims: list[dict], checkpointer):
    """Compile the adjudication graph. `tools` are LangChain tools (MCP-adapted or local)."""
    bound = model.bind_tools([*tools, SUBMIT_DECISION_SCHEMA])

    async def intake(state: State) -> dict:
        claim = Claim.model_validate(state["claim"])
        facts = gather_facts(claim, policy, prior_claims)
        return {
            "messages": [SystemMessage(SYSTEM_PROMPT), HumanMessage(_user_prompt(claim, facts))],
            "facts": facts.model_dump(),
        }

    async def agent(state: State) -> dict:
        return {"messages": [await bound.ainvoke(state["messages"])]}

    def route(state: State) -> str:
        calls = getattr(state["messages"][-1], "tool_calls", None) or []
        if any(c["name"] == "submit_decision" for c in calls):
            return "reconcile"
        return "tools" if calls else "reconcile"

    async def reconcile(state: State) -> dict:
        claim = Claim.model_validate(state["claim"])
        facts = ToolResults.model_validate(state["facts"]) if state.get("facts") else gather_facts(claim, policy, prior_claims)

        raw = _extract_proposal_args(state["messages"])
        proposal, llm_failed = None, False
        if raw is not None:
            try:
                proposal = Proposal.model_validate(raw)
            except ValidationError:
                llm_failed = True

        dec = decide(facts, policy, proposal=proposal, llm_failed=llm_failed)

        if dec.decision is Outcome.MANUAL_REVIEW:
            human = interrupt({
                "claim_id": claim.claim_id,
                "proposed_decision": dec.decision.value,
                "approved_amount": dec.approved_amount,
                "manual_review_reasons": dec.manual_review_reasons,
                "required_approver_role": facts.required_approver_role,
            })
            dec = _apply_human(dec, human, claim)

        return {"decision": dec.model_dump()}

    g = StateGraph(State)
    g.add_node("intake", intake)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools))
    g.add_node("reconcile", reconcile)
    g.add_edge(START, "intake")
    g.add_edge("intake", "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", "reconcile": "reconcile"})
    g.add_edge("tools", "agent")
    g.add_edge("reconcile", END)
    return g.compile(checkpointer=checkpointer)
