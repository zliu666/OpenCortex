"""Memory prompt helpers."""

from __future__ import annotations

from pathlib import Path

from opencortex.memory.paths import (
    get_global_memory_dir,
    get_global_memory_entrypoint,
    get_memory_entrypoint,
    get_project_memory_dir,
    _is_temp_cwd,
)


def _read_entrypoint(entrypoint: Path, max_lines: int) -> list[str] | None:
    """Read up to *max_lines* from an entrypoint file, or return None."""
    if not entrypoint.exists():
        return None
    content_lines = entrypoint.read_text(encoding="utf-8").splitlines()[:max_lines]
    return content_lines if content_lines else None


def load_memory_prompt(cwd: str | Path, *, max_entrypoint_lines: int = 200) -> str | None:
    """Return the memory prompt section, combining global and project memories.

    Global memory is always loaded.  Project-specific memory is also loaded
    unless *cwd* looks like a temporary / non-project directory.
    """
    project_dir = get_project_memory_dir(cwd)
    global_dir = get_global_memory_dir()
    use_project = not _is_temp_cwd(cwd)

    lines = [
        "# Memory",
        f"- Global memory directory: {global_dir}",
    ]
    if use_project:
        lines.append(f"- Project memory directory: {project_dir}")
    lines.extend([
        "- Use these directories to store durable user or project context that should survive future sessions.",
        "- Prefer concise topic files plus an index entry in MEMORY.md.",
    ])

    # Always load global memory
    global_entry = get_global_memory_entrypoint()
    global_content = _read_entrypoint(global_entry, max_entrypoint_lines)
    if global_content:
        lines.extend(["", "## Global MEMORY.md", "```md", *global_content, "```"])

    # Optionally load project-specific memory
    if use_project:
        project_entry = get_memory_entrypoint(cwd)
        project_content = _read_entrypoint(project_entry, max_entrypoint_lines)
        if project_content:
            lines.extend(["", "## Project MEMORY.md", "```md", *project_content, "```"])
        else:
            lines.extend(["", "## Project MEMORY.md", "(not created yet)"])
    elif not global_content:
        lines.extend(["", "## Global MEMORY.md", "(not created yet)"])

    return "\n".join(lines)
