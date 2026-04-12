"""Tests for memory nudge background review."""

import pytest
from pathlib import Path

from opencortex.memory.nudge import MemoryNudge, MEMORY_REVIEW_PROMPT
from opencortex.memory.files import MemoryFiles


@pytest.fixture
def temp_memory_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for memory files."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


@pytest.fixture
def memory_files(temp_memory_dir: Path) -> MemoryFiles:
    """Create a MemoryFiles instance for testing."""
    return MemoryFiles(memory_dir=temp_memory_dir)


@pytest.fixture
def memory_nudge(memory_files: MemoryFiles) -> MemoryNudge:
    """Create a MemoryNudge instance for testing."""
    return MemoryNudge(memory_files=memory_files, interval=3)


class TestTick:
    """Test tick triggering logic."""

    def test_tick_triggers_at_interval(self, memory_nudge: MemoryNudge) -> None:
        """tick() should return True only after reaching interval."""
        assert memory_nudge.tick() is False
        assert memory_nudge.tick() is False
        assert memory_nudge.tick() is True  # Third tick triggers
        assert memory_nudge.tick() is False  # Reset and start over

    def test_tick_resets_after_trigger(self, memory_nudge: MemoryNudge) -> None:
        """tick() should reset counter after triggering."""
        # First trigger (3 ticks needed)
        assert memory_nudge.tick() is False
        assert memory_nudge.tick() is False
        assert memory_nudge.tick() is True  # Triggered and reset
        # Now start fresh cycle
        assert memory_nudge.tick() is False
        assert memory_nudge.tick() is False
        assert memory_nudge.tick() is True  # Triggered again


class TestReviewWithRules:
    """Test rule-based review without API client."""

    @pytest.mark.asyncio
    async def test_extract_user_preferences(self, memory_nudge: MemoryNudge) -> None:
        """Should extract preference statements from user messages."""
        messages = [
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "I always prefer concise answers."},
            {"role": "assistant", "content": "Got it!"},
        ]
        suggestions = await memory_nudge.review(messages, api_client=None)
        assert len(suggestions) == 1
        assert "preference" in suggestions[0]
        assert "concise" in suggestions[0]

    @pytest.mark.asyncio
    async def test_extract_user_instructions(self, memory_nudge: MemoryNudge) -> None:
        """Should extract instructions from user messages."""
        messages = [
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "Please make sure to use markdown for code."},
            {"role": "assistant", "content": "Will do!"},
        ]
        suggestions = await memory_nudge.review(messages, api_client=None)
        assert len(suggestions) == 1
        assert "instruction" in suggestions[0]
        assert "markdown" in suggestions[0]

    @pytest.mark.asyncio
    async def test_extract_user_identity(self, memory_nudge: MemoryNudge) -> None:
        """Should extract identity information from user messages."""
        messages = [
            {"role": "assistant", "content": "How can I help?"},
            {"role": "user", "content": "My name is Alice."},
            {"role": "assistant", "content": "Nice to meet you, Alice!"},
        ]
        suggestions = await memory_nudge.review(messages, api_client=None)
        assert len(suggestions) == 1
        assert "identity" in suggestions[0]
        assert "Alice" in suggestions[0]

    @pytest.mark.asyncio
    async def test_extract_work_info(self, memory_nudge: MemoryNudge) -> None:
        """Should extract work-related information."""
        messages = [
            {"role": "assistant", "content": "What do you need?"},
            {"role": "user", "content": "I work as a software engineer at a startup."},
            {"role": "assistant", "content": "Cool!"},
        ]
        suggestions = await memory_nudge.review(messages, api_client=None)
        assert len(suggestions) == 1
        assert "work" in suggestions[0]
        assert "software engineer" in suggestions[0]

    @pytest.mark.asyncio
    async def test_no_suggestions_from_empty_conversation(self, memory_nudge: MemoryNudge) -> None:
        """Should return empty list for conversations without memory-worthy content."""
        messages = [
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "Hi there!"},
            {"role": "assistant", "content": "How are you?"},
            {"role": "user", "content": "Good thanks!"},
        ]
        suggestions = await memory_nudge.review(messages, api_client=None)
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_deduplicate_suggestions(self, memory_nudge: MemoryNudge) -> None:
        """Should not duplicate similar patterns."""
        messages = [
            {"role": "user", "content": "I always prefer concise answers."},
            {"role": "assistant", "content": "OK!"},
            {"role": "user", "content": "I always prefer clear answers."},
            {"role": "assistant", "content": "Got it!"},
        ]
        suggestions = await memory_nudge.review(messages, api_client=None)
        assert len(suggestions) == 2

    @pytest.mark.asyncio
    async def test_ignores_assistant_messages(self, memory_nudge: MemoryNudge) -> None:
        """Should only analyze user messages."""
        messages = [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "I always use a formal tone."},
            {"role": "user", "content": "That's fine."},
        ]
        suggestions = await memory_nudge.review(messages, api_client=None)
        assert suggestions == []


