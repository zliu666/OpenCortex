"""Tool result sanitizer — detects and removes injected instructions."""

from __future__ import annotations

import ast
import logging
import random
import re
from typing import TYPE_CHECKING

from opencortex.security.prompts import (
    DETECTOR_SYSTEM_PROMPT,
    DETECTOR_QUERY_TEMPLATE,
    SANITIZER_SYSTEM_PROMPT,
    SANITIZER_QUERY_TEMPLATE,
)

if TYPE_CHECKING:
    from opencortex.api.client import SupportsStreamingMessages

log = logging.getLogger(__name__)


class ToolResultSanitizer:
    """Detects and removes prompt-injection instructions from tool return values.

    Two-step process (from AgentSys):
    1. Ask LLM to detect if the text contains any instructions.
    2. If yes, ask LLM to extract them, then remove from the original text.
    """

    def __init__(self, api_client: SupportsStreamingMessages, model: str) -> None:
        self._api_client = api_client
        self._model = model

    async def sanitize(self, tool_result_text: str) -> str:
        """Return cleaned tool result with injected instructions removed."""
        # Step 1: detect
        has_instructions = await self._detect(tool_result_text)
        if not has_instructions:
            return tool_result_text

        # Step 2: extract + remove
        detected = await self._extract(tool_result_text)
        if not detected:
            return tool_result_text

        cleaned = self._remove_instructions(tool_result_text, detected)
        log.info("sanitizer removed %d instruction(s) from tool result", len(detected))
        return cleaned

    async def _detect(self, text: str) -> bool:
        """Ask LLM if text contains any instructions."""
        from opencortex.api.client import ApiMessageRequest
        from opencortex.engine.messages import ConversationMessage

        query = DETECTOR_QUERY_TEMPLATE.format(user_query=text)
        request = ApiMessageRequest(
            model=self._model,
            messages=[ConversationMessage.from_user_text(query)],
            system_prompt=DETECTOR_SYSTEM_PROMPT,
            max_tokens=10,
        )
        response_text = ""
        # Bug 8 fix: add 30s timeout to prevent security LLM from hanging indefinitely
        import asyncio
        try:
            async def _stream():
                nonlocal response_text
                async for event in self._api_client.stream_message(request):
                    if hasattr(event, "text"):
                        response_text += event.text
            await asyncio.wait_for(_stream(), timeout=30.0)
        except asyncio.TimeoutError:
            log.warning("Security detector LLM timed out after 30s, assuming safe")
            return False

        return "true" in response_text.lower()

    async def _extract(self, text: str) -> list[str]:
        """Ask LLM to extract instructions, return as list of strings."""
        from opencortex.api.client import ApiMessageRequest
        from opencortex.engine.messages import ConversationMessage

        query = SANITIZER_QUERY_TEMPLATE.format(user_query=text)
        request = ApiMessageRequest(
            model=self._model,
            messages=[ConversationMessage.from_user_text(query)],
            system_prompt=SANITIZER_SYSTEM_PROMPT,
            max_tokens=1024,
        )
        response_text = ""
        # Bug 8 fix: add 30s timeout to prevent security LLM from hanging indefinitely
        import asyncio
        try:
            async def _stream():
                nonlocal response_text
                async for event in self._api_client.stream_message(request):
                    if hasattr(event, "text"):
                        response_text += event.text
            await asyncio.wait_for(_stream(), timeout=30.0)
        except asyncio.TimeoutError:
            log.warning("Security extractor LLM timed out after 30s")
            return []

        return self._parse_detected_instructions(response_text)

    @staticmethod
    def _parse_detected_instructions(model_output: str) -> list[str]:
        """Parse the LLM output to extract the list of detected instructions."""
        if "<|Detected_Instructions|>" not in model_output:
            return []
        pattern = re.compile(
            r"<\|Detected_Instructions\|>(.*?)<\|/Detected_Instructions\|>",
            re.DOTALL,
        )
        match = pattern.search(model_output)
        if not match:
            return []
        content = match.group(1).strip()
        try:
            result = ast.literal_eval(content)
            if isinstance(result, list):
                return result
        except (ValueError, SyntaxError):
            pass
        return []

    @staticmethod
    def _remove_instructions(text: str, detected: list[str]) -> str:
        """Remove detected instruction sentences from text."""
        cleaned = text
        for sentence in detected:
            cleaned = _remove_sentence(cleaned, sentence)
        return cleaned


def _remove_sentence(text: str, sentence: str) -> str:
    """Remove a sentence from text, matching words flexibly."""
    if not isinstance(sentence, str) or not sentence.strip():
        return text
    inner = re.sub(r"^\W+|\W+$", "", sentence)
    words = [re.escape(w) for w in inner.split()]
    core = r"[\s\\\\]+".join(words)
    pattern = rf"\b{core}\b"
    return re.sub(rf"\s*{pattern}\s*", " ", text).strip()
