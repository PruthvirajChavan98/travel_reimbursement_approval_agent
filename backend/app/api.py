"""FastAPI service. The lifespan owns the long-lived async resources (MCP client +
checkpointer pool + compiled graph) on the serving loop; requests read app.state.

- live (Azure key present): the LangGraph path (Postgres checkpointer if DATABASE_URL, else in-memory)
- mock  (no key): the deterministic pipeline, so the service still runs with no secrets
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.checkpoint import memory_checkpointer, postgres_checkpointer
from app.config import get_settings
from app.models import ReceiptExtraction
from app.receipts import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, extract_receipt
from app.runner import adjudicate, live_graph, resume, run_mock
from app.tracing import emit_trace


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    if not settings.live_ready:
        app.state.graph, app.state.mode = None, "mock"
        yield
        return
    if settings.database_url:
        async with postgres_checkpointer(settings.database_url) as saver, live_graph(saver, settings) as graph:
            app.state.graph, app.state.mode = graph, "live"
            yield
    else:
        async with live_graph(memory_checkpointer(), settings) as graph:
            app.state.graph, app.state.mode = graph, "live"
            yield


app = FastAPI(title="Travel Reimbursement Approval Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AdjudicateBody(BaseModel):
    claim: dict


class ResumeBody(BaseModel):
    claim_id: str
    approved: bool
    approver: str = "api"
    note: str = ""


@app.get("/healthz")
async def healthz(request: Request):
    return {"status": "ok", "mode": request.app.state.mode}


@app.post("/adjudicate")
async def adjudicate_endpoint(body: AdjudicateBody, request: Request):
    settings, graph = request.app.state.settings, request.app.state.graph
    claim = body.claim
    if graph is None:  # mock mode
        result = run_mock(claim)
        decision = result.decision.model_dump()
        emit_trace(claim, decision, "mock", settings=settings)
        return {"decision": decision, "interrupt": None, "trace": result.trace.model_dump(), "mode": "mock"}
    out = await adjudicate(graph, claim, claim["claim_id"])
    emit_trace(claim, out["decision"], "live", settings=settings)
    return {**out, "mode": "live"}


@app.post("/resume")
async def resume_endpoint(body: ResumeBody, request: Request):
    settings, graph = request.app.state.settings, request.app.state.graph
    if graph is None:
        return {"error": "resume is only available in live mode (mock mode never interrupts)"}
    human = {"approved": body.approved, "approver": body.approver, "note": body.note}
    out = await resume(graph, body.claim_id, human)
    emit_trace({"claim_id": body.claim_id}, out["decision"], "live", settings=settings)
    return {**out, "mode": "live"}


@app.post("/receipts/extract", response_model=ReceiptExtraction)
async def extract_receipt_endpoint(file: UploadFile = File(...)):
    """Upload a bill (png/jpeg/pdf) → structured receipt fields to prefill the claim form.

    Parsable PDFs go to the text LLM; images / scanned PDFs go to the VLM. Model/transport
    failures degrade to source='unavailable' (never 500); only an unsupported type is 415.
    """
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"uploaded file exceeds the {MAX_UPLOAD_MB} MB limit")
    try:
        # extract_receipt is synchronous (blocking openai/pymupdf calls); offload to a worker
        # thread so a slow extraction doesn't block the event loop / other requests.
        return await run_in_threadpool(extract_receipt, data, file.content_type or "")
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc))
