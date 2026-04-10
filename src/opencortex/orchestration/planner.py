"""Task planner for decomposing complex tasks into subtask DAGs."""

import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import TaskGraph, TaskNode


class TaskPlanner:
    """Task decomposer.

    Breaks down complex tasks into subtask DAGs. Supports two modes:
    1. Rule-based decomposition (split by predefined rules)
    2. LLM-assisted decomposition (let LLM analyze and split)
    """

    def decompose(self, task_description: str, strategy: str = "auto") -> "TaskGraph":
        """Decompose a task into a subtask graph.

        Args:
            task_description: Description of the task to decompose
            strategy: Decomposition strategy ("rule", "llm", or "auto")

        Returns:
            TaskGraph: The decomposed task graph
        """
        if strategy == "auto":
            strategy = "rule"  # Default to rule-based

        if strategy == "rule":
            return self._rule_based_decompose(task_description)
        elif strategy == "llm":
            # LLM-based decomposition would be implemented here
            # For now, fall back to rule-based
            return self._rule_based_decompose(task_description)
        else:
            raise ValueError(f"Unknown decomposition strategy: {strategy}")

    def _rule_based_decompose(self, description: str) -> "TaskGraph":
        """Rule-based task decomposition.

        Simple rule-based approach that splits tasks based on common patterns.
        In production, this would be enhanced with more sophisticated rules.

        Args:
            description: Task description

        Returns:
            TaskGraph: Decomposed task graph
        """
        from .types import TaskGraph, TaskNode, TaskState, TaskPriority

        graph_id = str(uuid.uuid4())
        timestamp = time.time()

        # Create root task
        root_task = TaskNode(
            id="root",
            name="Root Task",
            description=description,
            state=TaskState.PENDING,
            priority=TaskPriority.NORMAL,
            created_at=timestamp
        )

        # Analyze description and create subtasks based on patterns
        nodes = {"root": root_task}
        subtasks = self._analyze_and_create_subtasks(description, timestamp)

        for i, subtask in enumerate(subtasks, 1):
            task_id = f"task_{i}"
            nodes[task_id] = subtask
            # Subtasks depend on root for now
            subtask.dependencies = ["root"]

        # Update root to know about its children
        root_task.dependencies = []

        graph = TaskGraph(
            id=graph_id,
            name="Orchestration Plan",
            description=description,
            root_task_id="root",
            nodes=nodes,
            state=TaskState.PENDING
        )

        # Validate the DAG
        if not self._validate_dag(graph):
            cycles = self._detect_cycles(graph)
            raise ValueError(f"Invalid DAG: detected cycles: {cycles}")

        return graph

    def _analyze_and_create_subtasks(self, description: str, timestamp: float) -> list["TaskNode"]:
        """Analyze task description and create subtasks.

        Args:
            description: Task description
            timestamp: Creation timestamp

        Returns:
            List of TaskNode objects
        """
        from .types import TaskNode, TaskState, TaskPriority

        subtasks = []
        desc_lower = description.lower()

        # Simple pattern-based decomposition
        # This is a placeholder - in production, this would use more sophisticated rules or LLM

        # Common task patterns
        if "and" in desc_lower:
            # Split by "and" - sequential tasks
            parts = description.split(" and ")
            for i, part in enumerate(parts):
                subtasks.append(TaskNode(
                    id=f"temp_{i}",
                    name=f"Subtask {i+1}",
                    description=part.strip(),
                    state=TaskState.PENDING,
                    priority=TaskPriority.NORMAL,
                    created_at=timestamp
                ))
                if i > 0:
                    # Sequential dependency
                    subtasks[-1].dependencies = [f"temp_{i-1}"]
        elif "or" in desc_lower:
            # Split by "or" - parallel tasks
            parts = description.split(" or ")
            for i, part in enumerate(parts):
                subtasks.append(TaskNode(
                    id=f"temp_{i}",
                    name=f"Alternative {i+1}",
                    description=part.strip(),
                    state=TaskState.PENDING,
                    priority=TaskPriority.NORMAL,
                    created_at=timestamp
                ))
        else:
            # Single task - no decomposition
            subtasks.append(TaskNode(
                id="temp_0",
                name="Main Task",
                description=description,
                state=TaskState.PENDING,
                priority=TaskPriority.NORMAL,
                created_at=timestamp
            ))

        return subtasks

    def _validate_dag(self, graph: "TaskGraph") -> bool:
        """Validate that the graph is a DAG (no cycles).

        Args:
            graph: Task graph to validate

        Returns:
            bool: True if DAG is valid (no cycles)
        """
        cycles = self._detect_cycles(graph)
        return len(cycles) == 0

    def _detect_cycles(self, graph: "TaskGraph") -> list[list[str]]:
        """Detect cycles in the task graph.

        Uses depth-first search (DFS) to find cycles.

        Args:
            graph: Task graph to analyze

        Returns:
            List of cycles (each cycle is a list of task IDs)
        """
        cycles = []
        visited = set()
        rec_stack = set()

        def dfs(node_id: str, path: list[str]) -> list[str] | None:
            """DFS traversal to detect cycles.

            Args:
                node_id: Current node ID
                path: Current path from root

            Returns:
                Cycle path if found, None otherwise
            """
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)

            # Check all dependencies
            node = graph.nodes.get(node_id)
            if node:
                for dep_id in node.dependencies:
                    if dep_id not in graph.nodes:
                        continue  # Skip invalid dependencies

                    if dep_id not in visited:
                        cycle = dfs(dep_id, path.copy())
                        if cycle:
                            return cycle
                    elif dep_id in rec_stack:
                        # Found a cycle
                        cycle_start = path.index(dep_id)
                        return path[cycle_start:] + [dep_id]

            rec_stack.remove(node_id)
            return None

        # Check all nodes
        for node_id in graph.nodes:
            if node_id not in visited:
                cycle = dfs(node_id, [])
                if cycle:
                    cycles.append(cycle)

        return cycles
