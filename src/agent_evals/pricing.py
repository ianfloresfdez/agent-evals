"""Token prices in USD per million tokens (input, output). Local models cost nothing per token.

Prices change: override them per suite with `target.price_per_mtok: {input: ..., output: ...}`.
"""

from __future__ import annotations

from .schema import Usage

# Deliberately empty: fill in from your provider's current price page, e.g.
# PRICES["openai:gpt-4.1-mini"] = (0.40, 1.60)
PRICES: dict[str, tuple[float, float]] = {}


def cost_usd(spec: str, usage: Usage, override: dict | None = None) -> float:
    if override:
        pin, pout = float(override.get("input", 0)), float(override.get("output", 0))
    elif spec.startswith("ollama:"):
        return 0.0
    elif spec in PRICES:
        pin, pout = PRICES[spec]
    else:
        return 0.0
    return round((usage.input_tokens * pin + usage.output_tokens * pout) / 1_000_000, 6)
