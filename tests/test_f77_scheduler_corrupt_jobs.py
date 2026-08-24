"""R11-F77 ("scheduler corrupt jobs.json kills process") — a crisp finding.

scheduler.py load() comments "a corrupt jobs.json must not kill the
process" but only catches JSONDecodeError/OSError. Job(**j) is outside
that try: an extra key, a missing id, or `jobs` not a list raises
TypeError/KeyError from SessionScheduler.__init__.

Fix: ignore unknown fields; skip rows that still cannot construct;
refuse a non-list `jobs` without raising.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.scheduler import SessionScheduler


def test_extra_key_does_not_kill_and_job_still_loads(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "abcd1234",
                        "name": "keep",
                        "interval_sec": 60,
                        "extra": True,
                    }
                ]
            }
        )
    )
    s = SessionScheduler(path)
    jobs = s.list()
    assert len(jobs) == 1
    assert jobs[0].id == "abcd1234"
    assert jobs[0].name == "keep"


def test_missing_id_is_skipped_not_raised(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"name": "bad", "interval_sec": 60},
                    {"id": "good0001", "name": "ok", "interval_sec": 30},
                ]
            }
        )
    )
    s = SessionScheduler(path)
    jobs = s.list()
    assert [j.id for j in jobs] == ["good0001"]


def test_jobs_not_a_list_does_not_kill(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps({"jobs": "nope"}))
    s = SessionScheduler(path)
    assert s.list() == []


def test_invalid_json_still_soft(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text("{not json")
    s = SessionScheduler(path)
    assert s.list() == []
