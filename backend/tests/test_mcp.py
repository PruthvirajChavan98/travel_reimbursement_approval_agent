"""Phase B: the MCP server exposes the tools and returns results matching in-process funcs."""
import json
import sys

import pytest
from langchain_mcp_adapters.client import MultiServerMCPClient

from app import config
from app.tools import compute_line, lookup_policy

SERVER = {
    "travel": {
        "command": sys.executable,
        "args": ["-m", "app.mcp_server"],
        "cwd": str(config.PROJECT_ROOT),
        "transport": "stdio",
    }
}

EXPECTED_TOOLS = {
    "lookup_policy",
    "check_per_diem_or_limit",
    "check_approval_threshold",
    "check_receipt_completeness",
    "detect_duplicates",
}


def _parse(result):
    """langchain-mcp-adapters returns MCP content blocks: [{'type':'text','text': <json>}]."""
    if isinstance(result, list):
        text = "".join(b.get("text", "") for b in result if isinstance(b, dict))
        return json.loads(text)
    if isinstance(result, str):
        return json.loads(result)
    return result


@pytest.fixture
async def mcp_tools():
    client = MultiServerMCPClient(SERVER)
    tools = await client.get_tools()
    return {t.name: t for t in tools}


async def test_all_tools_exposed(mcp_tools):
    assert EXPECTED_TOOLS <= set(mcp_tools)


async def test_lookup_policy_matches_inprocess(mcp_tools):
    data = _parse(await mcp_tools["lookup_policy"].ainvoke({"category": "lodging"}))
    assert data["rule_id"] == lookup_policy("lodging", config.load_policy())["rule_id"]


async def test_per_diem_math_over_cap(mcp_tools):
    data = _parse(await mcp_tools["check_per_diem_or_limit"].ainvoke(
        {"category": "lodging", "amount": 300.0, "quantity": 2}
    ))
    expected = compute_line("lodging", 300.0, 2, None, config.load_policy())
    assert data["allowed"] == expected["allowed"] == 220.0
    assert data["deduction"] == expected["deduction"] == 80.0


async def test_claim_scoped_duplicate_tool(mcp_tools):
    claim = (config.CLAIMS_DIR / "01_approve.json").read_text()
    data = _parse(await mcp_tools["detect_duplicates"].ainvoke({"claim_json": claim}))
    assert data["has_suspected_duplicate"] is False
