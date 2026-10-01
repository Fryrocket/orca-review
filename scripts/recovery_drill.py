from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from orca.control_plane import ControlPlane
from orca.domain import Action
from orca.evidence import EvidenceStore
from orca.fleet import Heartbeat, sign_heartbeat


def file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def seed_database(path: Path) -> dict:
    control = ControlPlane(EvidenceStore(path))
    job = control.submit(title="recovery proof", lane="orca", requested_by="orca",
                         assigned_to="smith", action=Action("read", "recovery fixture"))
    control.start_job(job.id, actor="smith")
    control.submit_job_review(job.id, actor="smith", reviewer="quench")
    control.complete_job(job.id, actor="quench", note="recovery fixture reviewed")
    incident = control.open_incident(severity="S1", title="recovery fixture",
                                     lane="orca", owner="orca", detail="test only")
    control.set_node_pause("kiln", actor="orca", paused=True, reason="recovery fixture")
    node_key = b"recovery-fixture-key-material-32"
    control.enroll_node("forge", actor="fry", key=node_key)
    heartbeat = Heartbeat("forge", 10_000, 1, "healthy", "recovery fixture")
    control.accept_heartbeat(
        heartbeat, signature=sign_heartbeat(heartbeat, node_key), key=node_key, now=10_000)
    control.set_emergency_stop(actor="fry", active=True, reason="recovery fixture")
    assert control.evidence.verify()
    control.evidence.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    expected = {"job_id": job.id, "incident_id": incident.id,
                "node_key_fingerprint": control.node_enrollments["forge"]["key_fingerprint"],
                "event_count": len(control.evidence.list(limit=1000))}
    control.evidence.db.close()
    return expected


def copy_workspace(source: Path, target: Path) -> None:
    # Keep the recovery fixture aligned with the actual tested release surface.
    # The v1 suite imports governed bot workers from deploy/* and validates the
    # KILN desktop launchers, so omitting those trees creates a false recovery
    # failure (or worse, a falsely incomplete restore).
    for name in ("orca", "tests_v1", "docs", "scripts", "deploy", "desktop",
                 "benchmarks"):
        shutil.copytree(source / name, target / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(source / name, target / name)


def run_drill(source: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="orca-recovery-") as raw_temp:
        temp = Path(raw_temp)
        restored = temp / "restored"
        restored.mkdir()
        copy_workspace(source, restored)
        seed = temp / "seed.db"
        expected = seed_database(seed)
        restored_db = restored / "restored.db"
        shutil.copy2(seed, restored_db)

        installed = temp / "installed"
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--no-build-isolation",
             "--target", str(installed), "."],
            cwd=restored, text=True, capture_output=True, timeout=120, check=False,
        )
        if install.returncode != 0:
            raise RuntimeError("isolated package install failed:\n" + install.stdout + install.stderr)
        smoke_environment = dict(os.environ)
        smoke_environment["PYTHONPATH"] = str(installed)
        smoke = subprocess.run(
            [sys.executable, "-c", "import orca; print(orca.__version__)"],
            cwd=temp, env=smoke_environment, text=True, capture_output=True,
            timeout=30, check=False,
        )
        if smoke.returncode != 0:
            raise RuntimeError("installed package smoke test failed:\n" + smoke.stdout + smoke.stderr)

        tests = subprocess.run(
            [sys.executable, "-m", "pytest", "tests_v1", "-q"], cwd=restored,
            text=True, capture_output=True, timeout=120, check=False,
        )
        if tests.returncode != 0:
            raise RuntimeError("restored test suite failed:\n" + tests.stdout + tests.stderr)

        probe_code = """
import json
from orca.control_plane import ControlPlane
from orca.evidence import EvidenceStore
cp = ControlPlane(EvidenceStore('restored.db'))
state = cp.snapshot()
assert state['evidence_chain_valid'] is True
assert any(j['id'] == %r and j['status'] == 'complete' for j in state['jobs'])
assert any(i['id'] == %r and i['status'] == 'open' for i in state['incidents'])
assert 'kiln' in state['paused_nodes']
assert state['emergency_stop'] is True
assert state['node_enrollments']['forge']['key_fingerprint'] == %r
assert 'recovery-fixture-key-material-32' not in json.dumps(state)
cp.set_emergency_stop(actor='fry', active=False, reason='recovery drill')
assert cp.expire_stale_nodes(now=10600) == ['forge']
state = cp.snapshot()
assert state['evidence_chain_valid'] is True
assert next(node for node in state['nodes'] if node['id'] == 'forge')['state'] == 'offline'
print(json.dumps({'schema_version': state['schema_version'], 'jobs': len(state['jobs']),
                  'incidents': len(state['incidents']), 'paused_nodes': state['paused_nodes'],
                  'emergency_stop_exercised': True, 'authenticated_node_exercised': 'forge',
                  'evidence_chain_valid': state['evidence_chain_valid']}))
""" % (expected["job_id"], expected["incident_id"], expected["node_key_fingerprint"])
        probe = subprocess.run(
            [sys.executable, "-c", probe_code], cwd=restored,
            text=True, capture_output=True, timeout=30, check=False,
        )
        if probe.returncode != 0:
            raise RuntimeError("restored state probe failed:\n" + probe.stdout + probe.stderr)

        return {
            "status": "passed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "source": str(source),
            "isolation": "fresh temporary directory",
            "database_sha256": file_digest(restored_db),
            "expected_seed": expected,
            "restored_state": json.loads(probe.stdout),
            "package_install": {"status": "passed", "version": smoke.stdout.strip(),
                                "dependencies_downloaded": False},
            "test_summary": tests.stdout.strip().splitlines()[-1],
            "limitations": [
                "local reconstruction from the current working tree, not an approved release",
                "no deployment, connector write, remote execution, or secret restoration",
                "independent QUENCH review remains separate",
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    source = REPOSITORY_ROOT
    report = run_drill(source)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
