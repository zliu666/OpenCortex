"""Extract reusable skills from execution trajectories."""

from __future__ import annotations

from collections import Counter

from opencortex.skills.types import SkillDefinition
from opencortex.skills.trajectory import TrajectoryEntry


class SkillExtractor:
    """从轨迹中提取可复用的技能。"""

    def __init__(self, min_occurrences: int = 2) -> None:
        self._min_occurrences = min_occurrences

    def analyze_patterns(self, entries: list[TrajectoryEntry]) -> list[dict]:
        """分析成功轨迹中的模式。"""
        successful = [e for e in entries if e.outcome == "success"]
        if not successful:
            return []

        # Group by common tool sequences
        tool_seq_counter: Counter[tuple[str, ...]] = Counter()
        entries_by_seq: dict[tuple[str, ...], list[TrajectoryEntry]] = {}

        for entry in successful:
            tools = tuple(step.get("tool", "") for step in entry.steps if step.get("tool"))
            if not tools:
                continue
            tool_seq_counter[tools] += 1
            entries_by_seq.setdefault(tools, []).append(entry)

        patterns: list[dict] = []
        for seq, count in tool_seq_counter.most_common():
            if count < self._min_occurrences:
                continue
            related = entries_by_seq[seq]
            all_lessons: list[str] = []
            for e in related:
                all_lessons.extend(e.lessons)
            patterns.append(
                {
                    "tool_sequence": list(seq),
                    "occurrences": count,
                    "task_descriptions": [e.task_description for e in related],
                    "lessons": all_lessons,
                }
            )
        return patterns

    def is_reusable(self, pattern: dict) -> bool:
        """判断模式是否值得提取为技能。"""
        return (
            len(pattern.get("tool_sequence", [])) >= 1
            and pattern.get("occurrences", 0) >= self._min_occurrences
        )

    def extract_skill(self, pattern: dict) -> SkillDefinition:
        """将模式转换为技能定义。"""
        tools = pattern.get("tool_sequence", [])
        descs = pattern.get("task_descriptions", [])
        lessons = pattern.get("lessons", [])

        name = f"auto-{tools[0]}" if len(tools) == 1 else f"auto-{'-'.join(tools[:2])}"
        description = f"Auto-extracted skill from {pattern.get('occurrences', 0)} trajectories."
        if descs:
            description += f" Tasks: {', '.join(descs[:3])}"

        sections = ["# Auto-Extracted Skill\n", f"## Description\n{description}\n"]
        if tools:
            sections.append(f"## Typical Tool Sequence\n{' → '.join(tools)}\n")
        if lessons:
            sections.append("## Lessons Learned\n" + "\n".join(f"- {l}" for l in lessons) + "\n")
        if descs:
            sections.append("## Example Tasks\n" + "\n".join(f"- {d}" for d in descs[:5]) + "\n")

        content = "\n".join(sections)
        return SkillDefinition(
            name=name,
            description=description,
            content=content,
            source="trajectory-extraction",
        )
