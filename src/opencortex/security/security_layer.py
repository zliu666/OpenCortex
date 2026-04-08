"""SecurityLayer — main entry point that wires Validator, Sanitizer, PrivilegeAssignor."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opencortex.security.privilege import ToolPrivilege, ToolPrivilegeAssignor
from opencortex.security.sanitizer import ToolResultSanitizer
from opencortex.security.validator import ToolCallValidator

if TYPE_CHECKING:
    from opencortex.api.client import SupportsStreamingMessages

log = logging.getLogger(__name__)


@dataclass
class SecurityCheckResult:
    """Result of a security check on a tool call."""
    allowed: bool
    reason: str = ""
    sanitized_output: str | None = None  # set after tool execution if sanitizer runs
    privilege: ToolPrivilege | None = None


class SecurityLayer:
    """Orchestrates the three AgentSys security components.

    Each component can be individually toggled. When the whole layer is
    disabled (via settings), all checks pass through with zero overhead.
    """

    def __init__(
        self,
        api_client: SupportsStreamingMessages,
        model: str = "glm-5.1",
        *,
        validator_enabled: bool = True,
        sanitizer_enabled: bool = True,
        privilege_assignor_enabled: bool = True,
    ) -> None:
        self._validator = ToolCallValidator(api_client, model) if validator_enabled else None
        self._sanitizer = ToolResultSanitizer(api_client, model) if sanitizer_enabled else None
        self._privilege_assignor = ToolPrivilegeAssignor(api_client, model) if privilege_assignor_enabled else None

    async def check_tool_call(
        self,
        tool_name: str,
        tool_args: dict,
        tool_description: str,
        user_query: str,
        call_history: str = "",
    ) -> SecurityCheckResult:
        """Pre-execution check: validate tool call is safe + necessary.

        Returns SecurityCheckResult with allowed=True/False.
        """
        privilege = None

        # Step 1: classify privilege level
        if self._privilege_assignor is not None:
            privilege = await self._privilege_assignor.classify(
                tool_name, tool_description,
            )

        # Step 2: validate safety + necessity
        if self._validator is not None:
            allowed = await self._validator.validate(
                tool_name, tool_args, tool_description,
                user_query, call_history,
            )
            if not allowed:
                log.warning("security layer blocked tool call: %s", tool_name)
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"Security validator blocked {tool_name}: deemed unsafe or unnecessary",
                    privilege=privilege,
                )

        return SecurityCheckResult(allowed=True, privilege=privilege)

    async def sanitize_tool_result(self, tool_result_text: str) -> str:
        """Post-execution: remove injected instructions from tool output."""
        if self._sanitizer is None:
            return tool_result_text
        return await self._sanitizer.sanitize(tool_result_text)
