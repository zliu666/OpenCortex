"""Tests for SubAgentDispatcher — isolation for external tool results."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opencortex.security.dispatcher import DispatchResult, SubAgentDispatcher, SUBAGENT_SYSTEM_PROMPT


class MockApiClient:
    """Mock API client for testing."""

    def __init__(self, response_text: str = '{"summary": "test content"}'):
        self.response_text = response_text
        self.stream_message = self._create_stream(response_text)

    def _create_stream(self, response_text: str):
        """Create an async generator that simulates streaming."""
        async def stream_generator(request):
            event = MagicMock()
            event.text = response_text
            yield event
            event = MagicMock()
            event.text = ""
            yield event

        # Return the generator function, not a generator instance
        return stream_generator


class TestSubAgentDispatcherInit:
    def test_default_values(self):
        mock_client = MagicMock()
        dispatcher = SubAgentDispatcher(mock_client, "model-x")
        assert dispatcher.max_depth == 5
        assert dispatcher.max_retries == 3
        assert dispatcher.depth == 0
        assert dispatcher.call_stack == []

    def test_custom_values(self):
        mock_client = MagicMock()
        dispatcher = SubAgentDispatcher(
            mock_client,
            "model-y",
            max_depth=3,
            max_retries=2,
        )
        assert dispatcher.max_depth == 3
        assert dispatcher.max_retries == 2


class TestSubAgentDispatcherMaxDepth:
    @pytest.mark.asyncio
    async def test_max_depth_exceeded(self):
        mock_client = MagicMock()
        dispatcher = SubAgentDispatcher(mock_client, "model", max_depth=2)
        # Manually set depth to limit
        dispatcher._depth = 2

        result = await dispatcher.dispatch("web_search", "some result")
        assert not result.success
        assert "depth" in result.error.lower()
        assert result.content == ""


class TestSubAgentDispatcherRecursiveProtection:
    @pytest.mark.asyncio
    async def test_recursive_dispatch_blocked(self):
        mock_client = MagicMock()
        dispatcher = SubAgentDispatcher(mock_client, "model")

        # First call adds to call stack
        dispatcher._call_stack.append("web_search")
        dispatcher._depth = 1

        # Try to dispatch same tool again
        result = await dispatcher.dispatch("web_search", "some result")

        assert not result.success
        assert "recursive" in result.error.lower()


class TestSubAgentDispatchSuccess:
    @pytest.mark.asyncio
    async def test_successful_dispatch_returns_json(self):
        mock_client = MagicMock()
        
        async def mock_stream(request):
            event = MagicMock()
            event.text = '{"summary": "The weather is sunny today"}'
            yield event

        mock_client.stream_message = mock_stream

        dispatcher = SubAgentDispatcher(mock_client, "model")
        result = await dispatcher.dispatch("web_fetch", "HTML content...", intent="Get weather")

        assert result.success
        assert "summary" in result.content
        assert result.retries_used == 0
        assert result.error is None


class TestSubAgentDispatchNonJsonOutput:
    @pytest.mark.asyncio
    async def test_non_json_but_non_empty_accepted(self):
        mock_client = MagicMock()

        async def mock_stream(request):
            event = MagicMock()
            event.text = "The weather is sunny today"
            yield event

        mock_client.stream_message = mock_stream

        dispatcher = SubAgentDispatcher(mock_client, "model")
        result = await dispatcher.dispatch("web_fetch", "HTML content...")

        assert result.success
        assert result.content == "The weather is sunny today"


class TestSubAgentDispatchWithRetry:
    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        mock_client = MagicMock()
        call_count = 0

        async def mock_stream(request):
            nonlocal call_count
            call_count += 1
            event = MagicMock()
            if call_count < 2:
                event.text = ""  # Empty on first try
            else:
                event.text = '{"result": "success"}'
            yield event

        mock_client.stream_message = mock_stream

        dispatcher = SubAgentDispatcher(mock_client, "model", max_retries=3)
        result = await dispatcher.dispatch("web_fetch", "HTML content...")

        assert result.success
        assert result.retries_used == 1
        assert call_count == 2


class TestSubAgentDispatchExhaustedRetries:
    @pytest.mark.asyncio
    async def test_all_retries_failed(self):
        mock_client = MagicMock()

        async def mock_stream(request):
            event = MagicMock()
            event.text = ""  # Always empty
            yield event

        mock_client.stream_message = mock_stream

        dispatcher = SubAgentDispatcher(mock_client, "model", max_retries=2)
        result = await dispatcher.dispatch("web_fetch", "HTML content...")

        assert not result.success
        assert result.retries_used == 2
        assert "exhausted" in result.error.lower()


class TestSubAgentCallStackTracking:
    @pytest.mark.asyncio
    async def test_call_stack_populated(self):
        mock_client = MagicMock()

        async def mock_stream(request):
            event = MagicMock()
            event.text = '{"result": "ok"}'
            yield event

        mock_client.stream_message = mock_stream

        dispatcher = SubAgentDispatcher(mock_client, "model")
        assert dispatcher.call_stack == []
        assert dispatcher.depth == 0

        await dispatcher.dispatch("web_search", "result")

        # After dispatch, stack should be empty and depth reset
        assert dispatcher.call_stack == []
        assert dispatcher.depth == 0

    @pytest.mark.asyncio
    async def test_nested_dispatch_depth_tracking(self):
        mock_client = MagicMock()

        async def mock_stream(request):
            event = MagicMock()
            event.text = '{"result": "ok"}'
            yield event

        mock_client.stream_message = mock_stream

        dispatcher = SubAgentDispatcher(mock_client, "model")

        # Simulate nested dispatch by manually tracking
        await dispatcher.dispatch("web_search", "result 1")
        assert dispatcher.depth == 0

        await dispatcher.dispatch("web_fetch", "result 2")
        assert dispatcher.depth == 0


class TestSubAgentPrompt:
    def test_system_prompt_exists(self):
        assert SUBAGENT_SYSTEM_PROMPT
        assert "sub-agent" in SUBAGENT_SYSTEM_PROMPT.lower()

    @pytest.mark.asyncio
    async def test_intent_passed_in_query(self):
        mock_client = MagicMock()

        captured_request = []

        async def capture_stream(request):
            captured_request.append(request)
            event = MagicMock()
            event.text = '{"extracted": "data"}'
            yield event

        mock_client.stream_message = capture_stream

        dispatcher = SubAgentDispatcher(mock_client, "model")
        await dispatcher.dispatch("web_fetch", "content...", intent="Extract title")

        assert len(captured_request) == 1
        request = captured_request[0]
        # messages[0].content is a list of TextBlocks
        content = request.messages[0].content[0].text
        assert "Extract title" in content


class TestSubAgentLongContentTruncation:
    @pytest.mark.asyncio
    async def test_very_long_tool_result_truncated(self):
        mock_client = MagicMock()

        captured_queries = []

        async def capture_stream(request):
            # messages[0].content is a list of TextBlocks
            captured_queries.append(request.messages[0].content[0].text)
            event = MagicMock()
            event.text = '{"result": "ok"}'
            yield event

        mock_client.stream_message = capture_stream

        dispatcher = SubAgentDispatcher(mock_client, "model")
        very_long_content = "x" * 10000  # 10k characters

        await dispatcher.dispatch("web_fetch", very_long_content, intent="Test")

        # The query should contain truncated content (max 4000 chars)
        assert len(captured_queries) == 1
        query = captured_queries[0]
        assert len(query) < 10000  # Should be truncated
        assert "..." in query or "Test" in query  # Intent should still be there
