"""Privilege assignor — classifies tools as Query (read) or Command (write)."""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

from opencortex.security.prompts import (
    PRIVILEGE_ASSIGN_SYSTEM_PROMPT,
    PRIVILEGE_ASSIGN_QUERY_TEMPLATE,
)

if TYPE_CHECKING:
    from opencortex.api.client import SupportsStreamingMessages

log = logging.getLogger(__name__)


class ToolPrivilege(str, Enum):
    QUERY = "query"      # read-only
    COMMAND = "command"  # write/modify


class ToolPrivilegeAssignor:
    """Classifies tools as Query or Command using an LLM.

    Adapted from AgentSys's AgentSysPrivilegeAssignor.
    """

    def __init__(self, api_client: SupportsStreamingMessages, model: str) -> None:
        self._api_client = api_client
        self._model = model
        self._cache: dict[str, ToolPrivilege] = {}

    async def classify(
        self,
        tool_name: str,
        tool_description: str,
        tool_parameters: str | None = None,
    ) -> ToolPrivilege:
        """Classify a tool as Query or Command.

        Results are cached by tool_name.
        """
        if tool_name in self._cache:
            return self._cache[tool_name]

        from opencortex.api.client import ApiMessageRequest
        from opencortex.engine.messages import ConversationMessage

        query = PRIVILEGE_ASSIGN_QUERY_TEMPLATE.format(
            func_str=tool_name,
            func_args=tool_parameters or "(unknown)",
            func_doc=tool_description,
        )
        request = ApiMessageRequest(
            model=self._model,
            messages=[ConversationMessage.from_user_text(query)],
            system_prompt=PRIVILEGE_ASSIGN_SYSTEM_PROMPT,
            max_tokens=10,
        )
        response_text = ""
        async for event in self._api_client.stream_message(request):
            if hasattr(event, "text"):
                response_text += event.text

        response_lower = response_text.lower()
        # Check "b" (Command) first for conservative classification.
        # When both "a" and "b" are present, default to the stricter Command.
        if "b" in response_lower:
            result = ToolPrivilege.COMMAND
        elif "a" in response_lower:
            result = ToolPrivilege.QUERY
        else:
            log.warning("privilege assignor returned ambiguous result for %s: %s, defaulting to Command",
                        tool_name, response_text.strip())
            result = ToolPrivilege.COMMAND

        self._cache[tool_name] = result
        log.debug("privilege assignor classified %s as %s", tool_name, result.value)
        return result
