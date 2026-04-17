"""SecurityLayer — three-stage pipeline: classify → validate → clean.

Replaces the old 6-component AgentSys design with a streamlined approach:
1. Classify (ToolClassifier, instant) → category + risk_level
2. Validate (ToolCallValidator, instant for whitelist/rules) → allow/block
3. Clean (ResultCleaner, instant rules + optional LLM) → safe output

Only EXTERNAL content triggers optional LLM cleaning. Everything else is rule-based.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opencortex.security.result_cleaner import ResultCleaner
from opencortex.security.tool_classifier import (
    CATEGORY_RISK,
    RiskLevel,
    ToolCategory,
    ToolClassifier,
)
from opencortex.security.validator import ToolCallValidator

if TYPE_CHECKING:
    from opencortex.api.client import SupportsStreamingMessages

log = logging.getLogger(__name__)


@dataclass
class SecurityCheckResult:
    """Result of a pre-execution security check."""
    allowed: bool
    reason: str = ""
    category: ToolCategory | None = None
    risk_level: RiskLevel | None = None


class SecurityLayer:
    """Three-stage security pipeline.

    Stage 1 (Classify): ToolClassifier → ToolCategory + RiskLevel (instant)
    Stage 2 (Validate): ToolCallValidator → allow/block (instant for most tools)
    Stage 3 (Clean): ResultCleaner → clean output (rules always, LLM optional)
    """

    def __init__(
        self,
        api_client: SupportsStreamingMessages | None = None,
        model: str = "glm-5.1",
        *,
        llm_cleaning_enabled: bool = True,
        llm_validation_enabled: bool = True,
    ) -> None:
        self._classifier = ToolClassifier()
        self._validator = ToolCallValidator(
            api_client=api_client if llm_validation_enabled else None,
            model=model,
        )
        self._cleaner = ResultCleaner(
            api_client=api_client,
            model=model,
            llm_cleaning_enabled=llm_cleaning_enabled,
        )
        self._llm_validation_enabled = llm_validation_enabled

    # ── Stage 1: Classify ──────────────────────────────────────────────

    def classify(self, tool_name: str, tool_description: str = "") -> tuple[ToolCategory, RiskLevel]:
        """Classify a tool and return (category, risk_level)."""
        category = self._classifier.classify(tool_name, tool_description)
        risk_level = CATEGORY_RISK[category]
        return category, risk_level

    # ── Stage 2: Validate (pre-execution) ──────────────────────────────

    async def check_tool_call(
        self,
        tool_name: str,
        tool_args: dict,
        tool_description: str = "",
        user_query: str = "",
        call_history: str = "",
    ) -> SecurityCheckResult:
        """Pre-execution check: classify + validate.

        Returns SecurityCheckResult with allowed=True/False.
        """
        # Stage 1: Classify
        category, risk_level = self.classify(tool_name, tool_description)
        log.info("security: %s → %s / %s", tool_name, category.value, risk_level.value)

        # Stage 2: Validate
        try:
            allowed = await self._validator.validate(
                category=category,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_description=tool_description,
                user_query=user_query,
                call_history=call_history,
            )
        except Exception:
            log.exception("security: validator error for %s, defaulting to allow", tool_name)
            allowed = True

        if not allowed:
            log.warning("security: BLOCKED %s (category=%s, risk=%s)",
                        tool_name, category.value, risk_level.value)
            return SecurityCheckResult(
                allowed=False,
                reason=f"Security check blocked {tool_name}: dangerous pattern detected",
                category=category,
                risk_level=risk_level,
            )

        return SecurityCheckResult(
            allowed=True,
            category=category,
            risk_level=risk_level,
        )

    # ── Stage 3: Clean (post-execution) ────────────────────────────────

    async def sanitize_tool_result(self, tool_result_text: str, category: str = "internal") -> str:
        """Post-execution: clean tool output."""
        if not tool_result_text:
            return tool_result_text

        try:
            return await self._cleaner.clean(tool_result_text, category=category)
        except Exception:
            log.exception("security: cleaner error, returning raw result")
            return tool_result_text
