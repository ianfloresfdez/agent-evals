"""Deterministic metrics: task success, tool-call correctness, budgets, and run-level aggregates."""

from __future__ import annotations

import re
import statistics
from typing import Any

from .schema import Budgets, CaseResult, Check, Expect, Summary, ToolCall, ToolExpectation, ToolsExpect, Trace

# ── Matchers ──────────────────────────────────────────────────────────────────
# A matcher is either a literal (compared with ==) or a dict with one or more operators.


def _norm(v: Any) -> str:
    return str(v).casefold()


def _ops(spec: Any) -> dict[str, Any]:
    if isinstance(spec, dict) and spec and all(k in OPERATORS for k in spec):
        return spec
    return {"equals": spec}


def _contains(value: Any, needle: Any) -> bool:
    if isinstance(value, list):
        return any(_norm(needle) in _norm(v) for v in value)
    return _norm(needle) in _norm(value)


OPERATORS = {
    "equals": lambda v, a: v == a,
    "not_equals": lambda v, a: v != a,
    "iequals": lambda v, a: _norm(v) == _norm(a),
    "contains": lambda v, a: v is not None and _contains(v, a),
    "not_contains": lambda v, a: v is None or not _contains(v, a),
    "contains_all": lambda v, a: v is not None and all(_contains(v, x) for x in a),
    "contains_any": lambda v, a: v is not None and any(_contains(v, x) for x in a),
    "regex": lambda v, a: v is not None and re.search(a, str(v)) is not None,
    "not_regex": lambda v, a: v is None or re.search(a, str(v)) is None,
    "any_of": lambda v, a: v in a,
    "gte": lambda v, a: v is not None and v >= a,
    "lte": lambda v, a: v is not None and v <= a,
    "exists": lambda v, a: (v is not None) == bool(a),
    "length": lambda v, a: v is not None and len(v) == a,
    "min_length": lambda v, a: v is not None and len(v) >= a,
}


def match(value: Any, spec: Any) -> bool:
    for op, arg in _ops(spec).items():
        try:
            if not OPERATORS[op](value, arg):
                return False
        except TypeError:
            return False
    return True


_MISSING = object()


def get_path(data: Any, path: str) -> Any:
    """Dotted path lookup: "risk.level", "stages.verify", "files.0.path"."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part, _MISSING)
        elif isinstance(cur, list) and part.lstrip("-").isdigit():
            idx = int(part)
            cur = cur[idx] if -len(cur) <= idx < len(cur) else _MISSING
        else:
            cur = _MISSING
        if cur is _MISSING:
            return None
    return cur


def _short(v: Any, n: int = 80) -> str:
    s = repr(v)
    return s if len(s) <= n else s[: n - 1] + "…"


# ── Checks ────────────────────────────────────────────────────────────────────


def output_checks(expect: Expect, trace: Trace) -> list[Check]:
    checks = []
    for spec in expect.output:
        ok = match(trace.output, spec)
        checks.append(Check(name=f"output {_short(spec, 70)}", passed=ok, detail="" if ok else "not satisfied by the final answer"))
    for path, spec in expect.fields.items():
        value = get_path(trace.data, path)
        ok = match(value, spec)
        checks.append(Check(name=f"{path} {_short(spec, 60)}", passed=ok, detail=f"got {_short(value)}"))
    return checks


def _call_matches(call: ToolCall, exp: ToolExpectation) -> bool:
    if call.name != exp.name:
        return False
    return all(match(call.args.get(k), spec) for k, spec in exp.args.items())


def tool_checks(expect: ToolsExpect | None, calls: list[ToolCall]) -> tuple[list[Check], float | None, float | None]:
    """Returns checks plus recall (required calls made) and precision (calls that were expected or allowed)."""
    if expect is None:
        return [], None, None
    checks: list[Check] = []
    matched = 0
    cursor = 0
    for exp in expect.required:
        pool = calls[cursor:] if expect.ordered else calls
        hit = next((i for i, c in enumerate(pool) if _call_matches(c, exp)), None)
        if hit is not None:
            matched += 1
            if expect.ordered:
                cursor += hit + 1
            checks.append(Check(name=f"calls {exp.name}", passed=True, kind="tools"))
        else:
            same_name = [c.args for c in calls if c.name == exp.name]
            detail = f"called with {_short(same_name, 160)}" if same_name else "never called"
            checks.append(Check(name=f"calls {exp.name} {_short(exp.args, 60) if exp.args else ''}".strip(), passed=False, detail=detail, kind="tools"))
    for name in expect.forbidden:
        n = sum(c.name == name for c in calls)
        checks.append(Check(name=f"never calls {name}", passed=n == 0, detail=f"called {n}x" if n else "", kind="tools"))
    if expect.max_calls is not None:
        checks.append(Check(name=f"at most {expect.max_calls} tool calls", passed=len(calls) <= expect.max_calls, detail=f"{len(calls)} calls", kind="tools"))

    recall = matched / len(expect.required) if expect.required else None
    ok_names = {e.name for e in expect.required} | set(expect.allowed)
    precision = (sum(c.name in ok_names for c in calls) / len(calls)) if calls else (1.0 if not expect.required else 0.0)
    return checks, recall, precision


def budget_checks(budgets: Budgets, trace: Trace) -> list[Check]:
    checks = []
    if budgets.latency_ms is not None:
        checks.append(Check(name=f"latency ≤ {budgets.latency_ms:.0f} ms", passed=trace.latency_ms <= budgets.latency_ms, detail=f"{trace.latency_ms:.0f} ms", kind="budget"))
    if budgets.total_tokens is not None:
        checks.append(Check(name=f"tokens ≤ {budgets.total_tokens}", passed=trace.usage.total <= budgets.total_tokens, detail=f"{trace.usage.total} tokens", kind="budget"))
    if budgets.cost_usd is not None:
        cost = trace.cost_usd or 0.0
        checks.append(Check(name=f"cost ≤ ${budgets.cost_usd}", passed=cost <= budgets.cost_usd, detail=f"${cost:.4f}", kind="budget"))
    return checks


def merge_budgets(base: Budgets, override: Budgets | None) -> Budgets:
    if override is None:
        return base
    return Budgets(**{**base.model_dump(), **override.model_dump(exclude_none=True)})


# ── Aggregates ────────────────────────────────────────────────────────────────


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def summarize(results: list[CaseResult]) -> Summary:
    n = len(results)
    lat = [r.trace.latency_ms for r in results]
    tokens = [r.trace.usage.total for r in results]
    judged = [r.judge.score for r in results if r.judge and r.judge.score is not None and not r.judge_control]
    return Summary(
        cases=n,
        passed=sum(r.passed for r in results),
        pass_rate=round(sum(r.passed for r in results) / n, 4) if n else 0.0,
        task_success_rate=round(sum(r.task_success for r in results) / n, 4) if n else 0.0,
        tool_recall_mean=_mean([r.tool_recall for r in results if r.tool_recall is not None]),
        tool_precision_mean=_mean([r.tool_precision for r in results if r.tool_precision is not None]),
        judge_mean=_mean(judged),
        latency_p50_ms=round(percentile(lat, 50), 1),
        latency_p95_ms=round(percentile(lat, 95), 1),
        tokens_total=sum(tokens),
        tokens_mean=round(sum(tokens) / n, 1) if n else 0.0,
        cost_usd_total=round(sum(r.trace.cost_usd or 0.0 for r in results), 6),
        judge_tokens_total=sum(r.judge.usage.total for r in results if r.judge),
        errors=sum(r.trace.error is not None for r in results),
    )
