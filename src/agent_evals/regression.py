"""Compares a run with a baseline (the previous run of the same suite, or a committed file) and decides pass/fail."""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import RegressionRules, RunResult


@dataclass
class Finding:
    metric: str
    baseline: float | None
    current: float | None
    ok: bool
    note: str = ""


@dataclass
class Comparison:
    baseline_id: str
    current_id: str
    findings: list[Finding] = field(default_factory=list)
    regressed_cases: list[str] = field(default_factory=list)
    fixed_cases: list[str] = field(default_factory=list)
    new_cases: list[str] = field(default_factory=list)
    suite_changed: bool = False

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.findings)


def _pct(base: float, cur: float) -> float:
    return 0.0 if base == 0 else (cur - base) / base * 100


def compare(base: RunResult, cur: RunResult, rules: RegressionRules, skip: set[str] | None = None) -> Comparison:
    skip = skip or set()
    out = Comparison(baseline_id=base.run_id, current_id=cur.run_id, suite_changed=base.suite_sha256 != cur.suite_sha256)
    b, c = base.summary, cur.summary

    def add(metric: str, bv, cv, ok: bool, note: str):
        if metric not in skip:
            out.findings.append(Finding(metric, bv, cv, ok, note))

    add("pass_rate", b.pass_rate, c.pass_rate, b.pass_rate - c.pass_rate <= rules.max_pass_rate_drop + 1e-9,
        f"max drop {rules.max_pass_rate_drop:.0%}")
    if b.judge_mean is not None and c.judge_mean is not None:
        add("judge_mean", b.judge_mean, c.judge_mean, b.judge_mean - c.judge_mean <= rules.max_judge_mean_drop + 1e-9,
            f"max drop {rules.max_judge_mean_drop}")
    add("latency_p50_ms", b.latency_p50_ms, c.latency_p50_ms,
        _pct(b.latency_p50_ms, c.latency_p50_ms) <= rules.max_latency_p50_increase_pct, f"max +{rules.max_latency_p50_increase_pct:g}%")
    add("tokens_mean", b.tokens_mean, c.tokens_mean,
        _pct(b.tokens_mean, c.tokens_mean) <= rules.max_tokens_mean_increase_pct, f"max +{rules.max_tokens_mean_increase_pct:g}%")
    add("cost_usd_total", b.cost_usd_total, c.cost_usd_total,
        _pct(b.cost_usd_total, c.cost_usd_total) <= rules.max_cost_increase_pct, f"max +{rules.max_cost_increase_pct:g}%")

    before = {r.id: r.passed for r in base.cases}
    for r in cur.cases:
        if r.id not in before:
            out.new_cases.append(r.id)
        elif before[r.id] and not r.passed:
            out.regressed_cases.append(r.id)
        elif not before[r.id] and r.passed:
            out.fixed_cases.append(r.id)
    if rules.fail_on_case_regression and "cases" not in skip:
        out.findings.append(Finding("cases", None, None, not out.regressed_cases,
                                    "regressed: " + ", ".join(out.regressed_cases) if out.regressed_cases else "no case went from pass to fail"))
    return out


def format_comparison(cmp: Comparison) -> str:
    lines = [f"baseline {cmp.baseline_id} → current {cmp.current_id}" + ("  (golden set changed since baseline)" if cmp.suite_changed else "")]
    for f in cmp.findings:
        mark = "OK  " if f.ok else "FAIL"
        vals = "" if f.baseline is None else f"{f.baseline:g} → {f.current:g}"
        lines.append(f"  {mark} {f.metric:<16} {vals:<24} {f.note}")
    if cmp.fixed_cases:
        lines.append(f"  fixed: {', '.join(cmp.fixed_cases)}")
    if cmp.new_cases:
        lines.append(f"  new cases: {', '.join(cmp.new_cases)}")
    lines.append("REGRESSION GATE: " + ("PASS" if cmp.ok else "FAIL"))
    return "\n".join(lines)
