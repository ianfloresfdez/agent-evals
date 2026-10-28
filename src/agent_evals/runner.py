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
from .schema import Attempt, Case, CaseResult, Check, RunResult, Suite, Trace
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


def _attempt(r: CaseResult) -> Attempt:
    return Attempt(
        passed=r.passed, task_success=r.task_success, latency_ms=r.trace.latency_ms, tokens=r.trace.usage.total,
        cost_usd=r.trace.cost_usd or 0.0, judge_score=r.judge.score if r.judge else None,
        judge_tokens=r.judge.usage.total if r.judge else 0, tool_recall=r.tool_recall, tool_precision=r.tool_precision,
        tool_calls=[c.name for c in r.trace.tool_calls], failed_checks=[c.name for c in r.checks if not c.passed],
        error=r.trace.error,
    )


def merge_attempts(results: list[CaseResult]) -> CaseResult:
    """Folds repeated executions of one case into a single result that passes only if every attempt passed."""
    first = results[0]
    if len(results) == 1:
        return first
    return first.model_copy(update={
        "attempts": [_attempt(r) for r in results],
        "passed": all(r.passed for r in results),
        "task_success": all(r.task_success for r in results),
    })


def run_suite(suite: Suite, judge: Judge | None = None, on_case: Callable[[CaseResult], None] | None = None,
              repeat: int = 1) -> RunResult:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    target = make_target(suite.target, Path(suite.path).parent)
    results: list[CaseResult] = []
    with target:
        info = target.describe()
        for case in suite.cases:
            runs = [score_case(case, target.run(case), suite, judge, target.judge_input(case)) for _ in range(max(1, repeat))]
            res = merge_attempts(runs)
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
