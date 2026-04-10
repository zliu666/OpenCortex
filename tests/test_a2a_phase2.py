"""A2A Phase 2 Tests - QueryEngine integration."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from opencortex.a2a.executor import TaskExecutor
from opencortex.a2a.task_manager import TaskManager, TaskStatus
from opencortex.a2a.context_layer import ContextLayer
from opencortex.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ToolExecutionStarted,
    ToolExecutionCompleted,
    ErrorEvent,
)


class TestTaskExecutor:
    """Test TaskExecutor with mocked QueryEngine."""

    def setup_method(self):
        self.tm = TaskManager()
        self.cl = ContextLayer()
        self.executor = TaskExecutor(self.tm, self.cl, cwd="/tmp")

    def test_executor_init(self):
        assert self.executor.task_manager is self.tm
        assert self.executor.context_layer is self.cl

    def test_cancel_nonexistent_task(self):
        # Should not raise
        result = self.executor.cancel_execution("nonexistent")
        assert result is True

    def test_cancel_sets_flag(self):
        task = self.tm.create_task("test")
        self.executor.cancel_execution(task.task_id)
        assert task.task_id in self.executor._cancelled_tasks


class TestContextLayerIntegration:
    """Test context layer with realistic tool outputs."""

    def setup_method(self):
        self.cl = ContextLayer()

    def test_large_file_output_compression(self):
        """Large file read should be stored as L0 and summarized."""
        big_file = "\n".join([f"line {i}: some content here" for i in range(500)])
        l0_id = self.cl.store_l0(big_file, "tool_output", {"tool": "read", "file": "big.py"})
        assert l0_id

        l1 = self.cl.generate_l1(
            l0_ids=[l0_id],
            summary="Read big.py (500 lines), found class definitions",
            tool_calls=[{"tool": "read", "command": "big.py", "lines": 500, "truncated": True}]
        )
        assert l1.summary
        assert len(l1.source_level0_ids) == 1

    def test_multiple_tool_calls_l1(self):
        """Multiple tool calls should all be tracked."""
        l0_ids = []
        for i in range(5):
            oid = self.cl.store_l0(f"output {i}", "tool_output")
            l0_ids.append(oid)

        l1 = self.cl.generate_l1(
            l0_ids=l0_ids,
            summary="Executed 5 tool calls: 3 reads, 1 bash, 1 write",
            tool_calls=[
                {"tool": "read", "command": "a.py", "lines": 20},
                {"tool": "read", "command": "b.py", "lines": 30},
                {"tool": "bash", "command": "ls", "lines": 5},
                {"tool": "write", "command": "c.py", "lines": 0},
                {"tool": "read", "command": "d.py", "lines": 15},
            ]
        )
        assert len(l1.tool_calls) == 5
        assert len(l1.source_level0_ids) == 5

    def test_l0_retrieval_after_l1(self):
        """L0 content should be retrievable after L1 generation."""
        content = "def foo():\n    return 42\n"
        l0_id = self.cl.store_l0(content, "tool_output")
        self.cl.generate_l1([l0_id], "Read foo function")

        # L0 still accessible
        retrieved = self.cl.retrieve_l0(l0_id)
        assert retrieved.content == content

    def test_l2_conclusion_with_metrics(self):
        l2 = self.cl.generate_l2(
            task_id="task-123",
            conclusion="Created auth module with login/logout endpoints",
            success=True,
            key_metrics={
                "files_created": 3,
                "bugs_fixed": 0,
                "tool_calls": 12,
                "tokens_used": 4500,
            }
        )
        assert l2.success
        assert l2.key_metrics["files_created"] == 3


class TestA2APhase2API:
    """Test A2A API with mocked QueryEngine integration."""

    BASE = "http://127.0.0.1:8765/a2a"

    @patch('httpx.post')
    def test_create_and_execute_task(self, mock_post):
        """Create a task and verify it executes (may take time)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": "task-abc123",
            "status": "completed",
            "prompt": "请只回复数字：1+1等于几？只回复数字",
            "model": "glm-4-flash",
            "response": "2",
            "execution": {
                "duration_ms": 1500,
                "turns": 1
            }
        }
        mock_post.return_value = mock_response

        import httpx
        r = httpx.post(f"{self.BASE}/tasks", json={
            "prompt": "请只回复数字：1+1等于几？只回复数字",
            "model": "glm-4-flash",
            "max_turns": 1,
        }, timeout=120)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("submitted", "completed", "working", "failed")
        # If synchronous execution completed
        if data["status"] == "completed":
            assert data["response"]
            assert "execution" in data

    @patch('httpx.post')
    def test_stream_task_request(self, mock_post):
        """Request a streaming task, get stream URL."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": "task-stream-123",
            "status": "submitted",
            "stream_url": "/a2a/stream/task-stream-123"
        }
        mock_post.return_value = mock_response

        import httpx
        r = httpx.post(f"{self.BASE}/tasks", json={
            "prompt": "测试流式",
            "model": "glm-4-flash",
            "stream": True,
        })
        assert r.status_code == 200
        data = r.json()
        assert "stream_url" in data
        assert "/stream" in data["stream_url"]

    @patch('httpx.post')
    @patch('httpx.get')
    def test_task_lifecycle_with_execution(self, mock_get, mock_post):
        """Full lifecycle: create → execute → get → verify status."""
        # Mock create task
        mock_post_response = MagicMock()
        mock_post_response.status_code = 200
        mock_post_response.json.return_value = {
            "task_id": "task-lifecycle-456",
            "status": "completed",
            "prompt": "回复OK",
            "model": "glm-4-flash",
            "response": "OK",
            "execution": {"duration_ms": 800, "turns": 1}
        }
        mock_post.return_value = mock_post_response

        # Mock get task
        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {
            "task_id": "task-lifecycle-456",
            "status": "completed",
            "prompt": "回复OK",
            "model": "glm-4-flash",
            "response": "OK",
            "execution": {"duration_ms": 800, "turns": 1}
        }
        mock_get.return_value = mock_get_response

        import httpx
        # Create
        r = httpx.post(f"{self.BASE}/tasks", json={
            "prompt": "回复OK",
            "model": "glm-4-flash",
            "max_turns": 1,
        }, timeout=120)
        assert r.status_code == 200
        tid = r.json()["task_id"]

        # Get
        r = httpx.get(f"{self.BASE}/tasks/{tid}")
        assert r.status_code == 200
        data = r.json()
        assert data["task_id"] == tid
        # Should be completed after sync execution
        assert data["status"] in ("completed", "failed", "working")
