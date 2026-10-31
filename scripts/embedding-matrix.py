"""Compare embedding models for codegraph's search on the same golden set.

For each model it starts its own codegraph UI server (free port, its own index folder, no jack link),
indexes the eval repo from scratch with that model, runs golden/codegraph/search.v2.yaml against it and
prints a table: recall@5 overall / English / Spanish, hit@1, MRR, indexing time and query latency.

    python scripts/embedding-matrix.py nomic-embed-text qwen3-embedding:0.6b embeddinggemma bge-m3
    CODEGRAPH_DIR=../codegraph  (default: next to this repo)

The models must be pulled in Ollama. Results go to results/codegraph-search/ like any other run, and
the table to results/embedding-matrix.md.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "golden" / "codegraph" / "search.v2.yaml"
CODEGRAPH = Path(os.environ.get("CODEGRAPH_DIR", ROOT.parent / "codegraph")).resolve()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def python_for(project: Path) -> str:
    venv = project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(venv) if venv.exists() else sys.executable


def run_model(model: str, index_root: Path) -> dict:
    port = free_port()
    env = {**os.environ, "CODEGRAPH_EMBED_MODEL": model, "CODEGRAPH_INDEX_DIR": str(index_root / model.replace(":", "_")),
           "CODEGRAPH_UI_PORT": str(port), "JACK_URL": "", "PYTHONUTF8": "1"}
    log = open(index_root / f"{model.replace(':', '_')}.log", "w", encoding="utf-8")
    server = subprocess.Popen([python_for(CODEGRAPH), "ui.py"], cwd=CODEGRAPH, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{url}/api/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        before = set((ROOT / "results" / "codegraph-search").glob("*.json"))
        subprocess.run([sys.executable, "-m", "agent_evals.cli", "run", str(SUITE), "--no-judge", "--no-report"],
                       cwd=ROOT, env={**os.environ, "CODEGRAPH_URL": url, "PYTHONUTF8": "1"}, check=False)
        new = sorted(set((ROOT / "results" / "codegraph-search").glob("*.json")) - before)
        if not new:
            return {"model": model, "error": "no result saved (see the log next to the indexes)"}
        return summarize(model, json.loads(new[-1].read_text("utf-8")))
    finally:
        server.terminate()
        server.wait(timeout=15)
        log.close()


def summarize(model: str, run: dict) -> dict:
    cases = run["cases"]

    def recall(tag: str | None) -> str:
        sel = [c for c in cases if tag is None or tag in c.get("tags", [])]
        hit = sum(1 for c in sel if (c["trace"].get("data") or {}).get("hit_at_k"))
        return f"{hit}/{len(sel)}"

    data = [c["trace"].get("data") or {} for c in cases]
    lat = sorted(c["trace"].get("latency_ms") or 0 for c in cases)
    return {
        "model": model,
        "recall@5": recall(None), "en": recall("en"), "es": recall("es"),
        "hit@1": f"{sum(1 for d in data if d.get('hit_at_1'))}/{len(cases)}",
        "mrr": round(sum(d.get("reciprocal_rank", 0) for d in data) / len(cases), 3),
        "index_s": run["target"].get("index_s"),
        "query_p50_ms": lat[len(lat) // 2] if lat else None,
        "run": run["run_id"],
    }


def main(models: list[str]) -> None:
    if not models:
        sys.exit(__doc__)
    rows = []
    with tempfile.TemporaryDirectory(prefix="embedding-matrix-") as tmp:
        for m in models:
            print(f"\n=== {m}", flush=True)
            rows.append(run_model(m, Path(tmp)))
    cols = ["model", "recall@5", "en", "es", "hit@1", "mrr", "index_s", "query_p50_ms"]
    table = "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] +
                      ["| " + " | ".join(str(r.get(c, r.get("error", ""))) for c in cols) + " |" for r in rows])
    out = ROOT / "results" / "embedding-matrix.md"
    out.write_text(f"# codegraph search by embedding model\n\n{SUITE.name}\n\n{table}\n", "utf-8")
    print("\n" + table + f"\n\nsaved {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
