"""System Guardian Agent — background monitoring and resource cleanup."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .lifecycle import AgentHealth, AgentState

if TYPE_CHECKING:
    from .lifecycle import AgentLifecycleManager
    from .message_bus import MessageBus

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    level: AlertLevel
    message: str
    agent_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class GuardianAgent:
    """系统守护 Agent — 后台监控和资源整理。"""

    HEARTBEAT_TIMEOUT = 300  # 5 minutes
    DEFAULT_CHECK_INTERVAL = 1800  # 30 minutes
    WORKTREE_MAX_AGE = 86400  # 24 hours

    def __init__(
        self,
        lifecycle_manager: AgentLifecycleManager,
        message_bus: MessageBus,
        *,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        worktree_dir: str | Path | None = None,
        temp_dir: str | Path | None = None,
        token_budget: dict[str, int] | None = None,
    ) -> None:
        self._lifecycle = lifecycle_manager
        self._message_bus = message_bus
        self._check_interval = check_interval
        self._worktree_dir = Path(worktree_dir) if worktree_dir else None
        self._temp_dir = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir())
        self._token_budget = token_budget or {}
        self._token_usage: dict[str, dict[str, int]] = {}  # date_str -> {model -> count}
        self._running = False
        self._alerts: list[Alert] = []

    # ------------------------------------------------------------------
    # Token usage tracking
    # ------------------------------------------------------------------

    def record_token_usage(self, model: str, tokens: int) -> None:
        """Record token consumption for a model."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self._token_usage:
            self._token_usage[today] = {}
        self._token_usage[today][model] = self._token_usage[today].get(model, 0) + tokens

    def get_token_usage(
        self, period: str = "day", model: str | None = None
    ) -> dict[str, int]:
        """Get token usage by period: day/week/month."""
        now = datetime.now()
        if period == "day":
            since = now - timedelta(days=1)
        elif period == "week":
            since = now - timedelta(weeks=1)
        elif period == "month":
            since = now - timedelta(days=30)
        else:
            raise ValueError(f"Invalid period: {period}")

        result: dict[str, int] = {}
        for date_str, models in self._token_usage.items():
            d = datetime.strptime(date_str, "%Y-%m-%d")
            if d < since:
                continue
            for m, count in models.items():
                if model and m != model:
                    continue
                result[m] = result.get(m, 0) + count
        return result

    async def collect_token_usage(self) -> dict[str, int]:
        """Collect all agents' token usage (aggregates today)."""
        return self.get_token_usage("day")

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def health_check_all(self) -> dict[str, AgentHealth]:
        """Check health of all registered agents."""
        agents = self._lifecycle.get_all_agents()
        now = time.time()
        for agent_id, health in agents.items():
            if health.state in (AgentState.CRASHED, AgentState.STOPPED):
                health.health = "unhealthy"
            elif (now - health.last_heartbeat) > self.HEARTBEAT_TIMEOUT:
                health.health = "unhealthy"
            elif health.state == AgentState.ERROR:
                health.health = "degraded"
        return agents

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    async def alert_if_needed(self) -> list[str]:
        """Detect anomalies and return alert messages."""
        alerts: list[str] = []
        agents = self._lifecycle.get_all_agents()
        now = time.time()

        for agent_id, health in agents.items():
            if health.state == AgentState.CRASHED:
                msg = f"[CRITICAL] Agent {agent_id} has crashed (restarts: {health.restart_count})"
                alerts.append(msg)
                await self._broadcast_alert(AlertLevel.CRITICAL, msg, agent_id)
            elif health.state == AgentState.STOPPED:
                msg = f"[WARNING] Agent {agent_id} is stopped"
                alerts.append(msg)
                await self._broadcast_alert(AlertLevel.WARNING, msg, agent_id)
            elif (now - health.last_heartbeat) > self.HEARTBEAT_TIMEOUT:
                msg = f"[WARNING] Agent {agent_id} heartbeat timeout ({int(now - health.last_heartbeat)}s)"
                alerts.append(msg)
                await self._broadcast_alert(AlertLevel.WARNING, msg, agent_id)
            elif health.state == AgentState.ERROR:
                msg = f"[INFO] Agent {agent_id} in error state (errors: {health.error_count})"
                alerts.append(msg)
                await self._broadcast_alert(AlertLevel.INFO, msg, agent_id)

        # Token budget alerts
        daily = self.get_token_usage("day")
        for model, budget in self._token_budget.items():
            used = daily.get(model, 0)
            if used > budget:
                msg = f"[CRITICAL] Token budget exceeded for {model}: {used}/{budget}"
                alerts.append(msg)
                await self._broadcast_alert(AlertLevel.CRITICAL, msg)

        # Disk space check
        disk_alert = self._check_disk_space()
        if disk_alert:
            alerts.append(disk_alert)
            level = AlertLevel.CRITICAL if "critical" in disk_alert.lower() else AlertLevel.WARNING
            await self._broadcast_alert(level, disk_alert)

        self._alerts.extend(
            Alert(level=AlertLevel.WARNING, message=a, timestamp=time.time()) for a in alerts
        )
        return alerts

    def _check_disk_space(self) -> str | None:
        """Check disk space, return alert or None."""
        try:
            usage = shutil.disk_usage("/")
            pct = usage.used / usage.total * 100
            if pct > 95:
                return f"[CRITICAL] Disk usage {pct:.1f}% — critically low space"
            if pct > 90:
                return f"[WARNING] Disk usage {pct:.1f}% — running low on space"
        except OSError:
            pass
        return None

    async def _broadcast_alert(self, level: AlertLevel, message: str, agent_id: str | None = None) -> None:
        """Broadcast alert via message bus."""
        from .message_bus import MessageType

        self._message_bus.broadcast(
            from_agent="guardian",
            message_type=MessageType.SYSTEM,
            content=message,
            payload={"level": level.value, "agent_id": agent_id},
        )

    # ------------------------------------------------------------------
    # Resource cleanup
    # ------------------------------------------------------------------

    async def cleanup_stale_resources(self) -> int:
        """Clean up stale resources. Returns count of items cleaned."""
        cleaned = 0
        now = time.time()

        # Clean stale worktrees
        if self._worktree_dir and self._worktree_dir.exists():
            for entry in self._worktree_dir.iterdir():
                if not entry.is_dir():
                    continue
                try:
                    mtime = entry.stat().st_mtime
                    if (now - mtime) > self.WORKTREE_MAX_AGE:
                        shutil.rmtree(entry, ignore_errors=True)
                        logger.info(f"Cleaned stale worktree: {entry}")
                        cleaned += 1
                except OSError as e:
                    logger.warning(f"Failed to clean {entry}: {e}")

        # Clean temp files older than 24h
        if self._temp_dir.exists():
            for entry in self._temp_dir.iterdir():
                if not entry.is_file():
                    continue
                try:
                    mtime = entry.stat().st_mtime
                    if (now - mtime) > self.WORKTREE_MAX_AGE:
                        entry.unlink(missing_ok=True)
                        logger.info(f"Cleaned temp file: {entry}")
                        cleaned += 1
                except OSError as e:
                    logger.warning(f"Failed to clean {entry}: {e}")

        return cleaned

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop: periodic health checks + cleanup."""
        self._running = True
        logger.info("Guardian agent started")

        while self._running:
            try:
                await self.health_check_all()
                alerts = await self.alert_if_needed()
                if alerts:
                    logger.warning(f"Guardian alerts: {alerts}")
                cleaned = await self.cleanup_stale_resources()
                if cleaned:
                    logger.info(f"Guardian cleaned {cleaned} stale resources")
            except Exception:
                logger.exception("Guardian check cycle failed")

            await asyncio.sleep(self._check_interval)

    def stop(self) -> None:
        """Stop the guardian main loop."""
        self._running = False
        logger.info("Guardian agent stopped")

    def get_alerts(self) -> list[Alert]:
        """Return recent alerts."""
        return list(self._alerts)
