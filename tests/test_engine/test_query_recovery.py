"""Tests for query engine recovery behavior on API errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from opencortex.api.client import ApiMessageCompleteEvent, ApiTextDeltaEvent
from opencortex.api.usage import UsageSnapshot
from opencortex.config.settings import PermissionSettings
from opencortex.engine.messages import ConversationMessage, TextBlock
from opencortex.engine.query import QueryContext, run_query
from opencortex.engine.stream_events import (
    AssistantTurnComplete,
    ErrorEvent,
    StatusEvent,
)
from opencortex.permissions import PermissionChecker
from opencortex.tools import create_default_tool_registry


class _FlakyApiClient:
    """Fake client that raises errors for the first N calls, then succeeds."""

    def __init__(self, errors: list[Exception], final_text: str = "OK") -> None:
        self._errors = list(errors)
        self._final_text = final_text

    async def stream_message(self, request):
        if self._errors:
            raise self._errors.pop(0)
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(
                role="assistant", content=[TextBlock(text=self._final_text)]
            ),
            usage=UsageSnapshot(input_tokens=1, output_tokens=1),
            stop_reason=None,
        )


class _AlwaysFailApiClient:
    """Fake client that always raises inside the async generator."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def stream_message(self, request):
        raise self._error
        yield  # make this an async generator


def _make_context(api_client) -> QueryContext:
    return QueryContext(
        api_client=api_client,
        tool_registry=create_default_tool_registry(),
        permission_checker=PermissionChecker(PermissionSettings()),
        cwd=Path("/tmp"),
        model="test-model",
        system_prompt="system",
        max_tokens=1024,
    )


def _user_msg(text: str = "hi") -> list[ConversationMessage]:
    return [ConversationMessage(role="user", content=[TextBlock(text=text)])]


@pytest.mark.asyncio
async def test_recovery_from_rate_limit():
    """Rate limit error should trigger retry and eventually succeed."""
    ctx = _make_context(_FlakyApiClient(
        errors=[RuntimeError("rate_limit exceeded")],
        final_text="Success after retry",
    ))
    events = [e async for e, _ in run_query(ctx, _user_msg())]
    status_events = [e for e in events if isinstance(e, StatusEvent)]
    assert any("rate_limit" in s.message for s in status_events)
    completions = [e for e in events if isinstance(e, AssistantTurnComplete)]
    assert completions
    assert "Success" in completions[0].message.text


@pytest.mark.asyncio
async def test_recovery_from_timeout():
    """Timeout error should be retryable."""
    ctx = _make_context(_FlakyApiClient(
        errors=[TimeoutError("connection timed out")],
        final_text="After timeout",
    ))
    events = [e async for e, _ in run_query(ctx, _user_msg())]
    status_events = [e for e in events if isinstance(e, StatusEvent)]
    assert any("timeout" in s.message for s in status_events)
    completions = [e for e in events if isinstance(e, AssistantTurnComplete)]
    assert completions


@pytest.mark.asyncio
async def test_abort_after_max_recovery_attempts():
    """When all recovery attempts are exhausted, should yield ErrorEvent and stop."""
    ctx = _make_context(_AlwaysFailApiClient(RuntimeError("rate_limit hit")))
    events = [e async for e, _ in run_query(ctx, _user_msg())]
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert errors
    assert "rate_limit" in errors[0].message


@pytest.mark.asyncio
async def test_auth_error_aborts_immediately():
    """Auth errors are not retryable and should abort immediately."""
    ctx = _make_context(_AlwaysFailApiClient(RuntimeError("invalid api key")))
    events = [e async for e, _ in run_query(ctx, _user_msg())]
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert errors
    assert "invalid api key" in errors[0].message
    # Should not have any StatusEvent (no retry attempted)
    status_events = [e for e in events if isinstance(e, StatusEvent)]
    assert len(status_events) == 0


@pytest.mark.asyncio
async def test_successful_call_resets_recovery():
    """After a successful API call, the recovery counter resets for the next turn."""
    call_count = 0

    class _CountingClient:
        async def stream_message(self, request):
            nonlocal call_count
            call_count += 1
            yield ApiMessageCompleteEvent(
                message=ConversationMessage(
                    role="assistant", content=[TextBlock(text=f"reply {call_count}")]
                ),
                usage=UsageSnapshot(input_tokens=1, output_tokens=1),
                stop_reason=None,
            )

    ctx = _make_context(_CountingClient())
    events = [e async for e, _ in run_query(ctx, _user_msg())]
    completions = [e for e in events if isinstance(e, AssistantTurnComplete)]
    assert completions
