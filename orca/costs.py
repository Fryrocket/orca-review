from __future__ import annotations

import sqlite3
import threading
import math

from .domain import new_id, utc_now
from .security import redact_text


class CostLedger:
    def __init__(self, db: sqlite3.Connection, hard_cap_usd: float = 0.0,
                 warning_threshold_usd: float | None = None, *, connection_lock=None) -> None:
        if (isinstance(hard_cap_usd, bool) or not isinstance(hard_cap_usd, (int, float))
                or not math.isfinite(hard_cap_usd) or hard_cap_usd < 0):
            raise ValueError("hard cap cannot be negative")
        if warning_threshold_usd is not None and (
                isinstance(warning_threshold_usd, bool)
                or not isinstance(warning_threshold_usd, (int, float))
                or not math.isfinite(warning_threshold_usd)
                or warning_threshold_usd < 0 or warning_threshold_usd > hard_cap_usd):
            raise ValueError("warning threshold must be between zero and the hard cap")
        self.db = db
        self._lock = connection_lock if connection_lock is not None else threading.RLock()
        self.hard_cap_usd = hard_cap_usd
        self.warning_threshold_usd = warning_threshold_usd
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS costs (
                id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, job_id TEXT NOT NULL,
                bot_id TEXT NOT NULL, lane TEXT NOT NULL, model TEXT NOT NULL,
                connector TEXT, tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL,
                cost_usd REAL NOT NULL CHECK(cost_usd >= 0)
            )"""
        )
        self.db.commit()

    def total(self) -> float:
        with self._lock:
            return float(self.db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM costs").fetchone()[0])

    def preflight(self, estimated_cost_usd: float) -> None:
        if (isinstance(estimated_cost_usd, bool)
                or not isinstance(estimated_cost_usd, (int, float))
                or not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0):
            raise ValueError("estimated cost cannot be negative")
        with self._lock:
            if estimated_cost_usd and (
                    self.hard_cap_usd <= 0
                    or self.total() + estimated_cost_usd > self.hard_cap_usd):
                raise PermissionError("cost exceeds approved hard cap")

    def record(self, *, job_id: str, bot_id: str, lane: str, model: str,
               tokens_in: int, tokens_out: int, cost_usd: float,
               connector: str | None = None) -> None:
        if (type(tokens_in) is not int or type(tokens_out) is not int
                or min(tokens_in, tokens_out) < 0
                or isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float))
                or not math.isfinite(cost_usd) or cost_usd < 0):
            raise ValueError("usage values cannot be negative")
        dimensions = (job_id, bot_id, lane, model) + ((connector,) if connector else ())
        if any(not isinstance(value, str) or not value.strip() or len(value) > 240
               for value in dimensions):
            raise ValueError("cost dimensions must be concise non-empty text")
        safe_job_id = redact_text(job_id)
        safe_bot_id = redact_text(bot_id)
        safe_lane = redact_text(lane)
        safe_model = redact_text(model)
        safe_connector = redact_text(connector) if connector else None
        with self._lock:
            owns_transaction = not self.db.in_transaction
            if owns_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            try:
                self.preflight(cost_usd)
                self.db.execute(
                    "INSERT INTO costs VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id("cost"), utc_now(), safe_job_id, safe_bot_id, safe_lane,
                     safe_model, safe_connector, tokens_in, tokens_out, cost_usd),
                )
                if owns_transaction:
                    self.db.commit()
            except BaseException:
                if owns_transaction:
                    self.db.rollback()
                raise

    def summary(self) -> dict:
        with self._lock:
            total = self.total()
            if self.hard_cap_usd <= 0:
                budget_status = "zero_spend"
            elif total >= self.hard_cap_usd:
                budget_status = "hard_stop"
            elif self.warning_threshold_usd is not None and total >= self.warning_threshold_usd:
                budget_status = "warning"
            else:
                budget_status = "within_budget"
            dimensions = {}
            for field in ("bot_id", "lane", "model", "connector"):
                rows = self.db.execute(
                    f"SELECT COALESCE({field}, 'none'), SUM(tokens_in), SUM(tokens_out), SUM(cost_usd) "
                    f"FROM costs GROUP BY {field} ORDER BY {field}"
                ).fetchall()
                dimensions[field] = [
                    {"key": redact_text(str(row[0])), "tokens_in": row[1],
                     "tokens_out": row[2], "cost_usd": row[3]}
                    for row in rows
                ]
            return {"total_usd": total, "hard_cap_usd": self.hard_cap_usd,
                    "warning_threshold_usd": self.warning_threshold_usd,
                    "budget_status": budget_status,
                    "paid_execution_authorized": self.hard_cap_usd > 0,
                    "remaining_usd": max(0.0, self.hard_cap_usd - total),
                    "by_dimension": dimensions}

    def retention_records(self) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT id, timestamp FROM costs ORDER BY timestamp").fetchall()
            return [{"id": row[0], "timestamp": row[1]} for row in rows]
