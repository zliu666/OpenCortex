"""Global token usage statistics with four dimensions.

Tracks token consumption across:
  - **Model**: per model name (e.g. "claude-sonnet-4", "glm-4-flash")
  - **Session**: per session ID (API server sessions)
  - **Hour**: hourly buckets for time-series analysis
  - **Task type**: per task category (query, session, a2a_task)

Thread-safe via a single asyncio.Lock.  All mutation goes through
``record()`` which acquires the lock.

Usage::

    from opencortex.engine.token_stats import global_token_stats

    # Record a usage event
    global_token_stats.record(
        input_tokens=1500,
        output_tokens=800,
        model="claude-sonnet-4",
        session_id="sess_abc",
        task_type="session",
    )

    # Get snapshot
    snapshot = global_token_stats.snapshot()
    print(snapshot["by_model"])
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class UsageBucket(BaseModel):
    """Accumulated token usage for a single bucket."""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


class TokenStatsSnapshot(BaseModel):
    """Immutable snapshot of the global token statistics."""
    uptime_seconds: float = 0.0
    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    by_model: dict[str, dict[str, int]] = Field(default_factory=dict)
    by_session: dict[str, dict[str, int]] = Field(default_factory=dict)
    by_hour: dict[str, dict[str, int]] = Field(default_factory=dict)
    by_task_type: dict[str, dict[str, int]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Global stats collector
# ---------------------------------------------------------------------------

class TokenStats:
    """Process-global token usage statistics.

    A single instance is created at module level as
    ``global_token_stats``.  Import and use that singleton.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._started_at: float = time.monotonic()
        self._total_requests: int = 0
        self._total_input: int = 0
        self._total_output: int = 0
        self._by_model: dict[str, UsageBucket] = defaultdict(UsageBucket)
        self._by_session: dict[str, UsageBucket] = defaultdict(UsageBucket)
        self._by_hour: dict[str, UsageBucket] = defaultdict(UsageBucket)
        self._by_task_type: dict[str, UsageBucket] = defaultdict(UsageBucket)

    # -- public API --------------------------------------------------------

    async def record(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        model: str = "unknown",
        session_id: str = "",
        task_type: str = "query",
    ) -> None:
        """Record a token usage event (thread-safe)."""
        async with self._lock:
            self._total_requests += 1
            self._total_input += input_tokens
            self._total_output += output_tokens

            # by model
            b = self._by_model[model]
            self._by_model[model] = UsageBucket(
                input_tokens=b.input_tokens + input_tokens,
                output_tokens=b.output_tokens + output_tokens,
            )

            # by session (only if provided)
            if session_id:
                b = self._by_session[session_id]
                self._by_session[session_id] = UsageBucket(
                    input_tokens=b.input_tokens + input_tokens,
                    output_tokens=b.output_tokens + output_tokens,
                )

            # by hour (UTC)
            hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
            b = self._by_hour[hour_key]
            self._by_hour[hour_key] = UsageBucket(
                input_tokens=b.input_tokens + input_tokens,
                output_tokens=b.output_tokens + output_tokens,
            )

            # by task type
            b = self._by_task_type[task_type]
            self._by_task_type[task_type] = UsageBucket(
                input_tokens=b.input_tokens + input_tokens,
                output_tokens=b.output_tokens + output_tokens,
            )

    def snapshot(self) -> dict[str, Any]:
        """Return a plain-dict snapshot (no lock needed — GIL-safe for CPython)."""
        return TokenStatsSnapshot(
            uptime_seconds=round(time.monotonic() - self._started_at, 1),
            total_requests=self._total_requests,
            total_input_tokens=self._total_input,
            total_output_tokens=self._total_output,
            by_model={k: v.to_dict() for k, v in self._by_model.items()},
            by_session={k: v.to_dict() for k, v in self._by_session.items()},
            by_hour={k: v.to_dict() for k, v in sorted(self._by_hour.items())},
            by_task_type={k: v.to_dict() for k, v in self._by_task_type.items()},
        ).model_dump()

    async def reset(self) -> None:
        """Reset all counters."""
        async with self._lock:
            self._started_at = time.monotonic()
            self._total_requests = 0
            self._total_input = 0
            self._total_output = 0
            self._by_model.clear()
            self._by_session.clear()
            self._by_hour.clear()
            self._by_task_type.clear()

    def remove_session(self, session_id: str) -> None:
        """Clean up a session bucket when the session is deleted."""
        self._by_session.pop(session_id, None)


# Singleton instance — import this.
global_token_stats = TokenStats()
