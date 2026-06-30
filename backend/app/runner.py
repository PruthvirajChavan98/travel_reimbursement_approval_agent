"""Shared orchestration used by both the API and the CLI.

`live_graph` wires the MCP tool server (stdio) + LLM + checkpointer into a compiled
graph; `run_mock` is the deterministic, no-network path (cold-clone runnable).
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.types import Command

from app import config
from app.config import Settings, get_settings, load_policy
from app.decision import evaluate_deterministic, load_prior_claims
from app.graph import build_graph
from app.llm import build_llm
from app.models import Claim, EvaluationResult

MCP_SERVER = {
    "travel": {
        "command": sys.executable,
        "args": ["-m", "app.mcp_server"],
        "cwd": str(config.PROJECT_ROOT),
        "transport": "stdio",
    }
}


@asynccontextmanager
async def live_graph(checkpointer, settings: Settings | None = None):
    """Build the live LangGraph (MCP tools + gpt-oss LLM) bound to a checkpointer."""
    settings = settings or get_settings()
    client = MultiServerMCPClient(MCP_SERVER)
    tools = await client.get_tools()
    graph = build_graph(build_llm(settings), tools, load_policy(), load_prior_claims(), checkpointer)
    yield graph


def run_mock(claim: dict) -> EvaluationResult:
    """Deterministic pipeline — no LLM/MCP/network. Used when no API key or --mock."""
    return evaluate_deterministic(Claim.model_validate(claim))


def _unpack(res: dict) -> dict:
    interrupts = res.get("__interrupt__")
    return {"decision": res.get("decision"), "interrupt": interrupts[0].value if interrupts else None}


async def adjudicate(graph, claim: dict, thread_id: str) -> dict:
    cfg = {"configurable": {"thread_id": thread_id}}
    return _unpack(await graph.ainvoke({"claim": claim}, cfg))


async def resume(graph, thread_id: str, human: dict) -> dict:
    cfg = {"configurable": {"thread_id": thread_id}}
    return _unpack(await graph.ainvoke(Command(resume=human), cfg))
