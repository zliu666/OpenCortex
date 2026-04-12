"""Tests for MemoryFiles (MEMORY.md / USER.md management)."""

import pytest
from pathlib import Path

from opencortex.memory.files import MemoryFiles, MEMORY_SECTION_SEP


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    return tmp_path / "memories"


@pytest.fixture
def mf(memory_dir: Path) -> MemoryFiles:
    return MemoryFiles(memory_dir)


def _write_file(path: Path, entries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"\n{MEMORY_SECTION_SEP}\n".join(entries) + "\n", encoding="utf-8")


class TestReadMemory:
    def test_empty_dir(self, mf: MemoryFiles):
        assert mf.read_memory() == []

    def test_single_entry(self, mf: MemoryFiles, memory_dir: Path):
        _write_file(memory_dir / "MEMORY.md", ["hello world"])
        assert mf.read_memory() == ["hello world"]

    def test_multiple_entries(self, mf: MemoryFiles, memory_dir: Path):
        entries = ["first", "second", "third"]
        _write_file(memory_dir / "MEMORY.md", entries)
        assert mf.read_memory() == entries

    def test_deduplication(self, mf: MemoryFiles, memory_dir: Path):
        _write_file(memory_dir / "MEMORY.md", ["dup", "dup", "unique"])
        assert mf.read_memory() == ["dup", "unique"]


class TestReadWrite:
    def test_add_memory(self, mf: MemoryFiles, memory_dir: Path):
        mf.add_memory("new entry")
        assert mf.read_memory() == ["new entry"]

    def test_add_duplicate(self, mf: MemoryFiles, memory_dir: Path):
        mf.add_memory("dup")
        mf.add_memory("dup")
        assert mf.read_memory() == ["dup"]

    def test_replace_memory(self, mf: MemoryFiles, memory_dir: Path):
        mf.add_memory("old")
        assert mf.replace_memory("old", "new")
        assert mf.read_memory() == ["new"]

    def test_replace_missing(self, mf: MemoryFiles):
        assert not mf.replace_memory("nope", "new")

    def test_remove_memory(self, mf: MemoryFiles, memory_dir: Path):
        mf.add_memory("keep")
        mf.add_memory("drop")
        assert mf.remove_memory("drop")
        assert mf.read_memory() == ["keep"]

    def test_remove_missing(self, mf: MemoryFiles):
        assert not mf.remove_memory("nope")


class TestReadUser:
    def test_empty(self, mf: MemoryFiles):
        assert mf.read_user() == []

    def test_read(self, mf: MemoryFiles, memory_dir: Path):
        _write_file(memory_dir / "USER.md", ["likes python"])
        assert mf.read_user() == ["likes python"]


class TestSnapshot:
    def test_empty_snapshot(self, mf: MemoryFiles):
        snap = mf.take_snapshot()
        assert snap == {"memory": "", "user": ""}

    def test_snapshot_content(self, mf: MemoryFiles, memory_dir: Path):
        _write_file(memory_dir / "MEMORY.md", ["mem1", "mem2"])
        _write_file(memory_dir / "USER.md", ["user1"])
        snap = mf.take_snapshot()
        assert "mem1" in snap["memory"]
        assert "mem2" in snap["memory"]
        assert "user1" in snap["user"]

    def test_snapshot_frozen(self, mf: MemoryFiles, memory_dir: Path):
        """Snapshot should not change after file modification."""
        _write_file(memory_dir / "MEMORY.md", ["original"])
        snap1 = mf.take_snapshot()
        # now modify the file
        _write_file(memory_dir / "MEMORY.md", ["modified"])
        # snap1 is still the old value
        assert "original" in snap1["memory"]
