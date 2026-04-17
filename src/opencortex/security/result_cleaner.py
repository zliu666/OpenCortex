"""Result cleaner — rule-based + optional LLM cleaning of tool results.

Replaces the old two-step sanitizer (detect + extract) with a unified approach:
1. Rule-based cleaning (instant): strip known injection patterns
2. LLM cleaning (optional, for EXTERNAL content): one-pass extract key info
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opencortex.api.client import SupportsStreamingMessages

log = logging.getLogger(__name__)

# ── Rule-based patterns ────────────────────────────────────────────────────

# Common prompt injection patterns
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?m)^<\|(?:(?:begin|start)\s+)?system\|>.*?(?:<\|end\s+system\|>|$)", re.I | re.S),
    re.compile(r"(?m)^\[SYSTEM\].*?(?:\[/SYSTEM\]|$)", re.I | re.S),
    re.compile(r"(?mi)^ignore\s+(?:(?:all|previous|above|prior)\s+)*instructions?\s*[.]?[ \t]*$"),
    re.compile(r"(?mi)^you\s+are\s+now\s+.*$"),
    re.compile(r"(?mi)^disregard\s+.*rules?\s*[.]?[ \t]*$"),
    re.compile(r"(?mi)^new\s+instructions?\s*:"),
    re.compile(r"(?mi)^###?\s*system\s*(?:prompt|message|instruction)"),
]

# Output length limit (characters)
MAX_RESULT_LENGTH = 100_000


def rule_based_clean(text: str) -> str:
    """Apply fast rule-based cleaning. Always runs, zero latency."""
    if not text or not isinstance(text, str):
        return text

    # Strip injection patterns
    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub("", text)

    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Truncate if too long
    if len(text) > MAX_RESULT_LENGTH:
        text = text[:MAX_RESULT_LENGTH] + "\n...[truncated]"
        log.info("result_cleaner: truncated output to %d chars", MAX_RESULT_LENGTH)

    return text.strip()


class ResultCleaner:
    """Unified result cleaning: rules (always) + LLM (optional for EXTERNAL)."""

    def __init__(
        self,
        api_client: SupportsStreamingMessages | None = None,
        model: str = "glm-5.1",
        llm_cleaning_enabled: bool = False,
    ) -> None:
        self._api_client = api_client
        self._model = model
        self._llm_enabled = llm_cleaning_enabled and api_client is not None

    async def clean(self, text: str, *, category: str = "internal") -> str:
        """Clean tool result text.

        Args:
            text: Raw tool output
            category: Tool category ("external", "internal", "command")

        Returns:
            Cleaned text
        """
        if not text:
            return text

        # Step 1: rule-based (always, instant)
        result = rule_based_clean(text)

        # Step 2: LLM cleaning (only for EXTERNAL content when enabled)
        if self._llm_enabled and category == "external" and len(result) > 200:
            result = await self._llm_clean(result)

        return result

    async def _llm_clean(self, text: str) -> str:
        """One-pass LLM cleaning for external content."""
        if self._api_client is None:
            return text

        from opencortex.api.client import ApiMessageRequest
        from opencortex.engine.messages import ConversationMessage
        from opencortex.security.prompts import CLEANER_SYSTEM_PROMPT, CLEANER_QUERY_TEMPLATE

        import asyncio

        # Truncate input to avoid huge LLM calls
        input_text = text[:8_000] if len(text) > 8_000 else text

        query = CLEANER_QUERY_TEMPLATE.format(content=input_text)
        request = ApiMessageRequest(
            model=self._model,
            messages=[ConversationMessage.from_user_text(query)],
            system_prompt=CLEANER_SYSTEM_PROMPT,
            max_tokens=4096,
        )

        try:
            response_text = ""

            async def _stream():
                nonlocal response_text
                async for event in self._api_client.stream_message(request):
                    if hasattr(event, "text"):
                        response_text += event.text

            await asyncio.wait_for(_stream(), timeout=30.0)

            if response_text.strip():
                return response_text.strip()
            return text

        except asyncio.TimeoutError:
            log.warning("result_cleaner LLM timed out, returning rule-cleaned text")
            return text
        except Exception:
            log.exception("result_cleaner LLM failed, returning rule-cleaned text")
            return text
