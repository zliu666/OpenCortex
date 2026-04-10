"""Tests for skill auto-learning: trajectory, extractor, generator."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from opencortex.skills.trajectory import TrajectoryEntry, TrajectoryRecorder
from opencortex.skills.extractor import SkillExtractor
from opencortex.skills.generator import SkillGenerator


def _make_entry(
    task: str,
    tools: list[str],
    outcome: str = "success",
    lessons: list[str] | None = None,
) -> TrajectoryEntry:
    steps = [{"tool": t, "input": {}, "output": "ok", "duration": 1.0} for t in tools]
    return TrajectoryEntry(
        timestamp=1000.0,
        task_description=task,
        steps=steps,
        outcome=outcome,
        lessons=lessons or [],
    )


class TestTrajectoryRecorder:
    def test_record_and_get(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder(tmp_path / "traj.jsonl")
        e = _make_entry("task1", ["search"])
        rec.record(e)
        entries = rec.get_entries()
        assert len(entries) == 1
        assert entries[0].task_description == "task1"

    def test_get_limit(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder(tmp_path / "traj.jsonl")
        for i in range(10):
            rec.record(_make_entry(f"task{i}", ["tool_a"]))
        assert len(rec.get_entries(limit=3)) == 3

    def test_clear(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder(tmp_path / "traj.jsonl")
        rec.record(_make_entry("t", ["x"]))
        rec.clear()
        assert rec.get_entries() == []

    def test_empty_storage(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder(tmp_path / "nonexistent.jsonl")
        assert rec.get_entries() == []


class TestSkillExtractor:
    def test_analyze_patterns(self) -> None:
        entries = [
            _make_entry("deploy app", ["build", "test", "deploy"]),
            _make_entry("deploy service", ["build", "test", "deploy"]),
            _make_entry("fix bug", ["search", "edit"]),
        ]
        ext = SkillExtractor(min_occurrences=2)
        patterns = ext.analyze_patterns(entries)
        assert len(patterns) == 1
        assert patterns[0]["tool_sequence"] == ["build", "test", "deploy"]
        assert patterns[0]["occurrences"] == 2

    def test_no_success(self) -> None:
        entries = [_make_entry("fail", ["x"], outcome="failure")]
        assert SkillExtractor().analyze_patterns(entries) == []

    def test_is_reusable(self) -> None:
        ext = SkillExtractor(min_occurrences=2)
        assert ext.is_reusable({"tool_sequence": ["a", "b"], "occurrences": 3})
        assert not ext.is_reusable({"tool_sequence": [], "occurrences": 1})

    def test_extract_skill(self) -> None:
        pattern = {
            "tool_sequence": ["build", "deploy"],
            "occurrences": 3,
            "task_descriptions": ["deploy app", "deploy service", "deploy api"],
            "lessons": ["always test first"],
        }
        skill = SkillExtractor().extract_skill(pattern)
        assert skill.name == "auto-build-deploy"
        assert "always test first" in skill.content


class TestSkillGenerator:
    def test_generate_skill_md(self) -> None:
        from opencortex.skills.types import SkillDefinition

        skill = SkillDefinition(
            name="test",
            description="desc",
            content="# Test\nHello",
            source="test",
        )
        assert SkillGenerator().generate_skill_md(skill) == "# Test\nHello"

    def test_save_skill(self, tmp_path: Path) -> None:
        from opencortex.skills.types import SkillDefinition

        skill = SkillDefinition(
            name="auto-deploy",
            description="Deploy skill",
            content="# Auto Deploy\n",
            source="trajectory",
        )
        path = SkillGenerator().save_skill(skill, tmp_path / "skills")
        assert path.exists()
        assert path.name == "SKILL.md"
