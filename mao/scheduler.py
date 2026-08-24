"""Session scheduler for personal automation.

Lightweight, file-backed job scheduler (no extra deps).
NTP is required at arm AND before each fire (A14).

R11-F41 / F42 (2026-08-23):
  - FATAL_ERRORS in _fire are no longer swallowed; job is disabled and
    the background loop is stopped.
  - max_catch_up_sec clamp prevents backlog storms after clock jumps
    or long downtime (Pi 5 has no RTC).
  - Monotonic clock-jump detector for observability only.
R11-F43-F49 (2026-08-24):
  - Clamp/rebase mutations in _due() are persisted (save after lock).
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .bus import FATAL_ERRORS
from .errors import NTPNotSyncedError
from .scheduler_ntp import require_ntp_or_refuse


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _redact(text: str) -> str:
    return re.sub(r"(sk-|xai-|Bearer )\S+", r"\1[REDACTED]", str(text))


@dataclass
class Job:
    id: str
    name: str
    interval_sec: float
    payload: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    next_run: str = ""
    last_run: str = ""
    last_status: str = ""
    runs: int = 0


class SessionScheduler:
    """Periodic jobs stored in JSON; callback receives Job."""

    def __init__(
        self,
        store_path: str | Path = "runs/scheduler/jobs.json",
        *,
        max_catch_up_sec: float = 300.0,
        clock_jump_threshold_sec: float = 90.0,
    ):
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_catch_up_sec = float(max_catch_up_sec)
        self.clock_jump_threshold_sec = float(clock_jump_threshold_sec)
        self._jobs: Dict[str, Job] = {}
        self._handler: Optional[Callable[[Job], Any]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last_wall: Optional[float] = None
        self._last_mono: Optional[float] = None
        self.last_clock_jump: Optional[str] = None
        self.load()

    def set_handler(self, fn: Callable[[Job], Any]) -> None:
        self._handler = fn

    def load(self) -> None:
        if not self.store_path.exists():
            return
        try:
            data = json.loads(self.store_path.read_text())
        except (json.JSONDecodeError, OSError):
            # Soft-load: a corrupt jobs.json must not kill the process
            return
        with self._lock:
            self._jobs = {j["id"]: Job(**j) for j in data.get("jobs", [])}

    def save(self) -> None:
        with self._lock:
            payload = {"jobs": [asdict(j) for j in self._jobs.values()]}
        # Atomic-ish write
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.store_path)

    def add(
        self,
        name: str,
        interval_sec: float,
        payload: Optional[dict] = None,
        run_immediately: bool = False,
    ) -> Job:
        jid = str(uuid.uuid4())[:8]
        now = _now()
        next_run = now if run_immediately else datetime.fromtimestamp(
            now.timestamp() + interval_sec, tz=timezone.utc
        )
        job = Job(
            id=jid,
            name=name,
            interval_sec=float(interval_sec),
            payload=payload or {},
            next_run=_iso(next_run),
        )
        with self._lock:
            self._jobs[jid] = job
        self.save()
        return job

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
        self.save()

    def list(self) -> List[Job]:
        with self._lock:
            return list(self._jobs.values())

    def enable(self, job_id: str, enabled: bool = True) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].enabled = enabled
        self.save()

    def status(self) -> dict:
        with self._lock:
            return {
                "job_count": len(self._jobs),
                "enabled": sum(1 for j in self._jobs.values() if j.enabled),
                "last_clock_jump": self.last_clock_jump,
                "max_catch_up_sec": self.max_catch_up_sec,
                "clock_jump_threshold_sec": self.clock_jump_threshold_sec,
                "running": bool(self._thread and self._thread.is_alive()),
            }

    def _check_clock_jump(self) -> None:
        """Observability only. Large wall vs monotonic divergence = clock moved."""
        wall = time.time()
        mono = time.monotonic()
        if self._last_wall is not None and self._last_mono is not None:
            wall_delta = wall - self._last_wall
            mono_delta = mono - self._last_mono
            divergence = abs(wall_delta - mono_delta)
            if divergence > self.clock_jump_threshold_sec:
                self.last_clock_jump = (
                    f"divergence={divergence:.1f}s "
                    f"wall_delta={wall_delta:.1f}s mono_delta={mono_delta:.1f}s "
                    f"at={_iso(_now())}"
                )
        self._last_wall = wall
        self._last_mono = mono

    def _due(self) -> List[Job]:
        """Return jobs that are due, applying the max-catch-up clamp (F42)."""
        now = _now()
        due: List[Job] = []
        mutated = False
        with self._lock:
            for j in self._jobs.values():
                if not j.enabled or not j.next_run:
                    continue
                try:
                    nxt = datetime.fromisoformat(j.next_run)
                except Exception:
                    # Corrupt next_run → re-base and record anomaly
                    j.next_run = _iso(now)
                    j.last_status = "rebased_corrupt_next_run"
                    mutated = True
                    continue
                overdue = (now - nxt).total_seconds()
                if overdue < 0:
                    continue
                if overdue > self.max_catch_up_sec:
                    # Clamp: re-anchor without firing the handler
                    j.next_run = _iso(
                        datetime.fromtimestamp(
                            now.timestamp() + j.interval_sec, tz=timezone.utc
                        )
                    )
                    j.last_status = (
                        f"clock_jump_reanchored: was {overdue:.0f}s overdue"
                    )
                    mutated = True
                    continue
                due.append(j)
        if mutated:
            # R11-F43-F49: persist clamp/rebase; _fire() never saves these jobs.
            self.save()
        return due

    def _fire(self, job: Job) -> None:
        try:
            require_ntp_or_refuse(stage="fire")
        except NTPNotSyncedError:
            status = "refused_ntp"
        else:
            status = "ok"
            try:
                if self._handler:
                    self._handler(job)
            except FATAL_ERRORS as e:
                # R11-F41: do not swallow privilege/cost/config errors
                status = f"FATAL: {_redact(e)}"
                with self._lock:
                    job.enabled = False
                    job.last_run = _iso(_now())
                    job.last_status = status
                    job.runs += 1
                self.save()
                self._stop.set()  # stop the background loop
                raise
            except Exception as e:
                status = f"degraded_offline: {_redact(e)}"

        now = _now()
        with self._lock:
            job.last_run = _iso(now)
            job.last_status = status
            job.runs += 1
            job.next_run = _iso(
                datetime.fromtimestamp(now.timestamp() + job.interval_sec, tz=timezone.utc)
            )
        self.save()

    def tick(self) -> int:
        """Run all due jobs once. Returns count fired."""
        self._check_clock_jump()
        due = self._due()
        for j in due:
            self._fire(j)
        return len(due)

    def start(self, poll_sec: float = 1.0) -> None:
        require_ntp_or_refuse(stage="arm")
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._last_wall = time.time()
        self._last_mono = time.monotonic()

        def loop():
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(poll_sec)

        self._thread = threading.Thread(target=loop, name="orca-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
