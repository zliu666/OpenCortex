"""Orchestration engine for task execution."""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Callable, Any

if TYPE_CHECKING:
    from .types import TaskGraph, TaskState, OrchestrationResult

log = logging.getLogger(__name__)


class OrchestrationEngine:
    """Task orchestration engine.

    Integrates planner + scheduler + tracker + aggregator for end-to-end
    task execution.  When *dual_model* mode is enabled (see ``settings.json``),
    each subtask is routed through :class:`~opencortex.swarm.task_tier.TaskTierRouter`
    so that CORE/CRITICAL tasks use the strong model and SYSTEM/UTILITY tasks
    use the lightweight executor (e.g. MiniMax-M2.7).
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
                     If None, auto-selects executor based on dual_model settings:
                     - When dual_model is enabled, uses :meth:`_tiered_executor`
                       which routes each task via TaskTierRouter.
                     - Otherwise, falls back to :meth:`_mock_executor`.

        Returns:
            OrchestrationResult containing aggregated results
        """
        from .types import TaskState

        graph = self._active_graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph not found: {graph_id}")

        if executor is None:
            executor = self._auto_executor()

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

    # ------------------------------------------------------------------
    # Executor selection
    # ------------------------------------------------------------------

    def _auto_executor(self) -> Callable[[str, "TaskGraph"], Any]:
        """Return the default executor based on dual_model settings.

        - **dual_model enabled** → :meth:`_tiered_executor` which routes each
          task through TaskTierRouter and uses LightweightExecutor for
          SYSTEM/UTILITY tasks.
        - **dual_model disabled** → :meth:`_mock_executor` (legacy behaviour).
        """
        try:
            from opencortex.config.settings import load_settings
            settings = load_settings()
            if settings.dual_model.enabled:
                log.info("dual_model enabled — using tiered executor")
                return self._tiered_executor
        except Exception:
            log.debug("Could not load settings, falling back to mock executor", exc_info=True)

        return self._mock_executor

    def _tiered_executor(self, task_id: str, graph: "TaskGraph") -> Any:
        """Executor that routes tasks by tier.

        - CORE / CRITICAL → returns a sentinel dict requesting the strong model.
        - SYSTEM / UTILITY → delegates to LightweightExecutor for cheap execution.

        This is a *synchronous* callable.  The async lightweight-executor call
        is scheduled on the *running* event loop when one is available
        (``_execute_task`` runs us via ``asyncio.to_thread``), otherwise
        falls back to ``asyncio.run`` in a fresh loop.
        """
        from opencortex.swarm.task_tier import TaskTier, TaskTierRouter

        task = graph.nodes[task_id]
        router = TaskTierRouter()
        tier = router.classify(task.description)

        if tier in (TaskTier.CORE, TaskTier.CRITICAL):
            model = router.route(tier)
            return {
                "_tier": tier.value,
                "_model": model,
                "task_id": task_id,
                "task": task.name,
                "description": task.description,
                "result": f"[{tier.value.upper()}] Requires strong model: {model}",
            }

        # SYSTEM / UTILITY → lightweight executor
        try:
            from opencortex.swarm.lightweight_executor import LightweightExecutor
            executor = LightweightExecutor(tier=tier)
            result_text = self._run_async(executor.summarize(task.description))
            return {
                "_tier": tier.value,
                "_model": executor.model,
                "task_id": task_id,
                "task": task.name,
                "description": task.description,
                "result": result_text,
            }
        except Exception as exc:
            log.warning(
                "Lightweight executor failed for task %s, falling back: %s",
                task_id, exc,
            )
            return {
                "_tier": tier.value,
                "_model": "fallback",
                "task_id": task_id,
                "task": task.name,
                "description": task.description,
                "result": f"Fallback: {task.description}",
            }

    @staticmethod
    def _run_async(coro) -> Any:
        """Run an async coroutine from sync code.

        When called from ``asyncio.to_thread`` there is no running loop in the
        current thread, so ``asyncio.run()`` works directly.  When called
        directly from an async context (e.g. tests), we offload to a thread.
        """
        try:
            asyncio.get_running_loop()
            # Already inside a running loop — run in a worker thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
