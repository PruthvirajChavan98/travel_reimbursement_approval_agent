"""Bill/receipt upload → structured extraction.

Routing — "non-parsable → VLM, parsable → LLM":
- image/* upload                → VLM (Kimi-K2.6, vision)
- PDF with a real text layer    → gpt-oss-120b (text LLM)
- scanned / image-only PDF      → rasterize page 0 → VLM

Both extractors use the SAME OpenAI-compatible `/openai/v1` client + API key (no Entra);
only the `model=` differs (gpt-oss for text, Kimi-K2.6 for image). gpt-oss is text-only;
Kimi-K2.6 is the vision model. Any failure degrades to source="unavailable" so the UI
falls back to manual entry — the endpoint never 500s on a model/transport error.
"""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import date
from functools import lru_cache

from openai import OpenAI

from app.config import Settings, get_settings
from app.models import Category, ReceiptExtraction, ReceiptLineItem

RECEIPT_MIN_CHARS = 15
RECEIPT_RENDER_DPI = 200
RECEIPT_MAX_IMAGE_BYTES = 18 * 1024 * 1024  # margin under Azure's 20 MB per-image limit
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg"}
ALLOWED_MIMES = IMAGE_MIMES | {"application/pdf"}

_SCHEMA_HINT = (
    "You extract structured data from a travel-expense receipt. Return ONLY a JSON object "
    "with keys: vendor (string|null), date (YYYY-MM-DD|null), total (number|null), "
    "suggested_category (one of: lodging, meals, airfare, ground_transport, mileage, other, personal), "
    "line_items (array of {description, amount, quantity (number|null), category (a category|null)}), "
    "raw_text (all readable text, verbatim). Use null when unknown; never invent amounts."
)


# --------------------------------------------------------------------------- #
# Routing (deterministic; pymupdf only)                                       #
# --------------------------------------------------------------------------- #
def _render_page_png(page, max_bytes: int = RECEIPT_MAX_IMAGE_BYTES, dpi: int = RECEIPT_RENDER_DPI) -> bytes:
    """Rasterize a PDF page to PNG, stepping DPI down until it fits the VLM image budget.

    A high-detail page can render to >20 MB even from a small PDF; Azure rejects images over
    20 MB, so keep the rendered PNG under ~18 MB before sending it to the VLM.
    """
    png = page.get_pixmap(dpi=dpi).tobytes("png")
    if len(png) <= max_bytes:
        return png
    for lower in (150, 110, 80):
        if lower >= dpi:
            continue
        png = page.get_pixmap(dpi=lower).tobytes("png")
        if len(png) <= max_bytes:
            break
    return png


def route_receipt(data: bytes, mimetype: str) -> tuple:
    """Return ('text', text) → gpt-oss, or ('image', img_bytes, mime) → VLM.

    Raises ValueError for unsupported content types (→ HTTP 415 at the endpoint).
    """
    mt = (mimetype or "").split(";")[0].strip().lower()
    if mt in IMAGE_MIMES:
        mime = "image/png" if mt == "image/png" else "image/jpeg"
        return ("image", data, mime)
    if mt == "application/pdf":
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as doc:
            text = "".join(page.get_text() for page in doc)
            if len(text.strip()) >= RECEIPT_MIN_CHARS:
                return ("text", text)
            return ("image", _render_page_png(doc[0]), "image/png")
    raise ValueError(f"unsupported content type: {mimetype!r}")


# --------------------------------------------------------------------------- #
# Extraction (raw OpenAI SDK; lenient JSON + one repair retry)                #
# --------------------------------------------------------------------------- #
def _data_url(img: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(img).decode("ascii")


@lru_cache(maxsize=4)
def _client(base_url: str | None, api_key: str | None) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key)


def _loads_lenient(content: str | None) -> dict:
    """Parse JSON tolerant of models that wrap it in prose/fences (gpt-oss/Kimi)."""
    if not content:
        raise ValueError("empty model response")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError("no JSON object in model response")
        return json.loads(match.group(0))


