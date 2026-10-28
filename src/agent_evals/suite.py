"""Loads golden sets from YAML or JSON and fingerprints them so results say exactly which version ran."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from .schema import Suite


def load_suite(path: str | Path) -> Suite:
    p = Path(path)
    raw = p.read_bytes()
    data = json.loads(raw) if p.suffix == ".json" else yaml.safe_load(raw)
    suite = Suite.model_validate(data)
    ids = [c.id for c in suite.cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"{p}: duplicate case ids: {', '.join(sorted(dupes))}")
    suite.path = str(p)
    suite.sha256 = hashlib.sha256(raw).hexdigest()
    return suite


def select_cases(suite: Suite, ids: list[str] | None = None, tags: list[str] | None = None) -> Suite:
    cases = suite.cases
    if ids:
        missing = set(ids) - {c.id for c in cases}
        if missing:
            raise ValueError(f"Unknown case ids: {', '.join(sorted(missing))}")
        cases = [c for c in cases if c.id in ids]
    if tags:
        cases = [c for c in cases if set(tags) & set(c.tags)]
    return suite.model_copy(update={"cases": cases})
