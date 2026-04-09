"""Tests for dual-model routing."""

from __future__ import annotations

import pytest

from opencortex.config.settings import DualModelSettings, ExecutionModelProviderConfig
from opencortex.engine.model_router import ModelRouter


class TestModelRouter:
    """Unit tests for ModelRouter."""

    def _make_settings(self, **kwargs) -> DualModelSettings:
        defaults = dict(
            enabled=True,
            primary_model="glm-5.1",
            execution_model="MiniMax-M2.7-highspeed",
            execution_agent_types=["Explore", "claude-code-guide"],
        )
        defaults.update(kwargs)
        return DualModelSettings(**defaults)

    def test_disabled_returns_primary(self):
        s = self._make_settings(enabled=False)
        router = ModelRouter(s)
        route = router.route(agent_type="Explore")
        assert route.model == "glm-5.1"
        assert route.provider_key == "primary"

    def test_execution_agent_type_routes_to_execution(self):
        router = ModelRouter(self._make_settings())
        route = router.route(agent_type="Explore")
        assert route.model == "MiniMax-M2.7-highspeed"
        assert route.provider_key == "execution"

    def test_unknown_agent_type_routes_to_primary(self):
        router = ModelRouter(self._make_settings())
        route = router.route(agent_type="general-purpose")
        assert route.model == "glm-5.1"
        assert route.provider_key == "primary"

    def test_simple_task_keyword_routes_to_execution(self):
        router = ModelRouter(self._make_settings())
        route = router.route(task_description="搜索所有Python文件")
        assert route.provider_key == "execution"

    def test_complex_task_routes_to_primary(self):
        router = ModelRouter(self._make_settings())
        route = router.route(task_description="设计系统架构并分析性能瓶颈")
        assert route.provider_key == "primary"

    def test_explicit_model_override_honored(self):
        router = ModelRouter(self._make_settings())
        route = router.route(explicit_model="claude-opus-4")
        assert route.model == "claude-opus-4"
        assert route.provider_key == "primary"

    def test_explicit_minimax_routes_to_execution(self):
        router = ModelRouter(self._make_settings())
        route = router.route(explicit_model="minimax-m2.7")
        assert route.provider_key == "execution"

    def test_inherit_model_goes_through_routing(self):
        router = ModelRouter(self._make_settings())
        route = router.route(agent_type="Explore", explicit_model="inherit")
        assert route.provider_key == "execution"

    def test_execution_route_has_provider_config(self):
        router = ModelRouter(self._make_settings())
        route = router.route(agent_type="Explore")
        assert route.base_url is not None
        assert "minimax" in route.base_url

    def test_fallback_returns_primary(self):
        router = ModelRouter(self._make_settings())
        route = router.get_fallback_route()
        assert route.model == "glm-5.1"
        assert route.provider_key == "primary"


class TestComplexMessageDetection:
    """Tests for the Hermes-style complex message heuristic."""

    def _make_router(self) -> ModelRouter:
        return ModelRouter(DualModelSettings(
            enabled=True,
            primary_model="glm-5.1",
            execution_model="MiniMax-M2.7-highspeed",
            execution_agent_types=["Explore"],
        ))

    # --- is_complex_message unit tests ---

    def test_empty_message_not_complex(self):
        router = self._make_router()
        assert not router.is_complex_message("")

    def test_simple_greeting_not_complex(self):
        router = self._make_router()
        assert not router.is_complex_message("你好")

    @pytest.mark.parametrize("msg", [
        "帮我 debug 这个错误",
        "请 implement 一个新功能",
        "refactor 这段代码",
        "出现了 exception",
        "分析一下这个 error",
        "请 review 这个 PR",
        "设计一个 architecture",
        "跑一下 pytest",
    ])
    def test_complex_keywords_detected(self, msg: str):
        router = self._make_router()
        assert router.is_complex_message(msg), f"Should detect complex keyword in: {msg}"

    def test_url_detected(self):
        router = self._make_router()
        assert router.is_complex_message("请看 https://example.com")
        assert router.is_complex_message("访问 www.example.org")

    def test_code_fence_detected(self):
        router = self._make_router()
        assert router.is_complex_message("```python\nprint('hi')\n```")

    def test_inline_code_detected(self):
        router = self._make_router()
        assert router.is_complex_message("运行 `pip install foo`")

    def test_multiline_detected(self):
        router = self._make_router()
        msg = "第一行\n第二行\n第三行"
        assert router.is_complex_message(msg)

    def test_long_message_detected(self):
        router = self._make_router()
        msg = "a" * 201
        assert router.is_complex_message(msg)

    def test_short_simple_message_not_complex(self):
        router = self._make_router()
        assert not router.is_complex_message("今天天气怎么样")

    # --- route() integration with user_message ---

    def test_complex_message_routes_to_primary(self):
        router = self._make_router()
        route = router.route(user_message="帮我 debug 一下这个 traceback")
        assert route.provider_key == "primary"

    def test_simple_message_routes_to_primary_default(self):
        """Without task_description, even simple messages go to primary (default)."""
        router = self._make_router()
        route = router.route(user_message="你好")
        assert route.provider_key == "primary"

    def test_simple_message_with_simple_task_routes_to_execution(self):
        router = self._make_router()
        route = router.route(user_message="你好", task_description="搜索文件")
        assert route.provider_key == "execution"

    def test_complex_message_overrides_simple_task(self):
        """Complex message detection takes priority over simple task keywords."""
        router = self._make_router()
        route = router.route(
            user_message="帮我 debug 搜索功能",
            task_description="搜索文件",
        )
        assert route.provider_key == "primary"


class TestDualModelSettings:
    """Tests for DualModelSettings config."""

    def test_default_disabled(self):
        s = DualModelSettings()
        assert s.enabled is False

    def test_default_models(self):
        s = DualModelSettings()
        assert s.primary_model == "glm-5.1"
        assert s.execution_model == "MiniMax-M2.7-highspeed"

    def test_execution_provider_defaults(self):
        s = DualModelSettings()
        assert s.execution_provider.api_format == "openai"
        assert "minimax" in s.execution_provider.base_url


class TestCostTrackerDualModel:
    """Tests for per-model cost tracking."""

    def test_per_model_tracking(self):
        from opencortex.api.usage import UsageSnapshot
        from opencortex.engine.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.add(UsageSnapshot(input_tokens=100, output_tokens=50), provider_key="primary")
        tracker.add(UsageSnapshot(input_tokens=30, output_tokens=10), provider_key="execution")

        assert tracker.total.input_tokens == 130
        assert tracker.total.output_tokens == 60
        assert tracker.per_model["primary"].input_tokens == 100
        assert tracker.per_model["execution"].input_tokens == 30

    def test_summary(self):
        from opencortex.api.usage import UsageSnapshot
        from opencortex.engine.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.add(UsageSnapshot(input_tokens=100, output_tokens=50), provider_key="primary")
        summary = tracker.summary()
        assert "primary" in summary
        assert "150 tokens" in summary
