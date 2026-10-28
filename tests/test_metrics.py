from agent_evals import metrics
from agent_evals.schema import Budgets, Expect, ToolCall, ToolsExpect, Trace, Usage


def test_literal_and_operator_matchers():
    assert metrics.match("low", "low")
    assert not metrics.match("low", "high")
    assert metrics.match("Hello World", {"contains": "world"})
    assert metrics.match(["tests-failed", "ai-review"], {"contains": "tests-failed"})
    assert metrics.match(["a", "b"], {"contains_all": ["a", "b"]})
    assert not metrics.match(["a"], {"contains_all": ["a", "b"]})
    assert metrics.match(50, {"gte": 45, "lte": 60})
    assert not metrics.match(None, {"gte": 1})
    assert metrics.match(None, {"exists": False})
    assert metrics.match("[remotive:12]", {"regex": r"\[[a-z]+:\d+\]"})
    assert metrics.match("nothing", {"not_regex": r"\d"})


def test_dict_literal_is_equality_not_operators():
    assert metrics.match({"by": "auto"}, {"by": "auto"})
    assert not metrics.match({"by": "human"}, {"by": "auto"})


def test_get_path_walks_dicts_and_lists():
    data = {"risk": {"level": "low", "factors": ["x", "y"]}, "errors": [False, True]}
    assert metrics.get_path(data, "risk.level") == "low"
    assert metrics.get_path(data, "risk.factors.1") == "y"
    assert metrics.get_path(data, "errors.-1") is True
    assert metrics.get_path(data, "risk.missing.deeper") is None


def test_output_and_field_checks():
    trace = Trace(output="Ranked 4 of 9 postings", data={"status": "completed"})
    expect = Expect(output=[{"regex": r"Ranked \d+"}], fields={"status": "completed", "risk.level": "low"})
    checks = metrics.output_checks(expect, trace)
    assert [c.passed for c in checks] == [True, True, False]
    assert "got None" in checks[2].detail


def test_tool_recall_precision_and_arguments():
    calls = [
        ToolCall(name="search_jobs", args={"query": "Python", "max_age_days": 7}),
        ToolCall(name="get_job", args={"id": "remotive:1"}),
        ToolCall(name="list_sources"),
    ]
    exp = ToolsExpect(
        required=[{"name": "search_jobs", "args": {"query": {"contains": "python"}, "max_age_days": {"lte": 7}}},
                  {"name": "get_job"}],
        forbidden=["rank_jobs_for_me"], max_calls=3,
    )
    checks, recall, precision = metrics.tool_checks(exp, calls)
    assert all(c.passed for c in checks)
    assert recall == 1.0
    assert precision == 2 / 3  # list_sources was neither required nor allowed


def test_tool_argument_mismatch_reports_actual_args():
    exp = ToolsExpect(required=[{"name": "search_jobs", "args": {"remote_only": True}}])
    checks, recall, _ = metrics.tool_checks(exp, [ToolCall(name="search_jobs", args={"query": "x"})])
    assert recall == 0.0
    assert "called with" in checks[0].detail


def test_ordered_tool_calls():
    exp = ToolsExpect(required=[{"name": "search_jobs"}, {"name": "get_job"}], ordered=True)
    wrong_order = [ToolCall(name="get_job"), ToolCall(name="search_jobs")]
    _, recall, _ = metrics.tool_checks(exp, wrong_order)
    assert recall == 0.5
    _, recall, _ = metrics.tool_checks(exp, list(reversed(wrong_order)))
    assert recall == 1.0


def test_forbidden_and_max_calls():
    exp = ToolsExpect(forbidden=["search_jobs"], max_calls=0)
    checks, recall, precision = metrics.tool_checks(exp, [ToolCall(name="search_jobs")])
    assert [c.passed for c in checks] == [False, False]
    assert recall is None and precision == 0.0
    checks, _, precision = metrics.tool_checks(exp, [])
    assert all(c.passed for c in checks) and precision == 1.0


def test_budgets_and_merge():
    merged = metrics.merge_budgets(Budgets(latency_ms=1000, total_tokens=50), Budgets(latency_ms=5000))
    assert merged.latency_ms == 5000 and merged.total_tokens == 50
    trace = Trace(latency_ms=2000, usage=Usage(input_tokens=40, output_tokens=20))
    assert [c.passed for c in metrics.budget_checks(merged, trace)] == [True, False]


def test_percentiles_and_summary(run_factory):
    _, make_case = run_factory
    assert metrics.percentile([1, 2, 3, 4], 50) == 2.5
    assert metrics.percentile([], 95) == 0.0
    cases = [make_case("a", latency=100, judge=4), make_case("b", passed=False, latency=300, judge=2)]
    s = metrics.summarize(cases)
    assert (s.passed, s.pass_rate, s.judge_mean, s.latency_p50_ms, s.tokens_total) == (1, 0.5, 3.0, 200.0, 200)
    cases[1].judge_control = True
    assert metrics.summarize(cases).judge_mean == 4.0
