"""Model routing for dual-model setup: primary (strong) + execution (fast).

Routes agent tasks to the appropriate model based on agent type,
task description, or explicit configuration.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from opencortex.config.settings import DualModelSettings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelRoute:
    """Resolved model routing decision."""

    model: str
    provider_key: str  # "primary" or "execution"
    base_url: str | None = None
    api_key: str | None = None
    api_format: str | None = None


class ModelRouter:
    """Decide which model to use for a given agent/task.

    Routing strategy (evaluated in order):
    1. Explicit model override (from AgentDefinition.model or AgentToolInput.model)
    2. Agent type in execution_agent_types list → execution model
    3. Task description heuristic → execution model for simple tasks
    4. Default → primary model
    """

    def __init__(self, settings: DualModelSettings) -> None:
        self._settings = settings

    @property
    def is_enabled(self) -> bool:
        return self._settings.enabled

    def route(
        self,
        *,
        agent_type: str | None = None,
        task_description: str | None = None,
        explicit_model: str | None = None,
    ) -> ModelRoute:
        """Determine which model to use.

        Args:
            agent_type: The subagent_type from AgentDefinition.
            task_description: Short description of the task.
            explicit_model: An explicit model override (from AgentToolInput.model
                or AgentDefinition.model).

        Returns:
            ModelRoute with resolved model and provider config.
        """
        s = self._settings

        # If dual-model is disabled, everything goes to primary
        if not s.enabled:
            return ModelRoute(model=s.primary_model, provider_key="primary")

        # Explicit model override — honor it but don't switch provider
        # unless the override matches the execution model name
        if explicit_model and explicit_model != "inherit":
            if self._is_execution_model(explicit_model):
                return self._execution_route()
            # Unknown explicit model: use primary provider with overridden model name
            return ModelRoute(model=explicit_model, provider_key="primary")

        # Agent type match
        if agent_type and agent_type in s.execution_agent_types:
            return self._execution_route()

        # Task description heuristic
        if task_description and self._is_simple_task(task_description):
            return self._execution_route()

        # Default: primary model
        return self._primary_route()

    def _primary_route(self) -> ModelRoute:
        return ModelRoute(model=self._settings.primary_model, provider_key="primary")

    def _execution_route(self) -> ModelRoute:
        ep = self._settings.execution_provider
        api_key = ep.api_key or os.environ.get("MINIMAX_API_KEY", "")
        return ModelRoute(
            model=self._settings.execution_model,
            provider_key="execution",
            base_url=ep.base_url,
            api_key=api_key or None,
            api_format=ep.api_format,
        )

    def _is_execution_model(self, model: str) -> bool:
        """Check if a model name refers to the execution model."""
        exec_model = self._settings.execution_model.lower()
        return model.lower() == exec_model or model.lower().startswith("minimax")

    @staticmethod
    def _is_simple_task(description: str) -> bool:
        """Heuristic: is this a simple/fast task?

        Matches keywords that suggest quick, mechanical work.
        """
        simple_keywords = (
            "搜索", "查找", "格式化", "列表", "统计",
            "search", "find", "list", "format", "grep", "glob",
            "read", "check", "count",
        )
        desc_lower = description.lower()
        return any(kw in desc_lower for kw in simple_keywords)

    def get_fallback_route(self) -> ModelRoute:
        """Return the primary model route for fallback when execution model fails."""
        return self._primary_route()
