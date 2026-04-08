"""Tests for ZellijPaneBackend."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opencortex.swarm.types import CreatePaneResult
from opencortex.swarm.zellij_backend import (
    ZellijPaneBackend,
    is_inside_zellij,
    is_zellij_available,
    get_zellij_backend,
)


# ---------------------------------------------------------------------------
# Environment detection tests
# ---------------------------------------------------------------------------


class TestZellijDetection:
    def test_is_inside_zellij_env_set(self):
        with patch.dict(os.environ, {"ZELLIJ": "/tmp/zellij-123"}):
            assert is_inside_zellij() is True

    def test_is_inside_zellij_env_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_inside_zellij() is False

    def test_is_zellij_available_found(self):
        with patch("shutil.which", return_value="/usr/bin/zellij"):
            assert is_zellij_available() is True

    def test_is_zellij_available_not_found(self):
        with patch("shutil.which", return_value=None):
            assert is_zellij_available() is False


# ---------------------------------------------------------------------------
# PaneBackend protocol tests (mocked zellij CLI)
# ---------------------------------------------------------------------------


class TestZellijPaneBackend:
    """Test ZellijPaneBackend with mocked subprocess calls."""

    def _make_backend(self) -> ZellijPaneBackend:
        return ZellijPaneBackend()

    @pytest.mark.asyncio
    async def test_is_available(self):
        backend = self._make_backend()
        with patch("shutil.which", return_value="/usr/bin/zellij"):
            assert await backend.is_available() is True
        with patch("shutil.which", return_value=None):
            assert await backend.is_available() is False

    @pytest.mark.asyncio
    async def test_is_running_inside(self):
        backend = self._make_backend()
        with patch.dict(os.environ, {"ZELLIJ": "1"}):
            assert await backend.is_running_inside() is True
        with patch.dict(os.environ, {}, clear=True):
            assert await backend.is_running_inside() is False

    @pytest.mark.asyncio
    async def test_create_pane_first_teammate(self):
        backend = self._make_backend()

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await backend.create_teammate_pane_in_swarm_view("researcher")

        assert isinstance(result, CreatePaneResult)
        assert result.is_first_teammate is True
        assert "researcher" in result.pane_id
        assert backend.list_panes() == [result.pane_id]

    @pytest.mark.asyncio
    async def test_create_pane_second_teammate(self):
        backend = self._make_backend()

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            r1 = await backend.create_teammate_pane_in_swarm_view("agent1")
            r2 = await backend.create_teammate_pane_in_swarm_view("agent2")

        assert r1.is_first_teammate is True
        assert r2.is_first_teammate is False
        assert len(backend.list_panes()) == 2

    @pytest.mark.asyncio
    async def test_kill_pane(self):
        backend = self._make_backend()

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await backend.create_teammate_pane_in_swarm_view("tester")
            killed = await backend.kill_pane(result.pane_id)

        assert killed is True
        assert backend.list_panes() == []

    @pytest.mark.asyncio
    async def test_kill_unknown_pane(self):
        backend = self._make_backend()
        killed = await backend.kill_pane("nonexistent")
        assert killed is False

    @pytest.mark.asyncio
    async def test_write_output(self):
        backend = self._make_backend()

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await backend.create_teammate_pane_in_swarm_view("worker")
            await backend.write_output("worker", "Hello from worker")

        # Should have called subprocess for write-chars
        # (we're just checking it doesn't crash)

    @pytest.mark.asyncio
    async def test_write_output_unknown_agent(self):
        backend = self._make_backend()
        # Should not raise
        await backend.write_output("unknown_agent", "test")

    @pytest.mark.asyncio
    async def test_mark_completed(self):
        backend = self._make_backend()

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await backend.create_teammate_pane_in_swarm_view("researcher")
            await backend.mark_completed("researcher", "Found 3 bugs")

        assert backend.get_pane_status("researcher") == "completed"

    @pytest.mark.asyncio
    async def test_mark_completed_unknown_agent(self):
        backend = self._make_backend()
        # Should not raise
        await backend.mark_completed("unknown", "done")

    def test_supports_hide_show(self):
        backend = self._make_backend()
        assert backend.supports_hide_show is False

    def test_display_name(self):
        backend = self._make_backend()
        assert backend.display_name == "Zellij"


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------


class TestGetZellijBackend:
    def test_returns_same_instance(self):
        import opencortex.swarm.zellij_backend as mod
        mod._zellij_backend = None  # Reset
        b1 = get_zellij_backend()
        b2 = get_zellij_backend()
        assert b1 is b2
