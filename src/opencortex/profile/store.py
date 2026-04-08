"""User profile storage backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from opencortex.config.paths import get_data_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    confidence REAL DEFAULT 1.0,
    source TEXT DEFAULT 'learned',
    updated_at REAL
);

CREATE INDEX IF NOT EXISTS idx_profile_category ON user_profile(category);
"""


class ProfileStore:
    """Stores learned user preferences in SQLite."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or (get_data_dir() / "profile" / "profile.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        return self._conn

    def set(
        self,
        key: str,
        value: str,
        *,
        category: str = "general",
        confidence: float = 1.0,
        source: str = "learned",
    ) -> None:
        """Store or update a preference."""
        conn = self._connect()
        conn.execute(
            """INSERT INTO user_profile (key, value, category, confidence, source, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,
                   category=excluded.category,
                   confidence=excluded.confidence,
                   source=excluded.source,
                   updated_at=excluded.updated_at""",
            (key, value, category, confidence, source, time.time()),
        )
        conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        """Get a preference by key."""
        conn = self._connect()
        row = conn.execute("SELECT * FROM user_profile WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        return dict(row)

    def get_by_category(self, category: str) -> list[dict[str, Any]]:
        """Get all preferences in a category."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM user_profile WHERE category = ? ORDER BY confidence DESC",
            (category,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all(self) -> list[dict[str, Any]]:
        """Get all preferences."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM user_profile ORDER BY category, confidence DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def format_for_prompt(self) -> str:
        """Format the profile as a system prompt section."""
        prefs = self.get_all()
        if not prefs:
            return ""
        lines = ["## Learned User Preferences", ""]
        current_cat = ""
        for p in prefs:
            if p["category"] != current_cat:
                current_cat = p["category"]
                lines.append(f"### {current_cat.title()}")
            conf = f" (confidence: {p['confidence']:.0%})" if p["confidence"] < 1.0 else ""
            lines.append(f"- **{p['key']}**: {p['value']}{conf}")
        return "\n".join(lines)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
