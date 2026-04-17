"""High-level conversation engine."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncIterator, Any

from opencortex.api.client import SupportsStreamingMessages
from opencortex.engine.cost_tracker import CostTracker
from opencortex.engine.messages import ConversationMessage, ToolResultBlock
from opencortex.engine.query import AskUserPrompt, PermissionPrompt, QueryContext, run_query
from opencortex.engine.stream_events import StreamEvent
from opencortex.hooks import HookExecutor
from opencortex.permissions.checker import PermissionChecker
from opencortex.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class QueryEngine:
    """Owns conversation history and the tool-aware model loop."""

    def __init__(
        self,
        *,
        api_client: SupportsStreamingMessages,
        tool_registry: ToolRegistry,
        permission_checker: PermissionChecker,
        cwd: str | Path,
        model: str,
        system_prompt: str,
        max_tokens: int = 4096,
        max_turns: int | None = 8,
        permission_prompt: PermissionPrompt | None = None,
        ask_user_prompt: AskUserPrompt | None = None,
        hook_executor: HookExecutor | None = None,
        tool_metadata: dict[str, object] | None = None,
        memory_dir: Path | None = None,
    ) -> None:
        self._api_client = api_client
        self._tool_registry = tool_registry
        self._permission_checker = permission_checker
        self._cwd = Path(cwd).resolve()
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._max_turns = max_turns
        self._permission_prompt = permission_prompt
        self._ask_user_prompt = ask_user_prompt
        self._hook_executor = hook_executor
        self._tool_metadata = tool_metadata or {}
        self._messages: list[ConversationMessage] = []
        self._cost_tracker = CostTracker()
        self._security_layer: object | None = None
        self._provider_key: str = "primary"  # for per-model cost tracking

        # Memory pipeline integration
        self._memory_pipeline: Any | None = None
        self._turn_count: int = 0
        if memory_dir is not None:
            try:
                from opencortex.memory.pipeline import MemoryPipeline
                self._memory_pipeline = MemoryPipeline(memory_dir)
                logger.info("Memory pipeline initialized: %s", memory_dir)
            except Exception as exc:
                logger.warning("Failed to init memory pipeline: %s", exc)

    @property
    def messages(self) -> list[ConversationMessage]:
        """Return the current conversation history."""
        return list(self._messages)

    @property
    def max_turns(self) -> int | None:
        """Return the maximum number of agentic turns per user input, if capped."""
        return self._max_turns

    @property
    def total_usage(self):
        """Return the total usage across all turns."""
        return self._cost_tracker.total

    def set_security_layer(self, layer: object | None) -> None:
        """Set or clear the security layer for future turns."""
        self._security_layer = layer

    def clear(self) -> None:
        """Clear the in-memory conversation history."""
        self._messages.clear()
        self._cost_tracker = CostTracker()

    def set_system_prompt(self, prompt: str) -> None:
        """Update the active system prompt for future turns."""
        self._system_prompt = prompt

    def set_model(self, model: str) -> None:
        """Update the active model for future turns."""
        self._model = model

    def set_api_client(self, api_client: SupportsStreamingMessages) -> None:
        """Update the active API client for future turns."""
        self._api_client = api_client

    def set_max_turns(self, max_turns: int | None) -> None:
        """Update the maximum number of agentic turns per user input."""
        self._max_turns = None if max_turns is None else max(1, int(max_turns))

    def set_permission_checker(self, checker: PermissionChecker) -> None:
        """Update the active permission checker for future turns."""
        self._permission_checker = checker

    def load_messages(self, messages: list[ConversationMessage]) -> None:
        """Replace the in-memory conversation history."""
        self._messages = list(messages)

    def has_pending_continuation(self) -> bool:
        """Return True when the conversation ends with tool results awaiting a follow-up model turn."""
        if not self._messages:
            return False
        last = self._messages[-1]
        if last.role != "user":
            return False
        if not any(isinstance(block, ToolResultBlock) for block in last.content):
            return False
        for msg in reversed(self._messages[:-1]):
            if msg.role != "assistant":
                continue
            return bool(msg.tool_uses)
        return False

    async def submit_message(self, prompt: str | ConversationMessage) -> AsyncIterator[StreamEvent]:
        """Append a user message and execute the query loop."""
        user_message = (
            prompt
            if isinstance(prompt, ConversationMessage)
            else ConversationMessage.from_user_text(prompt)
        )
        self._messages.append(user_message)
        self._turn_count += 1

        # Memory: prefetch + inject into system prompt (only first time)
        effective_prompt = self._system_prompt
        if self._memory_pipeline is not None:
            try:
                await self._memory_pipeline.prefetch()
                effective_prompt = self._memory_pipeline.inject_into(self._system_prompt)
            except Exception as exc:
                logger.warning("Memory prefetch/inject failed: %s", exc)

        # Bug 2 fix: load SESSION tier memories into system prompt for short-term recall
        session_context = self._load_session_context()
        if session_context:
            effective_prompt += f"\n\n<session-memory>\n{session_context}\n</session-memory>"

        # Bug 4 fix: only send the last 20 messages to the API, preserving first user msg
        messages_for_api = self._trim_messages_for_api(self._messages, max_messages=20)

        context = QueryContext(
            api_client=self._api_client,
            tool_registry=self._tool_registry,
            permission_checker=self._permission_checker,
            cwd=self._cwd,
            model=self._model,
            system_prompt=effective_prompt,
            max_tokens=self._max_tokens,
            max_turns=self._max_turns,
            permission_prompt=self._permission_prompt,
            ask_user_prompt=self._ask_user_prompt,
            hook_executor=self._hook_executor,
            tool_metadata=self._tool_metadata,
            security_layer=self._security_layer,
        )
        # Bug 4 fix: use trimmed messages for API call
        async for event, usage in run_query(context, messages_for_api):
            if usage is not None:
                self._cost_tracker.add(usage, provider_key=self._provider_key)
            yield event

        # Bug 1 fix: truncate oversized tool results + microcompact after each turn
        try:
            from opencortex.services.compact import truncate_tool_results, microcompact_messages
            truncated = truncate_tool_results(self._messages)
            if truncated > 0:
                logger.info("Truncated %d oversized tool results", truncated)
            self._messages, saved = microcompact_messages(self._messages)
            if saved > 0:
                logger.info("Microcompact saved ~%d tokens", saved)
        except Exception as exc:
            logger.warning("Post-turn compact failed: %s", exc)

        # Bug 2 fix: persist user/assistant messages to SESSION tier for short-term recall
        self._persist_to_session_memory(user_message)

        # Memory: post-process after query completes
        if self._memory_pipeline is not None:
            try:
                raw_msgs = [
                    {"role": m.role, "content": str(m.content)}
                    for m in self._messages
                    if m.role in ("user", "assistant")
                ]
                await self._memory_pipeline.post_process(raw_msgs, self._turn_count)
            except Exception as exc:
                logger.warning("Memory post_process failed: %s", exc)

    # -- Bug 2 fix: SESSION tier helpers for short-term memory --

    def _get_session_store(self) -> Any | None:
        """Lazy-init a TieredMemoryStore for SESSION tier."""
        if not hasattr(self, '_session_store'):
            self._session_store = None
            try:
                from opencortex.memory.tiered_store import TieredMemoryStore, MemoryTier
            except ImportError as exc:
                logger.warning("TieredMemoryStore not available (import failed): %s", exc)
                return None
            try:
                self._session_store = TieredMemoryStore()
                self._session_tier = MemoryTier.SESSION
            except (TypeError, ValueError, AttributeError) as exc:
                logger.warning("TieredMemoryStore init failed (config/args error): %s", exc)
                return None
            except Exception as exc:
                # Unexpected init errors — log at higher level so they're not silently swallowed
                logger.error("TieredMemoryStore init failed unexpectedly: %s", exc, exc_info=True)
                return None
        return self._session_store

    def _persist_to_session_memory(self, user_message: ConversationMessage) -> None:
        """Bug 2 fix: write user message to SESSION tier so it survives compaction."""
        store = self._get_session_store()
        if store is None:
            return
        try:
            text = user_message.text.strip()
            if text:
                store.add_entry(self._session_tier, text, tags=["session"])
        except Exception as exc:
            logger.debug("Session memory persist failed: %s", exc)

    def _load_session_context(self) -> str:
        """Bug 2 fix: load SESSION tier memories for injection into system prompt."""
        store = self._get_session_store()
        if store is None:
            return ""
        try:
            return store.load_context()
        except Exception as exc:
            logger.debug("Session memory load failed: %s", exc)
            return ""

    # -- Bug 4 fix: trim messages before sending to API --

    @staticmethod
    def _trim_messages_for_api(
        messages: list[ConversationMessage], *, max_messages: int = 20
    ) -> list[ConversationMessage]:
        """Bug 4 fix: only send the last N messages, preserving the first user message.

        This prevents sending huge conversation histories to the API, saving tokens.
        """
        if len(messages) <= max_messages:
            return messages
        # Always keep the first user message for context
        first_user = None
        for m in messages:
            if m.role == "user":
                first_user = m
                break
        tail = messages[-max_messages:]
        if first_user is not None and first_user not in tail:
            return [first_user] + tail
        return tail

    async def continue_pending(self, *, max_turns: int | None = None) -> AsyncIterator[StreamEvent]:
        """Continue an interrupted tool loop without appending a new user message."""
        context = QueryContext(
            api_client=self._api_client,
            tool_registry=self._tool_registry,
            permission_checker=self._permission_checker,
            cwd=self._cwd,
            model=self._model,
            system_prompt=self._system_prompt,
            max_tokens=self._max_tokens,
            max_turns=max_turns if max_turns is not None else self._max_turns,
            permission_prompt=self._permission_prompt,
            ask_user_prompt=self._ask_user_prompt,
            hook_executor=self._hook_executor,
            tool_metadata=self._tool_metadata,
            security_layer=self._security_layer,
        )
        async for event, usage in run_query(context, self._messages):
            if usage is not None:
                self._cost_tracker.add(usage, provider_key=self._provider_key)
            yield event
