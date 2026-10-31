"""The bench-shop golden set is only fair if each hidden test fails on the untouched fixture and passes
with the reference solution, together with the fixture's own suite."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "golden" / "jack" / "fixtures" / "bench-shop"
CASES = sorted(p for p in (ROOT / "golden" / "jack" / "bench-shop").iterdir() if (p / "hidden.test.js").exists())

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")


def node_test(cwd: Path, *files: str) -> tuple[int, int]:
    out = subprocess.run(["node", "--test", *files], cwd=cwd, capture_output=True, text=True, encoding="utf-8").stdout
    count = lambda k: int(re.search(rf"^# {k} (\d+)", out, re.M).group(1))  # noqa: E731
    return count("pass"), count("fail")


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_hidden_test_fails_before_and_passes_with_the_reference(case, tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    shutil.copy(case / "hidden.test.js", repo / "test" / "zz-hidden.test.js")
    passed, failed = node_test(repo, "test/zz-hidden.test.js")
    assert failed > 0, "the hidden test already passes on the untouched fixture"

    shutil.copytree(case / "reference", repo, dirs_exist_ok=True)
    passed, failed = node_test(repo, "test/zz-hidden.test.js")
    assert failed == 0 and passed > 0
    passed, failed = node_test(repo)  # the fixture's own suite still passes with the reference
    assert failed == 0, f"reference breaks the existing suite ({failed} failing)"


def test_every_case_in_the_suite_has_a_hidden_test():
    from agent_evals.suite import load_suite

    suite = load_suite(ROOT / "golden" / "jack" / "bench-shop.v1.yaml")
    assert sorted(c.id for c in suite.cases) == sorted(p.name for p in CASES)


def test_target_scores_the_hidden_test_on_the_repo_and_cleans_up(tmp_path):
    from agent_evals.targets.jack import JackPipelineTarget

    case = CASES[0]
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    before = JackPipelineTarget._hidden_tests(repo, case / "hidden.test.js")
    assert not before["passed"] and before["fail"] > 0 and before["output"]
    shutil.copytree(case / "reference", repo, dirs_exist_ok=True)
    after = JackPipelineTarget._hidden_tests(repo, case / "hidden.test.js")
    assert after["passed"] and after["fail"] == 0
    assert not (repo / "test" / "zz-hidden.test.js").exists(), "the hidden test must not stay in the agent's repo"
