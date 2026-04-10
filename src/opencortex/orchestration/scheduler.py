"""Task scheduler for executing tasks based on dependencies and priorities."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import TaskGraph, TaskState


class TaskScheduler:
    """Task scheduler.

    Determines task execution order based on dependency relationships and priorities.
    Supports parallel scheduling of independent tasks.
    """

    def schedule(self, graph: "TaskGraph") -> list[list[str]]:
        """Generate a layered execution plan (tasks within each layer can run in parallel).

        Args:
            graph: Task graph to schedule

        Returns:
            List of layers, where each layer is a list of task IDs that can run in parallel.
            Example: [[t1, t2], [t3], [t4, t5]] means:
            - Layer 1: t1, t2 run in parallel
            - Layer 2: t3 runs (waits for t1, t2 to complete)
            - Layer 3: t4, t5 run in parallel (waits for t3 to complete)
        """
        from .types import TaskState

        # Create a working copy of the graph
        # We'll use a list of (node_id, dependencies) tuples
        remaining_tasks = {}
        for node_id, node in graph.nodes.items():
            # Only include non-completed tasks
            if node.state in (TaskState.PENDING, TaskState.RUNNING, TaskState.FAILED):
                remaining_tasks[node_id] = list(node.dependencies)

        layers = []
        processed = set()

        while remaining_tasks:
            # Find tasks with no remaining dependencies
            ready_tasks = [
                task_id
                for task_id, deps in remaining_tasks.items()
                if all(
                    dep not in remaining_tasks or dep in processed
                    for dep in deps
                )
            ]

            if not ready_tasks:
                # No tasks are ready - this shouldn't happen in a valid DAG
                # but we handle it gracefully
                remaining_tasks.clear()
                break

            # Sort by priority (lower value = higher priority)
            ready_tasks.sort(key=lambda tid: graph.nodes[tid].priority.value)

            # Add current layer
            layers.append(ready_tasks)

            # Mark tasks as processed and remove from remaining
            for task_id in ready_tasks:
                processed.add(task_id)
                del remaining_tasks[task_id]

        return layers

    def get_ready_tasks(self, graph: "TaskGraph") -> list[str]:
        """Get tasks that are ready to execute (all dependencies completed).

        Args:
            graph: Task graph to check

        Returns:
            List of task IDs ready for execution
        """
        from .types import TaskState

        ready_tasks = []

        for task_id, task in graph.nodes.items():
            # Skip already completed or running tasks
            if task.state not in (TaskState.PENDING, TaskState.FAILED):
                continue

            # Check if all dependencies are completed
            dependencies_completed = True
            for dep_id in task.dependencies:
                dep_task = graph.nodes.get(dep_id)
                if not dep_task:
                    # Invalid dependency - treat as not ready
                    dependencies_completed = False
                    break
                if dep_task.state != TaskState.COMPLETED:
                    dependencies_completed = False
                    break

            if dependencies_completed:
                ready_tasks.append(task_id)

        # Sort by priority
        ready_tasks.sort(key=lambda tid: graph.nodes[tid].priority.value)

        return ready_tasks

    def mark_completed(self, graph: "TaskGraph", task_id: str) -> None:
        """Mark a task as completed and update graph state.

        Args:
            graph: Task graph to update
            task_id: ID of the completed task
        """
        from .types import TaskState

        task = graph.nodes.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        task.state = TaskState.COMPLETED
        import time
        task.completed_at = time.time()

        # Update graph state
        self._update_graph_state(graph)

    def mark_failed(self, graph: "TaskGraph", task_id: str, error: str) -> None:
        """Mark a task as failed and update graph state.

        Args:
            graph: Task graph to update
            task_id: ID of the failed task
            error: Error message
        """
        from .types import TaskState

        task = graph.nodes.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        task.state = TaskState.FAILED
        task.error = error
        import time
        task.completed_at = time.time()

        # Update graph state
        self._update_graph_state(graph)

    def mark_running(self, graph: "TaskGraph", task_id: str) -> None:
        """Mark a task as running.

        Args:
            graph: Task graph to update
            task_id: ID of the task to mark as running
        """
        from .types import TaskState

        task = graph.nodes.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        task.state = TaskState.RUNNING
        import time
        task.started_at = time.time()

        # Update graph state
        self._update_graph_state(graph)

    def _update_graph_state(self, graph: "TaskGraph") -> None:
        """Update the overall graph state based on task states.

        Args:
            graph: Task graph to update
        """
        from .types import TaskState

        states = [task.state for task in graph.nodes.values()]

        # If any task is running, graph is running
        if TaskState.RUNNING in states:
            graph.state = TaskState.RUNNING
            return

        # If any task failed, graph is failed (unless there are still pending tasks)
        if TaskState.FAILED in states and TaskState.PENDING not in states:
            graph.state = TaskState.FAILED
            return

        # If all tasks are completed, graph is completed
        if all(s == TaskState.COMPLETED for s in states):
            graph.state = TaskState.COMPLETED
            return

        # Default to pending
        graph.state = TaskState.PENDING
