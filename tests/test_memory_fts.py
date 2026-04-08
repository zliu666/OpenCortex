"""Tests for FTS5 memory store."""

import tempfile
from pathlib import Path

from opencortex.memory.store import FtsMemoryStore


def test_store_and_retrieve():
    """Test basic store and get."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FtsMemoryStore(db_path=Path(tmpdir) / "test.db")
        store.store("test-key", "Hello world, this is a test memory")
        result = store.get("test-key")
        assert result is not None
        assert result["key"] == "test-key"
        assert "Hello world" in result["content"]
        store.close()


def test_fulltext_search():
    """Test FTS5 search."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FtsMemoryStore(db_path=Path(tmpdir) / "test.db")
        store.store("python", "Python is a great programming language for data science")
        store.store("rust", "Rust provides memory safety without garbage collection")
        store.store("js", "JavaScript is the language of the web browser")

        results = store.search("programming language")
        assert len(results) >= 1
        assert any(r["key"] == "python" for r in results)
        store.close()


def test_search_chinese():
    """Test FTS5 with Chinese content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FtsMemoryStore(db_path=Path(tmpdir) / "test.db")
        store.store("greeting", "你好世界，这是一个测试记忆")
        # Trigram tokenizer requires >= 3 characters for CJK
        results = store.search("测试记")
        assert len(results) >= 1
        store.close()


def test_update():
    """Test upsert behavior."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FtsMemoryStore(db_path=Path(tmpdir) / "test.db")
        store.store("key1", "version 1")
        store.store("key1", "version 2")
        result = store.get("key1")
        assert result["content"] == "version 2"
        store.close()


def test_delete():
    """Test delete."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FtsMemoryStore(db_path=Path(tmpdir) / "test.db")
        store.store("key1", "delete me")
        assert store.delete("key1") is True
        assert store.get("key1") is None
        assert store.delete("nonexistent") is False
        store.close()


def test_list_keys():
    """Test listing keys."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FtsMemoryStore(db_path=Path(tmpdir) / "test.db")
        store.store("a", "content a")
        store.store("b", "content b")
        keys = store.list_keys()
        assert len(keys) == 2
        store.close()


def test_metadata():
    """Test storing with metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FtsMemoryStore(db_path=Path(tmpdir) / "test.db")
        store.store("meta-test", "content", metadata={"source": "test", "tags": ["a", "b"]})
        result = store.get("meta-test")
        assert result["metadata"]["source"] == "test"
        store.close()
