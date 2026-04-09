"""Regression tests for Top 3 critical bug fixes."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from opencortex.memory.store import FtsMemoryStore
from opencortex.profile.store import ProfileStore
from opencortex.security.privilege import ToolPrivilege, ToolPrivilegeAssignor
from opencortex.security.validator import ToolCallValidator


def _mock_api(response_text: str):
    mock = AsyncMock()

    async def _stream(request):
        event = MagicMock()
        event.text = response_text
        yield event

    mock.stream_message = _stream
    return mock


# ── Fix 1: Zellij pane writes to log file ────────────────────────────────────

@pytest.mark.skipif(
    shutil.which("zellij") is None,
    reason="Zellij not installed, skipping Zellij tests"
)
class TestZellijLogFile:
    """Verify write_output uses log file, not write-chars."""

    @pytest.mark.asyncio
    async def test_write_output_creates_and_appends_log(self, tmp_path):
        from opencortex.swarm.zellij_backend import ZellijPaneBackend

        backend = ZellijPaneBackend()
        backend._LOG_DIR = str(tmp_path)

        # Create a pane
        result = await backend.create_teammate_pane_in_swarm_view("test_agent")
        pane_id = result.pane_id

        # Write output
        await backend.write_output("test_agent", "Hello from agent\n")

        # Check log file content
        meta = backend._panes[pane_id]
        log_path = meta["log_path"]
        assert os.path.exists(log_path)
        with open(log_path) as f:
            assert "Hello from agent" in f.read()

    @pytest.mark.asyncio
    async def test_kill_pane_cleans_up_log(self, tmp_path):
        from opencortex.swarm.zellij_backend import ZellijPaneBackend

        backend = ZellijPaneBackend()
        backend._LOG_DIR = str(tmp_path)

        result = await backend.create_teammate_pane_in_swarm_view("cleanup_agent")
        pane_id = result.pane_id
        meta = backend._panes[pane_id]
        log_path = meta["log_path"]

        assert os.path.exists(log_path)
        await backend.kill_pane(pane_id)
        assert not os.path.exists(log_path)


# ── Fix 2: Privilege classification checks "b" first ────────────────────────

class TestPrivilegeConservativeClassification:
    """When response contains both 'a' and 'b', result should be COMMAND."""

    @pytest.mark.asyncio
    async def test_both_a_and_b_gives_command(self):
        client = _mock_api("a and b both present")
        assignor = ToolPrivilegeAssignor(client, "test-model")
        result = await assignor.classify("ambiguous_tool", "Does both read and write")
        assert result == ToolPrivilege.COMMAND

    @pytest.mark.asyncio
    async def test_only_a_gives_query(self):
        client = _mock_api("a")
        assignor = ToolPrivilegeAssignor(client, "test-model")
        result = await assignor.classify("read_tool", "Read-only tool")
        assert result == ToolPrivilege.QUERY

    @pytest.mark.asyncio
    async def test_only_b_gives_command(self):
        client = _mock_api("b")
        assignor = ToolPrivilegeAssignor(client, "test-model")
        result = await assignor.classify("write_tool", "Write tool")
        assert result == ToolPrivilege.COMMAND

    @pytest.mark.asyncio
    async def test_neither_defaults_to_command(self):
        client = _mock_api("xyz")
        assignor = ToolPrivilegeAssignor(client, "test-model")
        result = await assignor.classify("unknown_tool", "Unknown tool")
        assert result == ToolPrivilege.COMMAND


# ── Fix 3: Database connection management ────────────────────────────────────

class TestDatabaseConnectionManagement:
    """Verify close() and context manager work for both stores."""

    def test_profile_store_close(self, tmp_path):
        store = ProfileStore(tmp_path / "test.db")
        store.set("key1", "value1")
        store.close()
        assert store._conn is None

    def test_profile_store_context_manager(self, tmp_path):
        db = tmp_path / "test.db"
        with ProfileStore(db) as store:
            store.set("key1", "value1")
        assert store._conn is None
        # Data persists after close
        with ProfileStore(db) as store:
            assert store.get("key1") is not None

    def test_memory_store_close(self, tmp_path):
        store = FtsMemoryStore(tmp_path / "test.db")
        store.store("key1", "content1")
        store.close()
        assert store._conn is None

    def test_memory_store_context_manager(self, tmp_path):
        db = tmp_path / "test.db"
        with FtsMemoryStore(db) as store:
            store.store("key1", "hello world")
        assert store._conn is None
        with FtsMemoryStore(db) as store:
            assert store.get("key1") is not None


# ── Fix 4: Validator strict "true" matching ──────────────────────────────────

class TestValidatorStrictMatching:
    """Verify that 'true' substring doesn't false-positive."""

    @pytest.mark.asyncio
    async def test_false_positive_fix(self):
        """'contribute' contains 'true' but should not pass validation."""
        client = _mock_api("contribute")
        validator = ToolCallValidator(client, "test-model")
        result = await validator.validate(
            "some_tool", {}, "desc", "query", ""
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_exact_true_passes(self):
        client = _mock_api("true")
        validator = ToolCallValidator(client, "test-model")
        result = await validator.validate(
            "some_tool", {}, "desc", "query", ""
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_true_with_whitespace(self):
        client = _mock_api("  True  ")
        validator = ToolCallValidator(client, "test-model")
        result = await validator.validate(
            "some_tool", {}, "desc", "query", ""
        )
        assert result is True
