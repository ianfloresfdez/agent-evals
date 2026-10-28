"""Target for jack, a ticket → code → tests → risk → approval pipeline built on the Claude Agent SDK.

The harness starts jack's API unchanged, in its own data dir and port, and drives it over HTTP:
for each case it creates a throwaway git repo from a fixture, registers it as a project with the case's
policy, starts a run from a manual ticket and waits for a terminal state.

By default jack runs with JACK_AGENT_MODE=mock: the agents are simulated, but git, the test suite,
the risk scorer and the approval policy are real. That makes this suite a free, deterministic check of the
orchestration. Live mode works too (`agent_mode: live`), but costs tokens.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from ..schema import Case, ToolCall, Trace, Usage
from .base import Target, git_sha

TERMINAL = {"completed", "failed", "waiting_approval", "rejected", "cancelled"}
GIT_ENV = {"GIT_AUTHOR_NAME": "agent-evals", "GIT_AUTHOR_EMAIL": "evals@localhost",
           "GIT_COMMITTER_NAME": "agent-evals", "GIT_COMMITTER_EMAIL": "evals@localhost"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **GIT_ENV})


class JackPipelineTarget(Target):
    type = "jack-pipeline"

    def setup(self) -> None:
        self.repo = self.resolve(os.environ.get("JACK_PATH") or self.config.get("path", "../../jack"))
        if not (self.repo / "apps" / "api" / "src" / "index.ts").exists():
            raise RuntimeError(f"jack not found at {self.repo}. Set JACK_PATH or target.path.")
        self.mode = self.config.get("agent_mode", "mock")
        self.fixtures = self.resolve(self.config.get("fixtures", "fixtures"))
        self.timeout_s = float(self.config.get("timeout_s", 180))
        self.tmp = Path(tempfile.mkdtemp(prefix="agent-evals-jack-"))
        port = _free_port()
        self.base = f"http://127.0.0.1:{port}"
        env = {k: v for k, v in os.environ.items() if not k.startswith("JACK_")}
        # Explicit env wins over jack's .env (dotenv never overrides), so a live .env cannot leak in.
        env.update({"JACK_AGENT_MODE": self.mode, "JACK_PORT": str(port), "JACK_HOST": "127.0.0.1",
                    "JACK_DATA_DIR": str(self.tmp / "data"), "JIRA_BASE_URL": "", **GIT_ENV})
        self.log = open(self.tmp / "jack.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(["node", "--import", "tsx", "src/index.ts"], cwd=self.repo / "apps" / "api",
                                     env=env, stdout=self.log, stderr=subprocess.STDOUT, shell=False)
        self.http = httpx.Client(base_url=self.base, timeout=30)
        deadline = time.time() + 60
        while True:
            try:
                self.health = self.http.get("/api/health").json()
                break
            except httpx.HTTPError:
                if self.proc.poll() is not None or time.time() > deadline:
                    self.teardown()
                    raise RuntimeError(f"jack API did not start; see {self.tmp / 'jack.log'}")
                time.sleep(0.5)
        if self.health.get("agentMode") != self.mode:
            self.teardown()
            raise RuntimeError(f"jack reports agentMode={self.health.get('agentMode')}, expected {self.mode}. Refusing to run.")

    def teardown(self) -> None:
        if getattr(self, "proc", None) and self.proc.poll() is None:
            if os.name == "nt":  # node spawns children; kill the whole tree
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                self.proc.terminate()
            self.proc.wait(timeout=15)
        if getattr(self, "log", None):
            self.log.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def describe(self) -> dict[str, Any]:
        dirty = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
        return {"type": self.type, "repo": self.repo.name, "repo_sha": git_sha(self.repo), "repo_dirty": bool(dirty),
                "agent_mode": self.health.get("agentMode"), "model": f"jack:{self.health.get('model')}" if self.mode == "live" else None}

    def judge_input(self, case: Case) -> str:
        t = case.input["ticket"]
        return f"Ticket: {t['title']}\n\n{t.get('description', '')}"

    # ── one case ──────────────────────────────────────────────────────────────

    def _make_repo(self, case: Case) -> Path:
        src = self.fixtures / case.input["fixture"]
        dest = self.tmp / "repos" / case.id
        shutil.copytree(src, dest)
        _git(dest, "init", "-q", "-b", "main")
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "-m", "fixture")
        for rel, content in (case.input.get("uncommitted") or {}).items():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / rel).write_text(content, encoding="utf-8")
        return dest

    def run(self, case: Case) -> Trace:
        t0 = time.perf_counter()
        repo = self._make_repo(case)
        policy = {"qa": {"enabled": False}, "ship": {"commit": True, "push": False, "createPr": False, "provider": "none"},
                  **case.input.get("project", {})}
        project = self.http.post("/api/projects", json={"name": case.id, "path": str(repo), "baseBranch": "main", **policy}).json()
        try:
            r = self.http.post("/api/runs", json={"projectId": project["id"], "manual": case.input["ticket"]})
            if r.status_code >= 400:
                msg = r.json().get("error") or r.json().get("message") or r.text
                return Trace(output=f"API refused the run: {msg}", latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                             data={"api_status": r.status_code, "api_error": msg, "status": "refused"})
            run_id = r.json()["id"]
            deadline = time.time() + self.timeout_s
            while True:
                run = self.http.get(f"/api/runs/{run_id}").json()
                if run["status"] in TERMINAL:
                    break
                if time.time() > deadline:
                    self.http.post(f"/api/runs/{run_id}/cancel")
                    return Trace(error=f"timeout after {self.timeout_s:.0f}s in status {run['status']}",
                                 latency_ms=round((time.perf_counter() - t0) * 1000, 1))
                time.sleep(0.4)
            latency = (time.perf_counter() - t0) * 1000
            return self._trace(run, latency)
        finally:
            self.http.delete(f"/api/projects/{project['id']}")

    def _trace(self, run: dict, latency_ms: float) -> Trace:
        stages = {s["id"]: s["status"] for s in run["stages"]}
        risk = run.get("risk") or {}
        # jack logs its own commands (test runs, app boot, Playwright, git delivery) at the same level as agent
        # tool calls. Only agent calls count here.
        harness = {f"$ {c['command']}" for c in (run.get("tests") or {}).get("checks", [])}
        tools = []
        for log in run.get("logs", []):
            if log["level"] != "tool":
                continue
            msg = log["message"].strip()
            if msg in harness or log["stage"] == "ship" or msg.endswith("(background)") or msg.startswith("▶ Playwright"):
                continue
            name, _, rest = msg.partition(" ")
            if name == "$":
                name = "Bash"
            tools.append(ToolCall(name=name, args={"target": rest, "stage": log["stage"]}))
        out = {s["id"]: s.get("output") or {} for s in run["stages"]}
        intake, plan, review = out.get("intake", {}), out.get("plan", {}), out.get("review", {})
        crit = "\n".join(f"- {c}" for c in intake.get("acceptanceCriteria", []))
        output = (
            f"Intake summary: {intake.get('summary', '')}\nAcceptance criteria:\n{crit}\n\n"
            f"Plan: {plan.get('approach', '')}\n\n"
            f"Risk: {risk.get('level')} ({risk.get('score')}/100) → {risk.get('recommendation')}. Reviewer: {review.get('summary', '')}\n"
            f"Final status: {run['status']}"
        )
        tokens = run.get("tokens") or {}
        # jack's mock mode only estimates tokens (~4 chars/token); report real usage only for live runs.
        usage = Usage(input_tokens=tokens.get("input", 0), output_tokens=tokens.get("output", 0)) if self.mode == "live" else Usage()
        return Trace(
            output=output,
            tool_calls=tools,
            usage=usage,
            cost_usd=run.get("costUsd", 0.0),
            latency_ms=round(latency_ms, 1),
            turns=sum(1 for s in run["stages"] if s.get("skill")),
            data={
                "status": run["status"],
                "stages": stages,
                "stage_ms": {s["id"]: _dur(s) for s in run["stages"] if s.get("startedAt") and s.get("endedAt")},
                "risk": {"score": risk.get("score"), "level": risk.get("level"), "recommendation": risk.get("recommendation"),
                         "factors": [f["id"] for f in risk.get("factors", [])]},
                "approval": run.get("approval"),
                "tests_passed": (run.get("tests") or {}).get("passed"),
                "diff_files": [f["path"] for f in (run.get("diff") or {}).get("files", [])],
                "branch": run.get("branch"),
                "mock_tokens_estimate": tokens if self.mode != "live" else None,
            },
        )


def _dur(stage: dict) -> float:
    from datetime import datetime

    a = datetime.fromisoformat(stage["startedAt"].replace("Z", "+00:00"))
    b = datetime.fromisoformat(stage["endedAt"].replace("Z", "+00:00"))
    return round((b - a).total_seconds() * 1000, 1)
