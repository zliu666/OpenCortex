"""Tests for user profile and preference learning."""

import tempfile
from pathlib import Path

from opencortex.profile.store import ProfileStore
from opencortex.profile.learner import PreferenceLearner


def test_profile_store_basic():
    """Test basic CRUD on ProfileStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProfileStore(db_path=Path(tmpdir) / "test.db")
        store.set("name", "Alice", category="identity")
        result = store.get("name")
        assert result is not None
        assert result["value"] == "Alice"
        assert result["category"] == "identity"
        store.close()


def test_profile_store_update():
    """Test upsert behavior."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProfileStore(db_path=Path(tmpdir) / "test.db")
        store.set("name", "Alice")
        store.set("name", "Bob")
        assert store.get("name")["value"] == "Bob"
        store.close()


def test_profile_store_category():
    """Test querying by category."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProfileStore(db_path=Path(tmpdir) / "test.db")
        store.set("lang", "English", category="communication")
        store.set("tz", "UTC+8", category="identity")
        store.set("style", "concise", category="communication")

        comms = store.get_by_category("communication")
        assert len(comms) == 2
        store.close()


def test_profile_format_prompt():
    """Test prompt formatting."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProfileStore(db_path=Path(tmpdir) / "test.db")
        store.set("name", "Alice", category="identity")
        store.set("language", "Chinese", category="communication")
        prompt = store.format_for_prompt()
        assert "Alice" in prompt
        assert "Chinese" in prompt
        store.close()


def test_preference_learner_name():
    """Test detecting name preference."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProfileStore(db_path=Path(tmpdir) / "test.db")
        learner = PreferenceLearner(store=store)

        detected = learner.analyze_message("My name is Bob")
        assert len(detected) > 0
        assert any(d["category"] == "identity" for d in detected)


def test_preference_learner_dislike():
    """Test detecting dislike."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProfileStore(db_path=Path(tmpdir) / "test.db")
        learner = PreferenceLearner(store=store)

        detected = learner.analyze_message("I don't like verbose explanations")
        assert len(detected) > 0


def test_preference_learner_no_match():
    """Test that normal messages don't trigger false positives."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProfileStore(db_path=Path(tmpdir) / "test.db")
        learner = PreferenceLearner(store=store)

        detected = learner.analyze_message("What is the weather today?")
        assert len(detected) == 0


def test_preference_learner_prompt():
    """Test getting formatted profile prompt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProfileStore(db_path=Path(tmpdir) / "test.db")
        learner = PreferenceLearner(store=store)
        learner.analyze_message("My name is Test")
        prompt = learner.get_profile_prompt()
        assert isinstance(prompt, str)
