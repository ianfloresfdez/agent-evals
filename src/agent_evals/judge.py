"""LLM-as-judge: scores an answer 1-5 against a rubric and returns a short justification.

The judge sees the user input, the rubric and the agent's answer (plus a compact list of the tools it called),
never the expected deterministic checks, so it grades quality rather than re-doing exact-match work.
"""

from __future__ import annotations

import json
import re

from .llm import LLMClient
from .schema import JudgeVerdict, Trace

SYSTEM = """You are a strict evaluator of AI agent answers.
Score the ANSWER against the RUBRIC on this scale:
5 = fully meets every rubric point, accurate and grounded in the tool results
4 = meets the rubric with minor omissions
3 = partially meets it; a reader would need to ask follow-ups
2 = mostly misses the rubric or contains a clear error
1 = wrong, irrelevant, invented, or no answer
Judge only what is written. Do not reward length. If the answer contradicts the tool evidence, score at most 2.
Return JSON: {"reasoning": "<two or three sentences>", "score": <integer 1-5>}"""

SCHEMA = {
    "type": "object",
    "properties": {"reasoning": {"type": "string"}, "score": {"type": "integer", "minimum": 1, "maximum": 5}},
    "required": ["reasoning", "score"],
}


def build_prompt(case_input: str, rubric: str, trace: Trace, evidence_chars: int = 24000) -> str:
    tools = "\n".join(
        f"- {c.name}({json.dumps(c.args, ensure_ascii=False)[:200]}) -> {c.output_preview[:evidence_chars // max(1, len(trace.tool_calls))]}"
        for c in trace.tool_calls
    ) or "(no tool calls)"
    return (
        f"## USER INPUT\n{case_input}\n\n"
        f"## RUBRIC\n{rubric.strip()}\n\n"
        f"## TOOL CALLS AND EVIDENCE\n{tools}\n\n"
        f"## ANSWER\n{trace.output.strip() or '(empty)'}"
    )


def parse_verdict(text: str) -> tuple[float | None, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        try:
            data = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            data = {}
    score = data.get("score")
    if isinstance(score, (int, float)) and 1 <= score <= 5:
        return float(score), str(data.get("reasoning", "")).strip()
    return None, str(data.get("reasoning", text[:300])).strip()


class Judge:
    def __init__(self, client: LLMClient):
        self.client = client

    @property
    def spec(self) -> str:
        return self.client.spec

    def evaluate(self, case_input: str, rubric: str, trace: Trace) -> JudgeVerdict:
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": build_prompt(case_input, rubric, trace)}]
        try:
            resp = self.client.chat(messages, json_schema=SCHEMA, temperature=0.0)
        except Exception as e:  # network, model not found, provider error
            return JudgeVerdict(model=self.spec, error=f"{type(e).__name__}: {e}")
        score, reasoning = parse_verdict(resp.content)
        return JudgeVerdict(
            score=score, reasoning=reasoning, model=self.spec, usage=resp.usage, latency_ms=round(resp.latency_ms, 1),
            error=None if score is not None else "Judge did not return a valid score",
        )
