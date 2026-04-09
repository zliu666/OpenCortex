"""Session Insights Engine for OpenCortex.

Analyzes session history (JSON snapshots from session_storage) to produce
usage insights: token consumption, cost estimates, model breakdown,
tool usage patterns, and activity trends.

Inspired by Hermes InsightsEngine, adapted for OpenCortex's file-based
session storage and CostTracker infrastructure.

Usage:
    from opencortex.analytics.insights import InsightsEngine
    engine = InsightsEngine(session_dir="/path/to/sessions")
    report = engine.generate(days=30)
    print(engine.format_report(report))
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Pricing table (per-million tokens, USD) — subset of common models
# ---------------------------------------------------------------------------
_PRICING_TABLE: dict[str, dict[str, float]] = {
    "glm-5.1": {"input": 0.50, "output": 0.50},
    "glm-5": {"input": 0.50, "output": 0.50},
    "minimax-m2.7-highspeed": {"input": 0.10, "output": 0.10},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
}

_DEFAULT_PRICING = {"input": 0.0, "output": 0.0}


def _get_pricing(model: str) -> dict[str, float]:
    """Look up pricing for a model with fuzzy matching."""
    key = model.lower().split("/")[-1]
    return _PRICING_TABLE.get(key, _DEFAULT_PRICING)


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a model/token combination."""
    p = _get_pricing(model)
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    if hours < 24:
        remaining_min = int(minutes % 60)
        return f"{int(hours)}h {remaining_min}m" if remaining_min else f"{int(hours)}h"
    days = hours / 24
    return f"{days:.1f}d"


def _bar(values: list[int], max_width: int = 15) -> list[str]:
    peak = max(values) if values else 1
    if peak == 0:
        return ["" for _ in values]
    return ["█" * max(1, int(v / peak * max_width)) if v > 0 else "" for v in values]


