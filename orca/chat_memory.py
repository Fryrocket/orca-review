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
    capacity = 50_000_000

    def __init__(self, path, *, capacity=50_000_000):
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
                line_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(request_id, position)
            );
            CREATE TABLE IF NOT EXISTS memory_stats (
                id INTEGER PRIMARY KEY CHECK(id=1),
                total_lines INTEGER NOT NULL DEFAULT 0 CHECK(total_lines >= 0)
            );
            CREATE TABLE IF NOT EXISTS conversation_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkpoint_key TEXT NOT NULL UNIQUE,
                version INTEGER NOT NULL UNIQUE CHECK(version > 0),
                summary TEXT NOT NULL,
                source_message_count INTEGER NOT NULL CHECK(source_message_count >= 0),
                source_line_count INTEGER NOT NULL CHECK(source_line_count >= 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(messages)")}
        if "line_count" not in columns:
            self.db.execute(
                "ALTER TABLE messages ADD COLUMN line_count INTEGER NOT NULL DEFAULT 1")
            self.db.execute("""
                UPDATE messages SET line_count =
                    1 + length(content) - length(replace(content, char(10), ''))
            """)
        self.db.execute("""
            INSERT OR IGNORE INTO memory_stats(id,total_lines)
            SELECT 1,coalesce(sum(line_count),0) FROM messages
        """)
        self.db.executescript("""
            CREATE TRIGGER IF NOT EXISTS memory_line_insert AFTER INSERT ON messages BEGIN
                UPDATE memory_stats SET total_lines=total_lines+new.line_count WHERE id=1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_line_delete AFTER DELETE ON messages BEGIN
                UPDATE memory_stats SET total_lines=total_lines-old.line_count WHERE id=1;
            END;
            CREATE TRIGGER IF NOT EXISTS checkpoints_no_update
            BEFORE UPDATE ON conversation_checkpoints BEGIN
                SELECT RAISE(ABORT,'conversation checkpoints are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS checkpoints_no_delete
            BEFORE DELETE ON conversation_checkpoints BEGIN
                SELECT RAISE(ABORT,'conversation checkpoints are append-only');
            END;
        """)
        self.db.commit()

    @staticmethod
    def continuity_policy():
        return {
            "raw_transcript_preserved": True,
            "checkpoints_append_only": True,
            "checkpoints_versioned": True,
            "checkpoint_is_authority": False,
            "checkpoint_is_execution_evidence": False,
            "verified_runtime_evidence_wins_conflicts": True,
            "retrieval": "bounded_relevant_excerpts_plus_recent_context",
        }

    def checkpoint(self, checkpoint_key, summary):
        if (not isinstance(checkpoint_key, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", checkpoint_key)):
            raise ValueError("invalid checkpoint key")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 24_000:
            raise ValueError("invalid checkpoint summary")
        cleaned = redact_text(summary)
        with self.lock, self.db:
            existing = self.db.execute("""
                SELECT version,summary,source_message_count,source_line_count,created_at
                FROM conversation_checkpoints WHERE checkpoint_key=?
            """, (checkpoint_key,)).fetchone()
            if existing:
                if existing[1] != cleaned:
                    raise ValueError("checkpoint key already used for different summary")
                version, _, messages, lines, created_at = existing
                return {"checkpoint_key": checkpoint_key, "version": version,
                        "source_message_count": messages, "source_line_count": lines,
                        "created_at": created_at, "policy": self.continuity_policy()}
            version = self.db.execute(
                "SELECT coalesce(max(version),0)+1 FROM conversation_checkpoints").fetchone()[0]
            messages = self.db.execute("SELECT count(*) FROM messages").fetchone()[0]
            lines = self.db.execute(
                "SELECT total_lines FROM memory_stats WHERE id=1").fetchone()[0]
            self.db.execute("""
                INSERT INTO conversation_checkpoints(
                    checkpoint_key,version,summary,source_message_count,source_line_count
                ) VALUES(?,?,?,?,?)
            """, (checkpoint_key, version, cleaned, messages, lines))
            created_at = self.db.execute(
                "SELECT created_at FROM conversation_checkpoints WHERE checkpoint_key=?",
                (checkpoint_key,)).fetchone()[0]
            return {"checkpoint_key": checkpoint_key, "version": version,
                    "source_message_count": messages, "source_line_count": lines,
                    "created_at": created_at, "policy": self.continuity_policy()}

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
            content = redact_text(item["content"])
            cleaned.append((item["role"], content, content.count("\n") + 1))
        with self.lock, self.db:
            existing = self.db.execute(
                "SELECT role,content FROM messages WHERE request_id=? ORDER BY position",
                (request_id,)).fetchall()
            comparable = [(role, content) for role, content, _ in cleaned]
            if existing and comparable[:len(existing)] != existing:
                raise ValueError("memory request id already used for different messages")
            if len(cleaned) > len(existing):
                self.db.executemany(
                    "INSERT INTO messages(request_id,position,role,content,line_count) "
                    "VALUES(?,?,?,?,?)",
                    [(request_id, i, role, content, lines)
                     for i, (role, content, lines)
                     in enumerate(cleaned[len(existing):], len(existing))])
            total_lines = self.db.execute(
                "SELECT total_lines FROM memory_stats WHERE id=1").fetchone()[0]
            excess = total_lines - self.capacity
            if excess > 0:
                cutoff = self.db.execute("""
                    SELECT id FROM (
                        SELECT id,sum(line_count) OVER (ORDER BY id) AS removed_lines
                        FROM messages
                    ) WHERE removed_lines >= ? ORDER BY id LIMIT 1
                """, (excess,)).fetchone()
                if cutoff:
                    self.db.execute("DELETE FROM messages WHERE id <= ?", cutoff)
            stored_messages = self.db.execute("SELECT count(*) FROM messages").fetchone()[0]
            stored_lines = self.db.execute(
                "SELECT total_lines FROM memory_stats WHERE id=1").fetchone()[0]
            return {"stored_messages": stored_messages, "stored_lines": stored_lines,
                    "capacity": self.capacity, "capacity_lines": self.capacity}

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
