"""Tests for MemoryPipeline."""

import pytest
from pathlib import Path

from opencortex.memory.pipeline import MemoryPipeline
from opencortex.memory.store import FtsMemoryStore


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    d = tmp_path / "memories"
    d.mkdir()
    return d


@pytest.fixture
def fts(tmp_path: Path) -> FtsMemoryStore:
    return FtsMemoryStore(tmp_path / "test.db")


class TestPrefetchAndInject:
    @pytest.mark.asyncio
    async def test_empty(self, memory_dir: Path):
        pipe = MemoryPipeline(memory_dir)
        await pipe.prefetch()
        result = pipe.inject_into("system prompt")
        assert result == "system prompt"

    @pytest.mark.asyncio
    async def test_inject(self, memory_dir: Path):
        (memory_dir / "MEMORY.md").write_text("hello memory\n", encoding="utf-8")
        (memory_dir / "USER.md").write_text("hello user\n", encoding="utf-8")
        pipe = MemoryPipeline(memory_dir)
        await pipe.prefetch()
        result = pipe.inject_into("base prompt")
        assert "<memory-context>" in result
        assert "hello memory" in result
        assert "hello user" in result
        assert result.startswith("base prompt")

    @pytest.mark.asyncio
    async def test_frozen_snapshot(self, memory_dir: Path):
        """Once prefetched, modifying files should not affect injection."""
        (memory_dir / "MEMORY.md").write_text("original\n", encoding="utf-8")
        pipe = MemoryPipeline(memory_dir)
        await pipe.prefetch()
        # modify file after prefetch
        (memory_dir / "MEMORY.md").write_text("modified\n", encoding="utf-8")
        result = pipe.inject_into("p")
        assert "original" in result
        assert "modified" not in result


class TestPostProcess:
    @pytest.mark.asyncio
    async def test_nudge_at_interval(self, memory_dir: Path):
        pipe = MemoryPipeline(memory_dir)
        await pipe.post_process([], turn_count=10, nudge_interval=10)
        assert pipe.should_nudge is True

    @pytest.mark.asyncio
    async def test_no_nudge(self, memory_dir: Path):
        pipe = MemoryPipeline(memory_dir)
        await pipe.post_process([], turn_count=5, nudge_interval=10)
        assert pipe.should_nudge is False

    @pytest.mark.asyncio
    async def test_persist_to_fts(self, memory_dir: Path, fts: FtsMemoryStore):
        pipe = MemoryPipeline(memory_dir, fts5_store=fts)
        msgs = [{"role": "user", "content": "hello FTS5"}]
        await pipe.post_process(msgs, turn_count=1)
        results = fts.search("FTS5")
        assert len(results) == 1
        assert "hello FTS5" in results[0]["content"]


class TestSearch:
    @pytest.mark.asyncio
    async def test_no_store(self, memory_dir: Path):
        pipe = MemoryPipeline(memory_dir)
        assert await pipe.search("query") == ""

    @pytest.mark.asyncio
    async def test_with_store(self, memory_dir: Path, fts: FtsMemoryStore):
        fts.store("k1", "python is great", {"turn": 1})
        pipe = MemoryPipeline(memory_dir, fts5_store=fts)
        result = await pipe.search("python")
        assert "python is great" in result
