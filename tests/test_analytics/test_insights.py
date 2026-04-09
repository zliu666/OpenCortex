"""Tests for the session insights engine."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from opencortex.analytics.insights import InsightsEngine, _estimate_cost, _get_pricing


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """Create a temp dir with sample session data."""
    now = time.time()

    sessions = [
        {
            "session_id": "sess-001",
            "model": "glm-5.1",
            "created_at": now - 86400,
            "message_count": 12,
            "usage": {"input_tokens": 5000, "output_tokens": 2000},
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hello"}]},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "hi"},
                        {"type": "tool_use", "name": "read_file", "input": {}},
                    ],
                },
                {"role": "user", "content": [{"type": "text", "text": "read foo.py"}]},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "read_file", "input": {}},
                        {"type": "tool_use", "name": "search", "input": {}},
                    ],
                },
            ],
        },
        {
            "session_id": "sess-002",
            "model": "claude-sonnet-4-20250514",
            "created_at": now - 3600,
            "message_count": 25,
            "usage": {"input_tokens": 50000, "output_tokens": 15000},
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "complex task"}]},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "exec_shell", "input": {}},
                    ],
                },
            ],
        },
    ]

    # Create session files in a project subdirectory (like session_storage does)
    proj_dir = tmp_path / "myproject-abc123"
    proj_dir.mkdir()

    for s in sessions:
        path = proj_dir / f"session-{s['session_id']}.json"
        path.write_text(json.dumps(s), encoding="utf-8")

    return tmp_path


class TestPricing:
    def test_known_model(self):
        p = _get_pricing("glm-5.1")
        assert p["input"] > 0
        assert p["output"] > 0

    def test_unknown_model_returns_zero(self):
        p = _get_pricing("nonexistent-model")
        assert p["input"] == 0.0
        assert p["output"] == 0.0

    def test_estimate_cost(self):
        cost = _estimate_cost("glm-5.1", 1_000_000, 1_000_000)
        assert cost == pytest.approx(1.0)

    def test_estimate_cost_unknown(self):
        cost = _estimate_cost("unknown", 1_000_000, 1_000_000)
        assert cost == 0.0


class TestInsightsEngine:
    def test_empty_report(self, tmp_path):
        engine = InsightsEngine(tmp_path / "nonexistent")
        report = engine.generate(days=30)
        assert report["empty"] is True

    def test_generate_report(self, session_dir):
        engine = InsightsEngine(session_dir)
        report = engine.generate(days=30)

        assert report["empty"] is False
        assert report["overview"]["total_sessions"] == 2
        assert report["overview"]["total_messages"] == 37
        assert report["overview"]["total_input_tokens"] == 55000
        assert report["overview"]["total_output_tokens"] == 17000
        assert report["overview"]["total_tokens"] == 72000
        assert report["overview"]["estimated_cost_usd"] > 0

    def test_model_breakdown(self, session_dir):
        engine = InsightsEngine(session_dir)
        report = engine.generate(days=30)

        models = {m["model"]: m for m in report["models"]}
        assert "glm-5.1" in models
        assert "claude-sonnet-4-20250514" in models
        assert models["glm-5.1"]["sessions"] == 1
        assert models["claude-sonnet-4-20250514"]["sessions"] == 1

    def test_tool_breakdown(self, session_dir):
        engine = InsightsEngine(session_dir)
        report = engine.generate(days=30)

        assert len(report["tools"]) > 0
        tool_names = [t["tool"] for t in report["tools"]]
        assert "read_file" in tool_names
        assert "search" in tool_names
        assert "exec_shell" in tool_names

    def test_activity(self, session_dir):
        engine = InsightsEngine(session_dir)
        report = engine.generate(days=30)

        act = report["activity"]
        assert act["active_days"] >= 1

    def test_top_sessions(self, session_dir):
        engine = InsightsEngine(session_dir)
        report = engine.generate(days=30)

        top = report["top_sessions"]
        assert len(top) > 0
        labels = [t["label"] for t in top]
        assert "Most messages" in labels
        assert "Most tokens" in labels

    def test_format_report(self, session_dir):
        engine = InsightsEngine(session_dir)
        report = engine.generate(days=30)
        text = engine.format_report(report)

        assert "OpenCortex Insights" in text
        assert "glm-5.1" in text
        assert "read_file" in text

    def test_format_brief(self, session_dir):
        engine = InsightsEngine(session_dir)
        report = engine.generate(days=30)
        text = engine.format_brief(report)

        assert "会话" in text
        assert "glm-5.1" in text

    def test_format_empty(self, tmp_path):
        engine = InsightsEngine(tmp_path / "nonexistent")
        report = engine.generate(days=30)
        text = engine.format_report(report)
        assert "No sessions found" in text

    def test_format_brief_empty(self, tmp_path):
        engine = InsightsEngine(tmp_path / "nonexistent")
        report = engine.generate(days=30)
        text = engine.format_brief(report)
        assert "没有会话记录" in text
