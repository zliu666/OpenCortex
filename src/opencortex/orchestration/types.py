"""Core data types for task orchestration."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskState(Enum):
    """Task execution states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Task priority levels."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class TaskNode:
    """Single task node in the orchestration graph."""
    id: str
    name: str
    description: str
    state: TaskState = TaskState.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    dependencies: list[str] = field(default_factory=list)  # List of task_id this task depends on
    assigned_agent: str | None = None
    result: Any = None
    error: str | None = None
    created_at: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskGraph:
    """Task DAG (Directed Acyclic Graph) representing the orchestration plan."""
    id: str
    name: str
    description: str
    root_task_id: str  # Root task ID
    nodes: dict[str, TaskNode] = field(default_factory=dict)
    state: TaskState = TaskState.PENDING


@dataclass
class OrchestrationResult:
    """Result of task orchestration execution."""
    graph_id: str
    success: bool
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    results: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
