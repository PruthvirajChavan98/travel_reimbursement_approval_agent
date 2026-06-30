"""Shared test factories for building ad-hoc claims/line items."""
from app.models import Category, Claim, LineItem


def make_claim(line_items, **kw) -> Claim:
    defaults = dict(claim_id="T-1", employee_id="E-9999", employee_role="employee", trip_purpose="test")
    defaults.update(kw)
    return Claim(line_items=line_items, **defaults)


def line(id="L1", category=Category.lodging, amount=100.0, date="2026-06-10", **kw) -> LineItem:
    return LineItem(id=id, category=category, description=kw.pop("description", "x"), amount=amount, date=date, **kw)
