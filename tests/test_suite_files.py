from pathlib import Path

import pytest

from agent_evals.suite import load_suite, select_cases

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = sorted((ROOT / "golden").rglob("*.v*.yaml"))


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name)
def test_golden_sets_are_valid(path):
    suite = load_suite(path)
    assert suite.cases and len(suite.sha256) == 64
    for case in suite.cases:
        assert case.expect.output or case.expect.fields or case.expect.tools, f"{case.id} checks nothing"


def test_duplicate_ids_rejected(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("suite: s\nversion: 1\ntarget: {type: x}\ncases:\n- {id: a, input: x}\n- {id: a, input: y}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_suite(p)


def test_select_by_id_and_tag(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"suite":"s","version":1,"target":{"type":"x"},"cases":[{"id":"a","input":1,"tags":["t"]},{"id":"b","input":2}]}')
    s = load_suite(p)
    assert [c.id for c in select_cases(s, tags=["t"]).cases] == ["a"]
    assert [c.id for c in select_cases(s, ids=["b"]).cases] == ["b"]
    with pytest.raises(ValueError):
        select_cases(s, ids=["zzz"])


def test_jack_fixture_paths_cannot_escape(tmp_path):
    from agent_evals.targets.jack import _inside

    assert _inside(tmp_path, "src/a.ts") == (tmp_path / "src" / "a.ts").resolve()
    for bad in ("../outside.txt", "src/../../x", str(tmp_path.parent / "abs.txt")):
        with pytest.raises(ValueError, match="outside"):
            _inside(tmp_path, bad)

