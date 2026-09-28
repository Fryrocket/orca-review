from __future__ import annotations

import json
from threading import Thread
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .control_plane import ControlPlane
from .domain import JobStatus
from .web import OrcaHTTPServer


SIMULATION_BRIEF = (
    "Develop a weatherproof portable wildlife monitoring station with an AI camera, "
    "environmental sensors, Wi-Fi and Bluetooth, a rechargeable lithium battery, "
    "solar charging, local storage, a mobile app, and a serviceable enclosure."
)


class _SimulationInventory:
    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        return {
            "items": [
                {"sku": "ESP32-S3", "name": "ESP32-S3 module", "quantity": 4},
                {"sku": "CAM-5MP", "name": "5 MP camera module", "quantity": 2},
                {"sku": "R-10K", "name": "10 kOhm resistor", "quantity": 500},
                {"sku": "CELL-LFP", "name": "LiFePO4 cell", "quantity": 8},
            ]
        }


def _post_json(
        url: str, body: dict[str, object], headers: dict[str, str],
        ) -> tuple[dict, dict[str, str]]:
    request = Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    with urlopen(request) as response:
        return json.load(response), dict(response.headers.items())


def run_product_development_simulation() -> dict[str, Any]:
    """Exercise the complete safe product-planning path without external effects."""

    token = "simulation-operator-token-00000001"
    control = ControlPlane()
    server = OrcaHTTPServer(
        ("127.0.0.1", 0), control, operator_token=token,
        inventory_provider=_SimulationInventory(),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checks: dict[str, bool] = {}
    details: dict[str, object] = {}
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}/api/product-development/plans"
        initial_revision = control.state_revision
        headers = {
            "X-ORCA-Operator-Token": token,
            "Idempotency-Key": "product-simulation-primary-0001",
            "X-ORCA-Expected-Revision": str(initial_revision),
        }
        first, _ = _post_json(endpoint, {"prompt": SIMULATION_BRIEF}, headers)
        replay, replay_headers = _post_json(
            endpoint, {"prompt": SIMULATION_BRIEF}, headers)

        plan = first["plan"]
        job = first["job"]
        record = first["record"]
        track_ids = {track["id"] for track in plan["tracks"]}
        expected_tracks = {
            "product", "industrial", "quality", "supply", "electrical",
            "firmware", "mechanical", "rf", "battery", "ai",
        }
        expected_phases = [
            "discovery", "requirements", "architecture", "feasibility",
            "detailed_design", "prototype", "verification", "manufacturing",
            "launch", "lifecycle",
        ]
        checks.update({
            "all_engineering_tracks_selected": expected_tracks <= track_ids,
            "ten_stage_lifecycle_present": [item["id"] for item in plan["phases"]] == expected_phases,
            "requirements_are_traceable": all(
                item.get("id") and item.get("verification") and item.get("status") == "open"
                for item in plan["requirements"]),
            "fmea_math_and_priority_order_valid": (
                all(item["rpn"] == item["severity"] * item["occurrence"] * item["detection"]
                    for item in plan["risks"])
                and [item["rpn"] for item in plan["risks"]]
                == sorted((item["rpn"] for item in plan["risks"]), reverse=True)
            ),
            "inventory_read_without_allocation": (
                plan["inventory"]["state"] == "available"
                and plan["inventory"]["items_seen"] == 4
                and plan["inventory"]["matched_items"] == []
            ),
            "concept_not_falsely_released": (
                plan["maturity"] == "concept"
                and plan["release_state"] == "not_released"
                and record["status"] == "draft"
            ),
            "all_approval_gates_closed": all(
                item["status"] == "required" for item in plan["approval_gates"]),
            "canonical_product_record_created": (
                record["record_type"] == "product"
                and record["record_id"] == plan["product_id"]
                and record["version"] == 1
            ),
            "quench_review_requested": (
                job["status"] == "review" and job["reviewer"] == "quench"),
            "idempotent_replay_exact": first == replay,
            "idempotent_replay_marked": (
                replay_headers.get("X-ORCA-Idempotency-Replayed") == "true"),
            "idempotent_replay_created_one_job": len(control.jobs) == 1,
        })

        before_invalid = control.snapshot()
        invalid_headers = {
            "X-ORCA-Operator-Token": token,
            "Idempotency-Key": "product-simulation-invalid-0001",
            "X-ORCA-Expected-Revision": str(control.state_revision),
        }
        invalid_rejected = False
        try:
            _post_json(endpoint, {"prompt": SIMULATION_BRIEF, "release": True}, invalid_headers)
        except HTTPError as exc:
            invalid_rejected = exc.code == 400
        after_invalid = control.snapshot()
        checks["malformed_request_rejected"] = invalid_rejected
        checks["malformed_request_created_no_job_or_record"] = (
            len(after_invalid["jobs"]) == len(before_invalid["jobs"])
            and after_invalid["business"]["counts"] == before_invalid["business"]["counts"]
        )

        completed = control.complete_job(
            job["id"], actor="quench",
            note="Simulation review confirmed stage gates, traceability, risk math, and unreleased state.",
        )
        checks["independent_review_completes_job"] = completed.status is JobStatus.COMPLETE

        revised = control.create_product_development_plan(
            prompt=SIMULATION_BRIEF,
            inventory=_SimulationInventory().snapshot(), requested_by="fry",
        )
        checks["repeat_concept_creates_traceable_revision"] = (
            revised["record"]["version"] == 2
            and revised["record"]["source_revision"] == 2
            and revised["record"]["record_id"] == record["record_id"]
        )
        checks["ledger_integrity_valid"] = control.business.verify()
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/health") as response:
            health = json.load(response)
        checks["control_plane_integrity_valid"] = health == {
            "status": "healthy", "integrity_valid": True}
        checks["no_connector_or_external_action_claimed"] = (
            control.business.snapshot()["connector_claims"]
            == "not_inferred_from_source_names"
            and all(item["state"] != "connected" for item in plan["tool_plan"])
        )

        evidence_kinds = {
            item["kind"] for item in control.evidence.list(limit=100)
        }
        checks["audit_evidence_complete"] = {
            "product.development.plan_created", "job.review_requested", "job.completed"
        } <= evidence_kinds
        details = {
            "product_id": plan["product_id"],
            "tracks": len(plan["tracks"]),
            "phases": len(plan["phases"]),
            "requirements": len(plan["requirements"]),
            "risks": len(plan["risks"]),
            "deliverables": len(plan["deliverables"]),
            "inventory_items_seen": plan["inventory"]["items_seen"],
            "canonical_record_version": revised["record"]["version"],
            "jobs_created": len(control.jobs),
            "external_actions": 0,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "simulation": "ORCA product development end-to-end",
        "scenario": SIMULATION_BRIEF,
        "passed": not failed,
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "failed_checks": failed,
        "checks": checks,
        "details": details,
        "safety": {
            "network_scope": "loopback only",
            "purchases": 0,
            "supplier_contacts": 0,
            "inventory_allocations": 0,
            "deployments": 0,
        },
    }


def main() -> int:
    report = run_product_development_simulation()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
