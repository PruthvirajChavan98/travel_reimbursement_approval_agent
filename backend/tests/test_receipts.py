"""P1: receipt routing (parsable PDF → text; image / scanned-PDF → image)."""
import pymupdf
import pytest

from app.receipts import _render_page_png, route_receipt


def _text_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _blank_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()  # no text layer → scanned/image-only
    data = doc.tobytes()
    doc.close()
    return data


def test_png_routes_to_image():
    kind, data, mime = route_receipt(b"\x89PNG\r\n\x1a\n", "image/png")
    assert kind == "image" and mime == "image/png" and data


def test_jpeg_routes_to_image():
    kind, _data, mime = route_receipt(b"\xff\xd8\xff\xe0", "image/jpeg")
    assert kind == "image" and mime == "image/jpeg"


def test_mimetype_with_charset_suffix():
    assert route_receipt(b"\x89PNG", "image/png; charset=binary")[0] == "image"


def test_text_pdf_routes_to_text():
    route = route_receipt(_text_pdf("Grand Hotel Denver  Lodging  Total $300.00  2026-06-12"), "application/pdf")
    assert route[0] == "text" and "Total" in route[1]


def test_scanned_pdf_routes_to_image():
    route = route_receipt(_blank_pdf(), "application/pdf")
    assert route[0] == "image" and route[2] == "image/png" and len(route[1]) > 0


def test_unsupported_type_raises():
    with pytest.raises(ValueError):
        route_receipt(b"col1,col2", "text/csv")


def test_render_page_png_downscales_when_over_budget():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 50), "RECEIPT " * 300, fontsize=10)
    full = _render_page_png(page, max_bytes=10**9)  # huge budget → full 200-DPI render
    small = _render_page_png(page, max_bytes=1000)  # tiny budget → forces a down-step
    doc.close()
    assert len(small) > 0 and len(small) < len(full)  # downscale engaged
