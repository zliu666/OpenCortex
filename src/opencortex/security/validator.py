"""Tool call validator — three-tier strategy (whitelist / rules / LLM).

Tier 1: Whitelist — INTERNAL tools and known-safe patterns pass instantly.
Tier 2: Rules — dangerous command patterns are blocked instantly.
Tier 3: LLM — only for suspicious COMMAND calls; runs in parallel with execution.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from opencortex.security.tool_classifier import ToolCategory

if TYPE_CHECKING:
    from opencortex.api.client import SupportsStreamingMessages

log = logging.getLogger(__name__)


# ── Tier 2: Dangerous command patterns ─────────────────────────────────────

DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+-rf\s+/(?:\S|$)", re.I),
    re.compile(r"\bdd\s+if=", re.I),
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r">\s*/dev/sd", re.I),
    re.compile(r"\bcurl\b.*\|\s*(?:ba)?sh", re.I),
    re.compile(r"\bwget\b.*\|\s*(?:ba)?sh", re.I),
    re.compile(r"\bchmod\s+-R\s+777\s+/", re.I),
    re.compile(r"\bchown\s+-R\s+\S+\s+/", re.I),
    re.compile(r"nc\s+-[elp].*-\s*e\s", re.I),
    re.compile(r"/etc/passwd|/etc/shadow", re.I),
    re.compile(r"\bsudo\s+rm\b", re.I),
]

# Known-safe command prefixes (these never trigger Tier 3 even for COMMAND tools)
SAFE_COMMAND_PREFIXES = (
    "git status", "git log", "git diff", "git branch", "git show",
    "ls", "cat", "head", "tail", "grep", "find", "which", "echo",
    "pwd", "whoami", "hostname", "date", "python3 -c \"import",
    "pip list", "pip show", "npm list",
)


class ToolCallValidator:
    """Three-tier validation: whitelist → rules → LLM (only when needed)."""

    def __init__(
        self,
        api_client: SupportsStreamingMessages | None = None,
        model: str = "glm-5.1",
        llm_validation_enabled: bool = True,
    ) -> None:
        self._api_client = api_client
        self._model = model
        self._llm_enabled = llm_validation_enabled and api_client is not None

    async def validate(
        self,
        category: ToolCategory,
        tool_name: str,
        tool_args: dict,
        tool_description: str = "",
        user_query: str = "",
        call_history: str = "",
    ) -> bool:
        """Return True if the tool call is allowed.

        Three-tier strategy:
        1. INTERNAL tools → always pass (whitelist)
        2. COMMAND tools with dangerous patterns → always block (rules)
        3. Suspicious COMMAND calls → LLM validation (when enabled)
        """
        # ── Tier 1: Whitelist ──────────────────────────────────────
        if category == ToolCategory.INTERNAL:
            log.debug("validator: %s is INTERNAL, whitelisted", tool_name)
            return True

        # EXTERNAL tools are allowed (cleaning happens post-execution)
        if category == ToolCategory.EXTERNAL:
            log.debug("validator: %s is EXTERNAL, allowed (will be cleaned)", tool_name)
            return True

        # ── Tier 2: Rule-based check for COMMAND tools ─────────────
        if category == ToolCategory.COMMAND:
            # Check for safe commands first
            command_str = self._extract_command(tool_name, tool_args)
            if command_str:
                for safe_prefix in SAFE_COMMAND_PREFIXES:
                    if command_str.lower().startswith(safe_prefix):
                        log.debug("validator: %s matches safe prefix, allowed", tool_name)
                        return True

                # Check against dangerous patterns
                for pattern in DANGEROUS_PATTERNS:
                    if pattern.search(command_str):
                        log.warning(
                            "validator: BLOCKED %s — matched dangerous pattern: %s",
                            tool_name, pattern.pattern,
                        )
                        return False

            # Known-safe COMMAND tools (todo, task, plan, etc.)
            if tool_name in _SAFE_COMMAND_TOOLS:
                log.debug("validator: %s is known-safe COMMAND, allowed", tool_name)
                return True

        # ── Tier 3: LLM validation for remaining COMMAND tools ─────
        if self._llm_enabled and category == ToolCategory.COMMAND:
            log.info("validator: %s going to Tier 3 LLM validation", tool_name)
            return await self.validate_with_llm(
                tool_name=tool_name,
                tool_args=tool_args,
                tool_description=tool_description,
                user_query=user_query,
                call_history=call_history,
            )

        # Default allow for non-COMMAND that weren't caught above
        log.debug("validator: %s passed all tiers, allowed", tool_name)
        return True

    @staticmethod
    def _extract_command(tool_name: str, tool_args: dict) -> str | None:
        """Extract the command string from tool args for pattern matching."""
        for key in ("command", "cmd", "script"):
            val = tool_args.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return None

    async def validate_with_llm(
        self,
        tool_name: str,
        tool_args: dict,
        tool_description: str,
        user_query: str,
        call_history: str,
        timeout: float = 30.0,
    ) -> bool:
        """LLM-based validation for high-security mode. Not used by default."""
        if self._api_client is None:
            return True

        from opencortex.api.client import ApiMessageRequest
        from opencortex.engine.messages import ConversationMessage
        from opencortex.security.prompts import VALIDATOR_SYSTEM_PROMPT, VALIDATOR_QUERY_TEMPLATE

        import json
        func_call_str = json.dumps({"name": tool_name, "args": tool_args}, ensure_ascii=False)
        query = VALIDATOR_QUERY_TEMPLATE.format(
            func_description=tool_description,
            user_query=user_query,
            func_history=call_history or "(none)",
            new_func_call=func_call_str,
        )

        request = ApiMessageRequest(
            model=self._model,
            messages=[ConversationMessage.from_user_text(query)],
            system_prompt=VALIDATOR_SYSTEM_PROMPT,
            max_tokens=10,
        )

        try:
            response_text = ""
            async for event in self._api_client.stream_message(request):
                if hasattr(event, "text"):
                    response_text += event.text
        except Exception:
            log.exception("Validator LLM call failed, defaulting to block")
            return False

        result = response_text.strip().lower() == "true"
        log.debug("validator LLM result for %s: %s (raw: %s)", tool_name, result, response_text.strip())
        return result


# Known-safe COMMAND tools that never need validation
_SAFE_COMMAND_TOOLS = frozenset({
    "todo_write", "task_create", "task_update", "task_stop",
    "team_create", "team_delete",
    "cron_create", "cron_delete", "cron_toggle",
    "enter_plan_mode", "exit_plan_mode",
    "enter_worktree", "exit_worktree",
    "ask_user_question", "agent", "sleep",
    "skill", "notebook_edit",
    "mcp", "mcp_auth",
})
