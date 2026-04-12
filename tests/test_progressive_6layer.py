"""6-Layer Progressive Test Suite for OpenCortex A2A Bridge.

Layer 1: 单元测试（模块隔离）
Layer 2: 集成测试（模块协作）
Layer 3: API端点测试（HTTP接口）
Layer 4: 多Agent并发测试
Layer 5: 端到端场景测试
Layer 6: 压力/稳定性测试
"""

import httpx
import asyncio
import time
import json


BASE = "http://127.0.0.1:8765"


def run_layer_tests(layer_num: int, tests: list) -> tuple[int, int]:
    """Run a layer of tests, return (passed, failed)."""
    passed = 0
    failed = 0
    print(f"\n{'='*50}")
    print(f"Layer {layer_num}: {tests[0]['name'] if tests else 'Unknown'}")
    print(f"{'='*50}")

    for test in tests:
        name = test["name"]
        try:
            test["fn"]()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {name}: {str(e)[:80]}")
            failed += 1

    return passed, failed


# ============================================================
# Layer 1: Unit Tests (模块隔离)
# ============================================================

def test_agent_card_serialization():
    from opencortex.a2a.agent_card import DEFAULT_AGENT_CARD
    card = DEFAULT_AGENT_CARD.to_dict()
    assert card["name"] == "OpenCortex"
    assert len(card["capabilities"]) >= 10

def test_task_manager_lifecycle():
    from opencortex.a2a.task_manager import TaskManager, TaskStatus
    tm = TaskManager()
    t = tm.create_task("test")
    assert t.status == TaskStatus.SUBMITTED
    tm.update_task(t.task_id, status=TaskStatus.WORKING)
    assert tm.get_task(t.task_id).status == TaskStatus.WORKING
    tm.update_task(t.task_id, status=TaskStatus.COMPLETED, response="done")
    assert tm.get_task(t.task_id).response == "done"
    assert not tm.cancel_task(t.task_id)  # can't cancel completed

def test_context_layer_compression():
    from opencortex.a2a.context_layer import ContextLayer, summarize_tool_output
    cl = ContextLayer()
    # Store L0
    big = "\n".join([f"line {i}" for i in range(200)])
    l0_id = cl.store_l0(big, "tool_output", {"tool": "bash"})
    # Generate L1
    l1 = cl.generate_l1([l0_id], "Ran bash command", [{"tool": "bash", "lines": 200, "truncated": True}])
    assert l1.summary
    # L0 still accessible
    assert cl.retrieve_l0(l0_id).content == big
    # Summarize large output
    result = summarize_tool_output("bash", "cat", big, max_lines=50)
    assert result["truncated"] is True

def test_task_status_enum():
    from opencortex.a2a.task_manager import TaskStatus
    assert TaskStatus.SUBMITTED.value == "submitted"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.CANCELLED.value == "cancelled"


LAYER_1 = [
    {"name": "Agent Card 序列化", "fn": test_agent_card_serialization},
    {"name": "Task Manager 生命周期", "fn": test_task_manager_lifecycle},
    {"name": "上下文分层压缩", "fn": test_context_layer_compression},
    {"name": "TaskStatus 枚举", "fn": test_task_status_enum},
]


# ============================================================
# Layer 2: Integration Tests (模块协作)
# ============================================================

def test_executor_cancel():
    from opencortex.a2a.executor import TaskExecutor
    from opencortex.a2a.task_manager import TaskManager, TaskStatus
    from opencortex.a2a.context_layer import ContextLayer
    tm = TaskManager()
    cl = ContextLayer()
    ex = TaskExecutor(tm, cl)
    t = tm.create_task("test")
    ex.cancel_execution(t.task_id)
    assert tm.get_task(t.task_id).status == TaskStatus.CANCELLED

def test_mcp_module_tools():
    from opencortex.mcp import mcp_server
    tools = [t.name for t in mcp_server._tool_manager.list_tools()]
    assert "bash" in tools
    assert "read_file" in tools
    assert "write_file" in tools

def test_tool_registry_integration():
    from opencortex.tools import create_default_tool_registry
    registry = create_default_tool_registry()
    tools = registry.list_tools()
    assert len(tools) >= 30
    names = [t.name for t in tools]
    assert "bash" in names
    assert "grep" in names


LAYER_2 = [
    {"name": "Executor 取消机制", "fn": test_executor_cancel},
    {"name": "MCP 模块工具注册", "fn": test_mcp_module_tools},
    {"name": "工具注册表集成", "fn": test_tool_registry_integration},
]


# ============================================================
# Layer 3: API Endpoint Tests (HTTP接口)
# ============================================================

