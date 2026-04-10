"""Tests for the 5-layer tiered memory system."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from opencortex.memory.decay import MemoryDecayManager
from opencortex.memory.dream import MemoryDream
from opencortex.memory.tiered_store import (
    MemoryTier,
    TierConfig,
    TieredMemoryConfig,
    TieredMemoryStore,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_tiered.db"


@pytest.fixture
def store(db_path: Path) -> TieredMemoryStore:
    config = TieredMemoryConfig(tiers=TierConfig.defaults())
    return TieredMemoryStore(config=config, db_path=db_path)


# ======================================================================
# Tiered loading
# ======================================================================

class TestTieredLoading:
    def test_core_auto_loaded(self, store: TieredMemoryStore):
        store.add_entry(MemoryTier.CORE, "I am a helpful assistant")
        store.add_entry(MemoryTier.ARCHIVE, "old archived content")

        ctx = store.load_context()
        assert "helpful assistant" in ctx
        assert "old archived content" not in ctx

    def test_user_auto_loaded(self, store: TieredMemoryStore):
        store.add_entry(MemoryTier.USER, "prefers dark mode")
        ctx = store.load_context()
        assert "dark mode" in ctx

    def test_project_triggered_by_query(self, store: TieredMemoryStore):
        store.add_entry(MemoryTier.PROJECT, "use FastAPI for backend", tags=["python", "api"])
        # Without query — project tier not loaded
        ctx = store.load_context()
        assert "FastAPI" not in ctx

        # With matching query — project tier loaded
        ctx = store.load_context(query="FastAPI")
        assert "FastAPI" in ctx

    def test_archive_never_loaded(self, store: TieredMemoryStore):
        store.add_entry(MemoryTier.ARCHIVE, "very old discussion about socks")
        ctx = store.load_context()
        assert "socks" not in ctx

    def test_session_auto_loaded(self, store: TieredMemoryStore):
        store.add_entry(MemoryTier.SESSION, "discussed deployment strategy")
        ctx = store.load_context()
        assert "deployment strategy" in ctx


# ======================================================================
# Search
# ======================================================================

class TestSearch:
    def test_cross_tier_search(self, store: TieredMemoryStore):
        store.add_entry(MemoryTier.CORE, "identity info")
        store.add_entry(MemoryTier.PROJECT, "project architecture decisions")
        store.add_entry(MemoryTier.ARCHIVE, "old architecture notes")

        results = store.search("architecture")
        assert len(results) >= 2

    def test_search_limited_to_tiers(self, store: TieredMemoryStore):
        store.add_entry(MemoryTier.CORE, "core identity architecture")
        store.add_entry(MemoryTier.ARCHIVE, "old architecture notes")

        results = store.search("architecture", tiers=[MemoryTier.ARCHIVE])
        assert all(r["tier"] == "archive" for r in results)


# ======================================================================
# Decay
# ======================================================================

class TestDecay:
    def test_session_decays_to_project(self, store: TieredMemoryStore):
        conn = store._connect()
        # Insert a session entry with old timestamp (8 days ago)
        old_ts = _days_ago(8)
        conn.execute(
            "INSERT INTO tiered_memories (tier, content, tags, created_at, updated_at) VALUES (?, ?, '[]', ?, ?)",
            ("session", "old session note", old_ts, old_ts),
        )
        conn.commit()

        manager = MemoryDecayManager(store=store)
        records = manager.check_and_decay()
        assert len(records) >= 1
        assert records[0]["from_tier"] == "session"
        assert records[0]["to_tier"] == "project"

    def test_core_never_decays(self, store: TieredMemoryStore):
        conn = store._connect()
        old_ts = _days_ago(365)
        conn.execute(
            "INSERT INTO tiered_memories (tier, content, tags, created_at, updated_at) VALUES (?, ?, '[]', ?, ?)",
            ("core", "ancient core memory", old_ts, old_ts),
        )
        conn.commit()

        manager = MemoryDecayManager(store=store)
        records = manager.check_and_decay()
        assert all(r["from_tier"] != "core" for r in records)

    def test_project_decays_to_archive(self, store: TieredMemoryStore):
        conn = store._connect()
        old_ts = _days_ago(31)
        conn.execute(
            "INSERT INTO tiered_memories (tier, content, tags, created_at, updated_at) VALUES (?, ?, '[]', ?, ?)",
            ("project", "stale project info", old_ts, old_ts),
        )
        conn.commit()

        manager = MemoryDecayManager(store=store)
        records = manager.check_and_decay()
        assert any(r["from_tier"] == "project" and r["to_tier"] == "archive" for r in records)

    def test_force_decay(self, store: TieredMemoryStore):
        entry_id = store.add_entry(MemoryTier.PROJECT, "forced decay target")
        manager = MemoryDecayManager(store=store)
        result = manager.force_decay(entry_id, MemoryTier.ARCHIVE)
        assert result is True

        results = store.search("forced decay target", tiers=[MemoryTier.ARCHIVE])
        assert len(results) == 1

    def test_decay_via_store(self, store: TieredMemoryStore):
        conn = store._connect()
        old_ts = _days_ago(8)
        conn.execute(
            "INSERT INTO tiered_memories (tier, content, tags, created_at, updated_at) VALUES (?, ?, '[]', ?, ?)",
            ("session", "expiring session", old_ts, old_ts),
        )
        conn.commit()

        count = store.decay()
        assert count >= 1


# ======================================================================
# Auto Dream
# ======================================================================

class TestDream:
    def test_dream_full_cycle(self, store: TieredMemoryStore):
        # Add some duplicate entries
        store.add_entry(MemoryTier.SESSION, "discussed API design patterns", tags=["api"])
        store.add_entry(MemoryTier.SESSION, "discussed API design patterns", tags=["api"])
        store.add_entry(MemoryTier.PROJECT, "use pytest for testing", tags=["test"])

        dream = MemoryDream(store=store)
        result = asyncio.get_event_loop().run_until_complete(dream.dream())

        assert "inventory_summary" in result
        assert "signals_found" in result
        assert result["signals_found"] >= 1  # found the duplicate

    def test_dream_no_signals(self, store: TieredMemoryStore):
        store.add_entry(MemoryTier.CORE, "unique identity")
        store.add_entry(MemoryTier.PROJECT, "unique project note")

        dream = MemoryDream(store=store)
        result = asyncio.get_event_loop().run_until_complete(dream.dream())

        assert result["signals_found"] == 0
        assert result["archived"] == 0


# ======================================================================
# Stats
# ======================================================================

class TestStats:
    def test_tier_stats(self, store: TieredMemoryStore):
        store.add_entry(MemoryTier.CORE, "identity")
        store.add_entry(MemoryTier.SESSION, "session 1")
        store.add_entry(MemoryTier.SESSION, "session 2")

        stats = store.get_tier_stats()
        assert stats[MemoryTier.CORE]["count"] == 1
        assert stats[MemoryTier.SESSION]["count"] == 2
        assert stats[MemoryTier.CORE]["config"]["auto_load"] is True
        assert stats[MemoryTier.PROJECT]["config"]["trigger_load"] is True
        assert stats[MemoryTier.ARCHIVE]["config"]["search_only"] is True


# ======================================================================
# Helpers
# ======================================================================

def _days_ago(days: int) -> float:
    import time
    return time.time() - days * 86400
