"""Tests for user_profile module."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from opencortex.memory.user_profile import (
    UserProfile,
    learn_from_conversation,
    load_user_md,
    save_user_md,
)


class TestLearnFromConversation:
    def test_extracts_language(self):
        p = UserProfile()
        p = learn_from_conversation(p, "I love Python and TypeScript")
        assert p.preferences.get("language") in ("Python", "TypeScript")

    def test_extracts_framework(self):
        p = UserProfile()
        p = learn_from_conversation(p, "Using FastAPI with Pydantic")
        assert p.preferences.get("framework") in ("FastAPI", "Pydantic")

    def test_extracts_tools(self):
        p = UserProfile()
        p = learn_from_conversation(p, "I use git and pytest daily")
        assert "git" in p.frequently_used_tools
        assert "pytest" in p.frequently_used_tools

    def test_incremental_no_duplicate_tools(self):
        p = UserProfile(frequently_used_tools=["git"])
        p = learn_from_conversation(p, "use git and docker")
        assert p.frequently_used_tools.count("git") == 1
        assert "docker" in p.frequently_used_tools

    def test_updates_timestamp(self):
        import time
        p = UserProfile()
        before = p.last_updated
        time.sleep(0.01)
        p = learn_from_conversation(p, "Python")
        assert p.last_updated >= before


class TestSaveAndLoad:
    def test_roundtrip(self, tmp_path: Path):
        p = UserProfile(
            user_id="u1",
            name="Test",
            preferences={"language": "Python", "framework": "FastAPI"},
            communication_style="简洁直接",
            frequently_used_tools=["git", "pytest"],
            patterns=["偏好列表"],
            expertise=["后端开发"],
            project_preferences={"timezone": "Asia/Shanghai"},
        )
        f = tmp_path / "USER.md"
        save_user_md(p, f)

        loaded = load_user_md(f)
        assert loaded.name == "Test"
        assert loaded.preferences["language"] == "Python"
        assert loaded.preferences["framework"] == "FastAPI"
        assert loaded.communication_style == "简洁直接"
        assert "git" in loaded.frequently_used_tools
        assert loaded.patterns == ["偏好列表"]
        assert loaded.expertise == ["后端开发"]
        assert loaded.project_preferences["timezone"] == "Asia/Shanghai"

    def test_load_missing_file(self, tmp_path: Path):
        loaded = load_user_md(tmp_path / "nonexistent.md")
        assert loaded.name == ""
        assert loaded.preferences == {}

    def test_save_format(self, tmp_path: Path):
        p = UserProfile(name="张三", preferences={"language": "Python"})
        p.frequently_used_tools = ["git"]
        f = tmp_path / "USER.md"
        save_user_md(p, f)
        content = f.read_text(encoding="utf-8")
        assert "# User Profile" in content
        assert "张三" in content
        assert "Python" in content
        assert "git" in content


class TestUserProfile:
    def test_defaults(self):
        p = UserProfile()
        assert p.user_id == ""
        assert p.preferences == {}
        assert p.frequently_used_tools == []
