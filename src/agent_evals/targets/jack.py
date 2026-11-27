"""Target for jack, a ticket → code → tests → risk → approval pipeline built on the Claude Agent SDK.

The harness starts jack's API unchanged, in its own data dir and port, and drives it over HTTP:
for each case it creates a throwaway git repo from a fixture, registers it as a project with the case's
policy, starts a run from a manual ticket and waits for a terminal state.

By default jack runs with JACK_AGENT_MODE=mock: the agents are simulated, but git, the test suite,
the risk scorer and the approval policy are real. That makes this suite a free, deterministic check of the
orchestration. Live mode works too (`agent_mode: live`), but costs tokens.

`env` in the target config is passed to jack explicitly, so a live suite says which provider and which code
map it uses instead of inheriting them from jack's .env. AGENT_EVALS_JACK_CODEGRAPH_URL overrides
JACK_CODEGRAPH_URL for one run, to compare the same suite with and without codegraph's context.
"""

from __future__ import annotations

import os
import re
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


def _inside(root: Path, rel: str) -> Path:
    """root/rel, refusing paths from the golden set that would escape root ("../", absolute paths)."""
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"{rel!r} points outside {root}")
    return path


def remove_tree(path: Path) -> None:
    """rmtree that also removes git's read-only object files on Windows (ignore_errors left them behind)."""
    def unlock(fn, p, _exc):
        os.chmod(p, 0o700)
        fn(p)

    if path.exists():
        try:
            shutil.rmtree(path, onexc=unlock)
        except OSError:
            shutil.rmtree(path, ignore_errors=True)  # a file still held open: leave the rest, never fail the run


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
                    "JACK_DATA_DIR": str(self.tmp / "data"), "JIRA_BASE_URL": "",
                    # off unless the suite asks for it: a local .env must not change what is measured
                    "JACK_CODEGRAPH_URL": "", **GIT_ENV})
        env.update({k: str(v) for k, v in (self.config.get("env") or {}).items()})
        if "AGENT_EVALS_JACK_CODEGRAPH_URL" in os.environ:
            env["JACK_CODEGRAPH_URL"] = os.environ["AGENT_EVALS_JACK_CODEGRAPH_URL"]
        # Same suite, another provider or model (a SmartGate alias; the JWT comes from the environment or jack's .env)
        if os.environ.get("AGENT_EVALS_JACK_LLM_PROVIDER"):
            env["JACK_LLM_PROVIDER"] = os.environ["AGENT_EVALS_JACK_LLM_PROVIDER"]
        if os.environ.get("AGENT_EVALS_JACK_MODEL"):
            env["JACK_MODEL"] = os.environ["AGENT_EVALS_JACK_MODEL"]
        self.codegraph = env["JACK_CODEGRAPH_URL"] or None
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
        remove_tree(self.tmp)

    def describe(self) -> dict[str, Any]:
        dirty = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
        llm = self.health.get("llm") or {}
        model = f"jack:{self.health.get('model')}" if self.mode == "live" else None
        return {"type": self.type, "repo": self.repo.name, "repo_sha": git_sha(self.repo), "repo_dirty": bool(dirty),
                "agent_mode": self.health.get("agentMode"), "llm_provider": llm.get("provider"), "model": model,
                "codegraph": getattr(self, "codegraph", None)}

    def judge_input(self, case: Case) -> str:
        t = case.input["ticket"]
        return f"Ticket: {t['title']}\n\n{t.get('description', '')}"

    # ── one case ──────────────────────────────────────────────────────────────

    def _make_repo(self, case: Case) -> Path:
        src = _inside(self.fixtures, case.input["fixture"])
        dest = _inside(self.tmp / "repos", case.id)
        shutil.copytree(src, dest)
        _git(dest, "init", "-q", "-b", "main")
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "-m", "fixture")
        for rel, content in (case.input.get("uncommitted") or {}).items():
            path = _inside(dest, rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
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
            trace = self._trace(run, latency)
            if case.input.get("hidden_tests"):
                trace.data["hidden"] = self._hidden_tests(repo, self.resolve(case.input["hidden_tests"]))
            return trace
        finally:
            self.http.delete(f"/api/projects/{project['id']}")

    @staticmethod
    def _hidden_tests(repo: Path, src: Path) -> dict[str, Any]:
        """The case's acceptance test, which the agents never saw, run on the code jack left in the repo."""
        dest = repo / "test" / "zz-hidden.test.js"
        dest.parent.mkdir(exist_ok=True)
        shutil.copy(src, dest)
        try:
            r = subprocess.run(["node", "--test", str(dest.relative_to(repo))], cwd=repo, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=120)
            out = r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return {"passed": False, "pass": 0, "fail": 0, "output": "timeout after 120 s"}
        finally:
            dest.unlink(missing_ok=True)
        count = lambda k: int(m.group(1)) if (m := re.search(rf"^# {k} (\d+)", out, re.M)) else 0  # noqa: E731
        ok, ko = count("pass"), count("fail")
        failures = "\n".join(re.findall(r"^not ok \d+ - (.+)$", out, re.M))
        return {"passed": r.returncode == 0 and ko == 0 and ok > 0, "pass": ok, "fail": ko,
                "output": failures or ("" if r.returncode == 0 else out[-600:])}

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
                "tests_removed": "tests-removed" in [f["id"] for f in risk.get("factors", [])],
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
