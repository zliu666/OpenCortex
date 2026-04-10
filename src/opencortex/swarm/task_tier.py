"""Task tier classification and model routing for cost-aware agent dispatch."""

from __future__ import annotations

import re
from enum import Enum


class TaskTier(Enum):
    """Task priority tier determining model selection."""

    SYSTEM = "system"        # Memory consolidation, health checks, summarization → glm-4.7-flash
    UTILITY = "utility"      # Search, formatting, listing → glm-4.7-flash
    CORE = "core"            # Coding, analysis, design → glm-5.1
    CRITICAL = "critical"    # Architecture decisions, security review → glm-5.1


# Patterns that auto-classify into tiers (checked in priority order).
_CLASSIFY_RULES: list[tuple[re.Pattern[str], TaskTier]] = [
    # CRITICAL first
    (re.compile(r"安全|漏洞|审计|架构决策|安全审查|security|audit|vulnerability", re.I), TaskTier.CRITICAL),
    # CORE
    (re.compile(r"编码|编程|重构|设计|分析|实现|函数|debug|refactor|design|implement|code|coding", re.I), TaskTier.CORE),
    # SYSTEM
    (re.compile(r"记忆|健康检查|摘要|总结|整理|memory|health.?check|summarize|consolidate", re.I), TaskTier.SYSTEM),
    # UTILITY fallback patterns
    (re.compile(r"搜索|格式化|列表|翻译|search|format|list|translate", re.I), TaskTier.UTILITY),
]


class TaskTierRouter:
    """Route tasks to appropriate models based on tier."""

    TIER_MODELS: dict[TaskTier, str] = {
        TaskTier.SYSTEM: "glm-4.7-flash",
        TaskTier.UTILITY: "glm-4.7-flash",
        TaskTier.CORE: "glm-5.1",
        TaskTier.CRITICAL: "glm-5.1",
    }

    def route(self, tier: TaskTier) -> str:
        """Return the model name for a given task tier."""
        return self.TIER_MODELS[tier]

    def classify(self, task_description: str) -> TaskTier:
        """Auto-classify a task description into a tier."""
        for pattern, tier in _CLASSIFY_RULES:
            if pattern.search(task_description):
                return tier
        return TaskTier.UTILITY  # safe default: cheap model
