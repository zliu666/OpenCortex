from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

import logging

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent 状态枚举。"""
    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    STOPPED = "stopped"
    ERROR = "error"
    CRASHED = "crashed"


@dataclass
class AgentHealth:
    """Agent 健康度指标。"""
    agent_id: str
    state: AgentState
    health: Literal["healthy", "degraded", "unhealthy"]
    cpu_percent: float
    memory_mb: float
    disk_mb: float
    last_heartbeat: float
    uptime_seconds: float
    error_count: int
    restart_count: int


@dataclass
class AgentEvent:
    """Agent 事件。"""
    timestamp: float
    agent_id: str
    event_type: Literal["state_change", "error", "warning", "resource_limit", "heartbeat"]
    details: dict


class AgentLifecycleManager:
    """Agent 生命周期管理器。"""

    def __init__(self) -> None:
        self._agents: dict[str, AgentHealth] = {}
        self._events: list[AgentEvent] = []
        self._start_times: dict[str, float] = {}

    def register_agent(self, agent_id: str) -> None:
        if agent_id in self._agents:
            logger.warning(f"Agent {agent_id} already registered")
            return
        now = datetime.now().timestamp()
        self._agents[agent_id] = AgentHealth(
            agent_id=agent_id, state=AgentState.STARTING, health="healthy",
            cpu_percent=0, memory_mb=0, disk_mb=0, last_heartbeat=now,
            uptime_seconds=0, error_count=0, restart_count=0,
        )
        self._start_times[agent_id] = now

    def update_state(self, agent_id: str, new_state: AgentState) -> None:
        if agent_id not in self._agents:
            logger.warning(f"Agent {agent_id} not found for state update")
            return
        old_state = self._agents[agent_id].state
        self._agents[agent_id].state = new_state
        self._events.append(AgentEvent(
            timestamp=datetime.now().timestamp(), agent_id=agent_id,
            event_type="state_change", details={"from": old_state, "to": new_state},
        ))
        logger.debug(f"Agent {agent_id} state: {old_state} -> {new_state}")

    def record_error(self, agent_id: str, error_message: str) -> None:
        if agent_id not in self._agents:
            return
        self._agents[agent_id].error_count += 1
        if self._agents[agent_id].error_count > 5:
            self._agents[agent_id].health = "degraded"
        self._events.append(AgentEvent(
            timestamp=datetime.now().timestamp(), agent_id=agent_id,
            event_type="error", details={"message": error_message},
        ))
        logger.error(f"Agent {agent_id} error: {error_message}")

    def record_heartbeat(self, agent_id: str) -> None:
        if agent_id not in self._agents:
            return
        now = datetime.now().timestamp()
        self._agents[agent_id].last_heartbeat = now
        start = self._start_times.get(agent_id, now)
        self._agents[agent_id].uptime_seconds = now - start
        self._events.append(AgentEvent(
            timestamp=now, agent_id=agent_id, event_type="heartbeat", details={},
        ))

    def get_agent_health(self, agent_id: str) -> Optional[AgentHealth]:
        return self._agents.get(agent_id)

    def restart_agent(self, agent_id: str) -> None:
        if agent_id not in self._agents:
            logger.warning(f"Agent {agent_id} not found for restart")
            return
        self._agents[agent_id].restart_count += 1
        self._agents[agent_id].state = AgentState.STARTING
        self._agents[agent_id].health = "healthy"
        self._agents[agent_id].error_count = 0
        now = datetime.now().timestamp()
        self._start_times[agent_id] = now
        self._agents[agent_id].last_heartbeat = now
        self._events.append(AgentEvent(
            timestamp=now, agent_id=agent_id, event_type="state_change",
            details={"action": "restart", "reason": "manual"},
        ))
        logger.info(f"Agent {agent_id} restarting (count: {self._agents[agent_id].restart_count})")

    def get_all_agents(self) -> dict[str, AgentHealth]:
        return self._agents

    def cleanup_agent(self, agent_id: str) -> None:
        if agent_id in self._agents:
            del self._agents[agent_id]
        self._start_times.pop(agent_id, None)
