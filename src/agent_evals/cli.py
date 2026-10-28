"""agent-evals command line: run golden sets, compare runs, gate CI and build the HTML report."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from .judge import Judge
from .llm import make_client
from .regression import compare, format_comparison
from .report import build_report
from .runner import list_runs, load_run, run_suite, save_run
from .schema import CaseResult
from .suite import load_suite, select_cases

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)

ResultsDir = Annotated[Path, typer.Option("--results", help="Where run results are stored.")]
DEFAULT_JUDGE = "ollama:gemma4:12b"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _print_case(r: CaseResult) -> None:
    mark = typer.style("PASS", fg="green") if r.passed else typer.style("FAIL", fg="red")
    judge = f" judge={r.judge.score:g}" if r.judge and r.judge.score is not None else ""
    typer.echo(f"  {mark} {r.id:<34} {r.trace.latency_ms / 1000:6.1f}s {r.trace.usage.total:>7} tok{judge}")
    for c in r.checks:
        if not c.passed:
            typer.echo(f"         ✖ {c.name}" + (f" — {c.detail}" if c.detail else ""))


def _gate(base_path: Path, current, rules, skip: list[str]) -> bool:
    cmp = compare(load_run(base_path), current, rules, set(skip))
    typer.echo(format_comparison(cmp))
    return cmp.ok


@app.command()
def run(
    suite_path: Annotated[Path, typer.Argument(help="Golden set (YAML or JSON).")],
    judge: Annotated[str, typer.Option(help="Judge model as provider:model.")] = DEFAULT_JUDGE,
    no_judge: Annotated[bool, typer.Option("--no-judge", help="Skip the LLM judge (deterministic metrics only).")] = False,
    case: Annotated[Optional[list[str]], typer.Option("--case", help="Only these case ids (repeatable).")] = None,
    tag: Annotated[Optional[list[str]], typer.Option("--tag", help="Only cases with this tag (repeatable).")] = None,
    results: ResultsDir = Path("results"),
    gate: Annotated[bool, typer.Option("--gate", help="Fail (exit 1) if the run regressed against the baseline.")] = False,
    baseline: Annotated[Optional[Path], typer.Option(help="Baseline run JSON. Default: the previous run of this suite.")] = None,
    skip_metric: Annotated[Optional[list[str]], typer.Option("--skip-metric", help="Metric the gate ignores, e.g. latency_p50_ms.")] = None,
    save: Annotated[bool, typer.Option(help="Store the run under --results.")] = True,
    report: Annotated[Optional[Path], typer.Option(help="Also write the HTML report here.")] = None,
):
    """Run a golden set against its target and score every case."""
    suite = select_cases(load_suite(suite_path), case, tag)
    # Ollama's default context is too small for tool evidence plus the answer.
    j = None if no_judge else Judge(make_client(judge, **({"num_ctx": 16384} if judge.startswith("ollama:") else {})))
    typer.echo(f"{suite.suite} v{suite.version} · {len(suite.cases)} case(s) · target {suite.target.get('type')} · judge {j.spec if j else 'off'}")
    previous = list_runs(results, suite.suite)
    result = run_suite(suite, j, on_case=_print_case)
    s = result.summary
    typer.echo(
        f"\n{s.passed}/{s.cases} passed · task success {s.task_success_rate:.0%}"
        + (f" · tool recall {s.tool_recall_mean:.0%} precision {s.tool_precision_mean:.0%}" if s.tool_recall_mean is not None else "")
        + (f" · judge {s.judge_mean:.2f}/5" if s.judge_mean is not None else "")
        + f" · p50 {s.latency_p50_ms / 1000:.1f}s p95 {s.latency_p95_ms / 1000:.1f}s · {s.tokens_total} tokens · ${s.cost_usd_total:.4f}"
    )
    if save:
        typer.echo(f"saved {save_run(result, results)}")
    if report:
        typer.echo(f"report {build_report(results, report)}")

    base = baseline or (previous[-1] if previous else None)
    if gate:
        if base is None:
            typer.echo("No baseline yet: this run becomes the baseline. Gate passes.")
        elif not _gate(base, result, suite.regression, skip_metric or []):
            raise typer.Exit(1)
    elif s.passed < s.cases:
        typer.echo("(some cases failed; use --gate to turn regressions into a failing exit code)")


@app.command("compare")
def compare_cmd(
    baseline: Annotated[Path, typer.Argument(help="Baseline run JSON.")],
    current: Annotated[Optional[Path], typer.Argument(help="Current run JSON. Default: latest run of the same suite.")] = None,
    suite_path: Annotated[Optional[Path], typer.Option("--suite", help="Golden set whose regression rules apply.")] = None,
    results: ResultsDir = Path("results"),
    skip_metric: Annotated[Optional[list[str]], typer.Option("--skip-metric")] = None,
):
    """Compare two runs and exit 1 if the current one regressed."""
    from .schema import RegressionRules

    base = load_run(baseline)
    cur_path = current or list_runs(results, base.suite)[-1]
    rules = load_suite(suite_path).regression if suite_path else RegressionRules()
    if not _gate(baseline, load_run(cur_path), rules, skip_metric or []):
        raise typer.Exit(1)


@app.command("report")
def report_cmd(
    results: ResultsDir = Path("results"),
    out: Annotated[Path, typer.Option(help="HTML file to write.")] = Path("report/index.html"),
):
    """Build the static HTML report from stored runs."""
    typer.echo(f"report {build_report(results, out)}")


@app.command("list")
def list_cmd(results: ResultsDir = Path("results")):
    """List stored runs per suite."""
    for suite_dir in sorted(p for p in results.glob("*") if p.is_dir()):
        for p in list_runs(results, suite_dir.name):
            r = load_run(p)
            s = r.summary
            judge = f" judge {s.judge_mean:.2f}" if s.judge_mean is not None else ""
            typer.echo(f"{r.suite:<18} {r.run_id}  {s.passed}/{s.cases} pass{judge}  p50 {s.latency_p50_ms / 1000:.1f}s  {s.tokens_total} tok")


if __name__ == "__main__":
    app()
