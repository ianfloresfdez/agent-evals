from typer.testing import CliRunner

from agent_evals.cli import app
from agent_evals.regression import compare, format_comparison
from agent_evals.report import build_report
from agent_evals.runner import save_run
from agent_evals.schema import RegressionRules


def test_case_regression_fails_gate(run_factory):
    make_run, make_case = run_factory
    base = make_run("r1", [make_case("a"), make_case("b")])
    cur = make_run("r2", [make_case("a"), make_case("b", passed=False), make_case("c")])
    cmp = compare(base, cur, RegressionRules())
    assert not cmp.ok
    assert cmp.regressed_cases == ["b"] and cmp.new_cases == ["c"]
    assert "REGRESSION GATE: FAIL" in format_comparison(cmp)


def test_latency_and_tokens_thresholds(run_factory):
    make_run, make_case = run_factory
    base = make_run("r1", [make_case("a", latency=1000, tokens=100)])
    slow = make_run("r2", [make_case("a", latency=1600, tokens=120)])
    cmp = compare(base, slow, RegressionRules(max_latency_p50_increase_pct=50, max_tokens_mean_increase_pct=25))
    assert {f.metric for f in cmp.findings if not f.ok} == {"latency_p50_ms"}
    assert compare(base, slow, RegressionRules(), skip={"latency_p50_ms"}).ok


def test_judge_drop(run_factory):
    make_run, make_case = run_factory
    base = make_run("r1", [make_case("a", judge=4.5)])
    cur = make_run("r2", [make_case("a", judge=3.5)])
    assert not compare(base, cur, RegressionRules(max_judge_mean_drop=0.5)).ok


def test_report_and_cli(tmp_path, run_factory):
    make_run, make_case = run_factory
    results = tmp_path / "results"
    p1 = save_run(make_run("20261028T000000Z", [make_case("a"), make_case("b")]), results)
    save_run(make_run("20261028T010000Z", [make_case("a"), make_case("b", passed=False)]), results)
    html = build_report(results, tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "demo" in html and "regression gate FAIL" in html and "<b>b</b>" in html

    runner = CliRunner()
    res = runner.invoke(app, ["compare", str(p1), "--results", str(results)])
    assert res.exit_code == 1 and "regressed: b" in res.output
    res = runner.invoke(app, ["list", "--results", str(results)])
    assert res.exit_code == 0 and res.output.count("demo") == 2


def test_cost_and_tokens_from_zero_baseline_regress(run_factory):
    make_run, make_case = run_factory
    base = make_run("r1", [make_case("a", tokens=0)])
    cur = make_run("r2", [make_case("a", tokens=500)])
    cmp = compare(base, cur, RegressionRules())
    assert {f.metric for f in cmp.findings if not f.ok} == {"tokens_mean"}
    assert compare(base, base, RegressionRules()).ok


def test_report_without_results_and_compare_without_runs(tmp_path, run_factory):
    make_run, make_case = run_factory
    html = build_report(tmp_path / "missing", tmp_path / "out.html").read_text(encoding="utf-8")
    assert "<html" in html.lower()
    p = save_run(make_run("r1", [make_case("a")]), tmp_path / "elsewhere")
    res = CliRunner().invoke(app, ["compare", str(p), "--results", str(tmp_path / "empty")])
    assert res.exit_code == 2 and "No stored runs" in res.output
