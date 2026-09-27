"""Persistent, bounded conversation archive with indexed text retrieval.

Archive excerpts remain untrusted conversation, never instructions or tool evidence.
"""
import re
import sqlite3
from pathlib import Path
from threading import RLock

from .conversation import recent_history, validate_history
from .security import redact_text


class ChatMemory:
    capacity = 300_000

    def __init__(self, path, *, capacity=300_000):
        if not 2 <= capacity <= self.capacity:
            raise ValueError("invalid archive capacity")
        self.capacity = capacity
        self.lock = RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        if str(path) != ":memory:":
            Path(path).chmod(0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL, position INTEGER NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(request_id, position)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(
                content, content='messages', content_rowid='id', tokenize='unicode61'
            );
            CREATE TRIGGER IF NOT EXISTS memory_insert AFTER INSERT ON messages BEGIN
                INSERT INTO memory_search(rowid,content) VALUES(new.id,new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS memory_delete AFTER DELETE ON messages BEGIN
                INSERT INTO memory_search(memory_search,rowid,content)
                VALUES('delete',old.id,old.content);
            END;
        """)

    def append(self, request_id, messages):
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            raise ValueError("invalid memory request id")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 20:
            raise ValueError("archive batch must contain 1-20 messages")
        cleaned = []
        for item in messages:
            if (not isinstance(item, dict) or set(item) != {"role", "content"}
                    or item.get("role") not in ("user", "assistant")
                    or not isinstance(item.get("content"), str)
                    or not item["content"].strip() or len(item["content"]) > 24_000):
                raise ValueError("invalid archive message")
            cleaned.append((item["role"], redact_text(item["content"])))
        with self.lock, self.db:
            existing = self.db.execute(
                "SELECT role,content FROM messages WHERE request_id=? ORDER BY position",
                (request_id,)).fetchall()
            if existing and existing != cleaned:
                raise ValueError("memory request id already used for different messages")
            if not existing:
                self.db.executemany(
                    "INSERT INTO messages(request_id,position,role,content) VALUES(?,?,?,?)",
                    [(request_id, i, role, content) for i, (role, content) in enumerate(cleaned)])
            cutoff = self.db.execute(
                "SELECT id FROM messages ORDER BY id DESC LIMIT 1 OFFSET ?",
                (self.capacity - 1,)).fetchone()
            if cutoff:
                self.db.execute("DELETE FROM messages WHERE id < ?", cutoff)
            return {"stored_messages": self.db.execute("SELECT count(*) FROM messages").fetchone()[0],
                    "capacity": self.capacity}

    def context(self, prompt, history):
        current = recent_history(validate_history(history), 8000)
        if not isinstance(prompt, str) or len(prompt) > 12_000:
            raise ValueError("invalid memory query")
        stop = {"the", "and", "that", "this", "with", "what", "was", "for", "you", "your",
                "can", "could", "please", "remember", "about", "have", "from", "our", "did"}
        words = list(dict.fromkeys(w.lower() for w in re.findall(r"\w{3,40}", prompt)
                                   if w.lower() not in stop))[:16]
        with self.lock:
            rows = []
            if words:
                query = " OR ".join('"' + word + '"' for word in words)
                rows = self.db.execute("""
                    SELECT m.id,m.request_id,m.role,m.content FROM memory_search
                    JOIN messages m ON m.id=memory_search.rowid
                    WHERE memory_search MATCH ? ORDER BY rank LIMIT 12
                """, (query,)).fetchall()
            # Include recent archive context for cross-room follow-ups too.
            rows += self.db.execute(
                "SELECT id,request_id,role,content FROM messages ORDER BY id DESC LIMIT 6").fetchall()
            candidates = []
            seen_turns = set()
            for row in rows:
                if row[1] in seen_turns:
                    continue
                seen_turns.add(row[1])
                candidates += self.db.execute(
                    "SELECT id,role,content FROM messages WHERE request_id=? ORDER BY position",
                    (row[1],)).fetchall()
        remaining = 12_000 - sum(len(m["content"]) for m in current)
        seen = {(m["role"], m["content"]) for m in current}
        selected = []
        for ident, role, content in candidates:
            if (role, content) in seen or len(selected) + len(current) >= 20:
                continue
            seen.add((role, content))
            # Bounded excerpts allow retrieval of long archived messages.
            excerpt = content[:min(3000, remaining)]
            if not excerpt:
                break
            selected.append((ident, {"role": role, "content": excerpt}))
            remaining -= len(excerpt)
        return [m for _, m in sorted(selected)] + current

    def close(self):
        self.db.close()
