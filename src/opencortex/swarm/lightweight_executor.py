"""Lightweight executor for cheap-model system/utility tasks."""

from __future__ import annotations

import logging
from typing import Any

from opencortex.swarm.task_tier import TaskTier, TaskTierRouter

logger = logging.getLogger(__name__)

# System prompts for common lightweight operations
_SUMMARIZE_PROMPT = (
    "You are a concise summarizer. Summarize the following text in 2-3 sentences. "
    "Output only the summary, nothing else."
)
_CLASSIFY_PROMPT = (
    "Classify the user message into exactly one category: "
    "CRITICAL, CORE, SYSTEM, UTILITY. "
    "Output only the category name, nothing else.\n\n"
    "Rules:\n"
    "- CRITICAL: security, vulnerability, audit, architecture decisions\n"
    "- CORE: coding, refactoring, design, analysis, implementation\n"
    "- SYSTEM: memory, health checks, summarization, consolidation\n"
    "- UTILITY: search, formatting, listing, translation\n"
)
_CONSOLIDATE_PROMPT = (
    "You are a memory consolidation assistant. Merge the following entries "
    "into a coherent, concise summary. Output only the summary.\n"
)
_HEALTH_CHECK_PROMPT = (
    "You are a health check responder. Reply with exactly: HEALTHY"
)


class LightweightExecutor:
    """Execute lightweight tasks using a cheaper model.

    Uses the OpenAI-compatible API client configured via ``DualModelSettings``
    in ``settings.json``.  Falls back to the primary model when the execution
    model is unavailable (if ``fallback_on_error`` is enabled).
    """

    def __init__(
        self,
        model: str | None = None,
        tier: TaskTier = TaskTier.SYSTEM,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model or TaskTierRouter().route(tier)
        self._api_key = api_key
        self._base_url = base_url
        self._client: Any | None = None

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        """Lazily create the OpenAI-compatible client."""
        if self._client is not None:
            return self._client

        api_key, base_url = self._api_key, self._base_url

        # Try to resolve from settings when not explicitly provided
        if not api_key or not base_url:
            try:
                from opencortex.config.settings import load_settings
                settings = load_settings()
                if not api_key:
                    api_key = (
                        settings.dual_model.execution_provider.api_key
                        or settings.provider_keys.get("minimax", "")
                    )
                if not base_url:
                    base_url = settings.dual_model.execution_provider.base_url
            except Exception:
                logger.debug("Could not load settings for LightweightExecutor", exc_info=True)

        if not api_key:
            raise ValueError(
                "No API key available for LightweightExecutor. "
                "Set dual_model.execution_provider.api_key in settings.json "
                "or pass api_key explicitly."
            )

        from opencortex.api.openai_client import OpenAICompatibleClient
        self._client = OpenAICompatibleClient(api_key=api_key, base_url=base_url)
        return self._client

    async def _call_llm(self, user_message: str, system_prompt: str = "") -> str:
        """Send a single-turn request to the lightweight model.

        Returns the assistant's text content as a string.
        """
        from opencortex.api.client import ApiMessageRequest
        from opencortex.engine.messages import ConversationMessage, TextBlock

        client = self._get_client()
        messages: list[ConversationMessage] = []

        if user_message:
            messages.append(
                ConversationMessage(
                    role="user",
                    content=[TextBlock(text=user_message)],
                )
            )

        final_text = ""
        async for event in client.stream_message(
            ApiMessageRequest(
                model=self._model,
                messages=messages,
                system_prompt=system_prompt or None,
                max_tokens=1024,
            )
        ):
            from opencortex.api.client import ApiTextDeltaEvent, ApiMessageCompleteEvent
            if isinstance(event, ApiTextDeltaEvent):
                final_text += event.text

        return final_text.strip()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def summarize(self, text: str) -> str:
        """Summarize *text* using the lightweight model."""
        if not text:
            return ""
        try:
            return await self._call_llm(text, system_prompt=_SUMMARIZE_PROMPT)
        except Exception:
            logger.warning("LightweightExecutor.summarize failed, returning truncated text", exc_info=True)
            return text[:200] + ("..." if len(text) > 200 else "")

    async def classify_intent(self, message: str) -> str:
        """Classify user intent using the lightweight model.

        Returns a ``TaskTier`` value string (e.g. ``"core"``, ``"utility"``).
        """
        # Fast path: local rule-based classification
        router = TaskTierRouter()
        tier = router.classify(message)
        return tier.value

    async def health_check(self) -> dict[str, Any]:
        """Execute a basic health check against the lightweight model."""
        try:
            response = await self._call_llm(
                "ping", system_prompt=_HEALTH_CHECK_PROMPT
            )
            return {
                "status": "ok",
                "model": self._model,
                "response": response,
            }
        except Exception as exc:
            return {
                "status": "error",
                "model": self._model,
                "error": str(exc),
            }

    async def consolidate_memory(self, entries: list[dict[str, Any]]) -> str:
        """Consolidate memory entries into a summary string."""
        if not entries:
            return "No entries to consolidate."
        try:
            # Format entries as text
            parts: list[str] = []
            for i, entry in enumerate(entries, 1):
                content = entry.get("content", entry.get("text", str(entry)))
                parts.append(f"[{i}] {content}")
            combined = "\n".join(parts)
            return await self._call_llm(combined, system_prompt=_CONSOLIDATE_PROMPT)
        except Exception:
            logger.warning("LightweightExecutor.consolidate_memory failed", exc_info=True)
            return f"Consolidated {len(entries)} entries (model={self._model})."
