"""Task orchestration engine for OpenCortex.

This module provides task decomposition, scheduling, tracking, and aggregation
capabilities for AI agent orchestration.

Example usage:
    ```python
    from opencortex.orchestration import OrchestrationEngine

    engine = OrchestrationEngine()
    graph = await engine.submit("Build a web app")
    result = await engine.execute(graph.id)
    ```
"""

from .types import (
    TaskState,
    TaskPriority,
    TaskNode,
    TaskGraph,
    OrchestrationResult,
)
from .planner import TaskPlanner
from .scheduler import TaskScheduler
from .tracker import TaskTracker
from .aggregator import ResultAggregator
from .engine import OrchestrationEngine

__all__ = [
    # Types
    "TaskState",
    "TaskPriority",
    "TaskNode",
    "TaskGraph",
    "OrchestrationResult",
    # Core components
    "TaskPlanner",
    "TaskScheduler",
    "TaskTracker",
    "ResultAggregator",
    "OrchestrationEngine",
]
