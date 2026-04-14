"""Core tool-aware query loop."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from opencortex.api.client import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiRetryEvent,
    ApiTextDeltaEvent,
    SupportsStreamingMessages,
)
from opencortex.api.usage import UsageSnapshot
from opencortex.engine.messages import ConversationMessage, ToolResultBlock
from opencortex.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from opencortex.engine.recovery import RecoveryAction, RecoveryChain, classify_api_error
from opencortex.hooks import HookEvent, HookExecutor
from opencortex.permissions.checker import PermissionChecker
from opencortex.tools.base import ToolExecutionContext
from opencortex.tools.base import ToolRegistry

log = logging.getLogger(__name__)


PermissionPrompt = Callable[[str, str], Awaitable[bool]]
AskUserPrompt = Callable[[str], Awaitable[str]]


class MaxTurnsExceeded(RuntimeError):
    """Raised when the agent exceeds the configured max_turns for one user prompt."""

    def __init__(self, max_turns: int) -> None:
        super().__init__(f"Exceeded maximum turn limit ({max_turns})")
        self.max_turns = max_turns


@dataclass
class QueryContext:
    """Context shared across a query run."""

    api_client: SupportsStreamingMessages
    tool_registry: ToolRegistry
    permission_checker: PermissionChecker
    cwd: Path
    model: str
    system_prompt: str
    max_tokens: int
    permission_prompt: PermissionPrompt | None = None
    ask_user_prompt: AskUserPrompt | None = None
    max_turns: int | None = 200
    hook_executor: HookExecutor | None = None
    tool_metadata: dict[str, object] | None = None
    security_layer: object | None = None  # SecurityLayer when enabled


async def run_query(
    context: QueryContext,
    messages: list[ConversationMessage],
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]:
    """Run the conversation loop until the model stops requesting tools.

    Auto-compaction is checked at the start of each turn.  When the
    estimated token count exceeds the model's auto-compact threshold,
    the engine first tries a cheap microcompact (clearing old tool result
    content) and, if that is not enough, performs a full LLM-based
    summarization of older messages.
    """
    from opencortex.services.compact import (
        AutoCompactState,
        auto_compact_if_needed,
    )

    compact_state = AutoCompactState()
    recovery = RecoveryChain(max_attempts=3)

    # Extract user query from first user message for security layer
    context._user_query = ""
    for _msg in messages:
        if hasattr(_msg, 'role') and _msg.role == 'user':
            _c = getattr(_msg, 'content', '')
            if isinstance(_c, str) and _c:
                context._user_query = _c[:500]
                break

    turn_count = 0
    judge_extensions = 0
    _MAX_JUDGE_EXTENSIONS = 5  # Hard cap: prevent infinite loops even if judge always says continue
    while context.max_turns is None or turn_count < context.max_turns:
        turn_count += 1
        # --- auto-compact check before calling the model ---------------
        messages, was_compacted = await auto_compact_if_needed(
            messages,
            api_client=context.api_client,
            model=context.model,
            system_prompt=context.system_prompt,
            state=compact_state,
        )
        # ---------------------------------------------------------------

        final_message: ConversationMessage | None = None
        usage = UsageSnapshot()

        # --- API call with recovery loop ---
        while True:
            try:
                async for event in context.api_client.stream_message(
                    ApiMessageRequest(
                        model=context.model,
                        messages=messages,
                        system_prompt=context.system_prompt,
                        max_tokens=context.max_tokens,
                        tools=context.tool_registry.to_api_schema(),
                    )
                ):
                    if isinstance(event, ApiTextDeltaEvent):
                        yield AssistantTextDelta(text=event.text), None
                        continue
                    if isinstance(event, ApiRetryEvent):
                        yield StatusEvent(
                            message=(
                                f"Request failed; retrying in {event.delay_seconds:.1f}s "
                                f"(attempt {event.attempt + 1} of {event.max_attempts}): {event.message}"
                            )
                        ), None
                        continue

                    if isinstance(event, ApiMessageCompleteEvent):
                        final_message = event.message
                        usage = event.usage
                # Success — reset recovery counter and break out of recovery loop
                recovery.reset()
                break
            except Exception as exc:
                classified = classify_api_error(exc)
                action = await recovery.handle(classified)
                if action == RecoveryAction.ABORT:
                    yield ErrorEvent(message=f"API error: {classified.message}"), None
                    return
                # Recoverable — notify user and retry
                yield StatusEvent(
                    message=(
                        f"Recovering from {classified.reason.value}: "
                        f"{action.value} (attempt {recovery._attempts}/{recovery._max_attempts})"
                    )
                ), None
                continue

        if final_message is None:
            raise RuntimeError("Model stream finished without a final message")

        messages.append(final_message)
        yield AssistantTurnComplete(message=final_message, usage=usage), usage

        if not final_message.tool_uses:
            return

        tool_calls = final_message.tool_uses

        if len(tool_calls) == 1:
            # Single tool: sequential (stream events immediately)
            tc = tool_calls[0]
            yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None
            result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
            yield ToolExecutionCompleted(
                tool_name=tc.name,
                output=result.content,
                is_error=result.is_error,
            ), None
            tool_results = [result]
        else:
            # Multiple tools: execute concurrently, emit events after
            for tc in tool_calls:
                yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None

            async def _run(tc):
                return await _execute_tool_call(context, tc.name, tc.id, tc.input)

            results = await asyncio.gather(*[_run(tc) for tc in tool_calls], return_exceptions=True)
            tool_results = []
            for r in results:
                if isinstance(r, Exception):
                    tool_results.append(ToolResultBlock(
                        tool_use_id="error",
                        content=f"Tool execution failed: {r}",
                        is_error=True,
                    ))
                else:
                    tool_results.append(r)

            for tc, result in zip(tool_calls, tool_results):
                yield ToolExecutionCompleted(
                    tool_name=tc.name,
                    output=result.content,
                    is_error=result.is_error,
                ), None

        messages.append(ConversationMessage(role="user", content=tool_results))

        # --- Judge Agent: auto-extend turns when limit reached -------
        if context.max_turns is not None and turn_count >= context.max_turns:
            if judge_extensions >= _MAX_JUDGE_EXTENSIONS:
                log.warning(
                    "[JudgeAgent] Reached max judge extensions (%d), stopping.",
                    _MAX_JUDGE_EXTENSIONS,
                )
                raise MaxTurnsExceeded(context.max_turns)
            try:
                should_continue = await _judge_should_extend(context, messages, turn_count)
            except Exception:
                log.warning("[JudgeAgent] _judge_should_extend raised, stopping.", exc_info=True)
                should_continue = False
            if should_continue:
                judge_extensions += 1
                turn_count = 0  # reset counter, continue in the same loop
                continue
            raise MaxTurnsExceeded(context.max_turns)

    raise RuntimeError("Query loop exited without a max_turns limit or final response")


async def _execute_tool_call(
    context: QueryContext,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict[str, object],
) -> ToolResultBlock:
    if context.hook_executor is not None:
        pre_hooks = await context.hook_executor.execute(
            HookEvent.PRE_TOOL_USE,
            {"tool_name": tool_name, "tool_input": tool_input, "event": HookEvent.PRE_TOOL_USE.value},
        )
        if pre_hooks.blocked:
            return ToolResultBlock(
                tool_use_id=tool_use_id,
                content=pre_hooks.reason or f"pre_tool_use hook blocked {tool_name}",
                is_error=True,
            )

    log.debug("tool_call start: %s id=%s", tool_name, tool_use_id)

    tool = context.tool_registry.get(tool_name)
    if tool is None:
        log.warning("unknown tool: %s", tool_name)
        return ToolResultBlock(
            tool_use_id=tool_use_id,
            content=f"Unknown tool: {tool_name}",
            is_error=True,
        )

    try:
        parsed_input = tool.input_model.model_validate(tool_input)
    except Exception as exc:
        log.warning("invalid input for %s: %s", tool_name, exc)
        return ToolResultBlock(
            tool_use_id=tool_use_id,
            content=f"Invalid input for {tool_name}: {exc}",
            is_error=True,
        )

    # Normalize common tool inputs before permission checks so path rules apply
    # consistently across built-in tools that use either `file_path` or `path`.
    _file_path = _resolve_permission_file_path(context.cwd, tool_input, parsed_input)
    _command = _extract_permission_command(tool_input, parsed_input)
    log.debug("permission check: %s read_only=%s path=%s cmd=%s",
              tool_name, tool.is_read_only(parsed_input), _file_path, _command and _command[:80])
    decision = context.permission_checker.evaluate(
        tool_name,
        is_read_only=tool.is_read_only(parsed_input),
        file_path=_file_path,
        command=_command,
    )
    if not decision.allowed:
        if decision.requires_confirmation and context.permission_prompt is not None:
            log.debug("permission prompt for %s: %s", tool_name, decision.reason)
            confirmed = await context.permission_prompt(tool_name, decision.reason)
            if not confirmed:
                log.debug("permission denied by user for %s", tool_name)
                return ToolResultBlock(
                    tool_use_id=tool_use_id,
                    content=f"Permission denied for {tool_name}",
                    is_error=True,
                )
        else:
            log.debug("permission blocked for %s: %s", tool_name, decision.reason)
            return ToolResultBlock(
                tool_use_id=tool_use_id,
                content=decision.reason or f"Permission denied for {tool_name}",
                is_error=True,
            )

    # ── Security layer check (after permission, before execution) ──
    security_layer = context.security_layer
    if security_layer is not None:
        from opencortex.security.security_layer import SecurityLayer
        assert isinstance(security_layer, SecurityLayer)
        tool_desc = getattr(tool, "description", "") or ""
        user_query = getattr(context, '_user_query', '') or ""
        # call_history placeholder — could be derived from messages in future
        sec_result = await security_layer.check_tool_call(
            tool_name=tool_name,
            tool_args=tool_input,
            tool_description=tool_desc,
            user_query=user_query,
            call_history="",
        )
        if not sec_result.allowed:
            log.info("security layer blocked: %s (%s)", tool_name, sec_result.reason)
            return ToolResultBlock(
                tool_use_id=tool_use_id,
                content=sec_result.reason,
                is_error=True,
            )

    log.debug("executing %s ...", tool_name)
    t0 = time.monotonic()
    result = await tool.execute(
        parsed_input,
        ToolExecutionContext(
            cwd=context.cwd,
            metadata={
                "tool_registry": context.tool_registry,
                "ask_user_prompt": context.ask_user_prompt,
                **(context.tool_metadata or {}),
            },
        ),
    )
    elapsed = time.monotonic() - t0
    log.debug("executed %s in %.2fs err=%s output_len=%d",
              tool_name, elapsed, result.is_error, len(result.output or ""))
    tool_result = ToolResultBlock(
        tool_use_id=tool_use_id,
        content=result.output,
        is_error=result.is_error,
    )

    # ── Security layer: sanitize tool output ──
    if security_layer is not None and not tool_result.is_error and tool_result.content:
        sanitized = await security_layer.sanitize_tool_result(tool_result.content)
        tool_result = ToolResultBlock(
            tool_use_id=tool_use_id,
            content=sanitized,
            is_error=False,
        )

    if context.hook_executor is not None:
        await context.hook_executor.execute(
            HookEvent.POST_TOOL_USE,
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_result.content,
                "tool_is_error": tool_result.is_error,
                "event": HookEvent.POST_TOOL_USE.value,
            },
        )
    return tool_result


def _resolve_permission_file_path(
    cwd: Path,
    raw_input: dict[str, object],
    parsed_input: object,
) -> str | None:
    for key in ("file_path", "path"):
        value = raw_input.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = cwd / path
            return str(path.resolve())

    for attr in ("file_path", "path"):
        value = getattr(parsed_input, attr, None)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = cwd / path
            return str(path.resolve())

    return None


def _extract_permission_command(
    raw_input: dict[str, object],
    parsed_input: object,
) -> str | None:
    value = raw_input.get("command")
    if isinstance(value, str) and value.strip():
        return value

    value = getattr(parsed_input, "command", None)
    if isinstance(value, str) and value.strip():
        return value

    return None


# ---------------------------------------------------------------------------
# Judge Agent: decides whether to extend turns when limit is reached
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM_PROMPT = """\
You are a Judge Agent. Your ONLY job is to review the task progress and decide:

