from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
from threading import Lock
import time
from typing import Protocol

from .fleet import Heartbeat, sign_heartbeat
from .registry import NODES


_STATE_VERSION = 1
_MAX_STATE_BYTES = 16_384
_MAX_NONCE = (1 << 63) - 1
_MAX_DETAIL_CHARS = 4_000
_ALLOWED_STATES = frozenset({"healthy", "degraded", "offline"})
_REJECTED_ACK_STATUSES = frozenset({"denied", "error", "failed", "rejected"})
_TRANSPORT_EXCEPTION = object()


class HeartbeatStateError(RuntimeError):
    """The local nonce state cannot safely be read or advanced."""


class HeartbeatDeliveryError(RuntimeError):
    """A reserved heartbeat was not acknowledged by its transport."""


class HeartbeatTransport(Protocol):
    """Injected delivery boundary; implementations return an acknowledgement."""

    def __call__(self, heartbeat: Heartbeat, signature: str) -> object: ...


@dataclass(frozen=True)
class HeartbeatReceipt:
    heartbeat: Heartbeat
    signature: str
    acknowledgement: object


class HeartbeatAgent:
    """Build signed heartbeats while durably preventing local nonce reuse.

    This class deliberately has no network implementation.  Delivery is an
    injected callable, which keeps transport security and deployment choices
    outside the nonce/signing boundary.
    """

    def __init__(
        self,
        *,
        node_id: str,
        key: bytes,
        state_path: str | Path,
        transport: HeartbeatTransport,
        clock: Callable[[], int] | None = None,
    ) -> None:
        if not isinstance(node_id, str) or node_id not in NODES:
            raise ValueError("heartbeat agent requires a registered node")
        if type(key) is not bytes or len(key) < 32:
            raise ValueError("heartbeat key must contain at least 32 bytes")
        if not callable(transport):
            raise ValueError("heartbeat transport must be callable")
        if clock is not None and not callable(clock):
            raise ValueError("heartbeat clock must be callable")

        self.node_id = node_id
        self._key = bytes(key)
        self._state_path = Path(state_path)
        self._lock_path = self._state_path.with_name(f"{self._state_path.name}.lock")
        self._transport = transport
        self._clock = clock or (lambda: int(time.time()))
        self._lock = Lock()
        persisted = self._read_nonce()
        self._state_initialized = persisted is not None
        self._last_nonce = 0 if persisted is None else persisted

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(node_id={self.node_id!r}, "
            f"state_path={str(self._state_path)!r}, last_nonce={self._last_nonce})"
        )

    @property
    def last_nonce(self) -> int:
        return self._last_nonce

    def send(self, *, state: str, detail: str = "") -> HeartbeatReceipt:
        if not isinstance(state, str) or state not in _ALLOWED_STATES:
            raise ValueError("heartbeat state must be healthy, degraded, or offline")
        if not isinstance(detail, str):
            raise ValueError("heartbeat detail must be a string")
        if len(detail) > _MAX_DETAIL_CHARS:
            raise ValueError("heartbeat detail exceeds the size limit")

        timestamp = self._clock()
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError("heartbeat clock must return a non-negative integer")

        # Serialize both reservation and delivery.  The process lock prevents
        # two independently started agents from delivering nonce N+1 before
        # nonce N, which a receiver must correctly reject as a replay.
        with self._lock:
            with self._nonce_file_lock() as (lock_created, parent_descriptor):
                nonce = self._reserve_nonce(
                    lock_created=lock_created,
                    parent_descriptor=parent_descriptor,
                )
                heartbeat = Heartbeat(
                    node_id=self.node_id,
                    timestamp=timestamp,
                    nonce=nonce,
                    state=state,
                    detail=detail,
                )
                signature = sign_heartbeat(heartbeat, self._key)
                try:
                    acknowledgement = self._transport(heartbeat, signature)
                except Exception:
                    # Leave the exception scope before raising so provider
                    # exception types, messages, and tracebacks cannot leak via
                    # __cause__ or __context__.  The nonce remains consumed.
                    acknowledgement = _TRANSPORT_EXCEPTION
                if acknowledgement is _TRANSPORT_EXCEPTION:
                    raise HeartbeatDeliveryError("heartbeat delivery failed") from None
                if not self._is_positive_acknowledgement(acknowledgement):
                    raise HeartbeatDeliveryError(
                        "heartbeat delivery was not acknowledged") from None
                return HeartbeatReceipt(heartbeat, signature, acknowledgement)

    @staticmethod
    def _is_positive_acknowledgement(acknowledgement: object) -> bool:
        if acknowledgement is True:
            return True
        if not isinstance(acknowledgement, Mapping):
            return False
        try:
            if acknowledgement.get("accepted") is not True:
                return False
            if acknowledgement.get("rejected") is True:
                return False
            status = acknowledgement.get("status")
        except Exception:
            return False
        return not (
            isinstance(status, str)
            and status.strip().lower() in _REJECTED_ACK_STATUSES
        )

    def _reserve_nonce(self, *, lock_created: bool, parent_descriptor: int) -> int:
        persisted = self._read_nonce(parent_descriptor=parent_descriptor)
        if persisted is None:
            if self._state_initialized or not lock_created:
                raise HeartbeatStateError("heartbeat nonce state disappeared")
        else:
            if persisted < self._last_nonce:
                raise HeartbeatStateError("heartbeat nonce state moved backwards")
            self._last_nonce = persisted

        if self._last_nonce >= _MAX_NONCE:
            raise HeartbeatStateError("heartbeat nonce space is exhausted")
        candidate = self._last_nonce + 1
        try:
            self._write_nonce(candidate, parent_descriptor=parent_descriptor)
        except HeartbeatStateError:
            raise
        except OSError as exc:
            raise HeartbeatStateError("heartbeat nonce state could not be advanced") from exc
        self._last_nonce = candidate
        self._state_initialized = True
        return candidate

    @contextmanager
    def _validated_parent(self) -> Iterator[int]:
        """Open and validate the state parent without following its final link."""

        parent = self._state_path.parent
        try:
            metadata = parent.lstat()
        except OSError as exc:
            raise HeartbeatStateError(
                "heartbeat nonce state parent is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise HeartbeatStateError(
                "heartbeat nonce state parent must be a regular non-symlink directory")
        if os.name == "posix" and metadata.st_mode & 0o022:
            raise HeartbeatStateError(
                "heartbeat nonce state parent must not be group or world writable")
        if os.name == "posix" and metadata.st_uid != os.geteuid():
            raise HeartbeatStateError(
                "heartbeat nonce state parent must be owned by the current user")

        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = -1
        try:
            descriptor = os.open(parent, flags)
            opened = os.fstat(descriptor)
            if (not stat.S_ISDIR(opened.st_mode)
                    or (opened.st_dev, opened.st_ino)
                    != (metadata.st_dev, metadata.st_ino)):
                raise HeartbeatStateError(
                    "heartbeat nonce state parent changed while opening")
            if os.name == "posix" and opened.st_mode & 0o022:
                raise HeartbeatStateError(
                    "heartbeat nonce state parent must not be group or world writable")
            if os.name == "posix" and opened.st_uid != os.geteuid():
                raise HeartbeatStateError(
                    "heartbeat nonce state parent must be owned by the current user")
            yield descriptor
        except HeartbeatStateError:
            raise
        except OSError as exc:
            raise HeartbeatStateError(
                "heartbeat nonce state parent is unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @contextmanager
    def _nonce_file_lock(self) -> Iterator[tuple[bool, int]]:
        """Exclusively lock a validated, owner-only sibling lock file.

        The yielded boolean reports whether this call created the lock file.
        An existing lock without nonce state therefore fails closed instead of
        silently recreating nonce one after state loss.

        The parent directory is locked before publishing or opening the sibling
        lock file.  Without that outer lock, a second process can open a newly
        created-but-not-yet-flocked lock file and win the first flock, causing
        it to misclassify normal first-run initialization as lost state.
        """

        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        created = False
        descriptor = -1
        parent_locked = False
        with self._validated_parent() as parent_descriptor:
            try:
                fcntl.flock(parent_descriptor, fcntl.LOCK_EX)
                parent_locked = True
                try:
                    descriptor = os.open(
                        self._lock_path.name,
                        flags | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=parent_descriptor,
                    )
                    created = True
                except FileExistsError:
                    descriptor = os.open(
                        self._lock_path.name, flags, dir_fd=parent_descriptor)

                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode):
                    raise HeartbeatStateError(
                        "heartbeat nonce lock must be a regular non-symlink file")
                if os.name == "posix" and opened.st_mode & 0o077:
                    raise HeartbeatStateError(
                        "heartbeat nonce lock must not be accessible by group or others")
                if os.name == "posix" and opened.st_uid != os.geteuid():
                    raise HeartbeatStateError(
                        "heartbeat nonce lock must be owned by the current user")

                fcntl.flock(descriptor, fcntl.LOCK_EX)
                path_metadata = os.stat(
                    self._lock_path.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if (stat.S_ISLNK(path_metadata.st_mode)
                        or not stat.S_ISREG(path_metadata.st_mode)
                        or (path_metadata.st_dev, path_metadata.st_ino)
                        != (opened.st_dev, opened.st_ino)):
                    raise HeartbeatStateError(
                        "heartbeat nonce lock must be a regular non-symlink file")
                yield created, parent_descriptor
            except HeartbeatStateError:
                raise
            except OSError as exc:
                raise HeartbeatStateError("heartbeat nonce lock is unavailable") from exc
            finally:
                if descriptor >= 0:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    except OSError:
                        pass
                    os.close(descriptor)
                if parent_locked:
                    try:
                        fcntl.flock(parent_descriptor, fcntl.LOCK_UN)
                    except OSError:
                        pass

    def _read_nonce(self, *, parent_descriptor: int | None = None) -> int | None:
        if parent_descriptor is None:
            with self._validated_parent() as opened_parent:
                return self._read_nonce(parent_descriptor=opened_parent)

        try:
            metadata = os.stat(
                self._state_path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise HeartbeatStateError("heartbeat nonce state is unavailable") from exc

        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise HeartbeatStateError(
                "heartbeat nonce state must be a regular non-symlink file")
        if metadata.st_size <= 0 or metadata.st_size > _MAX_STATE_BYTES:
            raise HeartbeatStateError("heartbeat nonce state has an invalid size")
        if os.name == "posix" and metadata.st_mode & 0o077:
            raise HeartbeatStateError(
                "heartbeat nonce state must not be accessible by group or others")
        if os.name == "posix" and metadata.st_uid != os.geteuid():
            raise HeartbeatStateError(
                "heartbeat nonce state must be owned by the current user")

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(
                self._state_path.name, flags, dir_fd=parent_descriptor)
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                opened = os.fstat(handle.fileno())
                if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise HeartbeatStateError(
                        "heartbeat nonce state changed while opening")
                payload = json.load(handle)
        except HeartbeatStateError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HeartbeatStateError(
                "heartbeat nonce state must contain valid JSON") from exc

        if not isinstance(payload, dict) or set(payload) != {
            "version", "node_id", "last_nonce"
        }:
            raise HeartbeatStateError("heartbeat nonce state has an invalid schema")
        version = payload["version"]
        node_id = payload["node_id"]
        nonce = payload["last_nonce"]
        if type(version) is not int or version != _STATE_VERSION:
            raise HeartbeatStateError("heartbeat nonce state version is unsupported")
        if not isinstance(node_id, str) or node_id != self.node_id:
            raise HeartbeatStateError("heartbeat nonce state belongs to another node")
        if type(nonce) is not int or not 0 <= nonce <= _MAX_NONCE:
            raise HeartbeatStateError("heartbeat nonce state contains an invalid nonce")
        return nonce

    def _write_nonce(self, nonce: int, *, parent_descriptor: int) -> None:
        payload = json.dumps(
            {
                "version": _STATE_VERSION,
                "node_id": self.node_id,
                "last_nonce": nonce,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"

        descriptor = -1
        temporary_name: str | None = None
        try:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            for _ in range(128):
                candidate = f".{self._state_path.name}.{secrets.token_hex(16)}.tmp"
                try:
                    descriptor = os.open(
                        candidate, flags, 0o600, dir_fd=parent_descriptor)
                    temporary_name = candidate
                    break
                except FileExistsError:
                    continue
            if descriptor < 0 or temporary_name is None:
                raise HeartbeatStateError(
                    "heartbeat nonce temporary state could not be created")
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(
                temporary_name,
                self._state_path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_name = None
            os.fsync(parent_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=parent_descriptor)
                except FileNotFoundError:
                    pass
