import pytest

from agent_evals.judge import Judge, build_prompt, parse_verdict
from agent_evals.llm import ChatResponse, make_client
from agent_evals.runner import score_case
from agent_evals.schema import Case, Suite, ToolCall, Trace, Usage


def test_parse_verdict_variants():
    assert parse_verdict('{"reasoning": "fine", "score": 4}') == (4.0, "fine")
    assert parse_verdict('Sure!\n{"score": 2, "reasoning": "weak"}\nThanks')[0] == 2.0
    assert parse_verdict('{"score": 9}')[0] is None
    assert parse_verdict("no json at all")[0] is None


class FakeClient:
    spec = "fake:judge"

    def __init__(self, reply: str):
        self.reply = reply
        self.seen = None

    def chat(self, messages, tools=None, json_schema=None, temperature=0.0):
        self.seen = messages
        return ChatResponse(content=self.reply, usage=Usage(input_tokens=10, output_tokens=5))


def test_prompt_contains_rubric_evidence_and_answer():
    trace = Trace(output="Two jobs found.", tool_calls=[ToolCall(name="search_jobs", args={"query": "go"}, output_preview="2 postings")])
    prompt = build_prompt("find go jobs", "Be grounded.", trace)
    for part in ("find go jobs", "Be grounded.", "search_jobs", "2 postings", "Two jobs found."):
        assert part in prompt


def test_prompt_keeps_long_evidence():
    long = "x" * 5000 + "NEEDLE"
    trace = Trace(output="a", tool_calls=[ToolCall(name="search_jobs", output_preview=long)])
    assert "NEEDLE" in build_prompt("q", "r", trace)


def _suite(**case):
    return Suite(suite="s", version=1, target={"type": "fake"}, rubric="Answer well.", cases=[Case(**case)])


def test_score_case_combines_deterministic_and_judge():
    suite = _suite(id="c", input="q", expect={"output": [{"contains": "jobs"}], "judge": {"min_score": 4}})
    judge = Judge(FakeClient('{"score": 3, "reasoning": "partial"}'))
    res = score_case(suite.cases[0], Trace(output="Two jobs"), suite, judge, "q")
    assert res.task_success is True
    assert res.passed is False  # judge below threshold
    assert res.judge.score == 3 and res.judge.usage.total == 15


def test_negative_control_passes_when_judge_says_bad():
    suite = _suite(id="c", input="q", expect={"judge": {"max_score": 2}})
    res = score_case(suite.cases[0], Trace(output="off-topic"), suite, Judge(FakeClient('{"score": 1, "reasoning": "x"}')), "q")
    assert res.passed and res.judge_control


def test_judge_skip():
    suite = _suite(id="c", input="q", expect={"judge": {"skip": True}})
    client = FakeClient('{"score": 5, "reasoning": "x"}')
    assert score_case(suite.cases[0], Trace(output="refused"), suite, Judge(client), "q").judge is None


def test_target_error_fails_case_and_skips_judge():
    suite = _suite(id="c", input="q")
    client = FakeClient('{"score": 5, "reasoning": "x"}')
    res = score_case(suite.cases[0], Trace(error="boom"), suite, Judge(client), "q")
    assert not res.passed and res.judge is None and client.seen is None


def test_make_client_specs():
    assert make_client("ollama:gemma4:12b").model == "gemma4:12b"
    with pytest.raises(ValueError, match="provider:model"):
        make_client("nope")


def test_repeats_merge_and_flaky_summary():
    from agent_evals.metrics import summarize
    from agent_evals.runner import merge_attempts

    suite = _suite(id="c", input="q", expect={"output": [{"contains": "jobs"}]})
    ok = score_case(suite.cases[0], Trace(output="jobs", latency_ms=100, usage=Usage(input_tokens=10)), suite, None, "q")
    bad = score_case(suite.cases[0], Trace(output="nothing", latency_ms=300, usage=Usage(input_tokens=30)), suite, None, "q")
    merged = merge_attempts([ok, bad, ok])
    assert not merged.passed and merged.flaky and merged.attempts_passed == 2
    assert merged.attempts[1].failed_checks
    s = summarize([merged])
    assert (s.repeats, s.attempt_pass_rate, s.flaky_cases, s.tokens_mean) == (3, 0.6667, ["c"], 16.7)
    assert s.latency_p50_ms == 100 and merge_attempts([ok]) is ok
