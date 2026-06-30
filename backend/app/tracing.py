"""Langfuse v2 observability via MANUAL low-level spans.

The langfuse v2 langchain CallbackHandler imports the removed `langchain.callbacks`
module and is incompatible with langchain v1 (verified). So we instrument manually:
one trace per adjudication, with the decision as output. No-ops cleanly when keys
are absent, and never raises into the request path.
"""
from __future__ import annotations

from app.config import Settings, get_settings


def emit_trace(claim: dict, decision: dict | None, mode: str, *, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.langfuse_ready:
        return
    try:
        from langfuse import Langfuse

        lf = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        trace = lf.trace(
            name="adjudicate",
            input=claim,
            metadata={"mode": mode, "claim_id": claim.get("claim_id")},
        )
        if decision:
            trace.span(
                name="reconcile",
                input={"claim_id": claim.get("claim_id")},
                output={
                    "decision": decision.get("decision"),
                    "approved_amount": decision.get("approved_amount"),
                    "confidence": decision.get("confidence"),
                },
            ).end()
            trace.update(output=decision)
        lf.flush()
    except Exception:  # noqa: BLE001 — tracing must never break adjudication
        pass
