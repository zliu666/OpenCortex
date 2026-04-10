"""Tests for task tier routing, classification, and lightweight executor."""

from __future__ import annotations

import pytest

from opencortex.swarm.lightweight_executor import LightweightExecutor
from opencortex.swarm.task_tier import TaskTier, TaskTierRouter


# ── TaskTierRouter ──────────────────────────────────────────────

class TestTaskTierRouter:
    def test_route_system(self):
        router = TaskTierRouter()
        assert router.route(TaskTier.SYSTEM) == "glm-4.7-flash"

    def test_route_utility(self):
        router = TaskTierRouter()
        assert router.route(TaskTier.UTILITY) == "glm-4.7-flash"

    def test_route_core(self):
        router = TaskTierRouter()
        assert router.route(TaskTier.CORE) == "glm-5.1"

    def test_route_critical(self):
        router = TaskTierRouter()
        assert router.route(TaskTier.CRITICAL) == "glm-5.1"

    @pytest.mark.parametrize(
        "desc, expected",
        [
            ("整理记忆条目", TaskTier.SYSTEM),
            ("健康检查", TaskTier.SYSTEM),
            ("摘要上下文", TaskTier.SYSTEM),
            ("搜索相关文档", TaskTier.UTILITY),
            ("格式化列表", TaskTier.UTILITY),
            ("实现用户登录功能", TaskTier.CORE),
            ("重构代码架构", TaskTier.CORE),
            ("安全漏洞审计", TaskTier.CRITICAL),
            ("架构决策评审", TaskTier.CRITICAL),
            ("随便聊聊天气", TaskTier.UTILITY),  # default
        ],
    )
    def test_classify(self, desc: str, expected: TaskTier):
        router = TaskTierRouter()
        assert router.classify(desc) == expected


# ── LightweightExecutor ─────────────────────────────────────────

class TestLightweightExecutor:
    @pytest.mark.asyncio
    async def test_summarize_short(self):
        ex = LightweightExecutor()
        result = await ex.summarize("Hello world")
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_summarize_long(self):
        ex = LightweightExecutor()
        text = "A" * 500
        result = await ex.summarize(text)
        assert result.endswith("...")
        assert len(result) == 203  # 200 + "..."

    @pytest.mark.asyncio
    async def test_summarize_empty(self):
        ex = LightweightExecutor()
        assert await ex.summarize("") == ""

    @pytest.mark.asyncio
    async def test_classify_intent(self):
        ex = LightweightExecutor()
        assert await ex.classify_intent("帮我写个函数") == "core"

    @pytest.mark.asyncio
    async def test_health_check(self):
        ex = LightweightExecutor(model="test-model")
        result = await ex.health_check()
        assert result["status"] == "ok"
        assert result["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_consolidate_memory(self):
        ex = LightweightExecutor()
        entries = [{"k": "v"}] * 3
        result = await ex.consolidate_memory(entries)
        assert "3 entries" in result

    @pytest.mark.asyncio
    async def test_consolidate_empty(self):
        ex = LightweightExecutor()
        result = await ex.consolidate_memory([])
        assert "No entries" in result

    def test_default_model(self):
        ex = LightweightExecutor(tier=TaskTier.SYSTEM)
        assert ex.model == "glm-4.7-flash"

    def test_custom_model(self):
        ex = LightweightExecutor(model="my-custom-model")
        assert ex.model == "my-custom-model"
