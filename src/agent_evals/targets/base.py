from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..schema import Case, Trace


class Target:
    """An agent under test. Subclasses start whatever they need in setup() and answer one case per run()."""

    type = ""

    def __init__(self, config: dict[str, Any], base_dir: Path):
        self.config = config
        self.base_dir = base_dir

    def resolve(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.base_dir / p).resolve()

    def setup(self) -> None: ...

    def teardown(self) -> None: ...

    def run(self, case: Case) -> Trace:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"type": self.type}

    def judge_input(self, case: Case) -> str:
        return case.input if isinstance(case.input, str) else json.dumps(case.input, ensure_ascii=False, indent=2)

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, *exc):
        self.teardown()


def git_sha(path: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
