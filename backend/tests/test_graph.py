"""Phase C: the LangGraph adjudication graph with a MOCKED LLM + local tools + InMemorySaver.

No network, no subprocess, no Postgres. Covers: happy path, the agentic tool loop,
the manual-review interrupt + resume (approve/reject), and the invalid-proposal fallback.
"""
import json

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app import config
from app.decision import load_prior_claims
from app.graph import build_graph


# --- mocked LLM ------------------------------------------------------------- #
class FakeChat:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.i = 0

    def bind_tools(self, tools, **kw):
        return self

    async def ainvoke(self, messages, **kw):
        msg = self.scripted[min(self.i, len(self.scripted) - 1)]
        self.i += 1
        return msg


def ai_submit(decision, confidence=0.9, explanation="looks fine"):
    args = {"decision": decision, "confidence": confidence, "explanation": explanation,
            "missing_documents": [], "reasoning_summary": "test"}
    return AIMessage(content="", tool_calls=[{"name": "submit_decision", "args": args, "id": "sd1", "type": "tool_call"}])


def ai_tool(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "t1", "type": "tool_call"}])


@tool
def lookup_policy(category: str) -> dict:
    """Look up policy for a category."""
    from app.tools import lookup_policy as lp
    return lp(category, config.load_policy())


# --- helpers ---------------------------------------------------------------- #
def _graph(scripted):
    return build_graph(FakeChat(scripted), [lookup_policy], config.load_policy(), load_prior_claims(), InMemorySaver())


def _claim(name):
    return json.loads((config.CLAIMS_DIR / name).read_text())


def _cfg(thread):
    return {"configurable": {"thread_id": thread}}


# --- tests ------------------------------------------------------------------ #
async def test_happy_approve():
    graph = _graph([ai_submit("APPROVE")])
    res = await graph.ainvoke({"claim": _claim("01_approve.json")}, _cfg("t-approve"))
    assert "__interrupt__" not in res
    assert res["decision"]["decision"] == "APPROVE"
    assert res["decision"]["approved_amount"] == 420.0


async def test_agentic_tool_loop_executes_tool():
    graph = _graph([ai_tool("lookup_policy", {"category": "lodging"}), ai_submit("APPROVE")])
    res = await graph.ainvoke({"claim": _claim("01_approve.json")}, _cfg("t-loop"))
    assert any(isinstance(m, ToolMessage) for m in res["messages"])  # the tool ran
    assert res["decision"]["decision"] == "APPROVE"


async def test_partial_is_deterministic_even_if_llm_says_approve():
    # LLM says APPROVE; deterministic facts force PARTIAL (lodging over cap). LLM cannot loosen.
    graph = _graph([ai_submit("APPROVE")])
    res = await graph.ainvoke({"claim": _claim("02_partial.json")}, _cfg("t-partial"))
    assert res["decision"]["decision"] == "PARTIAL_APPROVE"
    assert res["decision"]["approved_amount"] == 340.0


async def test_manual_review_interrupt_then_human_approve():
    graph = _graph([ai_submit("APPROVE")])  # missing receipt forces MANUAL_REVIEW regardless
    cfg = _cfg("t-manual-approve")
    res = await graph.ainvoke({"claim": _claim("04_manual_review.json")}, cfg)
    assert res.get("__interrupt__")  # paused for a human
    res2 = await graph.ainvoke(Command(resume={"approved": True, "approver": "manager_jane"}), cfg)
    assert res2["decision"]["decision"] == "APPROVE"
    assert res2["decision"]["approved_amount"] == 570.0  # amounts stay deterministic


async def test_manual_review_human_reject():
    graph = _graph([ai_submit("APPROVE")])
    cfg = _cfg("t-manual-reject")
    await graph.ainvoke({"claim": _claim("04_manual_review.json")}, cfg)
    res2 = await graph.ainvoke(Command(resume={"approved": False, "approver": "manager_jane"}), cfg)
    assert res2["decision"]["decision"] == "REJECT"
    assert res2["decision"]["approved_amount"] == 0.0


async def test_invalid_proposal_falls_back_to_manual_review():
    graph = _graph([ai_submit("NOT_A_REAL_OUTCOME")])  # invalid Proposal -> llm_failed
    res = await graph.ainvoke({"claim": _claim("01_approve.json")}, _cfg("t-bad"))
    interrupts = res.get("__interrupt__")
    assert interrupts  # llm_failed -> MANUAL_REVIEW -> interrupt
    reasons = interrupts[0].value["manual_review_reasons"]
    assert any("failed" in r.lower() for r in reasons)
