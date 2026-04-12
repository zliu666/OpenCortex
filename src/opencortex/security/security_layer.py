"""SecurityLayer — main entry point that wires Validator, Sanitizer, PrivilegeAssignor."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opencortex.security.dispatcher import SubAgentDispatcher, DispatchResult
from opencortex.security.intent import IntentInjector
from opencortex.security.privilege import ToolPrivilege, ToolPrivilegeAssignor
from opencortex.security.sanitizer import ToolResultSanitizer
from opencortex.security.tool_classifier import ToolCategory, ToolClassifier
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
    category: ToolCategory | None = None
    stripped_args: dict | None = None  # tool args with intent removed


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
        dispatcher_enabled: bool = True,
        max_dispatch_depth: int = 5,
    ) -> None:
        self._classifier = ToolClassifier()
        self._validator = ToolCallValidator(api_client, model) if validator_enabled else None
        self._sanitizer = ToolResultSanitizer(api_client, model) if sanitizer_enabled else None
        self._privilege_assignor = ToolPrivilegeAssignor(api_client, model) if privilege_assignor_enabled else None
        self._dispatcher = SubAgentDispatcher(api_client, model, max_depth=max_dispatch_depth) if dispatcher_enabled else None
        self._intent_injector = IntentInjector()

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
        category = None

        # Step 0: rule-based tool classification
        category = self._classifier.classify(tool_name, tool_description)
        log.info("security layer: %s classified as %s", tool_name, category.value)

        # Step 1: classify privilege level
        if self._privilege_assignor is not None:
            privilege = await self._privilege_assignor.classify(
                tool_name, tool_description,
            )

        # Step 1b: extra scrutiny for Command tools
        if privilege == ToolPrivilege.COMMAND:
            log.info("security layer: %s classified as Command (write), applying strict validation",
                     tool_name)

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

        return SecurityCheckResult(allowed=True, privilege=privilege, category=category)

    async def sanitize_tool_result(self, tool_result_text: str) -> str:
        """Post-execution: remove injected instructions from tool output."""
        if self._sanitizer is None:
            return tool_result_text
        return await self._sanitizer.sanitize(tool_result_text)

    def strip_intent_from_args(self, tool_args: dict) -> dict:
        """Remove intent parameter from tool args before execution."""
        return self._intent_injector.strip_intent_from_args(tool_args)

    async def dispatch_external_result(
        self,
        tool_name: str,
        tool_result: str,
        intent: str | None = None,
    ) -> DispatchResult:
        """Dispatch EXTERNAL tool result to sub-agent for isolated processing."""
        if self._dispatcher is None:
            log.warning("dispatcher not enabled, returning raw result")
            return DispatchResult(
                success=True,
                content=tool_result,
                retries_used=0,
            )
        return await self._dispatcher.dispatch(tool_name, tool_result, intent)

    def truncate_command_result(self, tool_result: str, tool_name: str) -> str:
        """Truncate COMMAND tool results to confirmation only.

        Exception: if tool name contains 'get', return the full result.
        """
        if 'get' in tool_name.lower():
            return tool_result
        return f"Tool '{tool_name}' successfully executed."

    def should_dispatch(self, category: ToolCategory) -> bool:
        """Return True if this category should be dispatched to sub-agent."""
        return category == ToolCategory.EXTERNAL and self._dispatcher is not None
