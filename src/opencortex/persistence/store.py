"""Async SQLite persistence store with FTS5 full-text search."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT DEFAULT 'cli',
    user_id TEXT,
    model TEXT,
    title TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    cost_input REAL DEFAULT 0,
    cost_output REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_name TEXT,
    tool_calls TEXT,
    token_count INTEGER,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content=messages, content_rowid=id,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistenceStore:
    """Async SQLite persistence store with WAL mode and FTS5."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            db = await aiosqlite.connect(self.db_path)
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA foreign_keys=ON")
            self._db = db
            await self._init_schema(self._db)
        return self._db

    async def _init_schema(self, db: aiosqlite.Connection) -> None:
        await db.executescript(_SCHEMA_SQL)
        # Set schema version if not present
        cur = await db.execute("SELECT COUNT(*) FROM schema_version")
        count = (await cur.fetchone())[0]
        if count == 0:
            await db.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        await db.commit()

    # --- Session operations ---

    async def create_session(
        self,
        session_id: str,
        source: str = "cli",
        user_id: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        title: str | None = None,
    ) -> None:
        db = await self._get_db()
        await db.execute(
            """INSERT INTO sessions (id, source, user_id, model, title, started_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, source, user_id, model, title, _now_iso()),
        )
        # Optionally store system_prompt as first message
        if system_prompt:
            await db.execute(
                """INSERT INTO messages (session_id, role, content, timestamp)
                   VALUES (?, 'system', ?, ?)""",
                (session_id, system_prompt, _now_iso()),
            )
        await db.commit()

    async def end_session(self, session_id: str) -> None:
        db = await self._get_db()
        await db.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (_now_iso(), session_id),
        )
        await db.commit()

    # --- Message operations ---

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str | None,
        tool_name: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        token_count: int | None = None,
    ) -> int:
        db = await self._get_db()
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        cur = await db.execute(
            """INSERT INTO messages (session_id, role, content, tool_name, tool_calls, token_count, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, role, content, tool_name, tool_calls_json, token_count, _now_iso()),
        )
        await db.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def _fetch_as_dicts(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        db = await self._get_db()
        cursor = await db.execute(sql, params)
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_session_messages(
        self, session_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT id, session_id, role, content, tool_name, tool_calls, token_count, timestamp FROM messages WHERE session_id = ? ORDER BY id"
        params: list[Any] = [session_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return await self._fetch_as_dicts(sql, params)

    async def list_sessions(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self._fetch_as_dicts(
            "SELECT id, source, user_id, model, title, started_at, ended_at, cost_input, cost_output FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )

    # --- Search ---

    async def search_messages(
        self, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        fts_query = query.replace('"', '""')
        return await self._fetch_as_dicts(
            """SELECT m.id, m.session_id, m.role, m.content, m.tool_name, m.timestamp
               FROM messages_fts f
               JOIN messages m ON m.id = f.rowid
               WHERE messages_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        )

    # --- Lifecycle ---

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
