"""Generate SKILL.md files from skill definitions."""

from __future__ import annotations

from pathlib import Path

from opencortex.skills.types import SkillDefinition


class SkillGenerator:
    """生成 SKILL.md 文件。"""

    def generate_skill_md(self, skill: SkillDefinition) -> str:
        """生成 SKILL.md 内容。"""
        return skill.content

    def save_skill(self, skill: SkillDefinition, output_dir: Path) -> Path:
        """保存技能到目录。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        skill_dir = output_dir / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        path = skill_dir / "SKILL.md"
        path.write_text(self.generate_skill_md(skill), encoding="utf-8")
        return path
