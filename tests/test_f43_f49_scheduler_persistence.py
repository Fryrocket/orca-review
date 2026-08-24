"""R11-F43-F49 ("scheduler behaviour").

_due()'s clock-jump clamp (F42) and corrupt-next_run rebase both mutate
Job objects in place, but neither path ever called save() — only _fire()
does, and only for jobs that actually reach `due` (clamped/rebased jobs
never do, that's the whole point of the clamp). So a clamp or rebase only
existed in memory. If the process restarted before any other job happened
to trigger a save — plausible on the exact hardware this whole feature
exists for (Pi 5, no RTC, per F41/F42's docstring) — the stale, wildly
overdue next_run reloaded from disk on the next run and got reclamped all
over again, forever, never actually making persisted progress.

_due() now saves once at the end if it mutated any job."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mao.scheduler import SessionScheduler


def _scheduler(tmp_path, **kw):
    return SessionScheduler(tmp_path / "jobs.json", **kw)


def test_clock_jump_reanchor_persists_across_reload(tmp_path):
    """The exact F43-F49 bug: this used to be lost on reload."""
    s = _scheduler(tmp_path, max_catch_up_sec=10)
    job = s.add("t", interval_sec=60)
    with s._lock:
        job.next_run = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
    s.save()

    fired = s.tick()
    assert fired == 0
    reanchored_next_run = job.next_run

    reloaded = _scheduler(tmp_path, max_catch_up_sec=10).list()[0]
    assert reloaded.next_run == reanchored_next_run
    assert reloaded.last_status == job.last_status


def test_corrupt_next_run_rebase_persists_across_reload(tmp_path):
    s = _scheduler(tmp_path)
    job = s.add("t", interval_sec=60)
    with s._lock:
        job.next_run = "not-a-valid-timestamp"
    s.save()

    s.tick()
    rebased_next_run = job.next_run
    assert job.last_status == "rebased_corrupt_next_run"

    reloaded = _scheduler(tmp_path).list()[0]
    assert reloaded.next_run == rebased_next_run
    assert reloaded.last_status == "rebased_corrupt_next_run"


def test_tick_with_nothing_due_does_not_write_unnecessarily(tmp_path):
    """No mutation happened, so _due() must not force an extra save —
    guards against overcorrecting into an unconditional save()."""
    s = _scheduler(tmp_path)
    s.add("t", interval_sec=3600)  # far in the future, nothing to clamp
    mtime_before = s.store_path.stat().st_mtime_ns
    s.tick()
    mtime_after = s.store_path.stat().st_mtime_ns
    assert mtime_before == mtime_after


def test_normal_fire_still_persists_as_before(tmp_path, monkeypatch):
    """Regression guard: a job that actually fires must still save via the
    existing _fire() path — this fix only adds a save for the clamp/rebase
    case, it must not double-save or break the normal path."""
    import mao.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "require_ntp_or_refuse", lambda stage="fire": None)
    s = _scheduler(tmp_path)
    s.set_handler(lambda job: None)
    job = s.add("t", interval_sec=60, run_immediately=True)
    fired = s.tick()
    assert fired == 1

    reloaded = _scheduler(tmp_path).list()[0]
    assert reloaded.runs == 1
    assert reloaded.last_status == "ok"
