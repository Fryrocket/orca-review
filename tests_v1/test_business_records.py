from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

import pytest

from orca.business import BusinessRevisionConflict
from orca.control_plane import ControlPlane
from orca.evidence import EvidenceStore
from orca.web import OrcaHTTPServer


def _product(**overrides):
    values = {
        "record_type": "product",
        "record_id": "QVS-HAT-001",
        "source_system": "orca_draft",
        "source_revision": 1,
        "status": "draft",
        "data": {"sku": "QVS-HAT-001", "name": "Pi cooling HAT"},
        "provenance": {"kind": "operator_draft", "reference": "test-fixture"},
        "confidence": 0.8,
        "requested_by": "fry",
    }
    values.update(overrides)
    return values


def test_canonical_business_record_is_durable_and_audited(tmp_path: Path):
    path = tmp_path / "orca.db"
    control = ControlPlane(EvidenceStore(path))

    result = control.upsert_business_record(**_product())

    assert result["replayed"] is False
    assert result["record"]["version"] == 1
    assert result["record"]["source_system"] == "orca_draft"
    assert control.business.verify() is True
    assert any(
        event["kind"] == "business.record.observed"
        for event in control.evidence.list(limit=20)
    )

    restored = ControlPlane(EvidenceStore(path))
    record = restored.business.get("product", "QVS-HAT-001")
    assert record["data"]["name"] == "Pi cooling HAT"
    assert restored.snapshot()["business"]["counts"]["product"] == 1


def test_same_source_revision_replays_only_identical_content():
    control = ControlPlane()
    first = control.upsert_business_record(**_product())
    replay = control.upsert_business_record(**_product())

    assert replay["replayed"] is True
    assert replay["event"]["event_id"] == first["event"]["event_id"]
    assert len(control.business.snapshot()["events"]) == 1

    with pytest.raises(BusinessRevisionConflict, match="different content"):
        control.upsert_business_record(**_product(
            data={"sku": "QVS-HAT-001", "name": "Changed silently"}))


def test_stale_source_revision_cannot_overwrite_newer_record():
    control = ControlPlane()
    control.upsert_business_record(**_product(source_revision=2))

    with pytest.raises(BusinessRevisionConflict, match="stale"):
        control.upsert_business_record(**_product(source_revision=1))


def test_cross_source_observation_advances_canonical_version_with_provenance():
    control = ControlPlane()
    control.upsert_business_record(**_product())
    second = control.upsert_business_record(**_product(
        source_system="supplier_feed", source_revision=1,
        provenance={"kind": "supplier_file", "reference": "offer-42"},
        confidence=0.95,
    ))

    assert second["record"]["version"] == 2
    assert second["record"]["source_system"] == "supplier_feed"
    assert second["record"]["provenance"]["reference"] == "offer-42"


def test_inventory_projection_blocks_oversell_and_derives_available():
    control = ControlPlane()
    valid = _product(
        record_type="inventory_position", record_id="QVS-HAT-001:kansas",
        data={"sku": "QVS-HAT-001", "location": "kansas", "on_hand": 12,
              "reserved": 5},
    )
    result = control.upsert_business_record(**valid)
    assert result["record"]["data"]["available"] == 7

    with pytest.raises(ValueError, match="exceeds stock"):
        control.upsert_business_record(**{
            **valid, "record_id": "QVS-HAT-001:kiln", "source_revision": 2,
            "data": {"sku": "QVS-HAT-001", "location": "kiln", "on_hand": 2,
                     "reserved": 3},
        })


def test_business_integrity_detects_projection_tampering():
    control = ControlPlane()
    control.upsert_business_record(**_product())
    control.evidence.db.execute(
        "UPDATE business_records SET status='active' WHERE record_type='product' AND record_id='QVS-HAT-001'")
    control.evidence.db.commit()

    assert control.business.verify() is False
    with pytest.raises(RuntimeError, match="business ledger integrity"):
        control.snapshot()


def test_business_record_http_route_is_idempotent_and_readable():
    token = "b" * 32
    control = ControlPlane()
    server = OrcaHTTPServer(
        ("127.0.0.1", 0), control, operator_token=token)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = _product()
        payload.pop("requested_by")
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "X-ORCA-Operator-Token": token,
            "Idempotency-Key": "business-record-test-0001",
            "X-ORCA-Expected-Revision": str(control.state_revision),
        }
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/business/records",
            data=body, method="POST", headers=headers)
        with urlopen(request) as response:
            created = json.load(response)
        assert response.status == 201
        assert created["record"]["record_id"] == "QVS-HAT-001"

        # A transport retry replays the mutation receipt rather than adding an event.
        with urlopen(request) as response:
            replayed = json.load(response)
        assert response.headers["X-ORCA-Idempotency-Replayed"] == "true"
        assert replayed == created
        assert len(control.business.snapshot()["events"]) == 1

        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/business/state") as response:
            state = json.load(response)
        assert state["counts"]["product"] == 1
        assert state["connector_claims"] == "not_inferred_from_source_names"
    finally:
        server.shutdown()
        server.server_close()
