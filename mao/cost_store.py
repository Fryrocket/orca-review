"""Persisted per-day cost counter with flock; fail closed."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .errors import CostCapExceeded, CostLedgerCorrupt, OrcaConfigError

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

# Legitimate UTC rollover is +1 day; +2 tolerates a long-running process.
# Anything beyond that is a clock event, not a calendar event.
MAX_FORWARD_DAY_JUMP = 2


class DayCostStore:
    def __init__(self, path: str | Path | None = None):
        if path is None:
            root = os.environ.get("ORCA_REPO_ROOT") or os.environ.get("MAO_REPO_ROOT")
            if not root:
                # A missing env var is a configuration failure, not a corrupt
                # ledger. Using CostLedgerCorrupt here made callers reach for
                # the wrong except clause.
                raise OrcaConfigError(
                    "ORCA_REPO_ROOT required for DayCostStore default path"
                )
            path = str(Path(root) / "runs" / "cost_day.json")
        self.path = Path(path)

    def _utc_day(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def read(self) -> dict:
        if not self.path.exists():
            return {"day": self._utc_day(), "cost_usd": 0.0}
        try:
            data = json.loads(self.path.read_text())
            day = data["day"]
            cost = float(data["cost_usd"])
            return {"day": day, "cost_usd": cost}
        except Exception as e:
            return {"day": self._utc_day(), "cost_usd": 1e12, "corrupt": True, "error": str(e)}

    def add(self, amount: float, ceiling: Optional[float] = None) -> float:
        if float(amount) < 0:
            raise OrcaConfigError(
                f"DayCostStore.add amount must be >= 0 (got {amount})"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        with open(self.path, "r+") as f:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                raw = f.read()
                if not raw.strip():
                    data = {"day": self._utc_day(), "cost_usd": 0.0}
                else:
                    try:
                        parsed = json.loads(raw)
                        data = {"day": parsed["day"], "cost_usd": float(parsed["cost_usd"])}
                    except Exception as e:
                        raise CostLedgerCorrupt(f"corrupt ledger: {e}") from e
                day = self._utc_day()
                if data["day"] != day:
                    if data["day"] > day:
                        raise CostLedgerCorrupt(
                            f"clock went backward: stored day {data['day']} > now {day}"
                        )
                    stored = date.fromisoformat(data["day"])
                    now = date.fromisoformat(day)
                    if (now - stored).days > MAX_FORWARD_DAY_JUMP:
                        raise CostLedgerCorrupt(
                            f"clock jumped forward too far: stored {data['day']} now {day}"
                        )
                    data = {"day": day, "cost_usd": 0.0}
                new_total = float(data["cost_usd"]) + float(amount)
                if ceiling is not None and new_total > ceiling:
                    raise CostCapExceeded(
                        f"per-day ceiling ${ceiling} exceeded (would be ${new_total:.4f})"
                    )
                f.seek(0)
                f.truncate()
                f.write(json.dumps({"day": day, "cost_usd": new_total}))
                f.flush()
                os.fsync(f.fileno())
                return new_total
            finally:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def remaining(self, ceiling: float) -> float:
        data = self.read()
        if data.get("corrupt"):
            return 0.0
        day = self._utc_day()
        spent = float(data["cost_usd"]) if data["day"] == day else 0.0
        return max(0.0, ceiling - spent)
