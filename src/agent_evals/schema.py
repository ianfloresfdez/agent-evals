"""Data model shared by every part of the harness: golden sets, traces and results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Golden set ────────────────────────────────────────────────────────────────


class ToolExpectation(BaseModel):
    """A tool call the agent must make. `args` maps argument names to matchers (see metrics.match)."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolsExpect(BaseModel):
    required: list[ToolExpectation] = Field(default_factory=list)
    # Tools the agent may call without being penalised in precision (required tools are always allowed).
    allowed: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    ordered: bool = False
    max_calls: int | None = None


class Budgets(BaseModel):
    latency_ms: float | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


class JudgeExpect(BaseModel):
    # Scores are 1-5. A negative control sets max_score to check the judge can say "bad".
    min_score: float | None = None
    max_score: float | None = None
    # Nothing for the judge to grade (e.g. the target refused the input on purpose).
    skip: bool = False


class Expect(BaseModel):
    # Matchers on the agent's final text, e.g. {"contains_any": ["Python", "LLM"]}
    output: list[dict[str, Any]] = Field(default_factory=list)
    # Matchers on structured trace data addressed by dotted path, e.g. {"risk.level": {"equals": "low"}}
    fields: dict[str, Any] = Field(default_factory=dict)
    tools: ToolsExpect | None = None
    judge: JudgeExpect | None = None


class Case(BaseModel):
    id: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    input: Any
    expect: Expect = Field(default_factory=Expect)
    budgets: Budgets | None = None
    rubric: str | None = None


class RegressionRules(BaseModel):
    """How much worse a run may be than its baseline before the gate fails."""

    max_pass_rate_drop: float = 0.0
    max_judge_mean_drop: float = 0.5
    max_latency_p50_increase_pct: float = 50.0
    max_tokens_mean_increase_pct: float = 25.0
    max_cost_increase_pct: float = 25.0
    # A case that passed in the baseline and fails now always fails the gate unless this is false.
    fail_on_case_regression: bool = True


class Suite(BaseModel):
    suite: str
    version: int
    description: str = ""
    target: dict[str, Any]
    rubric: str | None = None
    budgets: Budgets = Field(default_factory=Budgets)
    regression: RegressionRules = Field(default_factory=RegressionRules)
    cases: list[Case]
    # Filled by the loader
    path: str = ""
    sha256: str = ""


# ── Execution ─────────────────────────────────────────────────────────────────


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    output_preview: str = ""


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


class Trace(BaseModel):
    """What a target returns for one case: the answer plus everything we need to score it."""

    output: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float | None = None
    latency_ms: float = 0.0
    turns: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Check(BaseModel):
    name: str
    passed: bool
    detail: str = ""
    kind: str = "task"  # task | tools | budget | judge


class JudgeVerdict(BaseModel):
    score: float | None = None
    reasoning: str = ""
    model: str = ""
    usage: Usage = Field(default_factory=Usage)
    latency_ms: float = 0.0
    error: str | None = None


class CaseResult(BaseModel):
    id: str
    tags: list[str] = Field(default_factory=list)
    passed: bool
    task_success: bool
    checks: list[Check]
    tool_recall: float | None = None
    tool_precision: float | None = None
    judge: JudgeVerdict | None = None
    # Negative controls (expect.judge.max_score) check the judge itself and stay out of judge_mean.
    judge_control: bool = False
    trace: Trace


class Summary(BaseModel):
    cases: int
    passed: int
    pass_rate: float
    task_success_rate: float
    tool_recall_mean: float | None = None
    tool_precision_mean: float | None = None
    judge_mean: float | None = None
    latency_p50_ms: float
    latency_p95_ms: float
    tokens_total: int
    tokens_mean: float
    cost_usd_total: float
    judge_tokens_total: int = 0
    errors: int = 0


class RunResult(BaseModel):
    run_id: str
    suite: str
    suite_version: int
    suite_sha256: str
    target: dict[str, Any]
    judge: str | None
    started_at: str
    duration_s: float
    environment: dict[str, Any] = Field(default_factory=dict)
    summary: Summary
    cases: list[CaseResult]
