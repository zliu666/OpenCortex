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


def _escape_fts5_query(query: str) -> str:
    """Escape special characters for FTS5 MATCH queries."""
    return query.replace('"', '""')

logger = logging.getLogger(__name__)

_TIERED_SCHEMA = """
CREATE TABLE IF NOT EXISTS tiered_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tier TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT DEFAULT '',
    raw_content_path TEXT DEFAULT '',
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
class SimpleMemSettings:
    """Feature flags for SimpleMem upgrades. All default to False (off)."""

    novelty_filter: bool = False
    vector_search: bool = False
    pyramid_retrieval: bool = False
    novelty_threshold: float = 0.8
    novelty_window: int = 50
    pyramid_budget: int = 6000
    pyramid_similarity_threshold: float = 0.4


@dataclass
class TieredMemoryConfig:
    tiers: dict[MemoryTier, TierConfig] = field(default_factory=TierConfig.defaults)
    simplemem: SimpleMemSettings = field(default_factory=SimpleMemSettings)


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

        # --- SimpleMem subsystems (lazy-initialised) ---
        self._novelty_filter: NoveltyFilter | None = None
        self._vector_store: VectorStore | None = None  # noqa: F841

    # ------------------------------------------------------------------
    # Internal: sub-system accessors
    # ------------------------------------------------------------------

    def _get_novelty_filter(self) -> NoveltyFilter:
        if self._novelty_filter is None:
            from opencortex.memory.novelty_filter import NoveltyFilter

            novelty_db = self._db_path.parent / "novelty.db"
            self._novelty_filter = NoveltyFilter(
                threshold=self._config.simplemem.novelty_threshold,
                window_size=self._config.simplemem.novelty_window,
                db_path=novelty_db,
            )
        return self._novelty_filter

    def _get_vector_store(self) -> VectorStore:
        if self._vector_store is None:  # noqa: F841
            from opencortex.memory.vector_store import VectorStore

            vec_db = self._db_path.parent / "vectors.db"
            self._vector_store = VectorStore(db_path=vec_db)
        return self._vector_store

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
            "summary": row["summary"] if "summary" in row.keys() else "",
            "raw_content_path": row["raw_content_path"] if "raw_content_path" in row.keys() else "",
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

        When pyramid_retrieval is enabled, results are formatted via
        pyramid progressive retrieval with token budget control.
        """
        conn = self._connect()
        parts: list[str] = []

        # Collect candidate memories
        candidates: list[dict[str, Any]] = []

        # Auto-load tiers
        for tier, cfg in self._config.tiers.items():
            if not cfg.auto_load:
                continue
            rows = conn.execute(
                "SELECT * FROM tiered_memories WHERE tier = ? ORDER BY updated_at DESC LIMIT 200",
                (tier.value,),
            ).fetchall()
            candidates.extend(self._row_to_dict(r) for r in rows)

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
                        (f'"{_escape_fts5_query(query)}"',),
                    )
                else:
                    cursor = conn.execute(
                        """SELECT * FROM tiered_memories WHERE tier = ?
                           AND (content LIKE ? OR tags LIKE ?)
                           ORDER BY updated_at DESC LIMIT 50""",
                        (tier.value, f"%{query}%", f"%{query}%"),
                    )
                rows = cursor.fetchall()
                candidates.extend(self._row_to_dict(r) for r in rows)

        # --- Pyramid retrieval (optional) ---
        if self._config.simplemem.pyramid_retrieval and candidates:
            from opencortex.memory.pyramid_retrieval import (
                PyramidConfig,
                PyramidMemory,
                retrieve,
            )

            pmems = [
                PyramidMemory(
                    id=c["id"],
                    summary=c.get("summary") or c["content"][:100],
                    full_text=c["content"],
                    score=1.0,  # auto-load gets high score
                )
                for c in candidates
            ]
            cfg = PyramidConfig(
                similarity_threshold=self._config.simplemem.pyramid_similarity_threshold,
                token_budget=self._config.simplemem.pyramid_budget,
            )
            return retrieve(query, pmems, config=cfg)

        # --- Original behaviour ---
        # Group by tier for display
        seen_ids: set[int] = set()
        tier_order: list[str] = []
        tier_parts: dict[str, list[str]] = {}

        for c in candidates:
            tier = c["tier"]
            if tier not in tier_parts:
                tier_parts[tier] = []
                tier_order.append(tier)
            if c["id"] not in seen_ids:
                seen_ids.add(c["id"])
                tier_parts[tier].append(c["content"])

        for tier in tier_order:
            items = tier_parts[tier]
            if items:
                parts.append(f"## {tier.upper()}\n")
                parts.extend(items)
                parts.append("")

        return "\n".join(parts)

    def add_entry(
        self,
        tier: MemoryTier,
        content: str,
        tags: list[str] | None = None,
        *,
        summary: str = "",
        raw_content_path: str = "",
        embedding: Any | None = None,
    ) -> int | None:
        """Add a memory entry to the specified tier. Returns row ID or None if filtered."""
        # --- Novelty filter (optional) ---
        if self._config.simplemem.novelty_filter:
            nf = self._get_novelty_filter()
            if not nf.is_novel(content):
                logger.debug("Novelty filter rejected: %s", content[:80])
                return None

        conn = self._connect()
        now = time.time()
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        cursor = conn.execute(
            """INSERT INTO tiered_memories (tier, content, summary, raw_content_path, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tier.value, content, summary, raw_content_path, tags_json, now, now),
        )
        conn.commit()
        row_id = cursor.lastrowid

        # --- Vector store (optional) ---
        if self._config.simplemem.vector_search and embedding is not None:
            import numpy as np

            vs = self._get_vector_store()
            vec = np.asarray(embedding, dtype=np.float32)
            vs.upsert(row_id, vec)

        return row_id

    def search(
        self,
        query: str,
        tiers: list[MemoryTier] | None = None,
        *,
        limit: int = 10,
        query_embedding: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Cross-tier memory search.

        When vector_search is enabled and query_embedding is provided,
        performs hybrid search (dense ∪ FTS5) via set-union.
        """
        conn = self._connect()

        # --- FTS5 / LIKE search (original) ---
        fts_results: list[dict[str, Any]] = []
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
                    (f'"{_escape_fts5_query(query)}"', *tier_values, limit),
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
                    (f'"{_escape_fts5_query(query)}"', limit),
                )
            else:
                like = f"%{query}%"
                cursor = conn.execute(
                    """SELECT * FROM tiered_memories
                       WHERE content LIKE ? OR tags LIKE ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (like, like, limit),
                )

        fts_results = [self._row_to_dict(r) for r in cursor.fetchall()]

        # --- Hybrid search (optional) ---
        if self._config.simplemem.vector_search and query_embedding is not None:
            import numpy as np

            vs = self._get_vector_store()
            vec = np.asarray(query_embedding, dtype=np.float32)
            fts_ids = [{"id": r["id"]} for r in fts_results]
            merged = vs.hybrid_search(vec, fts_ids, limit=limit)

            # Build result set from merged IDs
            merged_ids = [r["id"] for r in merged]
            if not merged_ids:
                return []

            placeholders = ",".join("?" for _ in merged_ids)
            rows = conn.execute(
                f"SELECT * FROM tiered_memories WHERE id IN ({placeholders})",
                merged_ids,
            ).fetchall()
            row_map = {r["id"]: self._row_to_dict(r) for r in rows}

            # Preserve merged ordering
            results = []
            for mid in merged_ids:
                if mid in row_map:
                    results.append(row_map[mid])
            return results

        return fts_results

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
        if self._novelty_filter is not None:
            self._novelty_filter.close()
        if self._vector_store is not None:
            self._vector_store.close()
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> TieredMemoryStore:
        self._connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
