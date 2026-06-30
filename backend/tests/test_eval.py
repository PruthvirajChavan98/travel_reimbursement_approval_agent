"""DeepEval suite (offline by default).

Tier 1 (always on, no judge, no keys): a deterministic DecisionMatch metric asserts the
exact reimbursement outcome and money against the golden set — this is the gate that
matters for an adjudication agent.
Tier 2 (opt-in): a GEval qualitative check on the explanation, judged by the gpt-oss
endpoint; runs only when RUN_LLM_JUDGE=1 and Azure creds are present.

Run:  uv run deepeval test run tests/test_eval.py   (or plain `uv run pytest tests/test_eval.py`)
"""
import json
import os

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_DISABLE_PROGRESS_BAR", "YES")

import pytest  # noqa: E402
from deepeval import assert_test  # noqa: E402
from deepeval.metrics import BaseMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

from app import config  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.runner import run_mock  # noqa: E402


class DecisionMatch(BaseMetric):
    """Deterministic: exact decision + approved/rejected amounts (no LLM judge)."""

    def __init__(self, tol: float = 0.01):
        self.threshold = 1.0
        self.tol = tol
        self.async_mode = False
        self.evaluation_cost = None
        self.score = 0.0
        self.success = False
        self.reason = ""
        self.error = None

    def measure(self, test_case: LLMTestCase) -> float:
        got = json.loads(test_case.actual_output)
        exp = json.loads(test_case.expected_output)
        ok = (
            got["decision"] == exp["decision"]
            and abs(got["approved_amount"] - exp["approved_amount"]) <= self.tol
            and abs(got["rejected_amount"] - exp["rejected_amount"]) <= self.tol
        )
        self.score = 1.0 if ok else 0.0
        self.success = ok
        self.reason = (
            f"decision {got['decision']} vs {exp['decision']}; "
            f"approved {got['approved_amount']} vs {exp['approved_amount']}"
        )
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self):
        return "DecisionMatch"


SAMPLES = sorted(config.CLAIMS_DIR.glob("*.json"))


@pytest.mark.parametrize("claim_path", SAMPLES, ids=lambda p: p.stem)
def test_decision_matches_golden(claim_path):
    claim = json.loads(claim_path.read_text())
    gold = json.loads((config.DATA_DIR / "golden" / claim_path.name).read_text())
    actual = run_mock(claim).decision.model_dump()
    tc = LLMTestCase(
        input=claim_path.stem,
        actual_output=json.dumps(actual),
        expected_output=json.dumps(gold),
    )
    assert_test(tc, [DecisionMatch()])


class Groundedness(BaseMetric):
    """Opt-in qualitative metric: gpt-oss judges whether the explanation is grounded."""

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold
        self.async_mode = False
        self.evaluation_cost = None
        self.score = 0.0
        self.success = False
        self.reason = ""
        self.error = None

    def measure(self, test_case: LLMTestCase) -> float:
        from eval_judge import score_groundedness

        self.score, self.reason = score_groundedness(json.loads(test_case.actual_output))
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self):
        return "Groundedness"


@pytest.mark.skipif(
    not (os.getenv("RUN_LLM_JUDGE") and get_settings().live_ready),
    reason="LLM-judge metric is opt-in (set RUN_LLM_JUDGE=1 with Azure creds present)",
)
def test_explanation_is_grounded():
    claim = json.loads((config.CLAIMS_DIR / "02_partial.json").read_text())
    decision = run_mock(claim).decision.model_dump()
    tc = LLMTestCase(input=json.dumps(claim), actual_output=json.dumps(decision))
    try:
        assert_test(tc, [Groundedness()])
    except ValueError as exc:  # gpt-oss failed to emit a parseable score (harmony quirk)
        pytest.skip(f"gpt-oss judge could not produce structured output: {exc}")
