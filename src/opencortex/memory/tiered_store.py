"""5-layer tiered memory store for OpenCortex."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from opencortex.config.paths import get_data_dir

logger = logging.getLogger(__name__)

_TIERED_SCHEMA = """
CREATE TABLE IF NOT EXISTS tiered_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tier TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tiered_memories_tier ON tiered_memories(tier);
CREATE INDEX IF NOT EXISTS idx_tiered_memories_created ON tiered_memories(created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS tiered_memories_fts USING fts5(
    content,
    tags,
    content=tiered_memories,
    content_rowid=id,
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS tiered_ai AFTER INSERT ON tiered_memories BEGIN
    INSERT INTO tiered_memories_fts(rowid, content, tags)
    VALUES (new.id, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS tiered_ad AFTER DELETE ON tiered_memories BEGIN
    INSERT INTO tiered_memories_fts(tiered_memories_fts, rowid, content, tags)
    VALUES ('delete', old.id, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS tiered_au AFTER UPDATE ON tiered_memories BEGIN
    INSERT INTO tiered_memories_fts(tiered_memories_fts, rowid, content, tags)
    VALUES ('delete', old.id, old.content, old.tags);
    INSERT INTO tiered_memories_fts(rowid, content, tags)
    VALUES (new.id, new.content, new.tags);
END;
"""


class MemoryTier(Enum):
    CORE = "core"
    SESSION = "session"
    USER = "user"
    PROJECT = "project"
    ARCHIVE = "archive"


@dataclass
class TierConfig:
    max_lines: int = 500
    auto_load: bool = False
    trigger_load: bool = False
    search_only: bool = False
    ttl_days: int = 0

    @classmethod
    def defaults(cls) -> dict[MemoryTier, TierConfig]:
        return {
            MemoryTier.CORE: TierConfig(max_lines=100, auto_load=True, ttl_days=0),
            MemoryTier.SESSION: TierConfig(max_lines=200, auto_load=True, ttl_days=7),
            MemoryTier.USER: TierConfig(max_lines=100, auto_load=True, ttl_days=0),
            MemoryTier.PROJECT: TierConfig(max_lines=500, trigger_load=True, ttl_days=30),
            MemoryTier.ARCHIVE: TierConfig(max_lines=0, search_only=True, ttl_days=0),
        }


@dataclass
class TieredMemoryConfig:
    tiers: dict[MemoryTier, TierConfig] = field(default_factory=TierConfig.defaults)


class TieredMemoryStore:
    """5-layer memory manager for OpenCortex."""

    def __init__(
        self,
        config: TieredMemoryConfig | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._config = config or TieredMemoryConfig()
        self._db_path = db_path or (get_data_dir() / "memory" / "tiered.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_TIERED_SCHEMA)
        return self._conn

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tier": row["tier"],
            "content": row["content"],
            "tags": json.loads(row["tags"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_context(self, query: str = "") -> str:
        """Load memory context based on tier configs and optional query.

        - auto_load tiers are always included
        - trigger_load tiers are included only when query matches via FTS
        - search_only tiers are never loaded into context
        """
        conn = self._connect()
        parts: list[str] = []

        # Auto-load tiers
        for tier, cfg in self._config.tiers.items():
            if not cfg.auto_load:
                continue
            rows = conn.execute(
                "SELECT * FROM tiered_memories WHERE tier = ? ORDER BY updated_at DESC LIMIT 200",
                (tier.value,),
            ).fetchall()
            if rows:
                parts.append(f"## {tier.value.upper()}\n")
                for r in rows:
                    parts.append(r["content"])
                parts.append("")

        # Trigger-load tiers (keyword match)
        if query and len(query) >= 2:
            for tier, cfg in self._config.tiers.items():
                if not cfg.trigger_load:
                    continue
                if len(query) >= 3:
                    cursor = conn.execute(
                        """SELECT tm.* FROM tiered_memories_fts f
                           JOIN tiered_memories tm ON tm.id = f.rowid
                           WHERE tiered_memories_fts MATCH ?
                           ORDER BY rank LIMIT 50""",
                        (f'"{query}"',),
                    )
                else:
                    cursor = conn.execute(
                        """SELECT * FROM tiered_memories WHERE tier = ?
                           AND (content LIKE ? OR tags LIKE ?)
                           ORDER BY updated_at DESC LIMIT 50""",
                        (tier.value, f"%{query}%", f"%{query}%"),
                    )
                rows = cursor.fetchall()
                if rows:
                    parts.append(f"## {tier.value.upper()} (matched: {query})\n")
                    for r in rows:
                        parts.append(r["content"])
                    parts.append("")

        return "\n".join(parts)

    def add_entry(
        self,
        tier: MemoryTier,
        content: str,
        tags: list[str] | None = None,
    ) -> int:
        """Add a memory entry to the specified tier. Returns row ID."""
        conn = self._connect()
        now = time.time()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        cursor = conn.execute(
            """INSERT INTO tiered_memories (tier, content, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (tier.value, content, tags_json, now, now),
        )
        conn.commit()
        return cursor.lastrowid

    def search(
        self,
        query: str,
        tiers: list[MemoryTier] | None = None,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Cross-tier memory search."""
        conn = self._connect()

        if tiers:
            tier_values = [t.value for t in tiers]
            placeholders = ",".join("?" for _ in tier_values)

            if len(query) >= 3:
                cursor = conn.execute(
                    f"""SELECT tm.* FROM tiered_memories_fts f
                        JOIN tiered_memories tm ON tm.id = f.rowid
                        WHERE tiered_memories_fts MATCH ?
                        AND tm.tier IN ({placeholders})
                        ORDER BY rank LIMIT ?""",
                    (f'"{query}"', *tier_values, limit),
                )
            else:
                like = f"%{query}%"
                cursor = conn.execute(
                    f"""SELECT * FROM tiered_memories
                        WHERE tier IN ({placeholders})
                        AND (content LIKE ? OR tags LIKE ?)
                        ORDER BY updated_at DESC LIMIT ?""",
                    (*tier_values, like, like, limit),
                )
        else:
            if len(query) >= 3:
                cursor = conn.execute(
                    """SELECT tm.* FROM tiered_memories_fts f
                       JOIN tiered_memories tm ON tm.id = f.rowid
                       WHERE tiered_memories_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (f'"{query}"', limit),
                )
            else:
                like = f"%{query}%"
                cursor = conn.execute(
                    """SELECT * FROM tiered_memories
                       WHERE content LIKE ? OR tags LIKE ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (like, like, limit),
                )

        return [self._row_to_dict(r) for r in cursor.fetchall()]

    def decay(self) -> int:
        """Execute decay: downgrade expired memories based on tier TTL.

        SESSION (7d) → PROJECT, PROJECT (30d) → ARCHIVE.
        Returns count of decayed entries.
        """
        from opencortex.memory.decay import MemoryDecayManager

        manager = MemoryDecayManager(store=self)
        records = manager.check_and_decay()
        return len(records)

    def get_tier_stats(self) -> dict[MemoryTier, dict]:
        """Get statistics for each tier."""
        conn = self._connect()
        stats: dict[MemoryTier, dict] = {}
        for tier in MemoryTier:
            row = conn.execute(
                "SELECT COUNT(*) as cnt, MAX(updated_at) as last_updated FROM tiered_memories WHERE tier = ?",
                (tier.value,),
            ).fetchone()
            cfg = self._config.tiers.get(tier)
            stats[tier] = {
                "count": row["cnt"],
                "last_updated": row["last_updated"],
                "config": {
                    "auto_load": cfg.auto_load if cfg else False,
                    "trigger_load": cfg.trigger_load if cfg else False,
                    "search_only": cfg.search_only if cfg else False,
                    "ttl_days": cfg.ttl_days if cfg else 0,
                },
            }
        return stats

    # ------------------------------------------------------------------
    # Internal helpers used by decay manager
    # ------------------------------------------------------------------

    def _get_expired_entries(self, tier: MemoryTier, ttl_days: int) -> list[dict[str, Any]]:
        """Get entries in a tier older than ttl_days."""
        conn = self._connect()
        cutoff = time.time() - ttl_days * 86400
        rows = conn.execute(
            "SELECT * FROM tiered_memories WHERE tier = ? AND created_at < ?",
            (tier.value, cutoff),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _move_entry(self, entry_id: int, target_tier: MemoryTier) -> bool:
        """Move an entry to a different tier."""
        conn = self._connect()
        conn.execute(
            "UPDATE tiered_memories SET tier = ?, updated_at = ? WHERE id = ?",
            (target_tier.value, time.time(), entry_id),
        )
        conn.commit()
        return True

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> TieredMemoryStore:
        self._connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
