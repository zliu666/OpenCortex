"""Subprocess-based TeammateExecutor implementation."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from opencortex.swarm.spawn_utils import (
    build_inherited_cli_flags,
    build_inherited_env_vars,
    get_teammate_command,
)
from opencortex.swarm.types import (
    BackendType,
    SpawnResult,
    TeammateMessage,
    TeammateSpawnConfig,
)
from opencortex.swarm.worktree import WorktreeManager
from opencortex.swarm.worktree import _run_git  # noqa: F401  # Private function, used for isolation
from opencortex.tasks.manager import get_task_manager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SubprocessBackend:
    """TeammateExecutor that runs each teammate as a separate subprocess.

    Uses the existing :class:`~opencortex.tasks.manager.BackgroundTaskManager`
    to create and manage the child processes, communicating via stdin/stdout.
    """

    type: BackendType = "subprocess"

    # Maps agent_id -> task_id for tracking live agents
    _agent_tasks: dict[str, str]

    # Maps agent_id -> worktree_slug for cleanup
    _agent_worktrees: dict[str, str]

    # WorktreeManager instance for creating/removing worktrees
    _worktree_manager: WorktreeManager

    def __init__(self) -> None:
        self._agent_tasks = {}
        self._agent_worktrees = {}
        self._worktree_manager = WorktreeManager()

    def is_available(self) -> bool:
        """Subprocess backend is always available."""
        return True

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        """Spawn a new teammate as a subprocess via the task manager.

        Builds the appropriate CLI command and creates a ``local_agent`` task
        that accepts the initial prompt via stdin.

        If the config does not specify a worktree_path, a git worktree is
        automatically created to provide filesystem isolation for the agent.
        """
        agent_id = f"{config.name}@{config.team}"

        # Determine working directory: use explicit worktree_path if provided,
        # otherwise create a worktree for isolation
        worktree_path = config.worktree_path
        worktree_slug: str | None = None

        if worktree_path is None:
            # Find git root for isolation
            repo_path = await self._find_git_root(Path(config.cwd))
            if repo_path:
                # Create a worktree for this agent
                worktree_slug = f"{config.team}/{config.name}"
                try:
                    worktree_info = await self._worktree_manager.create_worktree(
                        repo_path=repo_path,
                        slug=worktree_slug,
                        agent_id=agent_id,
                    )
                    worktree_path = str(worktree_info.path)
                    self._agent_worktrees[agent_id] = worktree_slug
                    logger.debug("Created worktree %s for agent %s", worktree_path, agent_id)
                except Exception as exc:
                    logger.warning(
                        "Failed to create worktree for agent %s, using original cwd: %s",
                        agent_id,
                        exc,
                    )
                    worktree_path = config.cwd
            else:
                # Not in a git repo, use original cwd
                worktree_path = config.cwd

        cwd = worktree_path or config.cwd

        flags = build_inherited_cli_flags(
            model=config.model,
            plan_mode_required=config.plan_mode_required,
        )
        extra_env = build_inherited_env_vars()
        if config.execution_provider_env:
            extra_env.update(config.execution_provider_env)

        # Build environment export prefix for shell invocation
        env_prefix = " ".join(f"{k}={v!r}" for k, v in extra_env.items())

        teammate_cmd = get_teammate_command()
        if teammate_cmd.endswith("python") or teammate_cmd.endswith("python3") or "/python" in teammate_cmd:
            cmd_parts = [teammate_cmd, "-m", "opencortex", "--backend-only"] + flags
        else:
            cmd_parts = [teammate_cmd, "--backend-only"] + flags
        command = f"{env_prefix} {' '.join(cmd_parts)}" if env_prefix else " ".join(cmd_parts)

        manager = get_task_manager()
        try:
            record = await manager.create_agent_task(
                prompt=config.prompt,
                description=f"Teammate: {agent_id}",
                cwd=cwd,
                task_type="in_process_teammate",
                model=config.model,
                command=command,
            )
        except Exception as exc:
            logger.error("Failed to spawn teammate %s: %s", agent_id, exc)
            # Clean up worktree if we created one
            if worktree_slug and worktree_slug in self._agent_worktrees:
                await self._cleanup_worktree(agent_id, worktree_slug)
            return SpawnResult(
                task_id="",
                agent_id=agent_id,
                backend_type=self.type,
                success=False,
                error=str(exc),
            )

        self._agent_tasks[agent_id] = record.id
        logger.debug("Spawned teammate %s as task %s", agent_id, record.id)
        return SpawnResult(
            task_id=record.id,
            agent_id=agent_id,
            backend_type=self.type,
        )

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None:
        """Send a message to a running teammate via its stdin pipe.

        The message is serialised as a single JSON line so the teammate can
        distinguish structured messages from plain prompts.
        """
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            raise ValueError(f"No active subprocess for agent {agent_id!r}")

        payload = {
            "text": message.text,
            "from": message.from_agent,
            "timestamp": message.timestamp,
        }
        if message.color:
            payload["color"] = message.color
        if message.summary:
            payload["summary"] = message.summary

        manager = get_task_manager()
        await manager.write_to_task(task_id, json.dumps(payload))
        logger.debug("Sent message to %s (task %s)", agent_id, task_id)

    async def shutdown(self, agent_id: str, *, force: bool = False) -> bool:
        """Terminate a subprocess teammate.

        Args:
            agent_id: The agent to terminate.
            force: Ignored for subprocess backend; always sends SIGTERM then
                   SIGKILL after a brief wait (handled by the task manager).

        Returns:
            True if the task was found and terminated.
        """
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            logger.warning("shutdown() called for unknown agent %s", agent_id)
            return False

        manager = get_task_manager()
        try:
            await manager.stop_task(task_id)
        except ValueError as exc:
            logger.debug("stop_task for %s: %s", task_id, exc)
            # Task may have already finished — still clean up mapping
        finally:
            self._agent_tasks.pop(agent_id, None)

        # Clean up worktree if one was created for this agent
        worktree_slug = self._agent_worktrees.pop(agent_id, None)
        if worktree_slug:
            await self._cleanup_worktree(agent_id, worktree_slug)

        logger.debug("Shut down teammate %s (task %s)", agent_id, task_id)
        return True

    async def _find_git_root(self, path: Path) -> Path | None:
        """Find the git repository root for the given path.

        Returns None if not inside a git repository.
        """
        try:
            code, git_root, _ = await _run_git("rev-parse", "--show-toplevel", cwd=path)
            if code == 0 and git_root:
                return Path(git_root).resolve()
        except Exception:
            pass
        return None

    async def _cleanup_worktree(self, agent_id: str, worktree_slug: str) -> None:
        """Clean up the worktree for the given agent.

        Errors during cleanup are logged but do not fail the shutdown.
        """
        try:
            removed = await self._worktree_manager.remove_worktree(worktree_slug)
            if removed:
                logger.debug("Cleaned up worktree %s for agent %s", worktree_slug, agent_id)
            else:
                logger.debug("Worktree %s not found for cleanup", worktree_slug)
        except Exception as exc:
            logger.warning(
                "Failed to clean up worktree %s for agent %s: %s",
                worktree_slug,
                agent_id,
                exc,
            )

    def get_task_id(self, agent_id: str) -> str | None:
        """Return the task manager task ID for a given agent, if known."""
        return self._agent_tasks.get(agent_id)
