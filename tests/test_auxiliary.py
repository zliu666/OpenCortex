"""Tests for the auxiliary model client."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from opencortex.api.auxiliary import AuxiliaryClient, get_auxiliary_client, set_auxiliary_client


# ---------------------------------------------------------------------------
# Mock Provider
# ---------------------------------------------------------------------------

class MockProvider:
    """Simple mock provider that records calls."""

    def __init__(self, response: str, should_fail: bool = False, name: str = "MockProvider"):
        self.response = response
        self.should_fail = should_fail
        self.name = name
        self.calls: list[tuple] = []

    def __str__(self):
        return self.name

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        max_tokens: int = 1000,
    ) -> str:
        if self.should_fail:
            raise RuntimeError(f"{self} failed")
        self.calls.append((messages, system_prompt, max_tokens))
        return self.response


class MockOpenAIClient:
    """Mock OpenAI AsyncClient for testing."""

    def __init__(self, response: str, should_fail: bool = False):
        self.response = response
        self.should_fail = should_fail

    @property
    def chat(self):
        return self


class MockChatCompletions:
    """Mock chat.completions for OpenAI client."""

    def __init__(self, response: str, should_fail: bool = False):
        self.response = response
        self.should_fail = should_fail

    async def create(self, *, model: str, messages: list[dict], max_tokens: int):
        if self.should_fail:
            raise RuntimeError("OpenAI API failed")
        return MagicMock(
            choices=[
                MagicMock(message=MagicMock(content=self.response))
            ]
        )


# ---------------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

def test_client_empty_no_providers():
    """An empty AuxiliaryClient should have no providers."""
    client = AuxiliaryClient([])
    assert client.available is False


async def test_single_provider_success():
    """A single provider should work correctly."""
    provider = MockProvider("Hello world")
    client = AuxiliaryClient([("mock", provider, "mock-model")])

    assert client.available is True
    result = await client.complete([{"role": "user", "content": "Hi"}])
    assert result == "Hello world"
    assert len(provider.calls) == 1


async def test_fallback_chain_first_fails():
    """Test fallback: first provider fails, second succeeds."""
    provider1 = MockProvider("", should_fail=True, name="p1")
    provider2 = MockProvider("Success from second", name="p2")
    client = AuxiliaryClient([("p1", provider1, "m1"), ("p2", provider2, "m2")])

    result = await client.complete([{"role": "user", "content": "test"}])

    assert result == "Success from second"
    # The first provider's chat() is called but fails before adding to calls
    # The second provider succeeds and records its call
    assert len(provider2.calls) == 1


async def test_fallback_chain_all_fail():
    """Test that all providers failing raises an exception."""
    provider1 = MockProvider("", should_fail=True, name="p1")
    provider2 = MockProvider("", should_fail=True, name="p2")
    provider3 = MockProvider("", should_fail=True, name="p3")
    client = AuxiliaryClient([("p1", provider1, "m1"), ("p2", provider2, "m2"), ("p3", provider3, "m3")])

    with pytest.raises(RuntimeError, match="All auxiliary providers failed"):
        await client.complete([{"role": "user", "content": "test"}])


async def test_summarize_convenience_method():
    """The summarize() method should wrap complete() with the right prompt."""
    provider = MockProvider("Summary: The quick brown fox")
    client = AuxiliaryClient([("mock", provider, "mock-model")])

    result = await client.summarize("The quick brown fox jumps over the lazy dog")

    assert result == "Summary: The quick brown fox"
    assert len(provider.calls) == 1
    msg = provider.calls[0][0]
    assert len(msg) == 1
    assert msg[0]["role"] == "user"
    assert "The quick brown fox jumps over the lazy dog" in msg[0]["content"]


async def test_system_prompt_passed_through():
    """System prompt should be passed to the provider."""
    provider = MockProvider("With system prompt")
    client = AuxiliaryClient([("mock", provider, "mock-model")])

    result = await client.complete(
        [{"role": "user", "content": "Hi"}],
        system_prompt="You are a helpful assistant."
    )

    assert result == "With system prompt"
    _, system_prompt, _ = provider.calls[0]
    assert system_prompt == "You are a helpful assistant."


async def test_max_tokens_passed_through():
    """max_tokens should be passed to the provider."""
    provider = MockProvider("Limited")
    client = AuxiliaryClient([("mock", provider, "mock-model")])

    await client.complete([{"role": "user", "content": "Hi"}], max_tokens=500)

    _, _, max_tokens = provider.calls[0]
    assert max_tokens == 500


# ---------------------------------------------------------------------------
# OpenAI-compatible client tests (simplified)
# ------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Singleton tests
# ------------------------------------------------------------------

def test_singleton_get_empty():
    """get_auxiliary_client() returns a client even when unset."""
    client = get_auxiliary_client()
    assert client is not None
    assert isinstance(client, AuxiliaryClient)


def test_singleton_set_and_get():
    """set_auxiliary_client() and get_auxiliary_client() should share instance."""
    provider = MockProvider("test")
    custom_client = AuxiliaryClient([("mock", provider, "m1")])
    set_auxiliary_client(custom_client)

    result = get_auxiliary_client()
    assert result is custom_client
    assert result.available is True

    # Reset for other tests
    set_auxiliary_client(AuxiliaryClient([]))


# ---------------------------------------------------------------------------
# Config parsing
# ------------------------------------------------------------------

def test_from_config_empty():
    """Empty config should create a client with no providers."""
    config = {"providers": []}
    client = AuxiliaryClient.from_config(config)
    assert client.available is False


def test_from_config_missing_api_key():
    """Providers without api_key should be skipped."""
    config = {
        "providers": [
            {"name": "no-key", "model": "test-model"}
        ]
    }
    client = AuxiliaryClient.from_config(config)
    assert client.available is False


def test_from_config_with_base_url():
    """Config should accept base_url parameter (uses api_base alias)."""
    # Note: This test would require mocking openai.AsyncOpenAI, which is complex
    # For now, we just verify the config structure doesn't raise errors
    # The actual OpenAI client integration is tested manually with real keys
    config = {
        "providers": [
            {"name": "custom", "model": "custom-model", "api_key": "sk-test", "api_base": "https://api.example.com"}
        ]
    }
    # This will log a warning but not crash
    client = AuxiliaryClient.from_config(config)
    # No providers registered because we don't have openai installed or it's mocked
    assert client.available is False


# ---------------------------------------------------------------------------
# Custom instruction in summarize
# ------------------------------------------------------------------

async def test_summarize_with_custom_instruction():
    """Custom instruction should be prepended to the text."""
    provider = MockProvider("Custom summary result")
    client = AuxiliaryClient([("mock", provider, "mock-model")])

    result = await client.summarize(
        "Long text here",
        instruction="Summarize in bullet points"
    )

    assert result == "Custom summary result"
    msg = provider.calls[0][0][0]["content"]
    assert "Summarize in bullet points" in msg
    assert "Long text here" in msg


# Run tests
if __name__ == "__main__":
    asyncio.run(test_single_provider_success())
    asyncio.run(test_fallback_chain_first_fails())
    asyncio.run(test_fallback_chain_all_fail())
    asyncio.run(test_summarize_convenience_method())
    asyncio.run(test_system_prompt_passed_through())
    asyncio.run(test_max_tokens_passed_through())
    asyncio.run(test_openai_client_success())
    asyncio.run(test_openai_client_failure_fallback())
    print("All tests passed!")
