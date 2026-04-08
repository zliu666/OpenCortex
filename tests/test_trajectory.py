"""Tests for trajectory recording and skill extraction."""

import json
import tempfile
from pathlib import Path

from opencortex.trajectory.recorder import TrajectoryRecorder
from opencortex.trajectory.skill_extractor import SkillExtractor


def test_trajectory_recorder_session():
    """Test full session: start → record → end → load."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = TrajectoryRecorder(trajectory_dir=Path(tmpdir))

        recorder.start_session("test-session-1")
        recorder.record("read", {"path": "/tmp/a.py"}, "OK: 100 lines")
        recorder.record("edit", {"path": "/tmp/a.py", "old": "x", "new": "y"}, "Replaced 1 occurrence")
        path = recorder.end_session(completed=True)

        assert path.exists()
        assert path.name == "completed.jsonl"

        # Load and verify
        trajectories = recorder.load_trajectories()
        assert len(trajectories) == 1
        assert trajectories[0]["session_id"] == "test-session-1"
        assert len(trajectories[0]["entries"]) == 2
        assert trajectories[0]["entries"][0]["tool_name"] == "read"


def test_trajectory_recorder_failure():
    """Test failed session recording."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = TrajectoryRecorder(trajectory_dir=Path(tmpdir))
        recorder.start_session("fail-session")
        recorder.record("exec", {"cmd": "false"}, "exit code 1", success=False)
        path = recorder.end_session(completed=False)
        assert path.name == "failed.jsonl"


def test_skill_extractor_no_data():
    """Test extractor with no trajectories returns empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = TrajectoryRecorder(trajectory_dir=Path(tmpdir))
        extractor = SkillExtractor(recorder)
        patterns = extractor.extract_patterns()
        assert patterns == []


def test_skill_extractor_detects_pattern():
    """Test that extractor finds repeating tool sequences."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = TrajectoryRecorder(trajectory_dir=Path(tmpdir))

        # Create multiple sessions with same pattern
        for i in range(3):
            recorder.start_session(f"session-{i}")
            recorder.record("read", {"path": f"/tmp/{i}.py"}, "OK")
            recorder.record("edit", {"path": f"/tmp/{i}.py"}, "Done")
            recorder.end_session(completed=True)

        extractor = SkillExtractor(recorder)
        patterns = extractor.extract_patterns(min_occurrences=2)
        assert len(patterns) > 0

        # Convert to skills
        skills = extractor.patterns_to_skills(patterns)
        assert len(skills) > 0
        assert all(s.source == "auto-generated" for s in skills)
        assert all(s.content.startswith("---") for s in skills)
