"""MEMORY.md and USER.md file management with frozen snapshot pattern."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_SECTION_SEP = "§"


class MemoryFiles:
    """Manages MEMORY.md and USER.md with the frozen-snapshot pattern.

    The frozen snapshot is taken once at session start and never changes,
    enabling stable system prompts for API prefix caching.
    """

    def __init__(
        self,
        memory_dir: Path,
        memory_limit: int = 2200,
        user_limit: int = 1375,
    ) -> None:
        self.memory_dir = memory_dir
        self.memory_limit = memory_limit
        self.user_limit = user_limit
        self._memory_entries: list[str] = []
        self._user_entries: list[str] = []

    # -- read ----------------------------------------------------------------

    def _read_file(self, path: Path) -> list[str]:
        """Read a §-delimited file into a list of entries."""
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        entries = [e.strip() for e in text.split(MEMORY_SECTION_SEP) if e.strip()]
        # deduplicate preserving order
        return list(dict.fromkeys(entries))

    def read_memory(self) -> list[str]:
        self._memory_entries = self._read_file(self.memory_dir / "MEMORY.md")
        return list(self._memory_entries)

    def read_user(self) -> list[str]:
        self._user_entries = self._read_file(self.memory_dir / "USER.md")
        return list(self._user_entries)

    # -- write ---------------------------------------------------------------

    def _write_file(self, path: Path, entries: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"\n{MEMORY_SECTION_SEP}\n".join(entries)
        path.write_text(content + "\n", encoding="utf-8")

    def _truncate(self, text: str, limit: int) -> str:
        return text[:limit]

    def add_memory(self, entry: str) -> None:
        self.read_memory()
        if entry.strip() not in self._memory_entries:
            self._memory_entries.append(entry.strip())
        self._write_file(self.memory_dir / "MEMORY.md", self._memory_entries)

    def replace_memory(self, old: str, new: str) -> bool:
        self.read_memory()
        old_stripped = old.strip()
        if old_stripped not in self._memory_entries:
            return False
        idx = self._memory_entries.index(old_stripped)
        self._memory_entries[idx] = new.strip()
        self._write_file(self.memory_dir / "MEMORY.md", self._memory_entries)
        return True

    def remove_memory(self, old: str) -> bool:
        self.read_memory()
        old_stripped = old.strip()
        if old_stripped not in self._memory_entries:
            return False
        self._memory_entries.remove(old_stripped)
        self._write_file(self.memory_dir / "MEMORY.md", self._memory_entries)
        return True

    # -- snapshot ------------------------------------------------------------

    def take_snapshot(self) -> dict[str, str]:
        """Take a frozen snapshot of current MEMORY.md + USER.md content."""
        memory_entries = self.read_memory()
        user_entries = self.read_user()
        memory_text = self._truncate(
            "\n".join(memory_entries), self.memory_limit
        )
        user_text = self._truncate(
            "\n".join(user_entries), self.user_limit
        )
        return {"memory": memory_text, "user": user_text}
