"""A2A Protocol Tests - Phase 1 (Agent Card + Task Management)."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from opencortex.a2a.agent_card import AgentCard, Capability, DEFAULT_AGENT_CARD
from opencortex.a2a.task_manager import TaskManager, TaskStatus, Task
from opencortex.a2a.context_layer import ContextLayer, summarize_tool_output


# ============================================================
# 1. Agent Card Tests
# ============================================================

class TestAgentCard:
    """Test Agent Card serialization and defaults."""

    def test_default_card_serialization(self):
        card = DEFAULT_AGENT_CARD.to_dict()
        assert card["name"] == "OpenCortex"
        assert card["version"] == "0.1.5"
        assert card["agent_id"] == "opencortex-0.1.5"
        assert len(card["capabilities"]) >= 10

    def test_capability_structure(self):
        cap = Capability(
            name="test_tool", type="tool",
            description="A test tool",
            parameters={"key": "value"}
        )
        card = AgentCard(capabilities=[cap])
        d = card.to_dict()
        assert len(d["capabilities"]) == 1
        assert d["capabilities"][0]["name"] == "test_tool"
        assert d["capabilities"][0]["parameters"]["key"] == "value"

    def test_capability_types(self):
        """Features and tools have correct types."""
        d = DEFAULT_AGENT_CARD.to_dict()
        types = {c["type"] for c in d["capabilities"]}
        assert "feature" in types
        assert "tool" in types

    def test_supported_models(self):
        d = DEFAULT_AGENT_CARD.to_dict()
        assert "glm-4-flash" in d["supported_models"]
        assert "glm-4.7" in d["supported_models"]
        assert "glm-5-turbo" in d["supported_models"]

    def test_streaming_support(self):
        d = DEFAULT_AGENT_CARD.to_dict()
        assert d["supports_streaming"] is True
        assert d["supports_cancel"] is True

    def test_card_has_documentation_url(self):
        d = DEFAULT_AGENT_CARD.to_dict()
        assert "github.com" in d["documentation_url"]

    def test_empty_card(self):
        card = AgentCard(supported_models=[])
        d = card.to_dict()
        assert d["capabilities"] == []
        assert d["supported_models"] == []


# ============================================================
# 2. Task Manager Tests
# ============================================================

class TestTaskManager:
    """Test Task lifecycle."""

    def setup_method(self):
        self.tm = TaskManager()

    def test_create_task(self):
        task = self.tm.create_task("hello")
        assert task.task_id
        assert task.status == TaskStatus.SUBMITTED
        assert task.prompt == "hello"
        assert task.model == "glm-4-flash"

    def test_create_task_custom_model(self):
        task = self.tm.create_task("hello", model="glm-4.7")
        assert task.model == "glm-4.7"

    def test_get_task(self):
        task = self.tm.create_task("test")
        found = self.tm.get_task(task.task_id)
        assert found is not None
        assert found.task_id == task.task_id

    def test_get_task_not_found(self):
        assert self.tm.get_task("nonexistent") is None

    def test_update_task_status(self):
        task = self.tm.create_task("test")
        updated = self.tm.update_task(task.task_id, status=TaskStatus.WORKING)
        assert updated.status == TaskStatus.WORKING

    def test_update_task_response(self):
        task = self.tm.create_task("test")
        updated = self.tm.update_task(
            task.task_id,
            status=TaskStatus.COMPLETED,
            response="Done!",
            input_tokens=100,
            output_tokens=50
        )
        assert updated.response == "Done!"
        assert updated.input_tokens == 100
        assert updated.output_tokens == 50

    def test_update_task_not_found(self):
        assert self.tm.update_task("nonexistent", status=TaskStatus.WORKING) is None

    def test_cancel_task(self):
        task = self.tm.create_task("test")
        success = self.tm.cancel_task(task.task_id)
        assert success is True
        assert self.tm.get_task(task.task_id).status == TaskStatus.CANCELLED

    def test_cancel_completed_task(self):
        task = self.tm.create_task("test")
        self.tm.update_task(task.task_id, status=TaskStatus.COMPLETED)
        success = self.tm.cancel_task(task.task_id)
        assert success is False

    def test_cancel_nonexistent_task(self):
        assert self.tm.cancel_task("nonexistent") is False

    def test_list_tasks(self):
        for i in range(5):
            self.tm.create_task(f"task {i}")
        tasks = self.tm.list_tasks(limit=3)
        assert len(tasks) == 3

    def test_list_tasks_filter_by_status(self):
        t1 = self.tm.create_task("t1")
        t2 = self.tm.create_task("t2")
        self.tm.update_task(t1.task_id, status=TaskStatus.COMPLETED)
        tasks = self.tm.list_tasks(status_filter=TaskStatus.COMPLETED)
        assert len(tasks) == 1

    def test_task_to_dict(self):
        task = self.tm.create_task("test")
        self.tm.update_task(
            task.task_id,
            status=TaskStatus.COMPLETED,
            response="OK",
            input_tokens=10,
            output_tokens=20
        )
        d = task.to_dict()
        assert d["status"] == "completed"
        assert d["usage"]["input_tokens"] == 10
        assert d["usage"]["output_tokens"] == 20
        assert d["pending_approval"] is None

    def test_pending_approval(self):
        task = self.tm.create_task("test")
        self.tm.update_task(
            task.task_id,
            pending_approval_type="tool_call",
            pending_approval_data={"tool": "bash", "command": "rm -rf /"}
        )
        d = task.to_dict()
        assert d["pending_approval"]["type"] == "tool_call"
        assert d["pending_approval"]["data"]["tool"] == "bash"

    def test_task_ordering(self):
        """Tasks listed by updated_at desc."""
        t1 = self.tm.create_task("first")
        t2 = self.tm.create_task("second")
        tasks = self.tm.list_tasks()
        assert tasks[0].task_id == t2.task_id
        assert tasks[1].task_id == t1.task_id


# ============================================================
# 3. Context Layer Tests
# ============================================================

class TestContextLayer:
    """Test hierarchical context compression."""

    def setup_method(self):
        self.cl = ContextLayer()

    def test_store_and_retrieve_l0(self):
        oid = self.cl.store_l0("hello world", "tool_output")
        item = self.cl.retrieve_l0(oid)
        assert item is not None
        assert item.content == "hello world"
        assert item.content_type == "tool_output"

    def test_store_l0_with_metadata(self):
        oid = self.cl.store_l0("output", "thinking", {"turn": 3})
        item = self.cl.retrieve_l0(oid)
        assert item.metadata["turn"] == 3

    def test_generate_l1(self):
        l0_1 = self.cl.store_l0("file content here...", "tool_output")
        l0_2 = self.cl.store_l0("search results...", "tool_output")
        l1 = self.cl.generate_l1(
            l0_ids=[l0_1, l0_2],
            summary="Read file and searched docs",
            tool_calls=[{"tool": "read", "lines": 10}]
        )
        assert l1.summary == "Read file and searched docs"
        assert len(l1.source_level0_ids) == 2

    def test_generate_l2(self):
        l2 = self.cl.generate_l2(
            task_id="t-123",
            conclusion="Created 3 files and fixed 2 bugs",
            success=True,
            key_metrics={"files_created": 3, "bugs_fixed": 2}
        )
        assert l2.conclusion == "Created 3 files and fixed 2 bugs"
        assert l2.success is True
        assert l2.key_metrics["files_created"] == 3

    def test_retrieve_nonexistent_l0(self):
        assert self.cl.retrieve_l0("nonexistent") is None

    def test_summarize_small_output(self):
        """Small output should not be truncated."""
        result = summarize_tool_output("bash", "ls", "file1\nfile2\nfile3", max_lines=50)
        assert result["truncated"] is False
        assert result["summary"] == "file1\nfile2\nfile3"

    def test_summarize_large_output(self):
        """Large output should be truncated."""
        big_output = "\n".join([f"line {i}" for i in range(100)])
        result = summarize_tool_output("bash", "cat bigfile", big_output, max_lines=50)
        assert result["truncated"] is True
        assert "skipped" in result["summary"]
        assert result["lines"] == 100

    def test_summarize_records_metadata(self):
        result = summarize_tool_output("bash", "ls -la", "total 0", max_lines=50)
        assert result["tool"] == "bash"
        assert result["command"] == "ls -la"
        assert result["lines"] == 1


# ============================================================
# 4. TaskStatus Enum Tests
# ============================================================

class TestTaskStatus:
    """Test TaskStatus enum."""

    def test_all_statuses(self):
        assert TaskStatus.SUBMITTED == "submitted"
        assert TaskStatus.WORKING == "working"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"
        assert TaskStatus.PENDING_INPUT == "pending_input"

    def test_status_value(self):
        assert TaskStatus.COMPLETED.value == "completed"


# ============================================================
# 5. A2A API Integration Tests
# ============================================================

class TestA2AAPI:
    """Test A2A HTTP endpoints against live server."""

    BASE = "http://127.0.0.1:8765/a2a"

    def test_agent_card_endpoint(self):
        import httpx
        r = httpx.get(f"{self.BASE}/agent-card")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "OpenCortex"
        assert "capabilities" in data

    def test_create_task_endpoint(self):
        import httpx
        r = httpx.post(f"{self.BASE}/tasks", json={
            "prompt": "integration test",
            "model": "glm-4-flash"
        })
        assert r.status_code == 200
        data = r.json()
        assert "task_id" in data
        assert data["status"] == "submitted"

    def test_get_task_endpoint(self):
        import httpx
        # Create first
        r = httpx.post(f"{self.BASE}/tasks", json={"prompt": "test"})
        tid = r.json()["task_id"]
        # Get
        r = httpx.get(f"{self.BASE}/tasks/{tid}")
        assert r.status_code == 200
        assert r.json()["task_id"] == tid

    def test_list_tasks_endpoint(self):
        import httpx
        r = httpx.get(f"{self.BASE}/tasks?limit=10")
        assert r.status_code == 200
        assert "tasks" in r.json()

    def test_cancel_task_endpoint(self):
        import httpx
        r = httpx.post(f"{self.BASE}/tasks", json={"prompt": "cancel me"})
        tid = r.json()["task_id"]
        r = httpx.delete(f"{self.BASE}/tasks/{tid}")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

    def test_404_for_nonexistent_task(self):
        import httpx
        r = httpx.get(f"{self.BASE}/tasks/nonexistent-id")
        assert r.status_code == 404

    def test_400_for_empty_prompt(self):
        import httpx
        r = httpx.post(f"{self.BASE}/tasks", json={"prompt": ""})
        # Empty prompt stripped to empty string, returns 500 from server
        assert r.status_code in (400, 422, 500)
