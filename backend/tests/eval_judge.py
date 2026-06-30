"""gpt-oss-backed groundedness judge for DeepEval (no OpenAI key needed).

gpt-oss is a weak *structured-output* judge: under heavy reasoning it leaks the answer
into the harmony reasoning channel and emits malformed `content`, which breaks strict
parsers (instructor/GEval). So we judge with low reasoning effort and parse leniently
(content first, then the reasoning channel). The DETERMINISTIC metrics remain the
authoritative correctness gate; this is an opt-in qualitative signal.
"""
from __future__ import annotations

import json
import re

from openai import OpenAI

from app.config import get_settings

_FLAT_OBJ = re.compile(r"\{[^{}]*\}")


def _extract_scored_json(text: str | None) -> dict | None:
    if not text:
        return None
    for candidate in reversed(_FLAT_OBJ.findall(text)):  # prefer the last/final object
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if "score" in data:
            return data
    return None


def score_groundedness(decision: dict) -> tuple[float, str]:
    """Return (score in 0..1, reason): is the explanation grounded in the decision?"""
    s = get_settings()
    client = OpenAI(base_url=s.base_url, api_key=s.api_key)
    prompt = (
        "You are an evaluator. Score 0-10 whether the EXPLANATION is grounded in the DECISION: "
        "it must reference the actual outcome and the approved/deducted amounts, and must not "
        "invent policy or contradict the decision. Reply with ONLY compact JSON: "
        '{"score": <0-10 integer>, "reason": "<one sentence>"}.\n\n'
        f"DECISION: {json.dumps(decision)}\n\nEXPLANATION: {decision.get('explanation', '')}"
    )
    msg = client.chat.completions.create(
        model=s.deployment,
        messages=[{"role": "user", "content": prompt}],
        reasoning_effort="low",
    ).choices[0].message
    data = _extract_scored_json(msg.content) or _extract_scored_json(getattr(msg, "reasoning_content", None))
    if not data or "score" not in data:
        raise ValueError(f"gpt-oss judge produced no parseable score: {msg.content!r}")
    return float(data["score"]) / 10.0, str(data.get("reason", ""))
