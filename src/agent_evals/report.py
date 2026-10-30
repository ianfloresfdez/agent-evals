"""Static HTML report: one self-contained page with the latest run of every suite, its trend and its cases."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .regression import compare
from .runner import list_runs, load_run
from .schema import RegressionRules


def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _spark(values: list[float], width: int = 120, height: int = 28) -> str:
    """Polyline points for a tiny inline SVG trend."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = width / (len(values) - 1)
    return " ".join(f"{i * step:.1f},{height - 3 - (v - lo) / span * (height - 6):.1f}" for i, v in enumerate(values))


def build_report(results_dir: Path, out: Path, history: int = 20) -> Path:
    env = Environment(loader=PackageLoader("agent_evals", "templates"), autoescape=select_autoescape(["html"]))
    env.filters.update(ms=_fmt_ms, pct=_pct)
    suites = []
    dirs = sorted(p for p in results_dir.iterdir() if p.is_dir()) if results_dir.is_dir() else []
    for suite_dir in dirs:
        paths = list_runs(results_dir, suite_dir.name)[-history:]
        if not paths:
            continue
        runs = [load_run(p) for p in paths]
        latest = runs[-1]
        cmp = compare(runs[-2], latest, RegressionRules()) if len(runs) > 1 else None
        suites.append({
            "run": latest,
            "history": runs,
            "cmp": cmp,
            "spark_pass": _spark([r.summary.pass_rate for r in runs]),
            "spark_latency": _spark([r.summary.latency_p50_ms for r in runs]),
        })
    html = env.get_template("report.html.j2").render(suites=suites)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
