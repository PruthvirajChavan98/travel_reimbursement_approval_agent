"""Phase D: thin FastAPI smoke test in MOCK mode (no Azure key → deterministic path).

Forcing mock keeps the test offline (no MCP subprocess, no LLM); the live graph path
is covered by tests/test_graph.py.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)  # force mock mode
    from app.api import app

    with TestClient(app) as c:
        yield c


def _claim(name):
    return json.loads((config.CLAIMS_DIR / name).read_text())


def test_healthz_reports_mock(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["mode"] == "mock"


def test_adjudicate_approve(client):
    r = client.post("/adjudicate", json={"claim": _claim("01_approve.json")})
    body = r.json()
    assert r.status_code == 200
    assert body["decision"]["decision"] == "APPROVE"
    assert body["decision"]["approved_amount"] == 420.0
    assert body["interrupt"] is None


def test_adjudicate_partial(client):
    body = client.post("/adjudicate", json={"claim": _claim("02_partial.json")}).json()
    assert body["decision"]["decision"] == "PARTIAL_APPROVE"
    assert body["decision"]["approved_amount"] == 340.0


def test_resume_unavailable_in_mock(client):
    body = client.post("/resume", json={"claim_id": "X", "approved": True}).json()
    assert "error" in body
