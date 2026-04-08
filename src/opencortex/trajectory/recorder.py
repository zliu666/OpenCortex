"""Trajectory recorder — logs tool calls and decisions for later analysis."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from opencortex.config.paths import get_data_dir

logger = logging.getLogger(__name__)


@dataclass
class TrajectoryEntry:
    """A single tool call or decision event."""

    tool_name: str
    tool_args: dict[str, Any]
    result_summary: str
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""
    success: bool = True
    duration_ms: float = 0.0
    tags: list[str] = field(default_factory=list)


class TrajectoryRecorder:
    """Records tool-call trajectories to a JSONL file for skill extraction.

    Adapted from Hermes's trajectory.py but focused on tool invocations
    rather than full conversation history. This gives us structured data
    for pattern detection and automatic skill generation.
    """

    def __init__(self, trajectory_dir: Path | None = None) -> None:
        self._dir = trajectory_dir or (get_data_dir() / "trajectories")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._current_session: list[TrajectoryEntry] = []
        self._session_id = ""

    def start_session(self, session_id: str) -> None:
        """Begin a new recording session."""
        self._session_id = session_id
        self._current_session = []

    def record(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result_summary: str,
        *,
        success: bool = True,
        duration_ms: float = 0.0,
        tags: list[str] | None = None,
    ) -> None:
        """Record a single tool invocation."""
        entry = TrajectoryEntry(
            tool_name=tool_name,
            tool_args=tool_args,
            result_summary=result_summary,
            session_id=self._session_id,
            success=success,
            duration_ms=duration_ms,
            tags=tags or [],
        )
        self._current_session.append(entry)

    def end_session(self, completed: bool = True) -> Path:
        """Flush the current session to a JSONL file and return the path."""
        filename = "completed.jsonl" if completed else "failed.jsonl"
        path = self._dir / filename
        session_data = {
            "session_id": self._session_id,
            "timestamp": time.time(),
            "completed": completed,
            "entries": [asdict(e) for e in self._current_session],
            "entry_count": len(self._current_session),
        }
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(session_data, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning("Failed to save trajectory: %s", e)

        self._current_session = []
        self._session_id = ""
        return path

    def load_trajectories(self, limit: int = 100) -> list[dict]:
        """Load recent trajectories for pattern analysis."""
        results: list[dict] = []
        for jsonl_file in ("completed.jsonl", "failed.jsonl"):
            path = self._dir / jsonl_file
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                for line in lines[-limit:]:
                    if line.strip():
                        results.append(json.loads(line))
            except Exception:
                continue
        results.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return results[:limit]
