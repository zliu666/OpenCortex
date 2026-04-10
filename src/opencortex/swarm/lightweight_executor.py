"""Lightweight executor for cheap-model system/utility tasks."""

from __future__ import annotations

import logging
from typing import Any

from opencortex.swarm.task_tier import TaskTier, TaskTierRouter

logger = logging.getLogger(__name__)


class LightweightExecutor:
    """Execute lightweight tasks (summarization, intent classification, health checks)
    using a cheaper model to save costs."""

    def __init__(self, model: str | None = None, tier: TaskTier = TaskTier.SYSTEM) -> None:
        self._model = model or TaskTierRouter().route(tier)

    @property
    def model(self) -> str:
        return self._model

    async def summarize(self, text: str) -> str:
        """Summarize text. Override or mock in tests."""
        # Placeholder: real impl would call LLM API
        if not text:
            return ""
        return text[:200] + ("..." if len(text) > 200 else "")

    async def classify_intent(self, message: str) -> str:
        """Classify user intent from a message."""
        router = TaskTierRouter()
        tier = router.classify(message)
        return tier.value

    async def health_check(self) -> dict[str, Any]:
        """Execute a basic health check and return status dict."""
        return {
            "status": "ok",
            "model": self._model,
        }

    async def consolidate_memory(self, entries: list[dict[str, Any]]) -> str:
        """Consolidate memory entries into a summary string."""
        if not entries:
            return "No entries to consolidate."
        return f"Consolidated {len(entries)} entries (model={self._model})."
