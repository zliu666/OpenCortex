"""Tests for the Guardian Agent."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opencortex.swarm.guardian import AlertLevel, GuardianAgent
from opencortex.swarm.lifecycle import (
    AgentHealth,
    AgentLifecycleManager,
    AgentState,
)
from opencortex.swarm.message_bus import MessageBus


@pytest.fixture
def lifecycle():
    return AgentLifecycleManager()


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def guardian(lifecycle, bus, tmp_path):
    return GuardianAgent(
        lifecycle,
        bus,
        check_interval=1,
        worktree_dir=tmp_path / "worktrees",
        temp_dir=tmp_path / "tmp",
    )


def _make_health(agent_id: str, state=AgentState.RUNNING, last_heartbeat=None, **kw) -> AgentHealth:
    return AgentHealth(
        agent_id=agent_id,
        state=state,
        health="healthy",
        cpu_percent=0,
        memory_mb=0,
        disk_mb=0,
        last_heartbeat=last_heartbeat or time.time(),
        uptime_seconds=100,
        error_count=0,
        restart_count=0,
        **kw,
    )


# ---- Health check tests ----

class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_crashed_agent_marked_unhealthy(self, lifecycle, bus, guardian):
        lifecycle._agents["a1"] = _make_health("a1", state=AgentState.CRASHED)
        result = await guardian.health_check_all()
        assert result["a1"].health == "unhealthy"

    @pytest.mark.asyncio
    async def test_stopped_agent_marked_unhealthy(self, lifecycle, bus, guardian):
        lifecycle._agents["a1"] = _make_health("a1", state=AgentState.STOPPED)
        result = await guardian.health_check_all()
        assert result["a1"].health == "unhealthy"

    @pytest.mark.asyncio
    async def test_heartbeat_timeout_unhealthy(self, lifecycle, bus, guardian):
        lifecycle._agents["a1"] = _make_health("a1", last_heartbeat=time.time() - 600)
        result = await guardian.health_check_all()
        assert result["a1"].health == "unhealthy"

    @pytest.mark.asyncio
    async def test_healthy_agent_stays_healthy(self, lifecycle, bus, guardian):
        lifecycle._agents["a1"] = _make_health("a1")
        result = await guardian.health_check_all()
        assert result["a1"].health == "healthy"


# ---- Token usage tests ----

class TestTokenUsage:
    def test_record_and_get(self, guardian):
        guardian.record_token_usage("gpt-4", 100)
        guardian.record_token_usage("gpt-4", 50)
        guardian.record_token_usage("claude-3", 200)
        usage = guardian.get_token_usage("day")
        assert usage["gpt-4"] == 150
        assert usage["claude-3"] == 200

    def test_filter_by_model(self, guardian):
        guardian.record_token_usage("gpt-4", 100)
        guardian.record_token_usage("claude-3", 200)
        assert guardian.get_token_usage("day", model="gpt-4") == {"gpt-4": 100}

    def test_collect_token_usage(self, guardian):
        guardian.record_token_usage("gpt-4", 100)
        result = asyncio.get_event_loop().run_until_complete(guardian.collect_token_usage())
        assert result["gpt-4"] == 100

    def test_invalid_period(self, guardian):
        with pytest.raises(ValueError):
            guardian.get_token_usage("year")


# ---- Alert tests ----

class TestAlerts:
    @pytest.mark.asyncio
    async def test_crashed_agent_alert(self, lifecycle, bus, guardian):
        lifecycle._agents["a1"] = _make_health("a1", state=AgentState.CRASHED)
        alerts = await guardian.alert_if_needed()
        assert any("CRITICAL" in a and "crashed" in a for a in alerts)

    @pytest.mark.asyncio
    async def test_stopped_agent_alert(self, lifecycle, bus, guardian):
        lifecycle._agents["a1"] = _make_health("a1", state=AgentState.STOPPED)
        alerts = await guardian.alert_if_needed()
        assert any("WARNING" in a and "stopped" in a for a in alerts)

    @pytest.mark.asyncio
    async def test_heartbeat_timeout_alert(self, lifecycle, bus, guardian):
        lifecycle._agents["a1"] = _make_health("a1", last_heartbeat=time.time() - 600)
        alerts = await guardian.alert_if_needed()
        assert any("heartbeat timeout" in a for a in alerts)

    @pytest.mark.asyncio
    async def test_token_budget_exceeded(self, lifecycle, bus):
        g = GuardianAgent(lifecycle, bus, token_budget={"gpt-4": 50})
        g.record_token_usage("gpt-4", 100)
        alerts = await g.alert_if_needed()
        assert any("budget exceeded" in a for a in alerts)

    @pytest.mark.asyncio
    async def test_no_alerts_when_healthy(self, lifecycle, bus, guardian):
        lifecycle._agents["a1"] = _make_health("a1")
        alerts = await guardian.alert_if_needed()
        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_alerts_broadcast_via_bus(self, lifecycle, bus, guardian):
        bus.register_agent("listener")
        lifecycle._agents["a1"] = _make_health("a1", state=AgentState.CRASHED)
        await guardian.alert_if_needed()
        msg = await bus.receive("listener", timeout=1.0)
        assert msg is not None
        assert "CRITICAL" in msg.content

    @pytest.mark.asyncio
    async def test_disk_space_alert(self, lifecycle, bus):
        g = GuardianAgent(lifecycle, bus)
        with patch("shutil.disk_usage") as mock_du:
            mock_du.return_value = MagicMock(used=96, total=100)
            alerts = await g.alert_if_needed()
            assert any("Disk usage" in a for a in alerts)


# ---- Resource cleanup tests ----

class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_stale_worktree(self, lifecycle, bus, guardian, tmp_path):
        wt_dir = tmp_path / "worktrees"
        wt_dir.mkdir()
        old = wt_dir / "old_worktree"
        old.mkdir()
        # Set mtime to 25 hours ago
        old_mtime = time.time() - 90000
        os_utime(old, (old_mtime, old_mtime))

        cleaned = await guardian.cleanup_stale_resources()
        assert cleaned >= 1
        assert not old.exists()

    @pytest.mark.asyncio
    async def test_cleanup_stale_temp_files(self, lifecycle, bus, guardian, tmp_path):
        tmp = tmp_path / "tmp"
        tmp.mkdir()
        old_file = tmp / "old.tmp"
        old_file.write_text("x")
        os_utime(old_file, (time.time() - 90000, time.time() - 90000))

        cleaned = await guardian.cleanup_stale_resources()
        assert cleaned >= 1
        assert not old_file.exists()

    @pytest.mark.asyncio
    async def test_no_cleanup_for_fresh_files(self, lifecycle, bus, guardian, tmp_path):
        tmp = tmp_path / "tmp"
        tmp.mkdir()
        fresh = tmp / "fresh.tmp"
        fresh.write_text("x")

        cleaned = await guardian.cleanup_stale_resources()
        assert cleaned == 0
        assert fresh.exists()


# ---- Main loop test ----

class TestRun:
    @pytest.mark.asyncio
    async def test_run_stops_on_flag(self, lifecycle, bus, tmp_path):
        g = GuardianAgent(lifecycle, bus, check_interval=0.01, temp_dir=tmp_path / "tmp")
        task = asyncio.create_task(g.run())
        await asyncio.sleep(0.05)
        g.stop()
        await asyncio.sleep(0.05)
        assert not g._running
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# Helper
import os
def os_utime(path, times):
    os.utime(path, times)
