"""Built-in targets (agents under test)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Target


def make_target(config: dict[str, Any], base_dir: Path) -> Target:
    from .codegraph import CodegraphSearchTarget
    from .jack import JackPipelineTarget

    registry = {t.type: t for t in (CodegraphSearchTarget, JackPipelineTarget)}
    kind = config.get("type")
    if kind not in registry:
        raise ValueError(f'Unknown target type "{kind}". Available: {", ".join(sorted(registry))}')
    return registry[kind](config, base_dir)
