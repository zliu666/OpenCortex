"""Orchestration engine for task execution."""

import asyncio
import time
from typing import TYPE_CHECKING, Callable, Any

if TYPE_CHECKING:
    from .types import TaskGraph, TaskState, OrchestrationResult


class OrchestrationEngine:
    """Task orchestration engine.

    Integrates planner + scheduler + tracker + aggregator for end-to-end task execution.
    """

    def __init__(self):
        """Initialize the orchestration engine."""
        from .planner import TaskPlanner
        from .scheduler import TaskScheduler
        from .tracker import TaskTracker
        from .aggregator import ResultAggregator

        self._planner = TaskPlanner()
        self._scheduler = TaskScheduler()
        self._tracker = TaskTracker()
        self._aggregator = ResultAggregator()
        self._active_graphs: dict[str, "TaskGraph"] = {}

    async def submit(
        self,
        description: str,
        strategy: str = "auto"
    ) -> "TaskGraph":
        """Submit a task for orchestration.

        Decomposes the task and returns the task graph ready for execution.

        Args:
            description: Task description
            strategy: Decomposition strategy ("rule", "llm", or "auto")

        Returns:
            TaskGraph: Decomposed task graph
        """
        graph = self._planner.decompose(description, strategy)
        self._active_graphs[graph.id] = graph
        return graph

    async def execute(
        self,
        graph_id: str,
        executor: Callable[[str, "TaskGraph"], Any] | None = None
    ) -> "OrchestrationResult":
        """Execute a task graph.

        Args:
            graph_id: ID of the task graph to execute
            executor: Optional executor function(task_id, graph) -> result.
                     If None, uses a mock executor for testing.

        Returns:
            OrchestrationResult containing aggregated results
        """
        from .types import TaskState

        graph = self._active_graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph not found: {graph_id}")

        # Default mock executor for testing
        if executor is None:
            executor = self._mock_executor

        # Execute tasks in layers based on dependencies
        layers = self._scheduler.schedule(graph)

        for layer_index, layer in enumerate(layers):
            # Execute all tasks in current layer in parallel
            tasks_to_execute = [
                self._execute_task(task_id, graph, executor)
                for task_id in layer
            ]

            # Wait for all tasks in this layer to complete
            await asyncio.gather(*tasks_to_execute, return_exceptions=True)

            # Check for failures
            for task_id in layer:
                task = graph.nodes[task_id]
                if task.state == TaskState.FAILED:
                    # On failure, cancel dependent tasks
                    await self._cancel_dependent_tasks(graph, task_id)

        # Aggregate results
        result = self._aggregator.aggregate(graph)

        # Clean up completed graph
        if graph.state != TaskState.RUNNING:
            del self._active_graphs[graph_id]

        return result

    def get_status(self, graph_id: str) -> dict:
        """Get the status of a task graph.

        Args:
            graph_id: ID of the task graph

        Returns:
            Status dictionary with progress and state information
        """
        graph = self._active_graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph not found: {graph_id}")

        progress = self._tracker.get_progress(graph)
        critical_path = self._tracker.get_critical_path(graph)
        remaining_time = self._tracker.estimate_remaining_time(graph)

        return {
            "graph_id": graph_id,
            "graph_name": graph.name,
            "graph_state": graph.state.value,
            "progress": progress,
            "critical_path": critical_path,
            "estimated_remaining_time": remaining_time
        }

    async def cancel(self, graph_id: str) -> None:
        """Cancel a task graph execution.

        Args:
            graph_id: ID of the task graph to cancel
        """
        from .types import TaskState

        graph = self._active_graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph not found: {graph_id}")

        # Cancel all pending and running tasks
        for task in graph.nodes.values():
            if task.state in (TaskState.PENDING, TaskState.RUNNING):
                task.state = TaskState.CANCELLED
                task.completed_at = time.time()

        # Update graph state
        graph.state = TaskState.CANCELLED

        # Clean up
        del self._active_graphs[graph_id]

    async def _execute_task(
        self,
        task_id: str,
        graph: "TaskGraph",
        executor: Callable[[str, "TaskGraph"], Any]
    ) -> None:
        """Execute a single task.

        Args:
            task_id: ID of the task to execute
            graph: Task graph containing the task
            executor: Executor function
        """
        from .types import TaskState

        task = graph.nodes[task_id]

        # Check if task should run
        if task.state != TaskState.PENDING:
            return

        # Mark as running
        self._scheduler.mark_running(graph, task_id)

        try:
            # Execute the task
            result = await asyncio.to_thread(executor, task_id, graph)

            # Store result and mark as completed
            task.result = result
            self._scheduler.mark_completed(graph, task_id)

        except Exception as e:
            # Mark as failed
            error_msg = f"{type(e).__name__}: {str(e)}"
            self._scheduler.mark_failed(graph, task_id, error_msg)

    async def _cancel_dependent_tasks(
        self,
        graph: "TaskGraph",
        failed_task_id: str
    ) -> None:
        """Cancel tasks that depend on a failed task.

        Args:
            graph: Task graph
            failed_task_id: ID of the failed task
        """
        from .types import TaskState

        # Find all tasks that depend (directly or indirectly) on the failed task
        def find_dependents(current_id: str, visited: set[str]) -> set[str]:
            """Recursively find all dependent tasks.

            Args:
                current_id: Current task ID to check
                visited: Set of visited tasks

            Returns:
                Set of dependent task IDs
            """
            dependents = set()

            for task_id, task in graph.nodes.items():
                if task_id in visited:
                    continue

                if current_id in task.dependencies:
                    visited.add(task_id)
                    dependents.add(task_id)
                    # Recursively find dependents of this task
                    dependents.update(find_dependents(task_id, visited))

            return dependents

        dependents = find_dependents(failed_task_id, set())

        # Cancel all dependent tasks
        for task_id in dependents:
            task = graph.nodes[task_id]
            if task.state in (TaskState.PENDING, TaskState.RUNNING):
                task.state = TaskState.CANCELLED
                task.error = f"Cancelled due to dependency failure: {failed_task_id}"
                task.completed_at = time.time()

    def _mock_executor(self, task_id: str, graph: "TaskGraph") -> Any:
        """Mock executor for testing.

        Args:
            task_id: ID of the task
            graph: Task graph

        Returns:
            Mock result
        """
        task = graph.nodes[task_id]
        # Simulate work with a small delay
        time.sleep(0.01)
        return f"Mock result for {task.name}"
