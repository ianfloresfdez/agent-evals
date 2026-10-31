"""Target for codegraph's code search (github.com/ianfloresfdez/codegraph).

codegraph indexes a repository (tree-sitter graph + local embeddings) and answers "where is X"
with a ranked list of symbols. Agents downstream (jack's analysis stage, Claude Code through MCP)
only see what this search returns, so its quality is measured on its own: for each question the
case names the file(s) that hold the answer, and the trace records where the first one ranks.

The target talks to codegraph's HTTP API (python ui.py, port 8790 by default), reindexes the repo
once at setup (incremental) and then only searches. No LLM generation is involved; the query
embedding runs on CPU.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from ..schema import Case, Trace
from .base import Target, git_sha


class CodegraphSearchTarget(Target):
    type = "codegraph-search"

    def setup(self) -> None:
        self.url = (os.environ.get("CODEGRAPH_URL") or self.config.get("url", "http://127.0.0.1:8790")).rstrip("/")
        self.repo = self.resolve(os.environ.get("CODEGRAPH_EVAL_REPO") or self.config["repo"])
        if not self.repo.is_dir():
            raise RuntimeError(f"Repository to search not found at {self.repo}. Set CODEGRAPH_EVAL_REPO or target.repo.")
        self.k = int(self.config.get("k", 5))
        self.http = httpx.Client(base_url=self.url, timeout=60)
        try:
            job = self.http.post("/api/index", json={"repo": str(self.repo)}).json()["job"]
        except (httpx.HTTPError, KeyError) as e:
            raise RuntimeError(f"codegraph is not reachable at {self.url} (start it with python ui.py): {e}") from e
        started = time.time()
        deadline = started + float(self.config.get("index_timeout_s", 900))
        while True:
            state = self.http.get(f"/api/jobs/{job}").json()
            if state["phase"] == "done":
                self.index_stats = state["stats"]
                self.index_s = round(time.time() - started, 1)
                break
            if state["phase"] == "error" or time.time() > deadline:
                raise RuntimeError(f"codegraph could not index {self.repo}: {state.get('error') or 'timeout'}")
            time.sleep(1)

    def teardown(self) -> None:
        if getattr(self, "http", None):
            self.http.close()

    def describe(self) -> dict[str, Any]:
        stats = getattr(self, "index_stats", {}) or {}
        try:  # which embedding model answered, so runs of different models can be told apart
            embed_model = self.http.get("/api/health").json().get("embed")
        except (httpx.HTTPError, ValueError, AttributeError):
            embed_model = None
        return {"type": self.type, "repo": self.repo.name, "repo_sha": git_sha(self.repo), "k": self.k,
                "symbols": stats.get("symbols"), "files": stats.get("files"), "embed_model": embed_model,
                "index_s": getattr(self, "index_s", None)}

    def judge_input(self, case: Case) -> str:
        return case.input["query"]

    def run(self, case: Case) -> Trace:
        query = case.input["query"]
        expected = [f.replace("\\", "/") for f in case.input["expected_files"]]
        t0 = time.perf_counter()
        r = self.http.get("/api/search", params={"repo": str(self.repo), "q": query, "k": self.k})
        latency = round((time.perf_counter() - t0) * 1000, 1)
        if r.status_code >= 400:
            return Trace(error=f"codegraph /api/search → {r.status_code}: {r.text[:200]}", latency_ms=latency)
        files: list[str] = []
        for hit in r.json():  # symbols in rank order; a file counts at its best-ranked symbol
            if hit["file"] not in files:
                files.append(hit["file"])
        rank = next((i + 1 for i, f in enumerate(files) if f in expected), None)
        return Trace(
            output="\n".join(f"{i + 1}. {f}" + ("  ← expected" if f in expected else "") for i, f in enumerate(files[:10])),
            latency_ms=latency,
            data={
                "rank": rank,
                "hit_at_1": rank == 1,
                "hit_at_3": rank is not None and rank <= 3,
                "hit_at_k": rank is not None and rank <= self.k,
                "reciprocal_rank": round(1 / rank, 3) if rank else 0.0,
                "files": files[:10],
                "expected": expected,
            },
        )
