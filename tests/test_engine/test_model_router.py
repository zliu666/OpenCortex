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
