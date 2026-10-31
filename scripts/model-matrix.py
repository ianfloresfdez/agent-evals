"""Run jack's bench-shop golden set once per model and compare them.

Each model goes through llm-gateway pinned with LLM_GATEWAY_MODEL (any "provider/model" the gateway
knows, e.g. ollama/qwen3-coder-64k or ollama-reasoning/gpt-oss-64k). The table says, per model: hidden
acceptance tests passed (the real score), runs jack considered green, tests removed, and time.

    python scripts/model-matrix.py ollama-reasoning/gpt-oss-64k ollama/qwen3-coder-64k
    python scripts/model-matrix.py --case reserve-stock ollama/qwen3-coder-64k      # one case only
    python scripts/model-matrix.py smartgate                                         # SmartGate, JWT in jack/.env

The special name "smartgate" runs the same suite with JACK_LLM_PROVIDER=smartgate instead of the gateway.
Results go to results/jack-bench-shop/ like any other run, and the table to results/model-matrix.md
(appended, so several sessions build one table).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "golden" / "jack" / "bench-shop.v1.yaml"
RESULTS = ROOT / "results" / "jack-bench-shop"


def run_model(model: str, cases: list[str]) -> dict:
    env = {**os.environ, "PYTHONUTF8": "1"}
    if model == "smartgate":
        env["AGENT_EVALS_JACK_LLM_PROVIDER"] = "smartgate"
    else:
        env["AGENT_EVALS_JACK_MODEL"] = model
    before = set(RESULTS.glob("*.json")) if RESULTS.exists() else set()
    cmd = [sys.executable, "-m", "agent_evals.cli", "run", str(SUITE), "--no-judge", "--no-report"]
    for c in cases:
        cmd += ["--case", c]
    subprocess.run(cmd, cwd=ROOT, env=env, check=False)
    new = sorted(set(RESULTS.glob("*.json")) - before)
    if not new:
        return {"model": model, "error": "no result saved"}
    return summarize(model, json.loads(new[-1].read_text("utf-8")))


def summarize(model: str, run: dict) -> dict:
    cases = run["cases"]
    data = {c["id"]: (c["trace"].get("data") or {}) for c in cases}
    mins = [c["trace"]["latency_ms"] / 60000 for c in cases if c["trace"].get("latency_ms")]
    stage = lambda name: statistics.median([d["stage_ms"][name] / 1000 for d in data.values() if name in d.get("stage_ms", {})] or [0])  # noqa: E731
    return {
        "model": model if model == "smartgate" else model.split("/", 1)[-1],
        "answered_by": run["target"].get("model"),
        "hidden": f"{sum(1 for d in data.values() if (d.get('hidden') or {}).get('passed'))}/{len(cases)}",
        "jack_green": f"{sum(1 for d in data.values() if d.get('tests_passed'))}/{len(cases)}",
        "all_checks": f"{sum(1 for c in cases if c['passed'])}/{len(cases)}",
        "tests_removed": sum(1 for d in data.values() if d.get("tests_removed")),
        "errors": sum(1 for c in cases if c["trace"].get("error")),
        "min_p50": round(statistics.median(mins), 1) if mins else None,
        "min_total": round(sum(mins), 1),
        "implement_s": round(stage("implement")),
        "per_case": {cid: ("✓" if (d.get("hidden") or {}).get("passed") else "✗") for cid, d in data.items()},
        "run": run["run_id"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("models", nargs="+")
    ap.add_argument("--case", action="append", default=[], help="only these case ids (repeatable)")
    args = ap.parse_args()
    rows = []
    for m in args.models:
        print(f"\n=== {m}  {datetime.now():%H:%M}", flush=True)
        rows.append(run_model(m, args.case))
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    cols = ["model", "hidden", "jack_green", "all_checks", "tests_removed", "errors", "min_p50", "min_total", "implement_s"]
    case_ids = list(rows[0].get("per_case", {})) if rows and "per_case" in rows[0] else []
    head = "| " + " | ".join(cols + case_ids) + " |"
    lines = [head, "|" + "---|" * (len(cols) + len(case_ids))]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['model']} | {r['error']} |")
            continue
        lines.append("| " + " | ".join([str(r[c]) for c in cols] + [r["per_case"].get(c, "") for c in case_ids]) + " |")
    table = "\n".join(lines)
    out = ROOT / "results" / "model-matrix.md"
    with out.open("a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.now():%Y-%m-%d %H:%M} · {SUITE.name}\n\n{table}\n")
    print("\n" + table + f"\n\nappended to {out}")


if __name__ == "__main__":
    main()
