"""Extract reusable skill patterns from trajectory data."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opencortex.trajectory.recorder import TrajectoryRecorder
from opencortex.skills.types import SkillDefinition

logger = logging.getLogger(__name__)


@dataclass
class SkillPattern:
    """A detected reusable pattern from trajectories."""

    name: str
    description: str
    tool_sequence: list[str]
    occurrence_count: int
    sample_args: list[dict[str, Any]]
    category: str = "auto-generated"


class SkillExtractor:
    """Analyzes trajectories to find recurring tool-call patterns.

    Detection strategy:
    1. Extract consecutive tool-call sequences per session
    2. Normalize args to abstract patterns (keep tool names, summarize args)
    3. Find sequences that repeat across sessions (>= 2 occurrences)
    4. Generate a SkillDefinition with the pattern as content
    """

    def __init__(self, recorder: TrajectoryRecorder | None = None) -> None:
        self._recorder = recorder or TrajectoryRecorder()

    def extract_patterns(self, min_occurrences: int = 2) -> list[SkillPattern]:
        """Find recurring tool sequences in trajectory history."""
        trajectories = self._recorder.load_trajectories()
        if not trajectories:
            return []

        # Build sequences per session
        sequences: list[list[str]] = []
        session_args: dict[tuple[str, ...], list[dict]] = {}

        for traj in trajectories:
            entries = traj.get("entries", [])
            if not entries:
                continue
            seq = [e["tool_name"] for e in entries if e.get("tool_name")]
            if len(seq) < 2:
                continue
            sequences.append(seq)
            key = tuple(seq)
            if key not in session_args:
                session_args[key] = []
            for e in entries:
                session_args[key].append(e.get("tool_args", {}))

        # Count sequence patterns (also check subsequences of length 2-4)
        pattern_counter: Counter[tuple[str, ...]] = Counter()
        pattern_args: dict[tuple[str, ...], list[dict]] = {}

        for seq in sequences:
            # Full sequence
            if len(seq) >= 2:
                key = tuple(seq[:5])  # Cap at 5 tools
                pattern_counter[key] += 1
                if key not in pattern_args:
                    pattern_args[key] = session_args.get(tuple(seq), [])
            # Subsequences of length 2-3
            for window in (2, 3):
                for i in range(len(seq) - window + 1):
                    sub = tuple(seq[i : i + window])
                    pattern_counter[sub] += 1
                    if sub not in pattern_args:
                        pattern_args[sub] = []

        # Filter by minimum occurrences
        patterns: list[SkillPattern] = []
        for seq_tuple, count in pattern_counter.most_common(20):
            if count < min_occurrences:
                break
            name = _generate_skill_name(seq_tuple)
            desc = _generate_description(seq_tuple, count)
            patterns.append(
                SkillPattern(
                    name=name,
                    description=desc,
                    tool_sequence=list(seq_tuple),
                    occurrence_count=count,
                    sample_args=pattern_args.get(seq_tuple, [])[:3],
                    category="auto-generated",
                )
            )

        return patterns

    def patterns_to_skills(self, patterns: list[SkillPattern]) -> list[SkillDefinition]:
        """Convert detected patterns into SkillDefinitions."""
        skills: list[SkillDefinition] = []
        for p in patterns:
            content = _build_skill_markdown(p)
            skills.append(
                SkillDefinition(
                    name=p.name,
                    description=p.description,
                    content=content,
                    source="auto-generated",
                    path=None,
                )
            )
        return skills


def _generate_skill_name(tool_sequence: tuple[str, ...]) -> str:
    """Generate a human-readable skill name from a tool sequence."""
    parts = [t.replace("_", "-").replace(".", "-") for t in tool_sequence[:3]]
    return "auto-" + "-".join(parts)


def _generate_description(tool_sequence: tuple[str, ...], count: int) -> str:
    """Generate a description for a skill pattern."""
    tools = " → ".join(tool_sequence)
    return f"Recurring pattern ({count}x): {tools}"


def _build_skill_markdown(pattern: SkillPattern) -> str:
    """Build SKILL.md content for an auto-generated skill."""
    lines = [
        f"---",
        f"name: {pattern.name}",
        f"description: {pattern.description}",
        f"category: {pattern.category}",
        f"occurrences: {pattern.occurrence_count}",
        f"---",
        "",
        f"# {pattern.name}",
        "",
        f"Auto-detected pattern from trajectory analysis.",
        f"Observed **{pattern.occurrence_count}** times.",
        "",
        "## Tool Sequence",
        "",
    ]
    for i, tool in enumerate(pattern.tool_sequence, 1):
        lines.append(f"{i}. `{tool}`")

    lines.extend(["", "## Usage", "", "Follow the tool sequence above for the described task."])
    return "\n".join(lines)
