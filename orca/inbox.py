"""Privacy-minimized, read-only email summary inbox for ORCA."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any

from .security import redact_text
from .communications import build_communications_snapshot


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$")
_CATEGORIES = frozenset({
    "order", "invoice", "lead", "support", "compliance", "vendor", "spam", "other",
})
_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})
_FIELDS = frozenset({
    "message_reference", "sender_display", "subject", "received_at",
    "project_or_customer", "category", "priority", "summary", "follow_up",
    "deadline", "draft_reply", "uncertainty",
})


class InboxStore:
    """Store only sanitized summaries and drafts, never raw mail or attachments."""

    def __init__(self, path: str | Path) -> None:
        self.lock = RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if str(path) != ":memory:":
            Path(path).chmod(0o600)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS inbox_messages (
                message_reference TEXT PRIMARY KEY,
                sender_display TEXT NOT NULL,
                subject TEXT NOT NULL,
                received_at TEXT NOT NULL,
                project_or_customer TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                summary TEXT NOT NULL,
                follow_up TEXT NOT NULL,
                deadline TEXT,
                draft_reply TEXT,
                uncertainty TEXT NOT NULL,
                handoff_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS inbox_imports (
                request_id TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                response TEXT NOT NULL,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    @staticmethod
    def _text(value: object, field: str, maximum: int, *, nullable: bool = False) -> str | None:
        if value is None and nullable:
            return None
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError(f"Inbox {field} is invalid")
        result = value.strip()
        if not result and not nullable:
            raise ValueError(f"Inbox {field} is invalid")
        if redact_text(result) != result:
            raise ValueError(f"Inbox {field} contains secret-shaped content")
        return result or None

    @classmethod
    def _message(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise ValueError("Inbox message has an invalid schema")
        reference = cls._text(value["message_reference"], "message reference", 160)
        if not _ID.fullmatch(reference):
            raise ValueError("Inbox message reference is invalid")
        category = cls._text(value["category"], "category", 24)
        priority = cls._text(value["priority"], "priority", 16)
        if category not in _CATEGORIES or priority not in _PRIORITIES:
            raise ValueError("Inbox category or priority is invalid")
        return {
            "message_reference": reference,
            "sender_display": cls._text(value["sender_display"], "sender", 160),
            "subject": cls._text(value["subject"], "subject", 300),
            "received_at": cls._text(value["received_at"], "received time", 64),
            "project_or_customer": cls._text(value["project_or_customer"], "association", 160),
            "category": category,
            "priority": priority,
            "summary": cls._text(value["summary"], "summary", 2_000),
            "follow_up": cls._text(value["follow_up"], "follow up", 1_000),
            "deadline": cls._text(value["deadline"], "deadline", 160, nullable=True),
            "draft_reply": cls._text(value["draft_reply"], "draft reply", 4_000, nullable=True),
            "uncertainty": cls._text(value["uncertainty"], "uncertainty", 1_000),
        }

    def import_packet(self, packet: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(packet, dict) or set(packet) != {"request_id", "handoff_id", "messages"}:
            raise ValueError("Inbox import has an invalid schema")
        request_id = self._text(packet["request_id"], "request ID", 100)
        handoff_id = self._text(packet["handoff_id"], "handoff ID", 100)
        if not _ID.fullmatch(request_id) or not handoff_id.startswith("muse-email-"):
            raise ValueError("Inbox import identity is invalid")
        values = packet["messages"]
        if not isinstance(values, list) or not 1 <= len(values) <= 200:
            raise ValueError("Inbox import must contain 1-200 messages")
        messages = [self._message(value) for value in values]
        refs = [value["message_reference"] for value in messages]
        if len(refs) != len(set(refs)):
            raise ValueError("Inbox import contains duplicate message references")
        encoded = json.dumps({"handoff_id": handoff_id, "messages": messages},
                             sort_keys=True, separators=(",", ":"), allow_nan=False)
        request_hash = sha256(encoded.encode()).hexdigest()
        with self.lock, self.db:
            previous = self.db.execute(
                "SELECT request_hash,response FROM inbox_imports WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise ValueError("Inbox request ID was reused with different content")
                return json.loads(previous["response"])
            for message in messages:
                payload_hash = sha256(json.dumps(
                    message, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                existing = self.db.execute(
                    "SELECT payload_hash FROM inbox_messages WHERE message_reference=?",
                    (message["message_reference"],),
                ).fetchone()
                if existing and existing["payload_hash"] != payload_hash:
                    raise ValueError("Inbox message changed under an existing reference")
                self.db.execute(
                    "INSERT OR IGNORE INTO inbox_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                    tuple(message[field] for field in (
                        "message_reference", "sender_display", "subject", "received_at",
                        "project_or_customer", "category", "priority", "summary",
                        "follow_up", "deadline", "draft_reply", "uncertainty",
                    )) + (handoff_id, payload_hash),
                )
            response = {"status": "imported", "imported": len(messages),
                        "total": self.db.execute("SELECT count(*) FROM inbox_messages").fetchone()[0],
                        "raw_bodies_stored": False, "attachments_stored": False,
                        "mailbox_mutations": 0, "messages_sent": 0}
            self.db.execute("INSERT INTO inbox_imports VALUES(?,?,?,CURRENT_TIMESTAMP)",
                            (request_id, request_hash, json.dumps(response, sort_keys=True)))
            return response

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            rows = [dict(row) for row in self.db.execute(
                "SELECT message_reference,sender_display,subject,received_at,"
                "project_or_customer,category,priority,summary,follow_up,deadline,"
                "draft_reply,uncertainty,handoff_id,imported_at FROM inbox_messages "
                "ORDER BY received_at DESC,message_reference LIMIT 500")]
        return {
            "status": "ready" if rows else "waiting_for_muse_email_packet",
            "connection": "muse_governed_handoff",
            "messages": rows,
            "count": len(rows),
            "read_only": True,
            "raw_bodies_stored": False,
            "attachments_stored": False,
            "mailbox_mutations": 0,
        }

    def communications_snapshot(self) -> dict[str, Any]:
        """Return derived operating views without creating mailbox-side state."""
        return build_communications_snapshot(self.snapshot()["messages"])
