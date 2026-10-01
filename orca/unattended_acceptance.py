from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .credential_broker import plan_credential_use
from .roles import ROLE_CATALOG, validate_role_catalog
from .run_evidence import EvidenceRunLog, verify_run_log
from .temper_inference_simulation import run_temper_inference_simulation
from .temper_watch_simulation import (
    run_temper_watch_recovery_simulation,
    run_temper_watch_simulation,
)


def run_unattended_acceptance(output_dir: Path) -> dict:
    """Run the safe remote acceptance stack using disposable inputs only."""
    output_dir = Path(output_dir)
    run_id = datetime.now(timezone.utc).strftime("unattended-%Y%m%dT%H%M%SZ")
    evidence_path = output_dir / f"{run_id}.jsonl"
    checks: list[dict] = []

    with EvidenceRunLog(evidence_path, run_id=run_id) as log:
        for name, runner in (
            ("temper_watch_fault_matrix", run_temper_watch_simulation),
            ("temper_network_recovery_simulation", run_temper_watch_recovery_simulation),
            ("temper_dataset_to_hailo_plan", run_temper_inference_simulation),
        ):
            result = runner()
            passed = result.get("passed") is True
            checks.append({"name": name, "passed": passed})
            log.append("simulation", {"name": name, "passed": passed, "result": result})

        validate_role_catalog()
        forbidden = {
            role.id: sorted({"approve_r3", "deploy"} & set(role.authority))
            for role in ROLE_CATALOG.values() if role.id != "fry"
            and {"approve_r3", "deploy"} & set(role.authority)
        }
        bot_permissions_passed = forbidden == {}
        checks.append({"name": "bot_negative_permissions", "passed": bot_permissions_passed})
        log.append("permission_check", {"passed": bot_permissions_passed,
                                        "forbidden_authority": forbidden})

        rules = [{"reference": "kiln.amazon", "caller": "browser_operator",
                  "service": "amazon", "account": "owner", "host": "kiln",
                  "actions": ["existing_login"]}]
        routine = plan_credential_use(
            reference="kiln.amazon", caller="browser_operator", service="amazon",
            account="owner", purpose="read an existing signed-in page", host="kiln",
            action_class="existing_login", allowed=rules)
        sensitive = plan_credential_use(
            reference="kiln.amazon", caller="browser_operator", service="amazon",
            account="owner", purpose="change account settings", host="kiln",
            action_class="account_change", allowed=rules)
        broker_passed = (
            routine["approved"] is True and routine["secret_present"] is False
            and sensitive["approved"] is False
            and sensitive["next_gate"] == "authenticated remote owner approval"
        )
        checks.append({"name": "credential_broker_fake_reference", "passed": broker_passed})
        log.append("credential_broker_check", {
            "passed": broker_passed, "routine": routine, "sensitive": sensitive,
            "credential_value": "disposable-secret-must-not-appear",
        })

        passed = all(item["passed"] for item in checks)
        log.append("summary", {"passed": passed, "checks": checks,
                               "external_actions": 0, "live_state_changed": False})

    integrity = verify_run_log(evidence_path)
    return {
        "schema": "orca.unattended-acceptance.v1", "run_id": run_id,
        "passed": all(item["passed"] for item in checks) and integrity["valid"],
        "checks": checks, "checks_passed": sum(item["passed"] for item in checks),
        "checks_total": len(checks), "evidence": str(evidence_path),
        "evidence_integrity": integrity, "external_actions": 0,
        "live_state_changed": False,
        "blocked_physical_gates": [
            "real TEMPER interface-loss and restart exercise",
            "supervised TEMPER reboot and power-loss acceptance",
            "physical barcode scanner and headset acceptance",
            "real inventory image capture and two-pass human labeling",
            "iPhone Keychain MQTT installation and cutover",
        ],
    }
