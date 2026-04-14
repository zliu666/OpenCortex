"""Novelty filter based on Jaccard similarity (from Omni-SimpleMem research)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Set


class NoveltyFilter:
    """Jaccard-based text novelty filter.

    Prevents redundant content from being stored by comparing new text
    against a sliding window of recent summaries using Jaccard overlap.
    """

    def __init__(
        self,
        threshold: float = 0.8,
        window_size: int = 50,
        db_path: Path | None = None,
    ) -> None:
        self.threshold = threshold
        self.window_size = window_size
        self._recent: list[Set[str]] = []
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

        if db_path is not None:
            self._init_db()

    def _init_db(self) -> None:
        """Initialize persistence DB."""
        assert self._db_path is not None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS novelty_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL,
                summary TEXT,
                created_at REAL DEFAULT (strftime('%s','now'))
            )
        """)
        self._conn.commit()
        # Load recent from DB
        rows = self._conn.execute(
            "SELECT summary FROM novelty_state ORDER BY id DESC LIMIT ?",
            (self.window_size,),
        ).fetchall()
        for (text,) in reversed(rows):
            if text:
                self._recent.append(self._tokenize(text))

    @staticmethod
    def _tokenize(text: str) -> Set[str]:
        """Simple word-level tokenization."""
        return set(re.findall(r'\w+', text.lower()))

    @staticmethod
    def _jaccard(a: Set[str], b: Set[str]) -> float:
        """Compute Jaccard similarity between two sets."""
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def is_novel(self, text: str) -> bool:
        """Check if text is sufficiently novel (not redundant).

        Returns True if the text should be stored, False if it's a
        near-duplicate of recent content.
        """
        tokens = self._tokenize(text)

        # Too short to meaningfully compare
        if len(tokens) < 3:
            return True

        for prev in self._recent:
            if self._jaccard(tokens, prev) > self.threshold:
                return False  # Redundant

        # Novel: add to window
        self._recent.append(tokens)
        if len(self._recent) > self.window_size:
            self._recent.pop(0)

        # Persist
        if self._conn is not None:
            token_hash = str(hash(frozenset(tokens)))
            self._conn.execute(
                "INSERT INTO novelty_state (token_hash, summary) VALUES (?, ?)",
                (token_hash, text[:500]),
            )
            self._conn.commit()

        return True

    def reset(self) -> None:
        """Reset the sliding window and clear persisted state."""
        self._recent.clear()
        if self._conn is not None:
            self._conn.execute("DELETE FROM novelty_state")
            self._conn.commit()

    def close(self) -> None:
        """Close DB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