class TestReviewWithLLM:
    """Test LLM-based review (mocked)."""

    @pytest.mark.asyncio
    async def test_llm_review_parses_suggestions(self, memory_nudge: MemoryNudge) -> None:
        """Should parse multi-line LLM response into individual suggestions."""
        messages = [{"role": "user", "content": "I prefer Python."}]

        class MockAPIClient:
            async def chat(self, _messages):
                return "- User prefers Python\n- User works as a developer"

        suggestions = await memory_nudge.review(messages, api_client=MockAPIClient())
        assert len(suggestions) == 2
        assert "prefers Python" in suggestions[0]
        assert "works as a developer" in suggestions[1]

    @pytest.mark.asyncio
    async def test_llm_review_handles_nothing_to_save(self, memory_nudge: MemoryNudge) -> None:
        """Should return empty list when LLM says nothing to save."""
        messages = [{"role": "user", "content": "Hello!"}]

        class MockAPIClient:
            async def chat(self, _messages):
                return "Nothing to save."

        suggestions = await memory_nudge.review(messages, api_client=MockAPIClient())
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_llm_review_handles_empty_response(self, memory_nudge: MemoryNudge) -> None:
        """Should return empty list for empty LLM response."""
        messages = [{"role": "user", "content": "Hi!"}]

        class MockAPIClient:
            async def chat(self, _messages):
                return ""

        suggestions = await memory_nudge.review(messages, api_client=MockAPIClient())
        assert suggestions == []


class TestApplySuggestions:
    """Test applying suggestions to memory files."""

    def test_apply_suggestions_writes_to_memory(self, memory_files: MemoryFiles) -> None:
        """Should write suggestions to MEMORY.md."""
        nudge = MemoryNudge(memory_files=memory_files)
        suggestions = ["User prefers concise answers.", "User uses Python 3.12."]

        nudge.apply_suggestions(suggestions)

        entries = memory_files.read_memory()
        assert len(entries) == 2
        assert "prefers concise" in entries[0]
        assert "Python 3.12" in entries[1]

    def test_apply_suggestions_deduplicates(self, memory_files: MemoryFiles) -> None:
        """Should not add duplicate entries."""
        nudge = MemoryNudge(memory_files=memory_files)
        # First write
        nudge.apply_suggestions(["User prefers concise answers."])
        # Second write with duplicate
        nudge.apply_suggestions(["User prefers concise answers.", "User uses Python."])

        entries = memory_files.read_memory()
        assert len(entries) == 2
        assert "prefers concise" in entries[0]
        assert "Python" in entries[1]

    def test_apply_suggestions_empty_list(self, memory_files: MemoryFiles) -> None:
        """Should handle empty suggestion list gracefully."""
        nudge = MemoryNudge(memory_files=memory_files)

        nudge.apply_suggestions([])

        entries = memory_files.read_memory()
        assert entries == []

    def test_memory_file_created_if_missing(self, temp_memory_dir: Path) -> None:
        """Should create MEMORY.md file if it doesn't exist."""
        memory_files = MemoryFiles(memory_dir=temp_memory_dir)
        nudge = MemoryNudge(memory_files=memory_files)

        memory_file = temp_memory_dir / "MEMORY.md"
        assert not memory_file.exists()

        nudge.apply_suggestions(["Test entry."])

        assert memory_file.exists()
        assert "Test entry." in memory_file.read_text()
