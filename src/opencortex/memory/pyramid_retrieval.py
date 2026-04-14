"""Pyramid progressive retrieval for memory entries.

Level 1: summary only (cheap, ~10 tokens each)
Level 2: full text (expanded when similarity > similarity_threshold)
Level 3: greedy selection within token budget (reserved for future raw-content loading)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Rough estimate: 1 token ≈ 4 characters for English text
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / _CHARS_PER_TOKEN))


@dataclass
class PyramidMemory:
    """A single memory with summary and optional full text."""

    id: int
    summary: str
    full_text: str | None = None
    score: float = 0.0


@dataclass
class PyramidConfig:
    similarity_threshold: float = 0.4
    token_budget: int = 6000
    summary_prefix: str = "- "


def retrieve(
    query: str,
    memories: list[PyramidMemory],
    config: PyramidConfig | None = None,
) -> str:
    """Return a pyramid-formatted context string within *token_budget*.

    Args:
        query: The search query (used for logging / future expansion).
        memories: Scored memory entries with summary and optional full_text.
        config: Retrieval parameters.

    Returns:
        A newline-joined context string fitting within the token budget.
    """
    cfg = config or PyramidConfig()
    budget = cfg.token_budget
    parts: list[str] = []
    used_tokens = 0

    for mem in memories:
        # Decide level: summary (L1) or full text (L2)
        if mem.full_text and mem.score > cfg.similarity_threshold:
            text = mem.full_text
        else:
            text = mem.summary

        text_with_prefix = f"{cfg.summary_prefix}{text}"
        tokens = _estimate_tokens(text_with_prefix)

        if used_tokens + tokens > budget:
            continue

        parts.append(text_with_prefix)
        used_tokens += tokens

    return "\n".join(parts)
