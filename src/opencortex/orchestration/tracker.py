"""Task tracker for monitoring progress and estimating completion."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import TaskGraph, TaskState


class TaskTracker:
    """Task progress tracker.

    Monitors task execution progress, critical paths, and time estimates.
    """

    def get_progress(self, graph: "TaskGraph") -> dict:
        """Get progress information.

        Args:
            graph: Task graph to track

        Returns:
            Progress dictionary with keys:
            - total: Total number of tasks
            - completed: Number of completed tasks
            - running: Number of running tasks
            - pending: Number of pending tasks
            - failed: Number of failed tasks
            - percent: Completion percentage (0-100)
        """
        from .types import TaskState

        total = len(graph.nodes)
        completed = sum(1 for task in graph.nodes.values() if task.state == TaskState.COMPLETED)
        running = sum(1 for task in graph.nodes.values() if task.state == TaskState.RUNNING)
        pending = sum(1 for task in graph.nodes.values() if task.state == TaskState.PENDING)
        failed = sum(1 for task in graph.nodes.values() if task.state == TaskState.FAILED)

        percent = int((completed / total) * 100) if total > 0 else 0

        return {
            "total": total,
            "completed": completed,
            "running": running,
            "pending": pending,
            "failed": failed,
            "percent": percent
        }

    def get_critical_path(self, graph: "TaskGraph") -> list[str]:
        """Get the critical path (longest dependency chain).

        The critical path determines the minimum time required to complete all tasks.
        Tasks on the critical path have no slack time.

        Args:
            graph: Task graph to analyze

        Returns:
            List of task IDs in the critical path order
        """
        # Build the graph structure
        # We need to find the longest path from any source to any sink
        from .types import TaskState

        # Find source tasks (no dependencies)
        sources = [
            task_id for task_id, task in graph.nodes.items()
            if not task.dependencies or all(
                dep not in graph.nodes for dep in task.dependencies
            )
        ]

        if not sources:
            # No sources found - might be a cycle or empty graph
            return []

        # Find sink tasks (no other tasks depend on them)
        dependents = {task_id: set() for task_id in graph.nodes}
        for task_id, task in graph.nodes.items():
            for dep_id in task.dependencies:
                if dep_id in dependents:
                    dependents[dep_id].add(task_id)

        sinks = [
            task_id for task_id, deps in dependents.items()
            if not deps
        ]

        if not sinks:
            return []

        # Use DFS with path tracking to find the longest path
        longest_path = []
        longest_length = 0

        def dfs(current_id: str, path: list[str], visited: set[str]) -> None:
            """Depth-first search to find longest path.

            Args:
                current_id: Current task ID
                path: Current path from source
                visited: Set of visited nodes
            """
            nonlocal longest_path, longest_length

            path.append(current_id)
            visited.add(current_id)

            # Get tasks that depend on current task
            next_tasks = [
                dep_id for dep_id in dependents.get(current_id, [])
                if dep_id not in visited
            ]

            if not next_tasks:
                # Reached a sink - check if this is the longest path
                if len(path) > longest_length:
                    longest_path = path.copy()
                    longest_length = len(path)
            else:
                # Continue exploring
                for next_id in next_tasks:
                    dfs(next_id, path.copy(), visited)

        # Start DFS from each source
        for source_id in sources:
            dfs(source_id, [], set())

        return longest_path

    def estimate_remaining_time(self, graph: "TaskGraph") -> float:
        """Estimate remaining time based on completed tasks' average duration.

        Args:
            graph: Task graph to analyze

        Returns:
            Estimated remaining time in seconds (0 if cannot estimate)
        """
        from .types import TaskState

        # Find completed tasks with valid timing data
        completed_durations = []
        for task in graph.nodes.values():
            if (task.state == TaskState.COMPLETED and
                task.started_at is not None and
                task.completed_at is not None):
                duration = task.completed_at - task.started_at
                if duration > 0:
                    completed_durations.append(duration)

        if not completed_durations:
            # No completed tasks with timing data - cannot estimate
            return 0.0

        # Calculate average duration
        avg_duration = sum(completed_durations) / len(completed_durations)

        # Count remaining tasks
        remaining_tasks = sum(
            1 for task in graph.nodes.values()
            if task.state in (TaskState.PENDING, TaskState.RUNNING)
        )

        if remaining_tasks == 0:
            return 0.0

        # Simple estimate: remaining tasks * average duration
        # This is a rough estimate - actual parallel execution could be faster
        estimated_time = remaining_tasks * avg_duration

        # Adjust for parallel execution potential
        # Get critical path length to estimate parallelism
        critical_path = self.get_critical_path(graph)
        if critical_path:
            # Tasks not on critical path can potentially run in parallel
            critical_count = len(critical_path)
            non_critical_count = remaining_tasks - critical_count

            if non_critical_count > 0 and critical_count > 0:
                # Assume non-critical tasks can run in parallel with critical path tasks
                # This is optimistic but gives a better estimate
                estimated_time = critical_count * avg_duration + (non_critical_count * avg_duration / max(1, non_critical_count))

        return estimated_time
