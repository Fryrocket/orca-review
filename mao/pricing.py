"""Token price tables — unknown models refuse (fail closed)."""

from __future__ import annotations

from typing import Dict, Tuple

from .errors import UnknownModelError

# Priced IDs only — no floating aliases
PRICE_TABLE_AS_OF = "2026-08-16"
PRICE_TABLE: Dict[str, Tuple[float, float]] = {
    "echo": (0.0, 0.0),
    "grok-2-1212": (2.0, 10.0),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-haiku": (0.25, 1.25),
}

DEFAULT_MODEL = "grok-2-1212"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICE_TABLE:
        raise UnknownModelError(
            f"Unknown model {model!r} — not in PRICE_TABLE (as of {PRICE_TABLE_AS_OF}). "
            f"Pin a priced ID (default {DEFAULT_MODEL}). Refusing silent $0."
        )
    inp, out = PRICE_TABLE[model]
    return (input_tokens * inp + output_tokens * out) / 1_000_000.0
