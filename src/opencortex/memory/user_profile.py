"""用户画像模块 — 自动学习、持久化到 USER.md、增量更新。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ── data ──────────────────────────────────────────────────────────────

@dataclass
class UserProfile:
    """用户画像。"""
    user_id: str = ""
    name: str = ""
    preferences: dict[str, str] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)
    expertise: list[str] = field(default_factory=list)
    communication_style: str = ""
    frequently_used_tools: list[str] = field(default_factory=list)
    project_preferences: dict[str, str] = field(default_factory=dict)
    last_updated: float = field(default_factory=time.time)


# ── patterns for auto-learning ────────────────────────────────────────

_LANG_RE = re.compile(r"\b(Python|JavaScript|TypeScript|Rust|Go|Java|C\+\+|C#|Ruby|Swift|Kotlin|Shell|Bash)\b", re.I)
_FRAMEWORK_RE = re.compile(r"\b(FastAPI|Django|Flask|React|Vue|Next\.js|Pydantic|SQLAlchemy|Express|Axum|Spring|Rails)\b", re.I)
_TOOL_RE = re.compile(r"\b(git|docker|pytest|jest|cargo|pip|npm|yarn|pnpm|make|cmake|zellij|tmux|vim|neovim|vscode)\b", re.I)


def _extract_unique(text: str, pattern: re.Pattern) -> list[str]:
    seen: set[str] = set()
    for m in pattern.finditer(text):
        seen.add(m.group())
    return sorted(seen)


def learn_from_conversation(profile: UserProfile, conversation: str) -> UserProfile:
    """从对话文本中提取偏好并增量更新画像。"""
    # 语言偏好
    for lang in _extract_unique(conversation, _LANG_RE):
        profile.preferences.setdefault("language", lang)

    # 框架
    for fw in _extract_unique(conversation, _FRAMEWORK_RE):
        profile.preferences.setdefault("framework", fw)

    # 工具
    for tool in _extract_unique(conversation, _TOOL_RE):
        if tool not in profile.frequently_used_tools:
            profile.frequently_used_tools.append(tool)

    profile.last_updated = time.time()
    return profile


# ── USER.md serialization ────────────────────────────────────────────

_TEMPLATE = """\
# User Profile

## 基本信息
- 名称：{name}
{pref_lines}
- 时区：{timezone}

## 技术偏好
{tech_lines}
{fw_line}
{test_line}

## 沟通风格
- {comm_style}

## 常用工具
- {tools}

## 行为模式
{pattern_lines}

## 专业领域
{expertise_lines}

## 项目偏好
{proj_lines}
"""


def _format_user_md(profile: UserProfile) -> str:
    lines: list[str] = []

    # 基本信息
    pref_lines: list[str] = []
    for k, v in profile.preferences.items():
        label = {"language": "语言偏好", "framework": "框架偏好"}.get(k, k)
        pref_lines.append(f"- {label}：{v}")
    timezone = profile.project_preferences.get("timezone", "UTC")

    # 技术偏好
    tech_lines = ""
    lang = profile.preferences.get("language", "")
    if lang:
        tech_lines = f"- 主要语言：{lang}"
    fw = profile.preferences.get("framework", "")
    fw_line = f"- 框架：{fw}" if fw else ""
    test = profile.preferences.get("test_framework", "")
    test_line = f"- 测试：{test}" if test else ""

    # 沟通风格
    comm_style = profile.communication_style or "未设置"

    # 工具
    tools = ", ".join(profile.frequently_used_tools) if profile.frequently_used_tools else "未设置"

    # 行为模式
    pattern_lines = "\n".join(f"- {p}" for p in profile.patterns) if profile.patterns else "- 未设置"

    # 专业领域
    expertise_lines = "\n".join(f"- {e}" for e in profile.expertise) if profile.expertise else "- 未设置"

    # 项目偏好
    proj_lines = "\n".join(f"- {k}：{v}" for k, v in profile.project_preferences.items()) if profile.project_preferences else "- 未设置"

    return _TEMPLATE.format(
        name=profile.name or "未设置",
        pref_lines="\n".join(pref_lines),
        timezone=timezone,
        tech_lines=tech_lines,
        fw_line=fw_line,
        test_line=test_line,
        comm_style=comm_style,
        tools=tools,
        pattern_lines=pattern_lines,
        expertise_lines=expertise_lines,
        proj_lines=proj_lines,
    )


def save_user_md(profile: UserProfile, path: Path) -> None:
    """将画像保存为 USER.md。"""
    path.write_text(_format_user_md(profile), encoding="utf-8")


def load_user_md(path: Path) -> UserProfile:
    """从 USER.md 加载画像，文件不存在则返回空画像。"""
    if not path.exists():
        return UserProfile()

    text = path.read_text(encoding="utf-8")
    profile = UserProfile()

    # 简单解析
    section: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("- "):
            continue
        val = line[2:]
        if "：" in val:
            k, v = val.split("：", 1)
        elif ":" in val:
            k, v = val.split(":", 1)
        else:
            k, v = val, val

        if section == "基本信息":
            if k == "名称":
                profile.name = v
            elif k in ("语言偏好", "language"):
                profile.preferences["language"] = v
            elif k == "时区":
                profile.project_preferences["timezone"] = v
        elif section == "技术偏好":
            if k == "主要语言":
                profile.preferences["language"] = v
            elif k == "框架":
                profile.preferences["framework"] = v
            elif k == "测试":
                profile.preferences["test_framework"] = v
        elif section == "沟通风格":
            profile.communication_style = v
        elif section == "常用工具":
            profile.frequently_used_tools = [t.strip() for t in v.split(",") if t.strip()]
        elif section == "行为模式":
            profile.patterns.append(v)
        elif section == "专业领域":
            profile.expertise.append(v)
        elif section == "项目偏好":
            if "：" in val:
                pk, pv = val.split("：", 1)
                profile.project_preferences[pk] = pv

    return profile
