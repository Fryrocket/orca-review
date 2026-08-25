"""R11-F80 ("scheduler naive next_run kills poll thread").

_due() only guarded datetime.fromisoformat() itself. A valid ISO-8601
string with no UTC offset (e.g. "2020-01-01T00:00:00") parses, then
(now - nxt).total_seconds() raises TypeError outside the try/except.
tick() dies for every job, not just the corrupt one, and the daemon
thread in start() swallows the exception so the whole scheduler stops
silently.

Fix: reject naive datetimes inside the same try/except and rebase via
the existing rebased_corrupt_next_run path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mao.scheduler import SessionScheduler


def _scheduler(tmp_path, **kw):
    return SessionScheduler(tmp_path / "jobs.json", **kw)


def test_naive_next_run_does_not_crash_tick(tmp_path):
    """tick() must not raise; the bad job is rebased and stays enabled."""
    s = _scheduler(tmp_path)
    job = s.add("naive", interval_sec=60)
    with s._lock:
        job.next_run = "2020-01-01T00:00:00"
    s.save()
    s.tick()
    assert job.last_status == "rebased_corrupt_next_run"
    assert job.enabled is True


def test_naive_next_run_gets_rebased_not_silently_dropped(tmp_path):
    """Rebased next_run must itself be tz-aware so it will not recur."""
    s = _scheduler(tmp_path)
    job = s.add("naive", interval_sec=60)
    with s._lock:
        job.next_run = "2020-01-01T00:00:00"
    s.save()
    s.tick()
    nxt = datetime.fromisoformat(job.next_run)
    assert nxt.tzinfo is not None
    assert job.last_status == "rebased_corrupt_next_run"


def test_other_jobs_still_fire_when_one_job_has_naive_next_run(tmp_path, monkeypatch):
    """A healthy sibling still fires; the bug used to take down the whole tick."""
    import mao.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "require_ntp_or_refuse", lambda stage="fire": None)
    s = _scheduler(tmp_path)
    fired = []
    s.set_handler(lambda job: fired.append(job.id))
    bad = s.add("bad", interval_sec=60)
    good = s.add("good", interval_sec=60)
    now = datetime.now(timezone.utc)
    with s._lock:
        bad.next_run = "2020-01-01T00:00:00"
        good.next_run = (now - timedelta(seconds=5)).isoformat()
    s.save()
    count = s.tick()
    assert count == 1
    assert good.id in fired
    assert bad.id not in fired
    assert bad.last_status == "rebased_corrupt_next_run"
    assert good.last_status == "ok"
