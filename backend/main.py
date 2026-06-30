"""CLI for the Travel Reimbursement Approval Agent.

    python main.py evaluate data/claims/01_approve.json          # live if Azure key set, else mock
    python main.py evaluate data/claims/04_manual_review.json --resume-as approve
    python main.py evaluate <claim.json> --mock                  # force the deterministic path
    python main.py batch                                         # deterministic; writes outputs/*.decision.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app import config
from app.config import get_settings
from app.runner import adjudicate, live_graph, resume, run_mock
from app.tracing import emit_trace


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, default=str)


async def _evaluate_live(claim: dict, resume_as: str | None) -> dict:
    from app.checkpoint import memory_checkpointer  # CLI uses in-memory (single process)

    settings = get_settings()
    async with live_graph(memory_checkpointer(), settings) as graph:
        out = await adjudicate(graph, claim, claim["claim_id"])
        if out["interrupt"] and resume_as:
            human = {"approved": resume_as == "approve", "approver": "cli", "note": f"auto-{resume_as}"}
            out = await resume(graph, claim["claim_id"], human)
        emit_trace(claim, out["decision"], "live", settings=settings)
        return out


def cmd_evaluate(args) -> None:
    claim = json.loads(Path(args.claim).read_text())
    settings = get_settings()
    if args.mock or not settings.live_ready:
        result = run_mock(claim)
        emit_trace(claim, result.decision.model_dump(), "mock", settings=settings)
        print(_dump({"mode": "mock", "decision": result.decision.model_dump(), "trace": result.trace.model_dump()}))
    else:
        print(_dump({"mode": "live", **asyncio.run(_evaluate_live(claim, args.resume_as))}))


def cmd_batch(args) -> None:
    """Deterministic batch over the sample claims → outputs/ (reproducible, no secrets)."""
    out_dir = config.OUTPUTS_DIR
    out_dir.mkdir(exist_ok=True)
    count = 0
    for path in sorted(config.CLAIMS_DIR.glob("*.json")):
        claim = json.loads(path.read_text())
        result = run_mock(claim)
        payload = {"decision": result.decision.model_dump(), "trace": result.trace.model_dump()}
        (out_dir / f"{path.stem}.decision.json").write_text(_dump(payload))
        d = result.decision
        print(f"{path.name:24} {d.decision.value:16} approved=${d.approved_amount:<8} of ${d.claimed_amount}")
        count += 1
    print(f"\nWrote {count} decisions to {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Travel Reimbursement Approval Agent")
    sub = parser.add_subparsers(dest="command")

    ev = sub.add_parser("evaluate", help="adjudicate one claim JSON")
    ev.add_argument("claim", help="path to a claim JSON file")
    ev.add_argument("--mock", action="store_true", help="force the deterministic pipeline")
    ev.add_argument("--resume-as", choices=["approve", "reject"], help="auto-resume a manual-review interrupt")
    ev.set_defaults(func=cmd_evaluate)

    ba = sub.add_parser("batch", help="adjudicate all sample claims (deterministic) → outputs/")
    ba.add_argument("--mock", action="store_true", help="(default) deterministic")
    ba.set_defaults(func=cmd_batch)

    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
