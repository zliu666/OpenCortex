"""Memory pipeline: prefetch, inject, post-process."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from opencortex.memory.files import MemoryFiles

logger = logging.getLogger(__name__)


class MemoryPipeline:
    """Orchestrates the memory lifecycle for a session.

    1. *prefetch* — load MEMORY.md + USER.md, freeze snapshot
    2. *inject_into* — weave snapshot into the system prompt
    3. *post_process* — persist messages, maybe flag nudge
    4. *search* — FTS5 full-text search over history
    """

    def __init__(self, memory_dir: Path, fts5_store: Any | None = None) -> None:
        self.memory_dir = memory_dir
        self.fts5_store = fts5_store  # FtsMemoryStore or compatible
        self._files = MemoryFiles(memory_dir)
        self._snapshot: dict[str, str] = {}
        self._should_nudge: bool = False
        self._prefetched: bool = False

    # -- lifecycle -----------------------------------------------------------

    async def prefetch(self) -> None:
        """Read MEMORY.md + USER.md at session start and freeze a snapshot.

        Only reads once; subsequent calls are no-ops to avoid redundant I/O.
        """
        if self._prefetched:
            return
        self._snapshot = self._files.take_snapshot()
        self._prefetched = True
        logger.debug(
            "Memory snapshot taken: memory=%d chars, user=%d chars",
            len(self._snapshot.get("memory", "")),
            len(self._snapshot.get("user", "")),
        )

    def inject_into(self, system_prompt: str) -> str:
        """Append the frozen snapshot to *system_prompt* inside a fence."""
        parts = [system_prompt]

        memory_text = self._snapshot.get("memory", "")
        user_text = self._snapshot.get("user", "")

        sections: list[str] = []
        if memory_text:
            sections.append(f"<memory>\n{memory_text}\n</memory>")
        if user_text:
            sections.append(f"<user-profile>\n{user_text}\n</user-profile>")

        if sections:
            parts.append("\n\n<memory-context>\n" + "\n".join(sections) + "\n</memory-context>")

        return "".join(parts)

    # -- post-turn -----------------------------------------------------------

    async def post_process(
        self,
        messages: list[dict[str, Any]],
        turn_count: int,
        nudge_interval: int = 10,
    ) -> None:
        """Post-turn housekeeping: persist to FTS5 and check nudge."""
        self._should_nudge = (turn_count % nudge_interval == 0) and turn_count > 0

        if self.fts5_store is not None and messages:
            # Store all messages from this turn, not just the last one
            for msg in messages:
                role = msg.get("role", "unknown") if isinstance(msg, dict) else getattr(msg, "role", "unknown")
                content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                if content:
                    self.fts5_store.store(
                        key=f"turn:{turn_count}:{role}",
                        content=str(content),
                        metadata={"turn": turn_count, "role": role},
                    )

    # -- search --------------------------------------------------------------

    async def search(self, query: str, limit: int = 20) -> str:
        """FTS5 full-text search over stored messages."""
        if self.fts5_store is None:
            return ""
        results = self.fts5_store.search(query, limit=limit)
        if not results:
            return ""
        lines: list[str] = []
        for r in results:
            lines.append(f"[{r['key']}] {r['content']}")
        return "\n".join(lines)

    # -- properties ----------------------------------------------------------

    @property
    def should_nudge(self) -> bool:
        """Whether a background memory-review nudge is due."""
        return self._should_nudge
