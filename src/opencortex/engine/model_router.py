"""Model routing for dual-model setup: primary (strong) + execution (fast).

Routes agent tasks to the appropriate model based on agent type,
task description, or explicit configuration.

Routing strategy (evaluated in order):
1. Explicit model override (from AgentDefinition.model or AgentToolInput.model)
2. Budget exceeded → cheapest available model
3. Task-type routing rules (code/research/testing/review)
4. Agent type in execution_agent_types list → execution model
5. Message complexity heuristic → complex tasks stay on primary
6. Task description heuristic → execution model for simple tasks
7. Default → primary model

Budget control:
- Track per-model token usage
- Auto-downgrade when budget exceeded
- Reset daily

Dynamic fallback:
- Primary model unavailable → execution model
- Execution model unavailable → primary model
- Both unavailable → error
"""

from __future__ import annotations

import logging
import os
import re
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
    2. Budget exceeded → cheapest available model
    3. Task-type routing rules (code/research/testing/review)
    4. Agent type in execution_agent_types list → execution model
    5. Message complexity heuristic → complex tasks stay on primary
    6. Task description heuristic → execution model for simple tasks
    7. Default → primary model
    """

    # Task-type routing rules: task_type → {complexity → model_tier}
    # model_tier: "primary" or "execution"
    TASK_ROUTING_RULES: dict[str, dict[str, str]] = {
        "code_generation": {"simple": "execution", "complex": "primary"},
        "code_review": {"default": "primary"},
        "research": {"default": "execution"},
        "testing": {"default": "execution"},
        "documentation": {"default": "execution"},
        "planning": {"default": "primary"},
        "debugging": {"default": "primary"},
    }

    # Keywords for task-type detection
    _TASK_TYPE_KEYWORDS: dict[str, frozenset[str]] = {
        "code_generation": frozenset({"implement", "write code", "create", "build", "develop", "编码", "实现", "开发", "编写"}),
        "code_review": frozenset({"review", "audit", "inspect", "审查", "审计", "检查"}),
        "research": frozenset({"search", "find", "lookup", "investigate", "搜索", "查找", "调研"}),
        "testing": frozenset({"test", "pytest", "unittest", "测试"}),
        "documentation": frozenset({"document", "readme", "doc", "文档", "注释"}),
        "planning": frozenset({"plan", "design", "architect", "规划", "设计", "架构"}),
        "debugging": frozenset({"debug", "fix", "error", "traceback", "调试", "修复", "排错"}),
    }

    def __init__(self, settings: DualModelSettings) -> None:
        self._settings = settings
        # Budget tracking: model -> token count
        self._usage: dict[str, int] = {}
        # Daily budget per model (tokens). 0 = unlimited
        self._budgets: dict[str, int] = {
            "primary": 0,  # unlimited by default
            "execution": 0,  # unlimited by default
        }

    @property
    def is_enabled(self) -> bool:
        return self._settings.enabled

    def route(
        self,
        *,
        agent_type: str | None = None,
        task_description: str | None = None,
        explicit_model: str | None = None,
        user_message: str | None = None,
        task_type: str | None = None,
        complexity: str | None = None,
    ) -> ModelRoute:
        """Determine which model to use.

        Args:
            agent_type: The subagent_type from AgentDefinition.
            task_description: Short description of the task.
            explicit_model: An explicit model override (from AgentToolInput.model
                or AgentDefinition.model).
            user_message: The actual user message for complexity analysis.
            task_type: Explicit task type (code_generation/research/testing/etc).
            complexity: Explicit complexity (simple/complex).

        Returns:
            ModelRoute with resolved model and provider config.
        """
        s = self._settings

        # If dual-model is disabled, everything goes to primary
        if not s.enabled:
            return ModelRoute(model=s.primary_model, provider_key="primary")

        # 1. Explicit model override
        if explicit_model and explicit_model != "inherit":
            if self._is_execution_model(explicit_model):
                return self._execution_route()
            return ModelRoute(model=explicit_model, provider_key="primary")

        # 2. Budget check — if primary budget exceeded, downgrade
        primary_budget = self._budgets.get("primary", 0)
        if primary_budget > 0:
            primary_usage = self._usage.get("primary", 0)
            if primary_usage >= primary_budget:
                log.info("Primary model budget exceeded (%d/%d), using execution model",
                         primary_usage, primary_budget)
                return self._execution_route()

        # 3. Task-type routing
        detected_type = task_type or self._detect_task_type(
            task_description or "", user_message or ""
        )
        if detected_type and detected_type in self.TASK_ROUTING_RULES:
            tier = self._resolve_tier(detected_type, complexity)
            if tier == "execution":
                return self._execution_route()
            else:
                return self._primary_route()

        # 4. Agent type match
        if agent_type and agent_type in s.execution_agent_types:
            return self._execution_route()

        # 5. Message complexity check
        if user_message and self.is_complex_message(user_message):
            return self._primary_route()

        # 6. Task description heuristic
        if task_description and self._is_simple_task(task_description):
            return self._execution_route()

        # 7. Default: primary model
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

    # Keywords that signal complex work → keep on primary model.
    # Derived from Hermes smart_model_routing.
    _COMPLEX_KEYWORDS = frozenset({
        # Debugging & errors
        "debug", "debugging", "traceback", "stacktrace", "exception", "error",
        # Implementation
        "implement", "implementation", "refactor", "patch",
        # Analysis & planning
        "analyze", "analysis", "investigate", "architecture", "design",
        "compare", "benchmark", "optimize", "optimise", "review",
        # Dev & infra
        "plan", "planning", "delegate", "subagent",
        "cron", "docker", "kubernetes", "terminal", "shell",
        # Testing
        "pytest", "test", "tests",
        # Tool usage
        "tool", "tools",
    })

    _URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)

    def is_complex_message(self, message: str) -> bool:
        """Check if a user message looks complex (should stay on primary model).

        Uses multiple signals: complex keywords, code fences, URLs,
        message length, and multi-line content.
        """
        text = (message or "").strip()
        if not text:
            return False

        # Code fences or inline code → complex
        if "```" in text or "`" in text:
            return True

        # URLs → complex
        if self._URL_RE.search(text):
            return True

        # Multi-line (more than 1 newline) → complex
        if text.count("\n") > 1:
            return True

        # Complex keywords → complex
        lowered = text.lower()
        words = {token.strip(".,:;!?()[]{}\"'`") for token in lowered.split()}
        if words & self._COMPLEX_KEYWORDS:
            return True

        # Very long message → complex
        if len(text) > 200:
            return True

        return False

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

    def record_usage(self, model: str, tokens: int) -> None:
        """Record token usage for budget tracking.

        Records under both the model name AND the tier name ('primary'/'execution')
        to ensure budget checks work correctly.
        """
        self._usage[model] = self._usage.get(model, 0) + tokens
        # Also record under the tier for budget checking
        tier = self._model_to_tier(model)
        if tier:
            self._usage[tier] = self._usage.get(tier, 0) + tokens

    def _model_to_tier(self, model: str) -> str | None:
        """Map a model name back to its tier (primary/execution).

        Bug 10 fix: use case-insensitive comparison to avoid key mismatch
        when model names have inconsistent casing (e.g. 'GPT-4' vs 'gpt-4').
        """
        model_lower = model.lower()
        if model_lower == self._settings.primary_model.lower():
            return "primary"
        if model_lower == self._settings.execution_model.lower():
            return "execution"
        return None

    def set_budget(self, tier: str, max_tokens: int) -> None:
        """Set daily token budget for a model tier.

        Args:
            tier: "primary" or "execution"
            max_tokens: Maximum tokens per day. 0 = unlimited.
        """
        self._budgets[tier] = max_tokens

    def get_usage(self) -> dict[str, int]:
        """Get current token usage per model."""
        return dict(self._usage)

    def reset_daily(self) -> None:
        """Reset daily usage counters."""
        self._usage.clear()

    def _detect_task_type(self, description: str, message: str) -> str | None:
        """Detect task type from description and message content."""
        text = f"{description} {message}".lower()
        words = {token.strip(".,:;!?()[]{}\"'` ") for token in text.split()}

        best_match: str | None = None
        best_count = 0

        for task_type, keywords in self._TASK_TYPE_KEYWORDS.items():
            overlap = words & {kw.lower() for kw in keywords}
            if len(overlap) > best_count:
                best_count = len(overlap)
                best_match = task_type

        return best_match

    def _resolve_tier(self, task_type: str, complexity: str | None) -> str:
        """Resolve which tier to use for a task type."""
        rules = self.TASK_ROUTING_RULES.get(task_type, {})

        if complexity and complexity in rules:
            return rules[complexity]

        if "default" in rules:
            return rules["default"]

        # Default to primary for unknown
        return "primary"