1. Is the agent making meaningful progress toward the task goal?
2. Or is it stuck in a loop, repeating failed attempts, or doing nothing useful?

Recent tool calls and assistant messages are provided below.

Respond with ONLY one word:
- "continue" — if the agent is making progress and should get more turns
- "stop" — if the agent is stuck, looping, or the task appears complete
"""

async def _judge_should_extend(
    context: QueryContext,
    messages: list[ConversationMessage],
    turn_count: int,
) -> bool:
    """Ask the judge model whether the agent should get more turns.

    Uses the strongest available model (GLM 5.1) for high-quality judgment.
    Returns True to grant another batch of turns, False to stop.
    """
    import json

    log.info("[JudgeAgent] Turn limit reached (%d). Calling judge to evaluate progress...", turn_count)

    # Extract recent assistant messages (last 10) for context
    recent = messages[-10:] if len(messages) > 10 else messages
    summary_parts = []
    for msg in recent:
        role = msg.role
        if isinstance(msg.content, str):
            text = msg.content[:300]
        elif isinstance(msg.content, list):
            # Tool results or tool uses
            items = []
            for item in msg.content:
                if isinstance(item, dict):
                    if item.get("type") == "tool_result":
                        items.append(f"tool_result: {str(item.get('content', ''))[:100]}")
                    elif item.get("type") == "tool_use":
                        items.append(f"tool_call: {item.get('name', '?')}")
                elif isinstance(item, ToolResultBlock):
                    items.append(f"tool_result: {str(item.content)[:100]}")
            text = "; ".join(items)[:300]
        else:
            text = str(msg.content)[:300]
        summary_parts.append(f"[{role}] {text}")

    judge_prompt = "Recent activity:\n" + "\n".join(summary_parts)

    try:
        # Use GLM 5.1 (glm-5-turbo) as the judge model
        judge_api = context.api_client
        final_text = ""
        async for event in judge_api.stream_message(
            ApiMessageRequest(
                model=os.environ.get("OPENHARNESS_JUDGE_MODEL", "glm-5-turbo"),  # Judge model (configurable)
                messages=[{"role": "user", "content": judge_prompt}],
                system_prompt=_JUDGE_SYSTEM_PROMPT,
                max_tokens=10,
            )
        ):
            if isinstance(event, ApiMessageCompleteEvent):
                final_text = event.message.content or ""
                if isinstance(final_text, list):
                    final_text = final_text[0].get("text", "") if final_text else ""
                break

        decision = final_text.strip().lower()
        result = "continue" in decision

        log.info("[JudgeAgent] Decision: %s (raw: %s)", "CONTINUE" if result else "STOP", repr(final_text))
        return result

    except Exception as exc:
        log.warning("[JudgeAgent] Error calling judge, defaulting to continue: %s", exc)
        return True  # default: allow continuation on error
