from __future__ import annotations

import pytest

from agent_evals.metrics import summarize
from agent_evals.schema import CaseResult, Check, JudgeVerdict, RunResult, ToolCall, Trace, Usage


def make_case(id: str, passed: bool = True, latency: float = 1000, tokens: int = 100, judge: float | None = None) -> CaseResult:
    return CaseResult(
        id=id, passed=passed, task_success=passed,
        checks=[Check(name="x", passed=passed)],
        judge=JudgeVerdict(score=judge, model="fake") if judge is not None else None,
        trace=Trace(output="ok", latency_ms=latency, usage=Usage(input_tokens=tokens, output_tokens=0),
                    tool_calls=[ToolCall(name="search_jobs")]),
    )


def make_run(run_id: str, cases: list[CaseResult], suite: str = "demo", sha: str = "abc") -> RunResult:
    return RunResult(run_id=run_id, suite=suite, suite_version=1, suite_sha256=sha, target={"type": "fake"}, judge=None,
                     started_at="2026-10-28T00:00:00+00:00", duration_s=1.0, summary=summarize(cases), cases=cases)


@pytest.fixture
def run_factory():
    return make_run, make_case
