"""Task tier classification and model routing for cost-aware agent dispatch.

Agent pool (4 agents across 2 providers):
  - 智谱: glm-5.1 (规划/核心编码), glm-5-turbo (辅助编码)
  - MiniMax: MiniMax-M2.7 x2 (轻量执行)
When one provider rate-limits, tasks automatically fall back to the other.
"""

from __future__ import annotations

import re
from enum import Enum


class TaskTier(Enum):
    """Task priority tier determining model selection."""

    CRITICAL = "critical"    # Architecture decisions, security review → glm-5.1
    CORE = "core"            # Coding, analysis, design → glm-5.1 or glm-5-turbo
    SYSTEM = "system"        # Memory consolidation, health checks, summarization → MiniMax-M2.7
    UTILITY = "utility"      # Search, formatting, listing → MiniMax-M2.7


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
    """Route tasks to appropriate models based on tier.

    4-agent pool strategy:
      智谱 (glm-5.1 + glm-5-turbo): CORE and CRITICAL tasks
      MiniMax (MiniMax-M2.7 x2): SYSTEM and UTILITY tasks
    Fallback chain crosses providers to survive rate-limits.
    """

    # Primary model for each tier
    TIER_MODELS: dict[TaskTier, str] = {
        TaskTier.CRITICAL: "glm-5.1",
        TaskTier.CORE: "glm-5.1",
        TaskTier.SYSTEM: "MiniMax-M2.7",
        TaskTier.UTILITY: "MiniMax-M2.7",
    }

    # Fallback models — cross-provider to survive rate-limits
    TIER_FALLBACKS: dict[TaskTier, list[str]] = {
        TaskTier.CRITICAL: ["glm-5.1", "glm-5-turbo", "MiniMax-M2.7"],
        TaskTier.CORE: ["glm-5.1", "glm-5-turbo", "MiniMax-M2.7"],
        TaskTier.SYSTEM: ["MiniMax-M2.7", "glm-5-turbo", "glm-5.1"],
        TaskTier.UTILITY: ["MiniMax-M2.7", "glm-5-turbo", "glm-5.1"],
    }

    def route(self, tier: TaskTier) -> str:
        """Return the primary model name for a given task tier."""
        return self.TIER_MODELS[tier]

    def classify(self, task_description: str) -> TaskTier:
        """Auto-classify a task description into a tier."""
        for pattern, tier in _CLASSIFY_RULES:
            if pattern.search(task_description):
                return tier
        return TaskTier.UTILITY  # safe default: cheapest model