def _extract(client: OpenAI, model: str, messages: list, source: str, fallback_text: str = "", extra: dict | None = None) -> ReceiptExtraction:
    """One call + one repair retry; raises on persistent failure (caller degrades)."""
    convo = list(messages)
    last_err: Exception | None = None
    for attempt in range(2):
        resp = client.chat.completions.create(
            model=model, messages=convo, response_format={"type": "json_object"}, **(extra or {})
        )
        content = resp.choices[0].message.content
        try:
            out = ReceiptExtraction(**_loads_lenient(content))
            out.source = source
            if not out.raw_text and fallback_text:
                out.raw_text = fallback_text
            return out
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            convo = [*messages, {"role": "user", "content": "Your previous reply was not valid JSON for the schema. Reply with ONLY the JSON object."}]
    raise RuntimeError(f"receipt extraction failed: {last_err}")


def _is_empty(r: ReceiptExtraction) -> bool:
    return r.vendor is None and r.total is None and not r.line_items


def extract_from_text(text: str, settings: Settings | None = None) -> ReceiptExtraction:
    """Parsable path. Try gpt-oss (the project's text LLM) first; on this endpoint gpt-oss is
    unreliable for structured output (harmony channel leaks the answer, leaving empty/garbage
    content), so fall back to the VLM on the SAME text when gpt-oss returns empty/invalid."""
    s = settings or get_settings()
    msgs = [{"role": "system", "content": _SCHEMA_HINT}, {"role": "user", "content": f"Receipt text:\n{text}"}]
    try:
        out = _extract(_client(s.base_url, s.api_key), s.deployment, msgs, source="text",
                       fallback_text=text, extra={"extra_body": {"reasoning_effort": "low"}})
        if not _is_empty(out):
            return out
    except Exception:  # noqa: BLE001 — gpt-oss flaky here; fall through to the VLM
        pass
    return _extract(_client(s.vlm_base_url or s.base_url, s.vlm_api_key or s.api_key),
                    s.vlm_model, msgs, source="text", fallback_text=text)


def extract_from_image(img: bytes, mime: str, settings: Settings | None = None) -> ReceiptExtraction:
    s = settings or get_settings()
    client = _client(s.vlm_base_url or s.base_url, s.vlm_api_key or s.api_key)
    return _extract(
        client,
        s.vlm_model,
        [{"role": "user", "content": [
            {"type": "text", "text": _SCHEMA_HINT + " Transcribe all visible text into raw_text."},
            {"type": "image_url", "image_url": {"url": _data_url(img, mime), "detail": "high"}},
        ]}],
        source="vlm",
    )


def _extract_mock(route: tuple, source: str = "mock") -> ReceiptExtraction:
    """Deterministic stub for offline/mock mode and the graceful-failure path."""
    raw = route[1] if route[0] == "text" else "[receipt image — extraction unavailable]"
    return ReceiptExtraction(
        vendor="Sample Vendor Inc.",
        date=date(2026, 6, 15),
        total=128.50,
        suggested_category=Category.meals,
        line_items=[ReceiptLineItem(description="Business dinner", amount=128.50, category=Category.meals)],
        raw_text=raw if isinstance(raw, str) else "",
        source=source,
    )


def extract_receipt(data: bytes, mimetype: str, settings: Settings | None = None) -> ReceiptExtraction:
    """Top-level: route, then extract (or mock/degrade). Routing errors propagate (→415)."""
    s = settings or get_settings()
    route = route_receipt(data, mimetype)  # may raise ValueError → 415
    if not s.live_ready:
        return _extract_mock(route)
    try:
        if route[0] == "text":
            return extract_from_text(route[1], s)
        return extract_from_image(route[1], route[2], s)
    except Exception:  # noqa: BLE001 — degrade gracefully, never 500
        return _extract_mock(route, source="unavailable")
