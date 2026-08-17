"""Token price tables — unknown models refuse (fail closed)."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Dict, Tuple

from .errors import PriceTableStaleError, UnknownModelError

# Priced IDs only — no floating aliases
PRICE_TABLE_AS_OF = "2026-08-16"
DEFAULT_MAX_AGE_DAYS = 90
PRICE_TABLE: Dict[str, Tuple[float, float]] = {
    "echo": (0.0, 0.0),
    "grok-2-1212": (2.0, 10.0),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-haiku": (0.25, 1.25),
}

DEFAULT_MODEL = "grok-2-1212"


def _max_age_days() -> int:
    raw = os.environ.get("ORCA_PRICE_TABLE_MAX_AGE_DAYS")
    if not raw:
        return DEFAULT_MAX_AGE_DAYS
    try:
        return int(raw)
    except ValueError:
        raise PriceTableStaleError(
            f"ORCA_PRICE_TABLE_MAX_AGE_DAYS={raw!r} is not an integer"
        ) from None


def check_price_table_fresh() -> None:
    """Refuse to bill against a stale table. A stale table undercounts silently,
    and undercounting is what defeats the ceilings."""
    try:
        as_of = date.fromisoformat(PRICE_TABLE_AS_OF)
    except ValueError as e:
        raise PriceTableStaleError(f"PRICE_TABLE_AS_OF unparseable: {e}") from e
    today = datetime.now(timezone.utc).date()
    age = (today - as_of).days
    limit = _max_age_days()
    if age > limit:
        raise PriceTableStaleError(
            f"PRICE_TABLE is {age} days old (as of {PRICE_TABLE_AS_OF}, limit {limit}). "
            "Refresh prices or raise ORCA_PRICE_TABLE_MAX_AGE_DAYS deliberately."
        )
    if age < 0:
        raise PriceTableStaleError(
            f"PRICE_TABLE_AS_OF {PRICE_TABLE_AS_OF} is in the future vs {today} — check the clock."
        )


def normalize_model(model: str) -> str:
    return str(model).strip().lower()


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    check_price_table_fresh()
    key = normalize_model(model)
    if key not in PRICE_TABLE:
        raise UnknownModelError(
            f"Unknown model {model!r} — not in PRICE_TABLE (as of {PRICE_TABLE_AS_OF}). "
            f"Pin a priced ID (default {DEFAULT_MODEL}). Refusing silent $0."
        )
    inp, out = PRICE_TABLE[key]
    return (input_tokens * inp + output_tokens * out) / 1_000_000.0
