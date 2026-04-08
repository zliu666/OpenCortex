"""SQLite FTS5-backed memory store for fast full-text search."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from opencortex.config.paths import get_data_dir

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    created_at REAL,
    updated_at REAL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    key,
    content,
    metadata,
    content=memories,
    content_rowid=id,
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, key, content, metadata)
    VALUES (new.id, new.key, new.content, new.metadata);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, content, metadata)
    VALUES ('delete', old.id, old.key, old.content, old.metadata);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, content, metadata)
    VALUES ('delete', old.id, old.key, old.content, old.metadata);
    INSERT INTO memories_fts(rowid, key, content, metadata)
    VALUES (new.id, new.key, new.content, new.metadata);
END;
"""


class FtsMemoryStore:
    """SQLite FTS5 memory store for fast full-text search.

    Uses trigram tokenizer which natively supports CJK text.
    Complements the existing file-based memory system.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or (get_data_dir() / "memory" / "memory.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        return self._conn

    def store(self, key: str, content: str, metadata: dict[str, Any] | None = None) -> int:
        """Store or update a memory entry. Returns the row ID."""
        conn = self._connect()
        now = time.time()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        conn.execute(
            """INSERT INTO memories (key, content, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   content=excluded.content,
                   metadata=excluded.metadata,
                   updated_at=excluded.updated_at""",
            (key, content, meta_json, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT last_insert_rowid()").fetchone()
        return row[0]

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search across all memories.

        Uses trigram matching for CJK support. For short queries (< 3 chars),
        falls back to LIKE.
        """
        conn = self._connect()
        if len(query) >= 3:
            cursor = conn.execute(
                """SELECT m.id, m.key, m.content, m.metadata, m.created_at, m.updated_at
                   FROM memories_fts f
                   JOIN memories m ON m.id = f.rowid
                   WHERE memories_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (f'"{query}"', limit),
            )
        else:
            cursor = conn.execute(
                """SELECT id, key, content, metadata, created_at, updated_at
                   FROM memories
                   WHERE content LIKE ? OR key LIKE ?
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (f"%{query}%", f"%{query}%", limit),
            )
        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "id": row["id"],
                    "key": row["key"],
                    "content": row["content"],
                    "metadata": json.loads(row["metadata"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return results

    def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a memory by key."""
        conn = self._connect()
        row = conn.execute(
            "SELECT id, key, content, metadata, created_at, updated_at FROM memories WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "key": row["key"],
            "content": row["content"],
            "metadata": json.loads(row["metadata"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def delete(self, key: str) -> bool:
        """Delete a memory by key."""
        conn = self._connect()
        cursor = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
        conn.commit()
        return cursor.rowcount > 0

    def list_keys(self) -> list[str]:
        """List all memory keys."""
        conn = self._connect()
        rows = conn.execute("SELECT key FROM memories ORDER BY updated_at DESC").fetchall()
        return [row["key"] for row in rows]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