def test_status_endpoint():
    r = httpx.get(f"{BASE}/status", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_agent_card_endpoint():
    r = httpx.get(f"{BASE}/a2a/agent-card", timeout=10)
    assert r.status_code == 200
    assert r.json()["name"] == "OpenCortex"

def test_mcp_tools_endpoint():
    r = httpx.get(f"{BASE}/mcp/tools", timeout=10)
    assert r.status_code == 200
    assert len(r.json()["tools"]) >= 30

def test_list_tasks_endpoint():
    r = httpx.get(f"{BASE}/a2a/tasks?limit=5", timeout=10)
    assert r.status_code == 200
    assert "tasks" in r.json()

def test_404_nonexistent_task():
    r = httpx.get(f"{BASE}/a2a/tasks/nonexistent", timeout=10)
    assert r.status_code == 404

def test_stream_task_request():
    r = httpx.post(f"{BASE}/a2a/tasks", json={"prompt": "test", "stream": True})
    assert r.status_code == 200
    assert "stream_url" in r.json()


LAYER_3 = [
    {"name": "GET /status", "fn": test_status_endpoint},
    {"name": "GET /a2a/agent-card", "fn": test_agent_card_endpoint},
    {"name": "GET /mcp/tools", "fn": test_mcp_tools_endpoint},
    {"name": "GET /a2a/tasks", "fn": test_list_tasks_endpoint},
    {"name": "404 不存在任务", "fn": test_404_nonexistent_task},
    {"name": "POST stream=true", "fn": test_stream_task_request},
]


# ============================================================
# Layer 4: Multi-Agent Concurrent Tests
# ============================================================

def test_concurrent_task_creation():
    """5 agents 同时创建任务"""
    import concurrent.futures
    def create():
        r = httpx.post(f"{BASE}/a2a/tasks", json={"prompt": "test", "stream": True}, timeout=30)
        assert r.status_code == 200
        return r.json()["task_id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(create) for _ in range(5)]
        results = [f.result() for f in futures]

    assert len(results) == 5
    assert len(set(results)) == 5  # All unique IDs


LAYER_4 = [
    {"name": "5 Agent 并发创建任务", "fn": test_concurrent_task_creation},
]


# ============================================================
# Layer 5: End-to-End Scenario Tests
# ============================================================

def test_e2e_task_execution():
    """完整流程：创建→执行→获取→验证"""
    r = httpx.post(f"{BASE}/a2a/tasks", json={
        "prompt": "只回复数字2",
        "model": "glm-4-flash",
        "max_turns": 1,
    }, timeout=120)
    assert r.status_code == 200
    task = r.json()
    assert task["status"] == "completed"
    assert task["response"]
    assert task.get("execution") is not None

def test_e2e_task_cancellation():
    """创建stream任务后取消"""
    r = httpx.post(f"{BASE}/a2a/tasks", json={"prompt": "test", "stream": True})
    tid = r.json()["task_id"]
    r = httpx.delete(f"{BASE}/a2a/tasks/{tid}", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


LAYER_5 = [
    {"name": "E2E 任务执行", "fn": test_e2e_task_execution},
    {"name": "E2E 任务取消", "fn": test_e2e_task_cancellation},
]


# ============================================================
# Layer 6: Stress / Stability Tests
# ============================================================

def test_rapid_requests():
    """快速连续请求50次"""
    for i in range(50):
        r = httpx.get(f"{BASE}/status", timeout=5)
        assert r.status_code == 200

def test_large_task_list():
    """创建20个任务，检查列表"""
    tids = []
    for _ in range(20):
        r = httpx.post(f"{BASE}/a2a/tasks", json={"prompt": "test", "stream": True})
        tids.append(r.json()["task_id"])

    r = httpx.get(f"{BASE}/a2a/tasks?limit=20", timeout=10)
    assert r.status_code == 200
    assert len(r.json()["tasks"]) >= 20

    # Cleanup
    for tid in tids:
        httpx.delete(f"{BASE}/a2a/tasks/{tid}", timeout=5)


LAYER_6 = [
    {"name": "50次快速请求", "fn": test_rapid_requests},
    {"name": "20个任务列表", "fn": test_large_task_list},
]


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("OpenCortex A2A Bridge - 6-Layer Progressive Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0
    layers = [
        (1, "单元测试（模块隔离）", LAYER_1),
        (2, "集成测试（模块协作）", LAYER_2),
        (3, "API端点测试（HTTP接口）", LAYER_3),
        (4, "多Agent并发测试", LAYER_4),
        (5, "端到端场景测试", LAYER_5),
        (6, "压力/稳定性测试", LAYER_6),
    ]

    start = time.time()

    for num, name, tests in layers:
        print(f"\n{'='*50}")
        print(f"Layer {num}: {name} ({len(tests)} tests)")
        print(f"{'='*50}")

        for test in tests:
            try:
                test["fn"]()
                print(f"  ✅ {test['name']}")
                total_passed += 1
            except Exception as e:
                print(f"  ❌ {test['name']}: {str(e)[:80]}")
                total_failed += 1

    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print(f"📊 Results: {total_passed} passed, {total_failed} failed")
    print(f"⏱️  Time: {elapsed:.1f}s")
    print(f"{'='*60}")

    if total_failed == 0:
        print("\n🎉 ALL LAYERS PASSED!")
    else:
        print(f"\n⚠️ {total_failed} test(s) failed")


if __name__ == "__main__":
    main()
