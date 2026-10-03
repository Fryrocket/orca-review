"""Durable, bounded Administrator Screen acceptance runs for ORCA Studio.

This lane reports evidence produced by governed ORCA workflows.  It deliberately
does not expose shell execution or inherit normal chat authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Callable
import zipfile

from .product_package import create_pi5_cooling_hat_package, prepare_fabrication_readiness


MAX_ITERATIONS = 3
TERMINAL = frozenset({"ready_for_workbench", "blocked", "failed"})
ENABLED_TECHNICAL_AUTHORITY = frozenset({
    "orca_forge_source", "core_code", "diagnostics", "tests", "test_fixtures",
    "configuration", "local_services", "governed_permissions", "release_construction",
    "deployment", "rollback", "recovery", "local_tools", "registered_connectors",
    "autonomous_repair_rerun",
})
APPROVAL_GATED_AUTHORITY = frozenset({
    "credentials", "money", "purchasing", "publishing", "external_contact",
    "physical_hardware", "legal_acceptance", "unrecoverable_deletion",
})
PROHIBITED_SILENT_ACTIONS = frozenset({
    "credential_exposure", "permission_widening", "fake_evidence", "gate_bypass",
})
_RUN_ID = re.compile(r"eng_[0-9]{8}T[0-9]{6}Z_[a-f0-9]{12}")


class AcceptanceFailure(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _event(run: dict, state: str, step: str, detail: str, **evidence) -> None:
    run["state"] = state
    run["updated_at"] = _now()
    row = {"at": run["updated_at"], "state": state, "step": step, "detail": detail}
    if evidence:
        row["evidence"] = evidence
    run["events"].append(row)


def _verify_package(result: dict, root: Path) -> list[str]:
    failures: list[str] = []
    package = root / result["package_id"]
    archive = package / "ORCA-Pi5-Cooling-HAT.zip"
    manifest_path = package / "MANIFEST.json"
    required_paperwork = {
        "PROJECT.json", "REVIEW.json", "requirements.csv",
        "verification-plan.md", "fabrication-readiness.md", "owner-execution-checklist.md",
        "firmware-test-results.txt", "pi5-cooling-hat.kicad_sch", "pi5-cooling-hat.kicad_pcb",
    }
    if not archive.is_file() or not manifest_path.is_file():
        return ["real package archive or manifest is missing"]
    if sha256(archive.read_bytes()).hexdigest() != result.get("zip_sha256"):
        failures.append("download checksum does not match the real archive")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = {item["name"] for item in manifest.get("artifacts", [])}
    missing = sorted(name for name in required_paperwork
                     if name not in names or not (package / name).is_file())
    if missing:
        failures.append("required artifacts missing: " + ", ".join(missing))
    for item in manifest.get("artifacts", []):
        path = package / item["name"]
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            failures.append(f"artifact is absent or hash-invalid: {item['name']}")
    checks = result.get("review", {}).get("checks", {}).get("functional_electronics_gate", {})
    required_checks = {
        "schematic_has_symbols", "schematic_has_connectivity_labels", "pcb_is_routed", "pcb_unconnected_items",
        "pcb_drc_errors", "schematic_erc_errors", "gerbers_present", "firmware_tests_passed",
    }
    failed_checks = sorted(name for name in required_checks if checks.get(name) is not True)
    if failed_checks:
        failures.append("deterministic gates did not pass: " + ", ".join(failed_checks))
    board = (package / "pi5-cooling-hat.kicad_pcb").read_text(encoding="utf-8")
    schematic = (package / "pi5-cooling-hat.kicad_sch").read_text(encoding="utf-8")
    if board.count("(footprint") < 10 or board.count("(segment") < 20:
        failures.append("KiCad PCB is empty or materially incomplete")
    if schematic.count("(symbol") < 10 or schematic.count("(global_label") < 8:
        failures.append("KiCad schematic is empty or unconnected")
    firmware = (package / "firmware-test-results.txt").read_text(encoding="utf-8")
    if "Ran 4 tests" not in firmware or "OK" not in firmware:
        failures.append("firmware was not actually executed successfully")
    try:
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None or set(bundle.namelist()) != names | {"MANIFEST.json"}:
                failures.append("archive contents are corrupt or do not match the manifest")
    except zipfile.BadZipFile:
        failures.append("package download is not a real ZIP archive")
    return failures


def run_acceptance(prompt: str, root: str | Path,
                   builder: Callable = create_pi5_cooling_hat_package) -> dict:
    """Run one bounded, durable acceptance project to a truthful terminal state."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise ValueError("engineering prompt must contain 1-12000 characters")
    base = Path(root).resolve()
    runs = base / "engineering-runs"
    packages = base / "packages"
    runs.mkdir(parents=True, exist_ok=True)
    packages.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prompt_hash = sha256(prompt.encode()).hexdigest()
    run = {
        "run_id": f"eng_{stamp}_{prompt_hash[:12]}", "prompt_sha256": prompt_hash,
        "created_at": _now(), "updated_at": _now(), "state": "planned", "iteration": 0,
        "max_iterations": MAX_ITERATIONS, "authority": "administrator_screen",
        "chat_authority": False, "ordinary_orca_agents_have_authority": False,
        "capability_matrix": {
            "enabled": sorted(ENABLED_TECHNICAL_AUTHORITY),
            "approval_gated": sorted(APPROVAL_GATED_AUTHORITY),
            "prohibited": sorted(PROHIBITED_SILENT_ACTIONS),
        },
        "regression_baseline": {"scenario": "Pi 5 Active-Cooling HAT", "file_count": 48,
                                "sha256": "9d88d0a43403677d3ca4c88dedaceb441cafd8c117e5d31c809caff522987db6",
                                "firmware_tests": "passed", "unconnected_pads": 0,
                                "physical_gates": "pending"},
        "permission_decisions": [{"decision": "allow", "scopes": sorted(ENABLED_TECHNICAL_AUTHORITY),
                                  "reason": "external Frontier technical lane"},
                                 {"decision": "gate", "scopes": sorted(APPROVAL_GATED_AUTHORITY),
                                  "reason": "explicit owner, legal, or physical evidence required"},
                                 {"decision": "deny", "scopes": sorted(PROHIBITED_SILENT_ACTIONS),
                                  "reason": "never permitted silently"}],
        "events": [], "artifacts": [], "blockers": [], "rollback": {
            "state": "preserved", "activation": "not_requested", "target": None},
    }
    path = runs / f"{run['run_id']}.json"
    _event(run, "planned", "project", "Tracked engineering run created before execution")
    _write(path, run)
    failures: list[str] = []
    for iteration in range(1, MAX_ITERATIONS + 1):
        run["iteration"] = iteration
        _event(run, "running" if iteration == 1 else "repairing", "package",
               "Generating real project artifacts" if iteration == 1 else "Regenerating dependent artifacts after confirmed failure")
        _write(path, run)
        try:
            result = builder(prompt, packages)
            result = prepare_fabrication_readiness(packages, result["project"]["project_id"])
            failures = _verify_package(result, packages)
        except Exception as exc:
            failures = [f"execution failed: {type(exc).__name__}: {exc}"]
        if not failures:
            run["project_id"] = result["project"]["project_id"]
            run["artifacts"] = [
                {"kind": "package", "href": result["download_url"], "sha256": result["zip_sha256"]},
                {"kind": "manifest", "href": result["manifest_url"],
                 "sha256": sha256((packages / result["package_id"] / "MANIFEST.json").read_bytes()).hexdigest()},
            ]
            run["checks"] = result["review"]["checks"]
            blockers = list(result["review"].get("blocking_evidence", []))
            run["blockers"] = blockers
            _event(run, "passed", "independent_review", "Deterministic and independent evidence gates passed",
                   archive_sha256=result["zip_sha256"], artifact_count=result["artifact_count"])
            _event(run, "blocked" if blockers else "ready_for_workbench", "release",
                   "Functional package passed; owner-present physical gates remain" if blockers else "Ready for Workbench")
            _write(path, run)
            return run
        _event(run, "repairing" if iteration < MAX_ITERATIONS else "failed", "verification",
               "; ".join(failures))
        _write(path, run)
    run["blockers"] = failures
    _write(path, run)
    return run


def list_runs(root: str | Path) -> list[dict]:
    directory = Path(root).resolve() / "engineering-runs"
    if not directory.is_dir():
        return []
    results = []
    for path in sorted(directory.glob("eng_*.json"), reverse=True):
        try:
            results.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return results


def read_run(root: str | Path, run_id: str) -> dict:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("engineering run id is invalid")
    path = Path(root).resolve() / "engineering-runs" / f"{run_id}.json"
    if not path.is_file():
        raise FileNotFoundError(run_id)
    return json.loads(path.read_text(encoding="utf-8"))
