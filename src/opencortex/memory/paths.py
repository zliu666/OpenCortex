"""Paths for persistent project memory."""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from opencortex.config.paths import get_data_dir


def get_project_memory_dir(cwd: str | Path) -> Path:
    """Return the persistent memory directory for a project."""
    path = Path(cwd).resolve()
    digest = sha1(str(path).encode("utf-8")).hexdigest()[:12]
    memory_dir = get_data_dir() / "memory" / f"{path.name}-{digest}"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


def get_memory_entrypoint(cwd: str | Path) -> Path:
    """Return the project memory entrypoint file."""
    return get_project_memory_dir(cwd) / "MEMORY.md"


def get_global_memory_dir() -> Path:
    """Return the global memory directory for the user (not project-specific)."""
    memory_dir = get_data_dir() / "memory" / "_global"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


def get_global_memory_entrypoint() -> Path:
    """Return the global memory entrypoint file."""
    return get_global_memory_dir() / "MEMORY.md"


def _is_temp_cwd(cwd: str | Path) -> bool:
    """Return True if cwd looks like a temporary or non-project directory."""
    path = Path(cwd).resolve()
    name = path.name.lower()
    parts = [p.lower() for p in path.parts]
    return (
        name.startswith("tmp")
        or "/tmp" in str(path)
        or name == "desktop"
        or name == "downloads"
        or name == "home"
    )
