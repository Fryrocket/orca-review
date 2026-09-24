"""Deterministic alert delivery state with no built-in network transport.

The module deliberately knows nothing about Slack, webhooks, or any other
provider.  Callers inject a transport at the point where a due alert is
attempted.  All persisted payloads are redacted before they enter the outbox,
and transport failures are represented by fixed error codes rather than
exception text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
import json
import math
import threading
import time
from typing import Any
from uuid import uuid4

from .security import redact


class AlertStatus(StrEnum):
    """The complete set of persisted alert-delivery states."""

    QUEUED = "queued"
    RETRY = "retry"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"


class DeliveryOutcome(StrEnum):
    """Sanitized outcomes consumed by the pure transition function."""

    DELIVERED = "delivered"
    TRANSPORT_REJECTED = "transport_rejected"
    TRANSPORT_EXCEPTION = "transport_exception"
    DELIVERY_UNCONFIRMED = "delivery_unconfirmed"


class NotificationConflict(RuntimeError):
    """Notification content or delivery-lease ownership conflicted."""


@dataclass(frozen=True)
class Alert:
    """A restart-safe snapshot of one alert's delivery state."""

    id: str
    idempotency_key: str
    payload: dict[str, Any]
    status: AlertStatus
    attempts: int
    created_at: float
    next_attempt_at: float | None
    delivered_at: float | None = None
    last_error: str | None = None
    claim_id: str | None = None
    claim_started_at: float | None = None
    claim_until: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible state without exposing mutable internals."""

        return {
            "id": self.id,
            "idempotency_key": self.idempotency_key,
            "payload": _json_copy(self.payload),
            "status": self.status.value,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "next_attempt_at": self.next_attempt_at,
            "delivered_at": self.delivered_at,
            "last_error": self.last_error,
            "claim_id": self.claim_id,
            "claim_started_at": self.claim_started_at,
            "claim_until": self.claim_until,
        }


@dataclass(frozen=True)
class NotificationClaimBatch:
    """Bounded durable transitions made while looking for due work."""

    claimed: tuple[Alert, ...] = ()
    expired: tuple[Alert, ...] = ()

    # Preserve the old private-helper ergonomics for callers that only need
    # newly claimed alerts while exposing expired reservations explicitly.
    def __len__(self) -> int:
        return len(self.claimed)

    def __getitem__(self, index: int) -> Alert:
        return self.claimed[index]


@dataclass(frozen=True)
class NotificationLeaseLoss:
    """A standalone batch item whose provider result lost its lease race.

    Successful and expired standalone results remain ``Alert`` instances for
    compatibility.  A conflict previously raised and aborted the batch, so it
    can use this explicit result without changing successful callers.
    """

    alert: Alert
    delivery_result: str = "lease_lost"

    def to_dict(self) -> dict[str, Any]:
        return {**self.alert.to_dict(), "delivery_result": self.delivery_result}


AlertTransport = Callable[..., object]
CompletionClock = Callable[[], float]


def transition_alert(
    alert: Alert,
    *,
    outcome: DeliveryOutcome,
    now: float,
    retry_schedule: tuple[float, ...],
) -> Alert:
    """Purely finalize one reserved delivery attempt.

    The attempt counter is consumed durably when the reservation is created,
    before provider code can run. ``retry_schedule[n]`` is the delay applied
    after failed attempt ``n + 1``.
    """

    attempt_time = _finite_time(now, "attempt time")
    schedule = _validated_schedule(retry_schedule)
    if (alert.status is not AlertStatus.IN_FLIGHT
            or alert.claim_id is None
            or alert.claim_started_at is None
            or alert.claim_until is None):
        raise ValueError("alert does not have an active delivery reservation")
    if attempt_time < alert.claim_started_at or attempt_time >= alert.claim_until:
        raise NotificationConflict("notification delivery lease has expired")

    attempts = alert.attempts
    max_attempts = len(schedule) + 1
    if not 1 <= attempts <= max_attempts:
        raise ValueError("alert attempt count is invalid")

    if outcome is DeliveryOutcome.DELIVERED:
        return replace(
            alert,
            status=AlertStatus.DELIVERED,
            attempts=attempts,
            next_attempt_at=None,
            delivered_at=attempt_time,
            last_error=None,
            claim_id=None,
            claim_started_at=None,
            claim_until=None,
        )

    if outcome not in {
        DeliveryOutcome.TRANSPORT_REJECTED,
        DeliveryOutcome.TRANSPORT_EXCEPTION,
    }:
        raise ValueError("unknown delivery outcome")
    error_code = outcome.value
    if attempts >= max_attempts:
        return replace(
            alert,
            status=AlertStatus.DEAD_LETTER,
            attempts=attempts,
            next_attempt_at=None,
            last_error=error_code,
            claim_id=None,
            claim_started_at=None,
            claim_until=None,
        )

    return replace(
        alert,
        status=AlertStatus.RETRY,
        attempts=attempts,
        next_attempt_at=_checked_time_add(
            attempt_time,
            schedule[attempts - 1],
            "next notification attempt time",
        ),
        last_error=error_code,
        claim_id=None,
        claim_started_at=None,
        claim_until=None,
    )


class NotificationOutbox:
    """An in-memory outbox whose full state can be serialized and restored.

    State changes happen only through deterministic reducers.  The sole side
    effect is an explicitly injected transport callable.  A transport receives
    keyword arguments ``payload`` and ``idempotency_key``; only ``True`` or an
    explicit ``{"accepted": true}`` acknowledgement marks delivery successful.
    """

    SCHEMA_VERSION = 3
    DEFAULT_MAX_ALERTS = 10_000
    MAX_PAYLOAD_BYTES = 64_000
    DEFAULT_BATCH_SIZE = 32
    MAX_BATCH_SIZE = 100
    DEFAULT_LEASE_SECONDS = 300.0
    MAX_LEASE_SECONDS = 3_600.0

    def __init__(
        self,
        *,
        retry_schedule: tuple[float, ...] = (30.0, 300.0, 1800.0),
        max_alerts: int = DEFAULT_MAX_ALERTS,
    ):
        self.retry_schedule = _validated_schedule(retry_schedule)
        if type(max_alerts) is not int or not 1 <= max_alerts <= self.DEFAULT_MAX_ALERTS:
            raise ValueError("notification alert limit is invalid")
        self.max_alerts = max_alerts
        self._alerts: dict[str, Alert] = {}
        self._by_idempotency_key: dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def max_attempts(self) -> int:
        return len(self.retry_schedule) + 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._alerts)

    def alerts(self) -> tuple[Alert, ...]:
        """Return stable snapshots ordered by alert identifier."""

        with self._lock:
            return tuple(
                self._copy_alert(self._alerts[key]) for key in sorted(self._alerts))

    def get(self, alert_id: str) -> Alert:
        with self._lock:
            return self._copy_alert(self._alerts[alert_id])

    def enqueue(
        self,
        *,
        alert_id: str,
        payload: Mapping[str, Any],
        now: float,
        idempotency_key: str | None = None,
    ) -> Alert:
        """Queue a redacted alert, suppressing repeats by idempotency key.

        Raw idempotency material is never persisted or sent to the transport;
        a namespaced SHA-256 fingerprint is used instead.  When no separate key
        is supplied, ``alert_id`` is used as the source material.
        """

        safe_id = _validated_identifier(alert_id)
        created_at = _finite_time(now, "creation time")
        raw_key = idempotency_key if idempotency_key is not None else safe_id
        fingerprint = _fingerprint_idempotency_key(raw_key)

        safe_payload = _safe_payload(payload)
        with self._lock:
            duplicate_id = self._by_idempotency_key.get(fingerprint)
            if duplicate_id is not None:
                duplicate = self._alerts[duplicate_id]
                if duplicate.payload != safe_payload:
                    raise NotificationConflict(
                        "notification idempotency key was reused for different content")
                return self._copy_alert(duplicate)
            if safe_id in self._alerts:
                raise ValueError(
                    "alert identifier already exists with another idempotency key")
            if len(self._alerts) >= self.max_alerts:
                raise ValueError("notification alert limit reached")

            alert = Alert(
                id=safe_id,
                idempotency_key=fingerprint,
                payload=safe_payload,
                status=AlertStatus.QUEUED,
                attempts=0,
                created_at=created_at,
                next_attempt_at=created_at,
            )
            self._alerts[safe_id] = alert
            self._by_idempotency_key[fingerprint] = safe_id
            return self._copy_alert(alert)

    def attempt(
        self,
        alert_id: str,
        *,
        now: float,
        transport: AlertTransport,
        clock: CompletionClock | None = None,
    ) -> Alert:
        """Attempt one due alert with an injected transport.

        Transport exception types, messages, return values, and tracebacks are
        never saved.  This prevents credentials embedded in provider errors
        from entering serialized outbox state.  The completion clock is sampled
        only after provider code returns so lease expiry and retry timing use the
        completion time rather than the reservation time.
        """

        attempt_time = _finite_time(now, "attempt time")
        if not callable(transport):
            raise TypeError("transport must be callable")
        finish_clock = time.time if clock is None else clock
        if not callable(finish_clock):
            raise TypeError("notification clock must be callable")
        with self._lock:
            before = self._copy_alert(self._alerts[alert_id])
        if before.status in {AlertStatus.DELIVERED, AlertStatus.DEAD_LETTER}:
            return before
        claim_id = f"attempt-{uuid4().hex}"
        batch = self.claim_due(
            now=attempt_time,
            claim_id=claim_id,
            limit=1,
            only_alert_id=alert_id,
        )
        claimed = next(
            (item for item in batch.claimed if item.id == alert_id), None)
        if claimed is None:
            return self.get(alert_id)
        outcome = self.delivery_outcome(claimed, transport=transport)
        completion_time = _finite_time(
            finish_clock(), "notification completion time")
        return self.finish_claim(
            alert_id, claim_id=claim_id, outcome=outcome, now=completion_time)

    def claim_due(
        self,
        *,
        now: float,
        claim_id: str,
        limit: int = DEFAULT_BATCH_SIZE,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        only_alert_id: str | None = None,
    ) -> NotificationClaimBatch:
        """Resolve expired attempts, then reserve a bounded due batch.

        Reserving consumes an attempt before transport code can run. An
        expired reservation is never silently retried: it becomes an explicit
        unconfirmed failure with normal backoff or a dead-letter transition.
        Expired and new transitions together never exceed ``limit``.
        """

        claim_time = _finite_time(now, "claim time")
        safe_claim_id = _validated_identifier(claim_id)
        safe_alert_id = (
            None if only_alert_id is None else _validated_identifier(only_alert_id))
        if type(limit) is not int or not 1 <= limit <= self.MAX_BATCH_SIZE:
            raise ValueError("notification batch limit is invalid")
        lease = _finite_time(lease_seconds, "notification lease")
        if not 1 <= lease <= self.MAX_LEASE_SECONDS:
            raise ValueError("notification lease is outside the allowed range")
        claim_until = _checked_time_add(
            claim_time, lease, "notification claim expiry")
        if claim_until - claim_time > self.MAX_LEASE_SECONDS:
            raise ValueError(
                "notification claim expiry is outside the representable finite range")

        with self._lock:
            expired_candidates = sorted(
                (
                    alert for alert in self._alerts.values()
                    if alert.status is AlertStatus.IN_FLIGHT
                    and (safe_alert_id is None or alert.id == safe_alert_id)
                    and alert.claim_until is not None
                    and alert.claim_until <= claim_time
                ),
                key=lambda alert: (alert.claim_until, alert.id),
            )[:limit]
            expired_ids = {alert.id for alert in expired_candidates}
            expired_updates: list[Alert] = []
            for alert in expired_candidates:
                if alert.attempts >= self.max_attempts:
                    updated = replace(
                        alert,
                        status=AlertStatus.DEAD_LETTER,
                        next_attempt_at=None,
                        last_error=DeliveryOutcome.DELIVERY_UNCONFIRMED.value,
                        claim_id=None,
                        claim_started_at=None,
                        claim_until=None,
                    )
                else:
                    updated = replace(
                        alert,
                        status=AlertStatus.RETRY,
                        next_attempt_at=_checked_time_add(
                            claim_time,
                            self.retry_schedule[alert.attempts - 1],
                            "next notification attempt time",
                        ),
                        last_error=DeliveryOutcome.DELIVERY_UNCONFIRMED.value,
                        claim_id=None,
                        claim_started_at=None,
                        claim_until=None,
                    )
                expired_updates.append(updated)

            remaining = limit - len(expired_updates)
            due = sorted(
                (
                    alert for alert in self._alerts.values()
                    if alert.status in {AlertStatus.QUEUED, AlertStatus.RETRY}
                    and (safe_alert_id is None or alert.id == safe_alert_id)
                    and alert.next_attempt_at is not None
                    and alert.next_attempt_at <= claim_time
                    and alert.id not in expired_ids
                ),
                key=lambda alert: (alert.next_attempt_at, alert.id),
            )[:remaining]
            claimed_updates: list[Alert] = []
            for alert in due:
                attempts = alert.attempts + 1
                if attempts > self.max_attempts:
                    raise ValueError("alert attempt limit already reached")
                updated = replace(
                    alert,
                    status=AlertStatus.IN_FLIGHT,
                    attempts=attempts,
                    last_error=None,
                    claim_id=safe_claim_id,
                    claim_started_at=claim_time,
                    claim_until=claim_until,
                )
                claimed_updates.append(updated)

            for updated in (*expired_updates, *claimed_updates):
                self._alerts[updated.id] = updated
            expired = tuple(self._copy_alert(alert) for alert in expired_updates)
            claimed = tuple(self._copy_alert(alert) for alert in claimed_updates)
            return NotificationClaimBatch(
                claimed=claimed, expired=expired)

    def finish_claim(
        self,
        alert_id: str,
        *,
        claim_id: str,
        outcome: DeliveryOutcome,
        now: float,
    ) -> Alert:
        """Commit one leased delivery outcome if the caller still owns it."""

        attempt_time = _finite_time(now, "attempt time")
        safe_claim_id = _validated_identifier(claim_id)
        with self._lock:
            alert = self._alerts[alert_id]
            if (alert.status is not AlertStatus.IN_FLIGHT
                    or alert.claim_id != safe_claim_id
                    or alert.claim_started_at is None
                    or alert.claim_until is None):
                raise NotificationConflict("notification delivery lease is no longer owned")
            updated = transition_alert(
                alert,
                outcome=outcome,
                now=attempt_time,
                retry_schedule=self.retry_schedule,
            )
            self._alerts[alert_id] = updated
            return self._copy_alert(updated)

    @staticmethod
    def delivery_outcome(alert: Alert, *, transport: AlertTransport) -> DeliveryOutcome:
        """Call an injected transport without holding an outbox lock."""

        if not callable(transport):
            raise TypeError("transport must be callable")
        try:
            result = transport(
                payload=_json_copy(alert.payload),
                idempotency_key=alert.idempotency_key,
            )
            accepted = result is True or (
                isinstance(result, Mapping)
                and result.get("accepted") is True
                and result.get("rejected") is not True
            )
        except Exception:
            return DeliveryOutcome.TRANSPORT_EXCEPTION
        return (
            DeliveryOutcome.DELIVERED
            if accepted else DeliveryOutcome.TRANSPORT_REJECTED
        )

    def process_due(
        self,
        *,
        now: float,
        transport: AlertTransport,
        limit: int = DEFAULT_BATCH_SIZE,
        clock: CompletionClock | None = None,
    ) -> tuple[Alert | NotificationLeaseLoss, ...]:
        """Attempt one bounded batch without holding a lock during delivery.

        Every provider call gets its own completion timestamp.  A per-item
        lease loss is returned explicitly and does not prevent later items from
        being processed; unrelated validation and programming errors still
        propagate.
        """

        process_time = _finite_time(now, "process time")
        if not callable(transport):
            raise TypeError("transport must be callable")
        if type(limit) is not int or not 1 <= limit <= self.MAX_BATCH_SIZE:
            raise ValueError("notification batch limit is invalid")
        finish_clock = time.time if clock is None else clock
        if not callable(finish_clock):
            raise TypeError("notification clock must be callable")
        completed: list[Alert | NotificationLeaseLoss] = []
        for _ in range(limit):
            claim_id = f"batch-{uuid4().hex}"
            batch = self.claim_due(
                now=process_time,
                claim_id=claim_id,
                limit=1,
            )
            completed.extend(batch.expired)
            if not batch.claimed:
                if not batch.expired:
                    break
                continue
            alert = batch.claimed[0]
            outcome = self.delivery_outcome(alert, transport=transport)
            completion_time = _finite_time(
                finish_clock(), "notification completion time")
            try:
                finalized = self.finish_claim(
                    alert.id,
                    claim_id=claim_id,
                    outcome=outcome,
                    now=completion_time,
                )
            except NotificationConflict:
                completed.append(NotificationLeaseLoss(self.get(alert.id)))
            else:
                completed.append(finalized)
            process_time = completion_time
        return tuple(completed)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": self.SCHEMA_VERSION,
                "retry_schedule": list(self.retry_schedule),
                "max_alerts": self.max_alerts,
                "alerts": [
                    self._alerts[key].to_dict() for key in sorted(self._alerts)],
            }

    def to_json(self) -> str:
        """Serialize canonically for file or database persistence."""

        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, state: Mapping[str, Any]) -> NotificationOutbox:
        if not isinstance(state, Mapping):
            raise ValueError("notification state must be an object")
        schema_version = state.get("schema_version")
        if (type(schema_version) is not int
                or schema_version not in {1, 2, cls.SCHEMA_VERSION}):
            raise ValueError("unsupported notification state schema")
        schedule_value = state.get("retry_schedule")
        if not isinstance(schedule_value, (list, tuple)):
            raise ValueError("notification retry schedule is invalid")
        outbox = cls(
            retry_schedule=tuple(schedule_value),
            max_alerts=state.get("max_alerts", cls.DEFAULT_MAX_ALERTS),
        )
        rows = state.get("alerts")
        if not isinstance(rows, list):
            raise ValueError("notification alert state is invalid")
        if len(rows) > outbox.max_alerts:
            raise ValueError("notification alert state exceeds the configured limit")
        for row in rows:
            alert = _alert_from_dict(
                row, outbox.max_attempts,
                schema_version=schema_version,
            )
            if alert.id in outbox._alerts or alert.idempotency_key in outbox._by_idempotency_key:
                raise ValueError("duplicate alert state")
            outbox._alerts[alert.id] = alert
            outbox._by_idempotency_key[alert.idempotency_key] = alert.id
        return outbox

    @classmethod
    def from_json(cls, value: str) -> NotificationOutbox:
        try:
            state = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("notification state is not valid JSON") from exc
        if not isinstance(state, dict):
            raise ValueError("notification state must be an object")
        return cls.from_dict(state)

    @staticmethod
    def _copy_alert(alert: Alert) -> Alert:
        return replace(alert, payload=_json_copy(alert.payload))


def _fingerprint_idempotency_key(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4_000:
        raise ValueError("idempotency key must be a non-empty bounded string")
    digest = sha256(b"orca-alert-idempotency-v1\x00" + value.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _validated_identifier(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 240:
        raise ValueError("alert identifier must be a non-empty bounded string")
    if any(ord(character) < 32 for character in value):
        raise ValueError("alert identifier contains control characters")
    return value


def _finite_time(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _checked_time_add(value: float, delay: float, label: str) -> float:
    """Add validated times without creating infinity or losing progress."""

    result = value + delay
    if not math.isfinite(result) or (delay > 0 and result <= value):
        raise ValueError(f"{label} is outside the representable finite range")
    return result


def _validated_schedule(value: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError("retry schedule must be an explicit sequence")
    if len(value) > 64:
        raise ValueError("retry schedule exceeds the size limit")
    schedule: list[float] = []
    for delay in value:
        if (isinstance(delay, bool) or not isinstance(delay, (int, float))
                or not math.isfinite(delay) or delay < 0):
            raise ValueError("retry delays must be finite and non-negative")
        schedule.append(float(delay))
    return tuple(schedule)


def _safe_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("alert payload must be an object")
    try:
        encoded = json.dumps(
            redact(dict(payload)), sort_keys=True, ensure_ascii=True,
            allow_nan=False,
        )
    except Exception:
        # Custom mappings and cyclic containers may raise arbitrary exceptions;
        # provider detail must not escape through exception context.
        encoded = None
    if encoded is None:
        raise ValueError("alert payload must be JSON-compatible") from None
    if len(encoded.encode("utf-8")) > NotificationOutbox.MAX_PAYLOAD_BYTES:
        raise ValueError("alert payload exceeds the size limit")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError("alert payload must be an object")
    return decoded


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(
        value, sort_keys=True, ensure_ascii=True, allow_nan=False))


def _alert_from_dict(
    value: Any,
    max_attempts: int,
    *,
    schema_version: int,
) -> Alert:
    if not isinstance(value, Mapping):
        raise ValueError("serialized alert must be an object")
    try:
        alert_id = _validated_identifier(value["id"])
        key = value["idempotency_key"]
        status = AlertStatus(value["status"])
        attempts = value["attempts"]
        created_at = _finite_time(value["created_at"], "creation time")
        next_value = value.get("next_attempt_at")
        delivered_value = value.get("delivered_at")
        last_error = value.get("last_error")
        claim_id = value.get("claim_id") if schema_version >= 2 else None
        claim_value = value.get("claim_until") if schema_version >= 2 else None
        claim_started_value = (
            value.get("claim_started_at") if schema_version >= 3 else None)
        safe_payload = _safe_payload(value["payload"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("serialized alert is invalid") from exc

    if (not isinstance(key, str) or len(key) != 71 or not key.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in key[7:])):
        raise ValueError("serialized alert idempotency key is invalid")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 0 <= attempts <= max_attempts:
        raise ValueError("serialized alert attempt count is invalid")
    next_attempt_at = None if next_value is None else _finite_time(next_value, "next attempt time")
    delivered_at = None if delivered_value is None else _finite_time(delivered_value, "delivery time")
    claim_until = None if claim_value is None else _finite_time(claim_value, "claim expiry")
    claim_started_at = (
        None if claim_started_value is None
        else _finite_time(claim_started_value, "claim start"))
    if last_error not in {None, DeliveryOutcome.TRANSPORT_REJECTED.value,
                          DeliveryOutcome.TRANSPORT_EXCEPTION.value,
                          DeliveryOutcome.DELIVERY_UNCONFIRMED.value}:
        raise ValueError("serialized alert error code is invalid")
    if next_attempt_at is not None and next_attempt_at < created_at:
        raise ValueError("serialized alert chronology is inconsistent")
    if delivered_at is not None and delivered_at < created_at:
        raise ValueError("serialized alert chronology is inconsistent")

    # Schema v2 persisted leases but consumed attempts only after provider
    # return. Promote a leased v2 row to an in-flight v3 reservation and
    # conservatively consume that attempt during restoration. Validate the
    # complete source state first so migration cannot legitimize corruption.
    if schema_version == 2 and claim_id is not None and claim_until is not None:
        queued_source = (
            status is AlertStatus.QUEUED
            and attempts == 0
            and last_error is None
        )
        retry_source = (
            status is AlertStatus.RETRY
            and 0 < attempts < max_attempts
            and last_error is not None
        )
        if (not (queued_source or retry_source)
                or next_attempt_at is None
                or delivered_at is not None):
            raise ValueError("serialized legacy alert lease is inconsistent")
        claim_started_at = max(created_at, next_attempt_at)
        lease_duration = claim_until - claim_started_at
        if (not math.isfinite(lease_duration)
                or not 0 < lease_duration <= NotificationOutbox.MAX_LEASE_SECONDS):
            raise ValueError("serialized legacy alert lease is inconsistent")
        status = AlertStatus.IN_FLIGHT
        attempts += 1
        last_error = None

    if ((claim_id is None) != (claim_until is None)
            or (claim_id is None) != (claim_started_at is None)):
        raise ValueError("serialized alert delivery lease is incomplete")
    if claim_id is not None:
        _validated_identifier(claim_id)
        if status is not AlertStatus.IN_FLIGHT:
            raise ValueError("only an in-flight alert may retain a delivery lease")
        if (claim_started_at is None or claim_until is None
                or claim_started_at < created_at
                or claim_started_at >= claim_until
                or next_attempt_at is None
                or next_attempt_at > claim_started_at):
            raise ValueError("serialized alert delivery lease is inconsistent")
        lease_duration = claim_until - claim_started_at
        if (not math.isfinite(lease_duration)
                or lease_duration > NotificationOutbox.MAX_LEASE_SECONDS):
            raise ValueError("serialized alert delivery lease is inconsistent")
    elif status is AlertStatus.IN_FLIGHT:
        raise ValueError("in-flight alert is missing its delivery lease")

    if status is AlertStatus.QUEUED:
        valid = attempts == 0 and next_attempt_at is not None and delivered_at is None and last_error is None
    elif status is AlertStatus.RETRY:
        valid = 0 < attempts < max_attempts and next_attempt_at is not None and delivered_at is None and last_error is not None
    elif status is AlertStatus.IN_FLIGHT:
        valid = 0 < attempts <= max_attempts and delivered_at is None and last_error is None
    elif status is AlertStatus.DELIVERED:
        valid = 0 < attempts <= max_attempts and next_attempt_at is None and delivered_at is not None and last_error is None
    else:
        valid = attempts == max_attempts and next_attempt_at is None and delivered_at is None and last_error is not None
    if not valid:
        raise ValueError("serialized alert state is inconsistent")

    return Alert(
        id=alert_id,
        idempotency_key=key,
        payload=safe_payload,
        status=status,
        attempts=attempts,
        created_at=created_at,
        next_attempt_at=next_attempt_at,
        delivered_at=delivered_at,
        last_error=last_error,
        claim_id=claim_id,
        claim_started_at=claim_started_at,
        claim_until=claim_until,
    )
