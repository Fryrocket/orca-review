"""Session scheduler for personal automation.

Lightweight, file-backed job scheduler (no extra deps).
NTP is required at arm AND before each fire (A14).
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

    def __init__(self, store_path: str | Path = "runs/scheduler/jobs.json"):
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, Job] = {}
        self._handler: Optional[Callable[[Job], Any]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.load()

    def set_handler(self, fn: Callable[[Job], Any]) -> None:
        self._handler = fn

    def load(self) -> None:
        if not self.store_path.exists():
            return
        data = json.loads(self.store_path.read_text())
        with self._lock:
            self._jobs = {j["id"]: Job(**j) for j in data.get("jobs", [])}

    def save(self) -> None:
        with self._lock:
            payload = {"jobs": [asdict(j) for j in self._jobs.values()]}
        self.store_path.write_text(json.dumps(payload, indent=2))

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

    def _due(self) -> List[Job]:
        now = _now()
        due = []
        with self._lock:
            for j in self._jobs.values():
                if not j.enabled or not j.next_run:
                    continue
                try:
                    nxt = datetime.fromisoformat(j.next_run)
                except Exception:
                    continue
                if nxt <= now:
                    due.append(j)
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
        due = self._due()
        for j in due:
            self._fire(j)
        return len(due)

    def start(self, poll_sec: float = 1.0) -> None:
        require_ntp_or_refuse(stage="arm")
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

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