class InsightsEngine:
    """Analyze session history and produce usage insights.

    Reads JSON session snapshots from the session_storage directory layout.
    """

    def __init__(self, session_dir: str | Path) -> None:
        self._dir = Path(session_dir)

    def generate(self, days: int = 30) -> dict[str, Any]:
        """Generate a complete insights report."""
        cutoff = time.time() - (days * 86400)
        sessions = self._load_sessions(cutoff)

        if not sessions:
            return {"days": days, "empty": True, "overview": {}, "models": [], "tools": [], "activity": {}, "top_sessions": []}

        overview = self._compute_overview(sessions)
        models = self._compute_model_breakdown(sessions)
        tools = self._compute_tool_breakdown(sessions)
        activity = self._compute_activity(sessions)
        top = self._compute_top_sessions(sessions)

        return {
            "days": days,
            "empty": False,
            "generated_at": time.time(),
            "overview": overview,
            "models": models,
            "tools": tools,
            "activity": activity,
            "top_sessions": top,
        }

    def _load_sessions(self, cutoff: float) -> list[dict]:
        """Load all session snapshots newer than cutoff."""
        sessions: list[dict] = []
        if not self._dir.exists():
            return sessions

        for path in self._dir.rglob("session-*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                created = data.get("created_at", 0)
                if created >= cutoff:
                    sessions.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        # Also scan top-level latest.json files
        for path in self._dir.rglob("latest.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sid = data.get("session_id", "latest")
                created = data.get("created_at", 0)
                if created >= cutoff:
                    # Deduplicate: only add if not already present
                    if not any(s.get("session_id") == sid for s in sessions):
                        sessions.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        return sessions

    def _compute_overview(self, sessions: list[dict]) -> dict[str, Any]:
        total_input = 0
        total_output = 0
        total_cost = 0.0
        total_messages = 0

        for s in sessions:
            usage = s.get("usage", {})
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
            total_input += inp
            total_output += out
            total_messages += s.get("message_count", 0)
            model = s.get("model", "")
            total_cost += _estimate_cost(model, inp, out)

        return {
            "total_sessions": len(sessions),
            "total_messages": total_messages,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "estimated_cost_usd": total_cost,
            "avg_messages_per_session": total_messages / len(sessions) if sessions else 0,
        }

    def _compute_model_breakdown(self, sessions: list[dict]) -> list[dict]:
        model_data: dict[str, dict] = defaultdict(lambda: {
            "sessions": 0, "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "cost": 0.0,
        })
        for s in sessions:
            model = s.get("model") or "unknown"
            display = model.split("/")[-1] if "/" in model else model
            d = model_data[display]
            usage = s.get("usage", {})
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
            d["sessions"] += 1
            d["input_tokens"] += inp
            d["output_tokens"] += out
            d["total_tokens"] += inp + out
            d["cost"] += _estimate_cost(model, inp, out)

        result = [{"model": m, **d} for m, d in model_data.items()]
        result.sort(key=lambda x: x["total_tokens"], reverse=True)
        return result

    def _compute_tool_breakdown(self, sessions: list[dict]) -> list[dict]:
        tool_counts: Counter = Counter()
        for s in sessions:
            for msg in s.get("messages", []):
                # Count tool-use blocks
                for block in msg.get("content", []):
                    if block.get("type") == "tool_use":
                        name = block.get("name", "unknown")
                        tool_counts[name] += 1

        total = sum(tool_counts.values()) or 1
        return [
            {"tool": name, "count": count, "percentage": count / total * 100}
            for name, count in tool_counts.most_common()
        ]

    def _compute_activity(self, sessions: list[dict]) -> dict[str, Any]:
        day_counts: Counter = Counter()
        hour_counts: Counter = Counter()

        for s in sessions:
            ts = s.get("created_at")
            if not ts:
                continue
            dt = datetime.fromtimestamp(ts)
            day_counts[dt.strftime("%Y-%m-%d")] += 1
            hour_counts[dt.hour] += 1

        peak_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "active_days": len(day_counts),
            "peak_hours": [
                {"hour": h, "count": c} for h, c in peak_hours
            ],
            "busiest_day": max(day_counts.items(), key=lambda x: x[1]) if day_counts else None,
        }

    def _compute_top_sessions(self, sessions: list[dict]) -> list[dict]:
        top = []
        if not sessions:
            return top

        # Most messages
        most_msgs = max(sessions, key=lambda s: s.get("message_count", 0))
        mc = most_msgs.get("message_count", 0)
        if mc > 0:
            top.append({
                "label": "Most messages",
                "session_id": most_msgs.get("session_id", "?")[:16],
                "value": f"{mc} msgs",
            })

        # Most tokens
        def _tokens(s): return (s.get("usage") or {}).get("input_tokens", 0) + (s.get("usage") or {}).get("output_tokens", 0)
        most_tokens = max(sessions, key=_tokens)
        tt = _tokens(most_tokens)
        if tt > 0:
            top.append({
                "label": "Most tokens",
                "session_id": most_tokens.get("session_id", "?")[:16],
                "value": f"{tt:,} tokens",
            })

        return top

    # -----------------------------------------------------------------------
    # Formatting
    # -----------------------------------------------------------------------

    def format_report(self, report: dict) -> str:
        """Format insights report for terminal display."""
        if report.get("empty"):
            return f"  No sessions found in the last {report.get('days', 30)} days."

        lines: list[str] = []
        o = report["overview"]
        days = report["days"]

        lines.append("")
        lines.append("  ╔══════════════════════════════════════════════════════════╗")
        lines.append("  ║                📊 OpenCortex Insights                    ║")
        lines.append(f"  ║              Last {days} days{' ' * (44 - len(str(days)))}║")
        lines.append("  ╚══════════════════════════════════════════════════════════╝")
        lines.append("")

        # Overview
        lines.append("  📋 Overview")
        lines.append("  " + "─" * 56)
        lines.append(f"  Sessions:          {o['total_sessions']:<12}  Messages:        {o['total_messages']:,}")
        lines.append(f"  Input tokens:      {o['total_input_tokens']:<12,}  Output tokens:   {o['total_output_tokens']:,}")
        cost_str = f"${o['estimated_cost_usd']:.4f}"
        lines.append(f"  Total tokens:      {o['total_tokens']:<12,}  Est. cost:       {cost_str}")
        lines.append(f"  Avg msgs/session:  {o['avg_messages_per_session']:.1f}")
        lines.append("")

        # Models
        if report["models"]:
            lines.append("  🤖 Models Used")
            lines.append("  " + "─" * 56)
            lines.append(f"  {'Model':<30} {'Sessions':>8} {'Tokens':>12} {'Cost':>8}")
            for m in report["models"]:
                model_name = m["model"][:28]
                cost_cell = f"${m['cost']:>6.4f}" if m["cost"] > 0 else "  $0.00"
                lines.append(f"  {model_name:<30} {m['sessions']:>8} {m['total_tokens']:>12,} {cost_cell}")
            lines.append("")

        # Tools
        if report["tools"]:
            lines.append("  🔧 Top Tools")
            lines.append("  " + "─" * 56)
            for t in report["tools"][:10]:
                lines.append(f"  {t['tool']:<28} {t['count']:>6,} calls ({t['percentage']:.1f}%)")
            lines.append("")

        # Activity
        act = report.get("activity", {})
        if act.get("active_days"):
            lines.append("  📅 Activity")
            lines.append("  " + "─" * 56)
            lines.append(f"  Active days: {act['active_days']}")
            if act.get("busiest_day"):
                lines.append(f"  Busiest day: {act['busiest_day'][0]} ({act['busiest_day'][1]} sessions)")
            if act.get("peak_hours"):
                hour_strs = []
                for h in act["peak_hours"]:
                    ampm = "AM" if h["hour"] < 12 else "PM"
                    hr = h["hour"] % 12 or 12
                    hour_strs.append(f"{hr}{ampm} ({h['count']})")
                lines.append(f"  Peak hours: {', '.join(hour_strs)}")
            lines.append("")

        # Notable sessions
        if report.get("top_sessions"):
            lines.append("  🏆 Notable Sessions")
            lines.append("  " + "─" * 56)
            for ts in report["top_sessions"]:
                lines.append(f"  {ts['label']:<20} {ts['value']:<18} ({ts['session_id']})")
            lines.append("")

        return "\n".join(lines)

    def format_brief(self, report: dict) -> str:
        """Format a brief summary for messaging (Feishu/Slack/etc)."""
        if report.get("empty"):
            return f"最近 {report.get('days', 30)} 天没有会话记录。"

        o = report["overview"]
        lines = [
            f"📊 **OpenCortex Insights** — 最近 {report['days']} 天\n",
            f"**会话:** {o['total_sessions']} | **消息:** {o['total_messages']:,}",
            f"**Token:** {o['total_tokens']:,} (入: {o['total_input_tokens']:,} / 出: {o['total_output_tokens']:,})",
            f"**预估成本:** ${o['estimated_cost_usd']:.4f}",
        ]

        if report["models"]:
            lines.append("\n**🤖 模型:**")
            for m in report["models"][:5]:
                lines.append(f"  {m['model']} — {m['sessions']} 次会话, {m['total_tokens']:,} tokens")

        if report["tools"]:
            lines.append("\n**🔧 工具:**")
            for t in report["tools"][:5]:
                lines.append(f"  {t['tool']} — {t['count']} 次 ({t['percentage']:.1f}%)")

        return "\n".join(lines)
