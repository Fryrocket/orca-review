import json
import threading

import pytest

from orca.notifications import (
    Alert,
    AlertStatus,
    DeliveryOutcome,
    NotificationConflict,
    NotificationLeaseLoss,
    NotificationOutbox,
    transition_alert,
)
from orca.control_plane import ControlPlane
from orca.evidence import EvidenceStore


def test_success_uses_injected_transport_and_records_delivery():
    seen = []
    outbox = NotificationOutbox(retry_schedule=(5, 30))
    queued = outbox.enqueue(
        alert_id="alert-1",
        idempotency_key="incident-1",
        payload={"severity": "S2", "title": "node stale"},
        now=100,
    )

    def transport(*, payload, idempotency_key):
        seen.append((payload, idempotency_key))
        return {"accepted": True}

    delivered = outbox.attempt(
        queued.id, now=100, transport=transport, clock=lambda: 100)

    assert delivered.status is AlertStatus.DELIVERED
    assert delivered.attempts == 1
    assert delivered.delivered_at == 100
    assert seen == [(queued.payload, queued.idempotency_key)]


def test_failure_retries_only_after_explicit_schedule():
    calls = 0
    outbox = NotificationOutbox(retry_schedule=(5, 30))
    outbox.enqueue(alert_id="alert-1", payload={"title": "retry"}, now=100)

    def transport(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic provider failure")
        return True

    retry = outbox.attempt(
        "alert-1", now=100, transport=transport, clock=lambda: 100)
    assert retry.status is AlertStatus.RETRY
    assert retry.next_attempt_at == 105
    assert retry.last_error == "transport_exception"

    unchanged = outbox.attempt("alert-1", now=104.99, transport=transport)
    assert unchanged == retry
    assert calls == 1

    delivered = outbox.attempt(
        "alert-1", now=105, transport=transport, clock=lambda: 105)
    assert delivered.status is AlertStatus.DELIVERED
    assert delivered.attempts == 2
    assert calls == 2


def test_attempt_samples_completion_clock_after_transport_for_backoff():
    events = []
    outbox = NotificationOutbox(retry_schedule=(5,))
    outbox.enqueue(alert_id="alert-1", payload={"title": "timed"}, now=100)

    def transport(**_):
        events.append("transport")
        return False

    def clock():
        events.append("clock")
        return 107

    retry = outbox.attempt(
        "alert-1", now=100, transport=transport, clock=clock)

    assert events == ["transport", "clock"]
    assert retry.status is AlertStatus.RETRY
    assert retry.next_attempt_at == 112


def test_attempt_rejects_provider_result_completed_at_lease_expiry():
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-1", payload={"title": "late"}, now=100)

    with pytest.raises(NotificationConflict, match="expired"):
        outbox.attempt(
            "alert-1", now=100, transport=lambda **_: True,
            clock=lambda: 400,
        )

    reserved = outbox.get("alert-1")
    assert reserved.status is AlertStatus.IN_FLIGHT
    assert reserved.attempts == 1


def test_standalone_batch_advances_claim_time_after_each_transport():
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-a", payload={}, now=100)
    outbox.enqueue(alert_id="alert-b", payload={}, now=100)
    observed_claim_starts = []
    completion_times = iter((110, 120))

    def transport(**_):
        active = [
            alert for alert in outbox.alerts()
            if alert.status is AlertStatus.IN_FLIGHT
        ]
        assert len(active) == 1
        observed_claim_starts.append(active[0].claim_started_at)
        return True

    results = outbox.process_due(
        now=100,
        transport=transport,
        clock=lambda: next(completion_times),
        limit=2,
    )

    assert all(isinstance(result, Alert) for result in results)
    assert observed_claim_starts == [100, 110]
    assert [result.delivered_at for result in results] == [110, 120]


def test_standalone_batch_reports_lease_loss_and_continues():
    outbox = NotificationOutbox(retry_schedule=(30,))
    outbox.enqueue(alert_id="alert-a", payload={}, now=0)
    outbox.enqueue(alert_id="alert-b", payload={}, now=0)
    completion_times = iter((300, 301))
    calls = 0

    def transport(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            expired = outbox.claim_due(
                now=300, claim_id="reaper", limit=1)
            assert expired.expired[0].id == "alert-a"
        return True

    results = outbox.process_due(
        now=0,
        transport=transport,
        clock=lambda: next(completion_times),
        limit=2,
    )

    assert isinstance(results[0], NotificationLeaseLoss)
    assert results[0].to_dict() == {
        **results[0].alert.to_dict(),
        "delivery_result": "lease_lost",
    }
    assert results[0].alert.status is AlertStatus.RETRY
    assert isinstance(results[1], Alert)
    assert results[1].id == "alert-b"
    assert results[1].status is AlertStatus.DELIVERED
    assert calls == 2


def test_standalone_batch_does_not_swallow_completion_validation_errors():
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-1", payload={}, now=1)

    with pytest.raises(ValueError, match="completion time must be finite"):
        outbox.process_due(
            now=1, transport=lambda **_: True,
            clock=lambda: float("nan"), limit=1,
        )

    assert outbox.get("alert-1").status is AlertStatus.IN_FLIGHT


def test_duplicate_idempotency_key_suppresses_second_alert_and_send():
    calls = 0
    outbox = NotificationOutbox(retry_schedule=())
    first = outbox.enqueue(
        alert_id="alert-1", idempotency_key="same-incident",
        payload={"title": "first"}, now=1,
    )
    duplicate = outbox.enqueue(
        alert_id="alert-2", idempotency_key="same-incident",
        payload={"title": "first"}, now=2,
    )

    def transport(**_):
        nonlocal calls
        calls += 1
        return True

    outbox.process_due(now=2, transport=transport, clock=lambda: 2)
    outbox.process_due(now=3, transport=transport, clock=lambda: 3)

    assert duplicate.id == first.id
    assert len(outbox) == 1
    assert calls == 1


def test_duplicate_idempotency_key_rejects_different_content():
    outbox = NotificationOutbox()
    outbox.enqueue(
        alert_id="alert-1", idempotency_key="same-incident",
        payload={"title": "first"}, now=1,
    )
    with pytest.raises(NotificationConflict, match="different content"):
        outbox.enqueue(
            alert_id="alert-2", idempotency_key="same-incident",
            payload={"title": "changed"}, now=2,
        )
    assert len(outbox) == 1


def test_max_attempt_failure_enters_dead_letter_without_exception_secret():
    secret = "sk-syntheticsecret123456789"
    outbox = NotificationOutbox(retry_schedule=(2,))
    outbox.enqueue(alert_id="alert-1", payload={"title": "failure"}, now=10)

    def transport(**_):
        raise RuntimeError(f"provider leaked {secret}")

    retry = outbox.attempt(
        "alert-1", now=10, transport=transport, clock=lambda: 10)
    dead = outbox.attempt(
        "alert-1", now=retry.next_attempt_at, transport=transport,
        clock=lambda: retry.next_attempt_at,
    )

    assert dead.status is AlertStatus.DEAD_LETTER
    assert dead.attempts == outbox.max_attempts == 2
    assert dead.last_error == "transport_exception"
    assert secret not in outbox.to_json()


def test_payload_is_redacted_before_storage_or_transport():
    secret = "sk-syntheticsecret123456789"
    seen = []
    outbox = NotificationOutbox(retry_schedule=())
    alert = outbox.enqueue(
        alert_id="alert-1",
        payload={
            "token": secret,
            "nested": {"password": "synthetic-password"},
            "message": f"Authorization bearer {secret}",
        },
        now=1,
    )
    outbox.attempt(
        "alert-1", now=1,
        transport=lambda **kwargs: seen.append(kwargs) or True,
        clock=lambda: 1,
    )

    serialized = outbox.to_json()
    assert secret not in serialized
    assert "synthetic-password" not in serialized
    assert alert.payload["token"] == "[REDACTED]"
    assert seen[0]["payload"]["nested"]["password"] == "[REDACTED]"


@pytest.mark.parametrize("acknowledgement", [None, False, {}, {"accepted": False}, "ok"])
def test_delivery_requires_an_explicit_positive_acknowledgement(acknowledgement):
    outbox = NotificationOutbox(retry_schedule=())
    outbox.enqueue(alert_id="alert-1", payload={"title": "ack"}, now=1)
    result = outbox.attempt(
        "alert-1", now=1, transport=lambda **_: acknowledgement,
        clock=lambda: 1,
    )
    assert result.status is AlertStatus.DEAD_LETTER
    assert result.last_error == "transport_rejected"


def test_alert_count_and_payload_size_are_bounded():
    outbox = NotificationOutbox(max_alerts=1)
    outbox.enqueue(alert_id="alert-1", payload={"title": "first"}, now=1)
    with pytest.raises(ValueError, match="limit reached"):
        outbox.enqueue(alert_id="alert-2", payload={"title": "second"}, now=2)

    oversized = NotificationOutbox()
    with pytest.raises(ValueError, match="size limit"):
        oversized.enqueue(
            alert_id="alert-large",
            payload={"detail": "x" * NotificationOutbox.MAX_PAYLOAD_BYTES},
            now=1,
        )

    state = outbox.to_dict()
    state["alerts"] = state["alerts"] * 2
    with pytest.raises(ValueError, match="configured limit"):
        NotificationOutbox.from_dict(state)

    with pytest.raises(ValueError, match="schedule exceeds"):
        NotificationOutbox(retry_schedule=(1,) * 65)

    for non_finite in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="JSON-compatible"):
            NotificationOutbox().enqueue(
                alert_id="alert-nonfinite",
                payload={"value": non_finite},
                now=1,
            )


def test_retry_state_round_trips_and_resumes_after_restart():
    outbox = NotificationOutbox(retry_schedule=(10, 20))
    outbox.enqueue(
        alert_id="alert-1", idempotency_key="restart-key",
        payload={"severity": "S3", "title": "restart fixture"}, now=50,
    )
    outbox.attempt(
        "alert-1", now=50,
        transport=lambda **_: False,
        clock=lambda: 50,
    )

    encoded = outbox.to_json()
    restored = NotificationOutbox.from_json(encoded)
    assert json.loads(restored.to_json()) == json.loads(encoded)
    assert restored.get("alert-1").status is AlertStatus.RETRY

    delivered = restored.attempt(
        "alert-1", now=60, transport=lambda **_: True, clock=lambda: 60)
    assert delivered.status is AlertStatus.DELIVERED
    assert delivered.attempts == 2


def test_v1_notification_state_migrates_without_delivery_leases():
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-1", payload={"title": "legacy"}, now=1)
    state = outbox.to_dict()
    state["schema_version"] = 1
    for row in state["alerts"]:
        row.pop("claim_id")
        row.pop("claim_started_at")
        row.pop("claim_until")

    restored = NotificationOutbox.from_dict(state)
    assert restored.to_dict()["schema_version"] == NotificationOutbox.SCHEMA_VERSION
    assert restored.get("alert-1").claim_id is None


def test_control_plane_persists_redacted_alert_queue_without_delivery(tmp_path):
    path = tmp_path / "orca.db"
    secret = "sk-syntheticsecret123456789"
    control = ControlPlane(EvidenceStore(path))
    incident = control.open_incident(
        severity="S2", title=f"credential exposure {secret}", lane="orca",
        owner="orca", detail="fixture",
    )
    queued = control.notifications.alerts()
    assert len(queued) == 1
    assert queued[0].status is AlertStatus.QUEUED
    assert queued[0].payload["incident_id"] == incident.id
    assert secret not in control.notifications.to_json()

    restored = ControlPlane(EvidenceStore(path))
    assert restored.notifications.to_json() == control.notifications.to_json()
    assert restored.snapshot()["notification_outbox"]["alerts"][0]["status"] == "queued"


def test_control_plane_persists_injected_delivery_outcome_and_evidence(tmp_path):
    path = tmp_path / "delivery.db"
    control = ControlPlane(EvidenceStore(path))
    incident = control.open_incident(
        severity="S3", title="delivery fixture", lane="orca", owner="orca")
    sent = []
    before_revision = control.state_revision

    outcomes = control.process_notifications(
        actor="orca",
        now=control.notifications.alerts()[0].created_at,
        transport=lambda **kwargs: sent.append(kwargs) or {"accepted": True},
    )

    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "delivered"
    assert control.state_revision == before_revision + 2
    assert sent[0]["idempotency_key"].startswith("sha256:")
    assert control.alert_outbox[0]["status"] == "delivered"
    assert control.evidence.list(limit=1)[0]["kind"] == "notification.delivery_attempted"

    restored = ControlPlane(EvidenceStore(path))
    assert restored.notifications.get(outcomes[0]["id"]).status is AlertStatus.DELIVERED
    assert restored.alert_outbox[0]["incident_id"] == incident.id


def test_control_plane_notification_processor_is_inert_without_due_work():
    control = ControlPlane()
    revision = control.state_revision
    assert control.process_notifications(
        actor="orca", now=1, transport=lambda **_: True) == []
    assert control.state_revision == revision
    with pytest.raises(PermissionError, match="process notifications"):
        control.process_notifications(
            actor="smith", now=1, transport=lambda **_: True)


def test_control_plane_transport_does_not_hold_global_mutation_lock():
    control = ControlPlane()
    control.open_incident(
        severity="S3", title="blocking delivery fixture", lane="orca", owner="orca")
    now = control.notifications.alerts()[0].created_at
    transport_started = threading.Event()
    release_transport = threading.Event()
    delivery_finished = threading.Event()
    probe_finished = threading.Event()
    failures = []

    def blocking_transport(**_):
        transport_started.set()
        if not release_transport.wait(5):
            raise RuntimeError("test transport timed out")
        return True

    def deliver():
        try:
            control.process_notifications(
                actor="orca", now=now, transport=blocking_transport)
        except BaseException as exc:
            failures.append(exc)
        finally:
            delivery_finished.set()

    def mutate_while_blocked():
        try:
            control.open_incident(
                severity="S1", title="concurrent local mutation",
                lane="orca", owner="orca")
            control.snapshot()
        except BaseException as exc:
            failures.append(exc)
        finally:
            probe_finished.set()

    delivery_thread = threading.Thread(target=deliver, daemon=True)
    delivery_thread.start()
    assert transport_started.wait(2)
    probe_thread = threading.Thread(target=mutate_while_blocked, daemon=True)
    probe_thread.start()
    try:
        assert probe_finished.wait(2), "provider transport held the control-plane lock"
    finally:
        release_transport.set()
    assert delivery_finished.wait(2)
    delivery_thread.join(timeout=1)
    probe_thread.join(timeout=1)
    assert failures == []
    assert control.notifications.alerts()[0].status is AlertStatus.DELIVERED


def test_control_plane_processes_a_bounded_notification_batch():
    control = ControlPlane()
    for number in range(3):
        control.open_incident(
            severity="S2", title=f"batch fixture {number}",
            lane="orca", owner="orca")
    now = max(alert.created_at for alert in control.notifications.alerts())
    calls = []

    first = control.process_notifications(
        actor="orca", now=now,
        transport=lambda **kwargs: calls.append(kwargs) or True,
        max_batch=2,
    )
    assert len(first) == len(calls) == 2
    assert sum(
        alert.status is AlertStatus.QUEUED
        for alert in control.notifications.alerts()
    ) == 1

    second = control.process_notifications(
        actor="orca", now=now,
        transport=lambda **kwargs: calls.append(kwargs) or True,
        max_batch=2,
    )
    assert len(second) == 1
    assert len(calls) == 3
    assert all(
        alert.status is AlertStatus.DELIVERED
        for alert in control.notifications.alerts()
    )


def test_expired_notification_claim_is_recovered_after_restart(tmp_path):
    path = tmp_path / "claimed-delivery.db"
    control = ControlPlane(EvidenceStore(path))
    control.open_incident(
        severity="S2", title="claim recovery fixture", lane="orca", owner="orca")
    queued = control.notifications.alerts()[0]
    claimed = control._claim_notification_batch(
        actor="orca",
        now=queued.created_at,
        claim_id="crashed-worker",
        max_batch=1,
        lease_seconds=5,
    )
    assert len(claimed) == 1
    expected_key = claimed[0].idempotency_key
    control.evidence.db.close()

    restored = ControlPlane(EvidenceStore(path))
    calls = []
    assert restored.process_notifications(
        actor="orca",
        now=queued.created_at + 4,
        transport=lambda **kwargs: calls.append(kwargs) or True,
    ) == []
    assert calls == []

    delivered = restored.process_notifications(
        actor="orca",
        now=queued.created_at + 5,
        transport=lambda **kwargs: calls.append(kwargs) or True,
    )
    assert delivered[0]["status"] == "retry"
    assert delivered[0]["last_error"] == "delivery_unconfirmed"
    assert calls == []

    delivered = restored.process_notifications(
        actor="orca",
        now=queued.created_at + 35,
        clock=lambda: queued.created_at + 35.5,
        transport=lambda **kwargs: calls.append(kwargs) or True,
    )
    assert delivered[0]["status"] == "delivered"
    assert calls[0]["idempotency_key"] == expected_key


def test_reservation_consumes_attempt_before_transport_and_expiry_is_bounded():
    outbox = NotificationOutbox(retry_schedule=(0,))
    outbox.enqueue(alert_id="alert-1", payload={"title": "crash"}, now=100)

    first = outbox.claim_due(
        now=100, claim_id="worker-1", limit=1, lease_seconds=5)
    assert first.claimed[0].status is AlertStatus.IN_FLIGHT
    assert first.claimed[0].attempts == 1

    restored = NotificationOutbox.from_json(outbox.to_json())
    first_expiry = restored.claim_due(
        now=105, claim_id="reaper-1", limit=1, lease_seconds=5)
    assert first_expiry.expired[0].status is AlertStatus.RETRY
    assert first_expiry.expired[0].attempts == 1
    assert first_expiry.expired[0].last_error == "delivery_unconfirmed"

    second = restored.claim_due(
        now=105, claim_id="worker-2", limit=1, lease_seconds=5)
    assert second.claimed[0].attempts == 2
    restarted_again = NotificationOutbox.from_json(restored.to_json())
    second_expiry = restarted_again.claim_due(
        now=110, claim_id="reaper-2", limit=1, lease_seconds=5)
    assert second_expiry.expired[0].status is AlertStatus.DEAD_LETTER
    assert second_expiry.expired[0].attempts == restarted_again.max_attempts == 2

    assert restarted_again.claim_due(
        now=1_000, claim_id="worker-3", limit=1).claimed == ()


def test_finish_rejects_an_expired_reservation():
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-1", payload={"title": "late"}, now=1)
    batch = outbox.claim_due(
        now=1, claim_id="worker", limit=1, lease_seconds=5)

    with pytest.raises(NotificationConflict, match="expired"):
        outbox.finish_claim(
            batch.claimed[0].id,
            claim_id="worker",
            outcome=outbox.delivery_outcome(
                batch.claimed[0], transport=lambda **_: True),
            now=6,
        )
    assert outbox.get("alert-1").status is AlertStatus.IN_FLIGHT


def test_v2_leased_state_migrates_and_consumes_the_reserved_attempt():
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-1", payload={"title": "legacy lease"}, now=1)
    claimed = outbox.claim_due(
        now=2, claim_id="legacy-worker", limit=1, lease_seconds=10).claimed[0]
    state = outbox.to_dict()
    state["schema_version"] = 2
    row = state["alerts"][0]
    row["status"] = "queued"
    row["attempts"] = 0
    row.pop("claim_started_at")

    restored = NotificationOutbox.from_dict(state)
    migrated = restored.get(claimed.id)
    assert migrated.status is AlertStatus.IN_FLIGHT
    assert migrated.attempts == 1
    assert migrated.claim_started_at == 1


def test_valid_v2_retry_lease_migrates_without_erasing_prior_invariants():
    outbox = NotificationOutbox(retry_schedule=(5, 30))
    outbox.enqueue(alert_id="alert-1", payload={}, now=1)
    outbox.attempt(
        "alert-1", now=1, transport=lambda **_: False, clock=lambda: 1)
    claimed = outbox.claim_due(
        now=6, claim_id="legacy-retry-worker", limit=1,
        lease_seconds=10,
    ).claimed[0]
    state = outbox.to_dict()
    state["schema_version"] = 2
    row = state["alerts"][0]
    row["status"] = "retry"
    row["attempts"] = 1
    row["last_error"] = "transport_rejected"
    row.pop("claim_started_at")

    migrated = NotificationOutbox.from_dict(state).get(claimed.id)

    assert migrated.status is AlertStatus.IN_FLIGHT
    assert migrated.attempts == 2
    assert migrated.last_error is None
    assert migrated.claim_started_at == 6


@pytest.mark.parametrize(
    ("status", "attempts", "last_error"),
    [
        ("queued", 1, None),
        ("queued", 0, "transport_exception"),
        ("retry", 0, "transport_exception"),
        ("retry", 1, None),
    ],
)
def test_v2_migration_rejects_impossible_leased_source_state(
    status, attempts, last_error,
):
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-1", payload={}, now=1)
    outbox.claim_due(
        now=2, claim_id="legacy-worker", limit=1, lease_seconds=10)
    state = outbox.to_dict()
    state["schema_version"] = 2
    row = state["alerts"][0]
    row["status"] = status
    row["attempts"] = attempts
    row["last_error"] = last_error
    row.pop("claim_started_at")

    with pytest.raises(ValueError, match="legacy alert lease is inconsistent"):
        NotificationOutbox.from_dict(state)


def test_v2_migration_rejects_an_unprovably_long_legacy_lease():
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-1", payload={}, now=1)
    outbox.claim_due(
        now=2, claim_id="legacy-worker", limit=1, lease_seconds=10)
    state = outbox.to_dict()
    state["schema_version"] = 2
    row = state["alerts"][0]
    row["status"] = "queued"
    row["attempts"] = 0
    row["claim_until"] = 1 + NotificationOutbox.MAX_LEASE_SECONDS + 1
    row.pop("claim_started_at")

    with pytest.raises(ValueError, match="legacy alert lease is inconsistent"):
        NotificationOutbox.from_dict(state)


def test_v3_restore_rejects_a_lease_longer_than_the_runtime_cap():
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-1", payload={}, now=1)
    outbox.claim_due(
        now=2, claim_id="worker", limit=1, lease_seconds=10)
    state = outbox.to_dict()
    row = state["alerts"][0]
    row["claim_until"] = (
        row["claim_started_at"] + NotificationOutbox.MAX_LEASE_SECONDS + 1)

    with pytest.raises(ValueError, match="delivery lease is inconsistent"):
        NotificationOutbox.from_dict(state)


def test_serialized_alert_chronology_fails_closed():
    queued = NotificationOutbox()
    queued.enqueue(alert_id="queued", payload={}, now=100)
    queued_state = queued.to_dict()
    queued_state["alerts"][0]["next_attempt_at"] = 99
    with pytest.raises(ValueError, match="chronology is inconsistent"):
        NotificationOutbox.from_dict(queued_state)

    delivered = NotificationOutbox()
    delivered.enqueue(alert_id="delivered", payload={}, now=100)
    delivered.attempt(
        "delivered", now=100, transport=lambda **_: True, clock=lambda: 100)
    delivered_state = delivered.to_dict()
    delivered_state["alerts"][0]["delivered_at"] = 99
    with pytest.raises(ValueError, match="chronology is inconsistent"):
        NotificationOutbox.from_dict(delivered_state)


@pytest.mark.parametrize("claim_time", [1e19, 1e308])
def test_claim_deadline_must_be_representable_and_leave_state_unchanged(
    claim_time,
):
    outbox = NotificationOutbox()
    outbox.enqueue(alert_id="alert-1", payload={}, now=claim_time)
    before = outbox.to_json()

    with pytest.raises(ValueError, match="representable finite range"):
        outbox.claim_due(now=claim_time, claim_id="worker", limit=1)

    assert outbox.to_json() == before


def test_retry_deadline_overflow_fails_before_returning_invalid_state():
    alert = Alert(
        id="alert-1",
        idempotency_key="sha256:" + "0" * 64,
        payload={},
        status=AlertStatus.IN_FLIGHT,
        attempts=1,
        created_at=0,
        next_attempt_at=0,
        claim_id="worker",
        claim_started_at=0,
        claim_until=float.fromhex("0x1.fffffffffffffp+1023"),
    )

    with pytest.raises(ValueError, match="representable finite range"):
        transition_alert(
            alert,
            outcome=DeliveryOutcome.TRANSPORT_REJECTED,
            now=1e308,
            retry_schedule=(float.fromhex("0x1.fffffffffffffp+1023"),),
        )


def test_control_plane_never_preleases_later_batch_items():
    control = ControlPlane()
    for number in range(2):
        control.open_incident(
            severity="S2", title=f"sequential lease {number}",
            lane="orca", owner="orca")
    now = max(alert.created_at for alert in control.notifications.alerts())
    observed = []

    def inspect_transport(**_):
        observed.append(tuple(alert.status for alert in control.notifications.alerts()))
        return True

    control.process_notifications(
        actor="orca", now=now, clock=lambda: now + 0.1,
        transport=inspect_transport, max_batch=2)

    assert observed[0].count(AlertStatus.IN_FLIGHT) == 1
    assert observed[0].count(AlertStatus.QUEUED) == 1


def test_control_plane_uses_completion_clock_for_delivery_and_backoff():
    control = ControlPlane()
    control.open_incident(
        severity="S3", title="completion time", lane="orca", owner="orca")
    started = control.notifications.alerts()[0].created_at

    result = control.process_notifications(
        actor="orca", now=started, clock=lambda: started + 10,
        transport=lambda **_: False, max_batch=1, lease_seconds=30)

    assert result[0]["status"] == "retry"
    assert result[0]["next_attempt_at"] == started + 40


def test_crash_after_reservation_persists_attempt_and_audit_evidence(tmp_path):
    class SimulatedCrash(BaseException):
        pass

    path = tmp_path / "reservation-crash.db"
    control = ControlPlane(EvidenceStore(path))
    control.open_incident(
        severity="S2", title="reserved crash", lane="orca", owner="orca")
    started = control.notifications.alerts()[0].created_at

    with pytest.raises(SimulatedCrash):
        control.process_notifications(
            actor="orca", now=started, max_batch=1,
            transport=lambda **_: (_ for _ in ()).throw(SimulatedCrash()),
        )
    control.evidence.db.close()

    restored = ControlPlane(EvidenceStore(path))
    reserved = restored.notifications.alerts()[0]
    assert reserved.status is AlertStatus.IN_FLIGHT
    assert reserved.attempts == 1
    assert any(
        event["kind"] == "notification.delivery_reserved"
        for event in restored.evidence.list(limit=20)
    )


def test_lease_conflict_is_reported_and_later_items_continue():
    control = ControlPlane()
    for number in range(2):
        control.open_incident(
            severity="S2", title=f"lease conflict {number}",
            lane="orca", owner="orca")
    started = max(alert.created_at for alert in control.notifications.alerts())
    finish_times = iter((started + 5, started + 5.5))
    calls = []

    results = control.process_notifications(
        actor="orca", now=started, lease_seconds=5, max_batch=3,
        clock=lambda: next(finish_times),
        transport=lambda **kwargs: calls.append(kwargs) or True,
    )

    assert results[0]["delivery_result"] == "lease_lost"
    assert results[1]["last_error"] == "delivery_unconfirmed"
    assert results[2]["status"] == "delivered"
    assert len(calls) == 2
