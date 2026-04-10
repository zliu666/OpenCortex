"""Trajectory recording for skill learning."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


_DEFAULT_STORAGE = Path.home() / ".opencortex" / "trajectories.jsonl"


@dataclass
class TrajectoryEntry:
    """一条执行轨迹。"""

    timestamp: float
    task_description: str
    steps: list[dict[str, Any]]
    outcome: str  # "success" / "failure"
    lessons: list[str] = field(default_factory=list)


class TrajectoryRecorder:
    """记录 Agent 执行轨迹。"""

    def __init__(self, storage_path: Path | None = None) -> None:
        self._path = storage_path or _DEFAULT_STORAGE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: TrajectoryEntry) -> None:
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def get_entries(self, limit: int = 50) -> list[TrajectoryEntry]:
        entries: list[TrajectoryEntry] = []
        if not self._path.exists():
            return entries
        with open(self._path, encoding="utf-8") as f:
            lines = f.readlines()
        for line in reversed(lines[-limit:]):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            entries.append(TrajectoryEntry(**data))
        return entries

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
