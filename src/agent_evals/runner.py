"""Runs a suite against its target: one trace per case, then deterministic checks and (optionally) the judge."""

from __future__ import annotations

import json
import platform
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import metrics
from .judge import Judge
from .schema import Case, CaseResult, Check, RunResult, Suite, Trace
from .targets import make_target


def score_case(case: Case, trace: Trace, suite: Suite, judge: Judge | None, judge_input: str) -> CaseResult:
    checks: list[Check] = []
    if trace.error:
        checks.append(Check(name="target ran without error", passed=False, detail=trace.error[:300]))
    checks += metrics.output_checks(case.expect, trace)
    tool_checks, recall, precision = metrics.tool_checks(case.expect.tools, trace.tool_calls)
    checks += tool_checks
    checks += metrics.budget_checks(metrics.merge_budgets(suite.budgets, case.budgets), trace)
    task_success = all(c.passed for c in checks if c.kind in ("task", "tools"))

    verdict = None
    rubric = case.rubric or suite.rubric
    if judge and rubric and not trace.error and not (case.expect.judge and case.expect.judge.skip):
        verdict = judge.evaluate(judge_input, rubric, trace)
        exp = case.expect.judge
        if exp and verdict.score is not None:
            if exp.min_score is not None:
                checks.append(Check(name=f"judge ≥ {exp.min_score}", passed=verdict.score >= exp.min_score, detail=f"{verdict.score:g}", kind="judge"))
            if exp.max_score is not None:
                checks.append(Check(name=f"judge ≤ {exp.max_score} (negative control)", passed=verdict.score <= exp.max_score, detail=f"{verdict.score:g}", kind="judge"))
        elif exp and verdict.error:
            checks.append(Check(name="judge verdict", passed=False, detail=verdict.error, kind="judge"))

    return CaseResult(
        id=case.id, tags=case.tags, passed=all(c.passed for c in checks), task_success=task_success, checks=checks,
        tool_recall=recall, tool_precision=precision, judge=verdict, trace=trace,
        judge_control=bool(case.expect.judge and case.expect.judge.max_score is not None),
    )


def run_suite(suite: Suite, judge: Judge | None = None, on_case: Callable[[CaseResult], None] | None = None) -> RunResult:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    target = make_target(suite.target, Path(suite.path).parent)
    results: list[CaseResult] = []
    with target:
        info = target.describe()
        for case in suite.cases:
            trace = target.run(case)
            res = score_case(case, trace, suite, judge, target.judge_input(case))
            results.append(res)
            if on_case:
                on_case(res)
    return RunResult(
        run_id=started.strftime("%Y%m%dT%H%M%SZ"),
        suite=suite.suite,
        suite_version=suite.version,
        suite_sha256=suite.sha256[:12],
        target=info,
        judge=judge.spec if judge else None,
        started_at=started.isoformat(timespec="seconds"),
        duration_s=round(time.perf_counter() - t0, 1),
        environment={"python": platform.python_version(), "platform": platform.platform(terse=True)},
        summary=metrics.summarize(results),
        cases=results,
    )


# ── Storage: results/<suite>/<run_id>.json ────────────────────────────────────


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def save_run(run: RunResult, results_dir: Path) -> Path:
    """Stores the run. Email addresses in agent outputs (job posts often include one) are redacted first."""
    out = results_dir / run.suite / f"{run.run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(EMAIL.sub("[email]", run.model_dump_json(indent=1)), encoding="utf-8")
    return out


def load_run(path: Path) -> RunResult:
    return RunResult.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def list_runs(results_dir: Path, suite: str) -> list[Path]:
    return sorted((results_dir / suite).glob("*.json"))
