"""A2A Task Manager - Manages task lifecycle and state."""

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Optional, Dict, List
import uuid


class TaskStatus(str, Enum):
    """A2A Task status."""

    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PENDING_INPUT = "pending_input"


@dataclass
class Task:
    """A2A Task - Represents a complete request/response cycle."""

    task_id: str
    created_at: datetime
    updated_at: datetime
    status: TaskStatus
    metadata: Dict = field(default_factory=dict)

    # Request
    prompt: str = ""
    model: str = "glm-4-flash"
    max_tokens: int = 16384
    temperature: float = 0.7

    # Response
    response: str = ""
    artifact_id: Optional[str] = None
    error_message: Optional[str] = None

    # Usage
    input_tokens: int = 0
    output_tokens: int = 0

    # Human-in-loop
    pending_approval_type: Optional[str] = None  # "tool_call", "privilege"
    pending_approval_data: Optional[dict] = None

    def to_dict(self) -> dict:
        """Convert to A2A-compliant dict."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "prompt": self.prompt,
            "model": self.model,
            "response": self.response,
            "artifact_id": self.artifact_id,
            "error_message": self.error_message,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens
            },
            "pending_approval": {
                "type": self.pending_approval_type,
                "data": self.pending_approval_data
            } if self.pending_approval_type else None
        }


class TaskManager:
    """Manages all tasks."""

    def __init__(self):
        self._tasks: Dict[str, Task] = {}

    def create_task(
        self,
        prompt: str,
        model: str = "glm-4-flash",
        max_tokens: int = 16384,
        temperature: float = 0.7
    ) -> Task:
        """Create a new task."""
        task = Task(
            task_id=str(uuid.uuid4()),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            status=TaskStatus.SUBMITTED,
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature
        )
        self._tasks[task.task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        response: Optional[str] = None,
        artifact_id: Optional[str] = None,
        error_message: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        pending_approval_type: Optional[str] = None,
        pending_approval_data: Optional[dict] = None
    ) -> Optional[Task]:
        """Update a task."""
        task = self._tasks.get(task_id)
        if not task:
            return None

        if status:
            task.status = status
        if response is not None:
            task.response = response
        if artifact_id is not None:
            task.artifact_id = artifact_id
        if error_message is not None:
            task.error_message = error_message
        if input_tokens is not None:
            task.input_tokens = input_tokens
        if output_tokens is not None:
            task.output_tokens = output_tokens
        if pending_approval_type is not None:
            task.pending_approval_type = pending_approval_type
        if pending_approval_data is not None:
            task.pending_approval_data = pending_approval_data

        task.updated_at = datetime.now(UTC)
        return task

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False

        task.status = TaskStatus.CANCELLED
        task.updated_at = datetime.now(UTC)
        return True

    def list_tasks(
        self,
        limit: int = 100,
        status_filter: Optional[TaskStatus] = None
    ) -> List[Task]:
        """List tasks."""
        tasks = list(self._tasks.values())

        if status_filter:
            tasks = [t for t in tasks if t.status == status_filter]

        # Sort by updated_at desc
        tasks.sort(key=lambda t: t.updated_at, reverse=True)
        return tasks[:limit]
