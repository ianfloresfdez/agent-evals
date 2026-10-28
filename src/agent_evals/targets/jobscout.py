"""Targets for jobscout-mcp, a TypeScript MCP server that searches job boards.

- `jobscout-tools`: calls the MCP tools directly with fixed arguments. No LLM, fully deterministic with a cassette;
  this is the suite that runs in CI.
- `jobscout-agent`: a tool-calling LLM (Ollama by default) gets the MCP tools and a user request. We score which
  tools it calls and with what arguments, the final answer, tokens and latency.

The server runs unchanged: `node --import fetch-replay.mjs dist/index.js` records its HTTP traffic into a cassette
on the first run and replays it afterwards, with the clock frozen at recording time.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..llm import make_client
from ..pricing import cost_usd
from ..schema import Case, ToolCall, Trace, Usage
from .base import Target, git_sha

REPLAY = Path(__file__).resolve().parent.parent / "node" / "fetch-replay.mjs"
ID_RE = re.compile(r"\[([a-z]+:[^\]\s]+)\]")
# Keys that would leak into cassettes or enable paid sources: never forwarded to the server.
SCRUBBED_ENV = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JOBSCOUT_COMPANIES")


def _is_error(result: Any) -> bool:
    # mcp 1.x exposes isError, 2.x is_error
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def _root_cause(e: BaseException) -> BaseException:
    while isinstance(e, BaseExceptionGroup) and len(e.exceptions) == 1:
        e = e.exceptions[0]
    return e


def _text(result: Any) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content if getattr(c, "type", "") == "text")


class _JobscoutBase(Target):
    def setup(self) -> None:
        self.repo = self.resolve(os.environ.get("JOBSCOUT_PATH") or self.config.get("path", "../jobscout-mcp"))
        self.entry = self.repo / "dist" / "index.js"
        if not self.entry.exists():
            raise RuntimeError(f"{self.entry} not found. Run `npm install && npm run build` in {self.repo} or set JOBSCOUT_PATH.")
        cassette = self.config.get("cassette")
        self.cassette = self.resolve(cassette) if cassette else None
        self.cassette_mode = os.environ.get("AGENT_EVALS_CASSETTE_MODE") or self.config.get("cassette_mode", "replay")

    def server_params(self) -> StdioServerParameters:
        env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV}
        args = [str(self.entry)]
        if self.cassette:
            env["AGENT_EVALS_CASSETTE"] = str(self.cassette)
            env["AGENT_EVALS_CASSETTE_MODE"] = self.cassette_mode
            args = ["--import", REPLAY.as_uri(), *args]
        return StdioServerParameters(command="node", args=args, env=env, cwd=str(self.repo))

    @asynccontextmanager
    async def session(self):
        # A fresh server per case: no search cache or get_job state leaks between cases.
        with open(os.devnull, "w") as devnull:
            async with stdio_client(self.server_params(), errlog=devnull) as (read, write):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    yield s

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "repo": self.repo.name,
            "repo_sha": git_sha(self.repo),
            "cassette": self.cassette.name if self.cassette else None,
            "cassette_mode": self.cassette_mode if self.cassette else "live",
        }

    def run(self, case: Case) -> Trace:
        t0 = time.perf_counter()
        try:
            trace = asyncio.run(self._run(case))
        except Exception as e:
            e = _root_cause(e)
            trace = Trace(error=f"{type(e).__name__}: {e}")
        trace.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return trace

    async def _run(self, case: Case) -> Trace:
        raise NotImplementedError


class JobscoutToolsTarget(_JobscoutBase):
    """input: {calls: [{tool, args}]}. "{{first_id}}" in an argument is replaced by the first posting id seen so far."""

    type = "jobscout-tools"

    async def _run(self, case: Case) -> Trace:
        calls: list[ToolCall] = []
        outputs: list[str] = []
        first_id = None
        async with self.session() as s:
            for step in case.input["calls"]:
                args = json.loads(json.dumps(step.get("args", {})).replace("{{first_id}}", first_id or ""))
                try:
                    res = await s.call_tool(step["tool"], args)
                    text, ok = _text(res), not _is_error(res)
                except Exception as e:  # protocol-level rejection, e.g. schema validation (-32602)
                    text, ok = f"Tool error: {_root_cause(e)}", False
                outputs.append(text)
                calls.append(ToolCall(name=step["tool"], args=args, ok=ok, output_preview=text[:2000]))
                if first_id is None and (m := ID_RE.search(text)):
                    first_id = m.group(1)
        return Trace(
            output="\n\n".join(outputs),
            tool_calls=calls,
            turns=len(calls),
            data={"outputs": outputs, "errors": [not c.ok for c in calls], "first_id": first_id},
        )


DEFAULT_SYSTEM = (
    "You are a job-search assistant with access to jobscout tools that search live job boards. "
    "Always use the tools to answer; never invent postings, companies or numbers. "
    "Answer in the user's language, concisely, citing posting ids like [source:id] when you mention a job."
)


class JobscoutAgentTarget(_JobscoutBase):
    """input: the user's request as a string. The model is any provider:model spec (default ollama:gemma4:12b)."""

    type = "jobscout-agent"

    def setup(self) -> None:
        super().setup()
        self.model_spec = os.environ.get("AGENT_EVALS_AGENT_MODEL") or self.config.get("model", "ollama:gemma4:12b")
        opts = {k: self.config[k] for k in ("think", "num_ctx", "seed") if k in self.config} if self.model_spec.startswith("ollama:") else {}
        self.llm = make_client(self.model_spec, **opts)
        self.max_turns = int(self.config.get("max_turns", 6))
        # 0 by default for reproducible runs; raise it (and set seed: null) to measure sampling variance with --repeat
        self.temperature = float(self.config.get("temperature", 0.0))
        self.system = self.config.get("system_prompt", DEFAULT_SYSTEM)
        self.tool_output_chars = int(self.config.get("tool_output_chars", 6000))

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "model": self.model_spec, "max_turns": self.max_turns, "temperature": self.temperature}

    async def _run(self, case: Case) -> Trace:
        usage = Usage()
        calls: list[ToolCall] = []
        answer = ""
        turns = 0
        async with self.session() as s:
            listed = await s.list_tools()
            tools = [
                {"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": getattr(t, "input_schema", None) or getattr(t, "inputSchema", {})}}
                for t in listed.tools
            ]
            messages: list[dict] = [{"role": "system", "content": self.system}, {"role": "user", "content": case.input}]
            for turns in range(1, self.max_turns + 1):
                # The HTTP call blocks; keep the MCP session's event loop responsive meanwhile.
                resp = await asyncio.to_thread(self.llm.chat, messages, tools, None, self.temperature)
                usage.add(resp.usage)
                messages.append(resp.message)
                if not resp.tool_calls:
                    answer = resp.content
                    break
                for tc in resp.tool_calls:
                    try:
                        res = await s.call_tool(tc.name, tc.args)
                        text, ok = _text(res), not _is_error(res)
                    except Exception as e:  # invalid arguments are reported back to the model, like a real client would
                        text, ok = f"Tool error: {e}", False
                    # The judge must see exactly what the model saw, or it flags grounded facts as invented.
                    calls.append(ToolCall(name=tc.name, args=tc.args, ok=ok, output_preview=text[: self.tool_output_chars]))
                    messages.append(self.llm.tool_result_message(tc, text[: self.tool_output_chars]))
            else:
                answer = answer or "(no final answer: max turns reached)"
        return Trace(
            output=answer,
            tool_calls=calls,
            usage=usage,
            cost_usd=cost_usd(self.model_spec, usage, self.config.get("price_per_mtok")),
            turns=turns,
            data={"tool_names": [c.name for c in calls], "tool_errors": sum(not c.ok for c in calls)},
        )
