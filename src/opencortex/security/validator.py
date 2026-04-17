"""Tool call validator — three-tier strategy (whitelist / rules / LLM).

Tier 1: Whitelist — INTERNAL tools (with sensitive-path check) and known-safe tools pass instantly.
Tier 2: Rules — dangerous command patterns and shell metacharacters are blocked.
Tier 3: LLM — only for suspicious COMMAND calls; runs in parallel with execution.

Core principle: FAIL-CLOSED. Any unknown or ambiguous case defaults to block (return False).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from opencortex.security.tool_classifier import ToolCategory

if TYPE_CHECKING:
    from opencortex.api.client import SupportsStreamingMessages

log = logging.getLogger(__name__)


# ── Shell metacharacter detection (H1 fix) ─────────────────────────────────

# Characters/sequences that indicate command chaining or injection
_SHELL_METACHAR_PATTERN = (
    r"[;\n\r]"              # command separators: ; newline
    r"|\|\|?"               # pipes: | ||
    r"|&&"                  # and-chain
    r"|\$\("                # command substitution: $()
    r"|`"                   # backtick substitution
    r"|>{1,2}\s*/"          # redirect to absolute path: > /... >> /...
    r"|\\x[0-9a-f]{2}"     # hex escapes
)
_SHELL_METACHAR_RE = re.compile(_SHELL_METACHAR_PATTERN, re.I)

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
    re.compile(r"\bnc\s+-[elp].*-\s*e\s", re.I),
    re.compile(r"\bnc\s+-e\s", re.I),           # M3 fix: simplified nc reverse shell
    re.compile(r"/etc/passwd|/etc/shadow", re.I),
    re.compile(r"\bsudo\s+rm\b", re.I),
    re.compile(r"\bpython[23]?\s+-c\b.*\bimport\s+(?:os|subprocess|shutil|socket)\s*\.\s*(?:system|popen|exec|run|call|remove|rmtree)", re.I),  # python dangerous imports
    re.compile(r"\b(eval|exec)\s*\(", re.I),      # eval/exec in commands
]

# Known-safe command prefixes (only for pure commands without metacharacters)
SAFE_COMMAND_PREFIXES = (
    # VCS
    "git status", "git log", "git diff", "git branch", "git show", "git stash",
    "git remote", "git config", "git tag",
    # Read-only system
    "ls", "cat", "head", "tail", "grep", "find", "which", "echo",
    "pwd", "whoami", "hostname", "date", "env", "printenv",
    "stat", "file", "wc", "diff", "sort", "uniq", "tr", "cut",
    # Development tools (common in AI-assisted coding)
    "python3", "python", "pip list", "pip show", "pip check",
    "pytest", "py.test",
    "npm list", "npm test", "npm run",
    "node", "npx",
    "cargo check", "cargo test", "cargo build",
    "go test", "go build", "go vet",
    "make", "cmake",
    "docker ps", "docker images", "docker logs",
    "kubectl get", "kubectl describe", "kubectl logs",
    # Safe compute
    "bc", "expr", "python3 -c \"", "python -c \"",
)

# ── Sensitive path detection (H4 fix) ──────────────────────────────────────

_SENSITIVE_PATH_RE = re.compile(
    r"/etc/(?:passwd|shadow|ssh|hosts|gshadow|group)\b"
    r"|/\.ssh/(?:id_rsa|id_ed25519|id_ecdsa|authorized_keys|config)\b"
    r"|/\.gnupg/"
    r"|/\.aws/(?:credentials|config)\b"
    r"|/\.env\b"
    r"|/root/\."
    r"|\bPRIVATE\s+KEY\b"
    r"|\bBEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY\b",
    re.I,
)


class ToolCallValidator:
    """Three-tier validation: whitelist → rules → LLM (only when needed).

    FAIL-CLOSED design: any case not explicitly allowed is blocked.
    """

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

        Three-tier strategy (FAIL-CLOSED):
        1. INTERNAL tools → pass (unless sensitive-path args detected)
        2. COMMAND tools with dangerous patterns → block
        3. Remaining COMMAND → LLM validation or block
        """
        # ── Tier 1: Whitelist ──────────────────────────────────────

        if category == ToolCategory.INTERNAL:
            # H4 fix: check for sensitive paths in arguments
            if self._has_sensitive_args(tool_args):
                log.warning(
                    "validator: BLOCKED INTERNAL %s — sensitive path in args", tool_name
                )
                return False
            log.debug("validator: %s is INTERNAL, whitelisted", tool_name)
            return True

        # EXTERNAL tools are allowed (cleaning happens post-execution)
        if category == ToolCategory.EXTERNAL:
            log.debug("validator: %s is EXTERNAL, allowed (will be cleaned)", tool_name)
            return True

        # ── COMMAND tools ───────────────────────────────────────────

        if category == ToolCategory.COMMAND:
            # Known-safe COMMAND tools (highest priority for COMMAND)
            if tool_name in _SAFE_COMMAND_TOOLS:
                log.debug("validator: %s is known-safe COMMAND, allowed", tool_name)
                return True

            # Structured write tools (write_file, file_edit, mkdir, etc.)
            # These don't execute shell commands — only check for sensitive paths.
            if self._is_structured_write_tool(tool_name, tool_args):
                if self._has_sensitive_args(tool_args):
                    log.warning(
                        "validator: BLOCKED structured write %s — sensitive path in args",
                        tool_name,
                    )
                    return False
                log.debug("validator: %s is structured write tool, allowed", tool_name)
                return True

            # Extract command string (deep search — H2 fix)
            command_str = self._extract_command(tool_name, tool_args)

            if command_str:
                # H1 fix: check for shell metacharacters FIRST
                if self._has_shell_metacharacters(command_str):
                    log.warning(
                        "validator: %s has shell metacharacters, cannot use safe-prefix bypass",
                        tool_name,
                    )
                    # Fall through to dangerous pattern check, then LLM/block
                else:
                    # No metacharacters — safe to check known-safe prefixes
                    for safe_prefix in SAFE_COMMAND_PREFIXES:
                        if command_str.lower().startswith(safe_prefix):
                            # Even with safe prefix, check ALL other arg values
                            # for hidden injection (H2 extended)
                            if self._has_dangerous_in_args(tool_args, exclude_keys=("command", "cmd", "script")):
                                log.warning(
                                    "validator: BLOCKED %s — dangerous pattern in non-command args",
                                    tool_name,
                                )
                                return False
                            log.debug(
                                "validator: %s matches safe prefix (no metachars), allowed",
                                tool_name,
                            )
                            return True

                # Check against dangerous patterns (always, even with metacharacters)
                for pattern in DANGEROUS_PATTERNS:
                    if pattern.search(command_str):
                        log.warning(
                            "validator: BLOCKED %s — matched dangerous pattern: %s",
                            tool_name, pattern.pattern,
                        )
                        return False

            # H2 extended: check ALL string values in args for hidden injection
            if self._has_dangerous_in_args(tool_args):
                log.warning(
                    "validator: BLOCKED %s — dangerous pattern detected in args",
                    tool_name,
                )
                return False

            # ── Tier 3: LLM validation for remaining COMMAND tools ─────
            if self._llm_enabled:
                log.info("validator: %s going to Tier 3 LLM validation", tool_name)
                return await self.validate_with_llm(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_description=tool_description,
                    user_query=user_query,
                    call_history=call_history,
                )

            # FAIL-CLOSED: no LLM available, unknown COMMAND → block
            log.warning(
                "validator: BLOCKED %s — COMMAND with no LLM validator, fail-closed",
                tool_name,
            )
            return False

        # Unknown category — fail-closed
        log.warning("validator: BLOCKED %s — unknown category %s", tool_name, category)
        return False

    # ── Helper methods ──────────────────────────────────────────────────────

    @staticmethod
    def _has_shell_metacharacters(command: str) -> bool:
        """Check if a command string contains shell metacharacters.

        Commands with metacharacters cannot use the safe-prefix fast path.
        """
        return bool(_SHELL_METACHAR_RE.search(command))

    @staticmethod
    def _has_sensitive_args(tool_args: dict) -> bool:
        """Check if tool arguments contain references to sensitive paths.

        Prevents INTERNAL tools from reading /etc/shadow, ~/.ssh/id_rsa, etc.
        """
        for value in tool_args.values():
            if isinstance(value, str) and _SENSITIVE_PATH_RE.search(value):
                return True
        return False

    # Tools that perform structured writes (not shell execution).
    # Identified by having no 'command'/'cmd'/'script' keys in args.
    _STRUCTURED_WRITE_PREFIXES = (
        "write_", "edit_", "file_edit", "file_write",
        "mkdir", "cp", "mv", "touch", "create_",
        "update_", "todo_write", "notebook_edit",
    )

    def _is_structured_write_tool(self, tool_name: str, tool_args: dict) -> bool:
        """Check if this is a structured write tool (not a shell command).

        Structured tools don't have 'command'/'cmd'/'script' keys — they have
        structured arguments like 'path', 'content', etc.
        """
        # If it has a command key, it's shell-like, not structured
        for key in ("command", "cmd", "script"):
            if key in tool_args:
                return False
        # Check against known structured write tool prefixes
        for prefix in self._STRUCTURED_WRITE_PREFIXES:
            if tool_name.startswith(prefix) or tool_name == prefix:
                return True
        return False

    def _has_dangerous_in_args(self, tool_args: dict, *, exclude_keys: tuple = ()) -> bool:
        """Recursively check ALL string values in tool_args for dangerous patterns.

        H2 extended: injection can hide in nested args, not just 'command' key.
        """
        def _check_value(val):
            if isinstance(val, str):
                for pattern in DANGEROUS_PATTERNS:
                    if pattern.search(val):
                        return True
                if self._has_shell_metacharacters(val):
                    return True
            elif isinstance(val, dict):
                for k, v in val.items():
                    if k not in exclude_keys and _check_value(v):
                        return True
            elif isinstance(val, list):
                for item in val:
                    if _check_value(item):
                        return True
            return False

        for key, val in tool_args.items():
            if key in exclude_keys:
                continue
            if _check_value(val):
                return True
        return False

    @staticmethod
    def _extract_command(tool_name: str, tool_args: dict) -> str | None:
        """Extract command string from tool args — deep search (H2 fix).

        Checks standard keys first, then falls back to searching ALL string values.
        """
        # Priority keys
        for key in ("command", "cmd", "script"):
            val = tool_args.get(key)
            if isinstance(val, str) and val.strip():
                return val

        # Deep search: any string value that looks like a shell command
        for key, val in tool_args.items():
            if key in ("command", "cmd", "script"):
                continue  # already checked
            if isinstance(val, str) and val.strip() and len(val) > 2:
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
        """LLM-based validation for high-security mode."""
        if self._api_client is None:
            return False  # fail-closed

        from opencortex.api.client import ApiMessageRequest
        from opencortex.engine.messages import ConversationMessage
        from opencortex.security.prompts import VALIDATOR_SYSTEM_PROMPT, VALIDATOR_QUERY_TEMPLATE

        import asyncio
        import json

        func_call_str = json.dumps({"name": tool_name, "args": tool_args}, ensure_ascii=False)

        # H5 fix: sanitize user input before inserting into prompt
        safe_user_query = self._sanitize_prompt_input(user_query, max_len=500)
        safe_history = self._sanitize_prompt_input(call_history or "(none)", max_len=1000)

        query = VALIDATOR_QUERY_TEMPLATE.format(
            func_description=tool_description,
            user_query=safe_user_query,
            func_history=safe_history,
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

            async def _stream():
                nonlocal response_text
                async for event in self._api_client.stream_message(request):
                    if hasattr(event, "text"):
                        response_text += event.text

            # M4 fix: actually use the timeout parameter
            await asyncio.wait_for(_stream(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("validator LLM timed out, failing closed (blocked)")
            return False
        except Exception:
            log.exception("Validator LLM call failed, failing closed (blocked)")
            return False

        result = response_text.strip().lower() == "true"
        log.debug("validator LLM result for %s: %s (raw: %s)", tool_name, result, response_text.strip())
        return result

    @staticmethod
    def _sanitize_prompt_input(text: str, max_len: int = 500) -> str:
        """H5 fix: sanitize user input before inserting into LLM prompt.

        - Truncate to max_len
        - Remove control characters except common whitespace
        - Strip known injection patterns
        """
        if not text:
            return ""
        # Remove control characters (keep \t \n \r)
        cleaned = "".join(c for c in text if c.isprintable() or c in "\t\n\r")
        # Truncate
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len] + "...[truncated]"
        return cleaned


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
