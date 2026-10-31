from pathlib import Path

import httpx

from agent_evals.schema import Case
from agent_evals.targets import make_target


def make(tmp_path: Path, hits: list[dict]):
    t = make_target({"type": "codegraph-search", "repo": str(tmp_path), "k": 3}, tmp_path)
    t.repo, t.k = tmp_path, 3

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/search" and request.url.params["k"] == "3"
        return httpx.Response(200, json=hits)

    t.http = httpx.Client(base_url="http://cg", transport=httpx.MockTransport(handler))
    return t


def case(expected: list[str]) -> Case:
    return Case(id="c", input={"query": "where is X", "expected_files": expected})


def test_rank_counts_files_not_symbols(tmp_path):
    hits = [{"file": "a.ts"}, {"file": "a.ts"}, {"file": "b.ts"}, {"file": "c.ts"}]
    tr = make(tmp_path, hits).run(case(["c.ts"]))
    assert tr.data["files"] == ["a.ts", "b.ts", "c.ts"]
    assert tr.data["rank"] == 3 and tr.data["hit_at_k"] and not tr.data["hit_at_1"]
    assert tr.data["reciprocal_rank"] == 0.333
    assert "c.ts  ← expected" in tr.output


def test_miss_and_windows_paths(tmp_path):
    tr = make(tmp_path, [{"file": "a.ts"}, {"file": "b.ts"}, {"file": "d.ts"}, {"file": "z.ts"}]).run(case([r"src\z.ts"]))
    assert tr.data["rank"] is None and not tr.data["hit_at_k"] and tr.data["reciprocal_rank"] == 0.0
