"""Result aggregator for combining subtask outputs."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .types import TaskGraph, OrchestrationResult


class ResultAggregator:
    """Result aggregator.

    Collects and merges results from subtasks into a unified output.
    """

    def aggregate(self, graph: "TaskGraph") -> "OrchestrationResult":
        """Aggregate results from all subtasks.

        Args:
            graph: Task graph to aggregate results from

        Returns:
            OrchestrationResult containing aggregated results and metadata
        """
        from .types import TaskState, OrchestrationResult

        # Collect results and errors
        results = {}
        errors = {}
        completed_tasks = 0
        failed_tasks = 0

        for task_id, task in graph.nodes.items():
            if task.state == TaskState.COMPLETED:
                completed_tasks += 1
                if task.result is not None:
                    results[task_id] = task.result
            elif task.state == TaskState.FAILED:
                failed_tasks += 1
                if task.error:
                    errors[task_id] = task.error

        total_tasks = len(graph.nodes)
        success = failed_tasks == 0 and completed_tasks == total_tasks

        # Create result object
        result = OrchestrationResult(
            graph_id=graph.id,
            success=success,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            results=results,
            errors=errors
        )

        # Merge results if possible
        if results:
            try:
                merged_result = self._merge_results(results)
                # Add merged result as a special entry
                result.results["_merged"] = merged_result
            except Exception as e:
                # If merge fails, keep individual results
                errors["_merge_error"] = str(e)

        return result

    def _merge_results(self, results: dict[str, Any]) -> Any:
        """Merge subtask results using intelligent merging strategy.

        The merging strategy depends on the types and structures of the results:

        1. If all results are dicts: merge them recursively
        2. If all results are lists: concatenate them
        3. If all results are strings: join them with newlines
        4. If results are mixed: return a dict with task_id as key

        Args:
            results: Dict mapping task_id to result

        Returns:
            Merged result
        """
        if not results:
            return None

        # Get all result values
        values = list(results.values())

        if len(values) == 1:
            return values[0]

        # Check types and determine merge strategy
        all_dicts = all(isinstance(v, dict) for v in values)
        all_lists = all(isinstance(v, list) for v in values)
        all_strings = all(isinstance(v, str) for v in values)

        if all_dicts:
            # Merge dicts recursively
            merged = {}
            for value in values:
                merged.update(value)
            return merged
        elif all_lists:
            # Concatenate lists
            merged = []
            for value in values:
                merged.extend(value)
            return merged
        elif all_strings:
            # Join strings
            return "\n".join(values)
        else:
            # Mixed types - return as-is
            # The individual results are already stored in the OrchestrationResult
            return results

    def _generate_summary(self, result: "OrchestrationResult") -> str:
        """Generate a human-readable summary.

        Args:
            result: Orchestration result to summarize

        Returns:
            Human-readable summary string
        """
        lines = [
            f"Task Orchestration Summary",
            f"===========================",
            f"Graph ID: {result.graph_id}",
            f"Status: {'SUCCESS' if result.success else 'FAILED'}",
            f"Tasks: {result.completed_tasks}/{result.total_tasks} completed",
            f"Failed: {result.failed_tasks}",
        ]

        if result.errors:
            lines.append("\nErrors:")
            for task_id, error in result.errors.items():
                lines.append(f"  [{task_id}] {error}")

        if result.results:
            lines.append("\nResults:")
            for task_id, value in result.results.items():
                if task_id.startswith("_"):
                    continue  # Skip internal entries
                # Truncate long results
                value_str = str(value)
                if len(value_str) > 100:
                    value_str = value_str[:97] + "..."
                lines.append(f"  [{task_id}] {value_str}")

        return "\n".join(lines)
