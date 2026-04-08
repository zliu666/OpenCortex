"""Tool call validator — checks if a tool call is safe and necessary."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opencortex.security.prompts import VALIDATOR_SYSTEM_PROMPT, VALIDATOR_QUERY_TEMPLATE

if TYPE_CHECKING:
    from opencortex.api.client import SupportsStreamingMessages, ApiStreamEvent

log = logging.getLogger(__name__)


class ToolCallValidator:
    """Uses an LLM to judge whether a tool call is safe and necessary.

    Adapted from AgentSys's AgentSysValidator, but uses OpenCortex's own
    API client instead of agentdojo's pipeline.
    """

    def __init__(self, api_client: SupportsStreamingMessages, model: str) -> None:
        self._api_client = api_client
        self._model = model

    async def validate(
        self,
        tool_name: str,
        tool_args: dict,
        tool_description: str,
        user_query: str,
        call_history: str,
    ) -> bool:
        """Return True if the tool call is deemed safe and necessary."""
        from opencortex.api.client import ApiMessageRequest
        from opencortex.engine.messages import ConversationMessage

        new_func_call = f"{tool_name}({tool_args})"
        query = VALIDATOR_QUERY_TEMPLATE.format(
            func_description=tool_description,
            user_query=user_query,
            func_history=call_history or "(none)",
            new_func_call=new_func_call,
        )

        request = ApiMessageRequest(
            model=self._model,
            messages=[ConversationMessage.from_user_text(query)],
            system_prompt=VALIDATOR_SYSTEM_PROMPT,
            max_tokens=10,
        )

        response_text = ""
        async for event in self._api_client.stream_message(request):
            if hasattr(event, "text"):
                response_text += event.text

        result = "true" in response_text.lower()
        log.debug("validator result for %s: %s (raw: %s)", tool_name, result, response_text.strip())
        return result
