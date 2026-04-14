"""Lightweight vector store using numpy cosine similarity over SQLite BLOB storage."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_VECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS vector_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    dim INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vec_external ON vector_embeddings(external_id);
"""


def _emb_to_blob(vec: np.ndarray) -> bytes:
    return vec.astype(np.float32).tobytes()


def _blob_to_emb(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).copy()


class VectorStore:
    """Numpy-based vector store with hybrid search (dense ∪ FTS5).

    The FTS5 portion is delegated to the caller (tiered_store) which owns
    the FTS5 table. This class provides dense-vector indexing and a
    convenience ``hybrid_search`` that merges dense results with externally
    supplied FTS5 results via set-union.

    Args:
        db_path: Path to the SQLite database.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            if self._db_path is not None:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(str(self._db_path))
            else:
                self._conn = sqlite3.connect(":memory:")
            self._conn.executescript(_VECTOR_SCHEMA)
        return self._conn

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def upsert(self, external_id: int, embedding: np.ndarray) -> int:
        """Insert or update an embedding for *external_id*. Returns row ID."""
        conn = self._connect()
        dim = len(embedding)
        blob = _emb_to_blob(embedding)
        import time

        # Delete existing entry for this external_id
        conn.execute("DELETE FROM vector_embeddings WHERE external_id = ?", (external_id,))
        cursor = conn.execute(
            "INSERT INTO vector_embeddings (external_id, embedding, dim, created_at) VALUES (?, ?, ?, ?)",
            (external_id, blob, dim, time.time()),
        )
        conn.commit()
        return cursor.lastrowid

    def delete(self, external_id: int) -> bool:
        conn = self._connect()
        cursor = conn.execute("DELETE FROM vector_embeddings WHERE external_id = ?", (external_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Dense search
    # ------------------------------------------------------------------

    def dense_search(
        self,
        query_embedding: np.ndarray,
        *,
        limit: int = 10,
        candidate_limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return top-*limit* results by cosine similarity."""
        conn = self._connect()
        # Limit candidate set to avoid full table scan on large datasets
        rows = conn.execute(
            "SELECT external_id, embedding, dim FROM vector_embeddings ORDER BY id DESC LIMIT ?",
            (candidate_limit,)
        ).fetchall()

        if not rows:
            return []

        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
        scored: list[tuple[float, int]] = []
        for ext_id, blob, dim in rows:
            vec = _blob_to_emb(blob, dim)
            vec_norm = vec / (np.linalg.norm(vec) + 1e-10)
            sim = float(np.dot(query_norm, vec_norm))
            scored.append((sim, ext_id))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[dict[str, Any]] = []
        for sim, ext_id in scored[:limit]:
            results.append({"id": ext_id, "score": sim})
        return results

    # ------------------------------------------------------------------
    # Hybrid search (dense ∪ FTS5)
    # ------------------------------------------------------------------

    def hybrid_search(
        self,
        query_embedding: np.ndarray | None,
        fts_results: list[dict[str, Any]],
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Merge dense-vector results with FTS5 results using set-union.

        Dense results keep their similarity ordering; FTS5-only results are
        appended after.
        """
        dense_results: list[dict[str, Any]] = []
        if query_embedding is not None:
            dense_results = self.dense_search(query_embedding, limit=limit)

        seen_ids: set[int] = set()
        merged: list[dict[str, Any]] = []

        # Dense results first (preserving order)
        for r in dense_results:
            rid = r["id"]
            if rid not in seen_ids:
                seen_ids.add(rid)
                merged.append(r)

        # Append FTS5-only results
        for r in fts_results:
            rid = r["id"]
            if rid not in seen_ids:
                seen_ids.add(rid)
                merged.append(r)

        return merged[:limit]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
