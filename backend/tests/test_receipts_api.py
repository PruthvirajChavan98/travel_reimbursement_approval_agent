"""P2: receipt extraction (mocked LLM) + the /receipts/extract endpoint (mock mode)."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app import receipts
from app.models import ReceiptExtraction
from app.receipts import MAX_UPLOAD_BYTES

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


# --- fake OpenAI client ----------------------------------------------------- #
class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = 0

    def create(self, **kw):
        item = self.scripted[min(self.calls, len(self.scripted) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return _Resp(item)


class FakeClient:
    def __init__(self, scripted):
        self.chat = type("C", (), {"completions": _Completions(scripted)})()


def _patch_client(monkeypatch, scripted) -> FakeClient:
    fake = FakeClient(scripted)
    monkeypatch.setattr(receipts, "_client", lambda *a, **k: fake)
    return fake


VALID = '{"vendor":"Grand Hotel","date":"2026-06-12","total":300,"suggested_category":"lodging","line_items":[{"description":"2 nights","amount":300}],"raw_text":"Grand Hotel ... $300.00"}'


# --- extraction unit tests -------------------------------------------------- #
def test_extract_from_text_parses(monkeypatch):
    _patch_client(monkeypatch, [VALID])
    out = receipts.extract_from_text("Grand Hotel Total $300.00")
    assert out.source == "text"
    assert out.vendor == "Grand Hotel" and out.total == 300
    assert out.suggested_category.value == "lodging" and len(out.line_items) == 1


def test_extract_repair_retry(monkeypatch):
    fake = _patch_client(monkeypatch, ["this is not json", VALID])
    out = receipts.extract_from_text("...")
    assert out.vendor == "Grand Hotel" and fake.chat.completions.calls == 2


def test_extract_degrades_to_unavailable(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://x/openai/v1/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")  # force live_ready
    _patch_client(monkeypatch, [RuntimeError("boom"), RuntimeError("boom")])
    out = receipts.extract_receipt(b"\xff\xd8\xff", "image/jpeg")
    assert out.source == "unavailable"


# --- endpoint tests (mock mode) -------------------------------------------- #
@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)  # force mock mode
    from app.api import app

    with TestClient(app) as c:
        yield c


def test_endpoint_mock_extraction(client):
    r = client.post("/receipts/extract", files={"file": ("bill.png", PNG, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "mock" and body["total"] == 128.5


def test_endpoint_unsupported_type_415(client):
    r = client.post("/receipts/extract", files={"file": ("bill.csv", b"a,b,c", "text/csv")})
    assert r.status_code == 415


def test_endpoint_oversized_413(client):
    big = PNG + b"0" * (MAX_UPLOAD_BYTES + 1)
    r = client.post("/receipts/extract", files={"file": ("big.png", big, "image/png")})
    assert r.status_code == 413


async def test_extract_does_not_block_event_loop(monkeypatch):
    """Two concurrent extractions should overlap (run in threads), not serialize."""
    import app.api as api

    def slow_extract(data, mimetype):
        time.sleep(0.4)  # blocking work, like the real sync openai/pymupdf calls
        return ReceiptExtraction(source="mock")

    monkeypatch.setattr(api, "extract_receipt", slow_extract)

    async with AsyncClient(transport=ASGITransport(app=api.app), base_url="http://t") as ac:
        started = time.perf_counter()
        await asyncio.gather(
            ac.post("/receipts/extract", files={"file": ("a.png", PNG, "image/png")}),
            ac.post("/receipts/extract", files={"file": ("b.png", PNG, "image/png")}),
        )
        elapsed = time.perf_counter() - started

    # ~0.4s if offloaded to threads (overlapped); ~0.8s if the loop was blocked (serialized).
    assert elapsed < 0.7, f"requests serialized in {elapsed:.2f}s — event loop is blocked"
