"""Zellij pane backend for OpenCortex swarm visualization.

Provides a :class:`PaneBackend` implementation that creates and manages
Zellij terminal panes for teammate agents. When OpenCortex detects it is
running inside a Zellij session, teammate output is streamed to dedicated
panes so the user can observe all agents in real-time.

Architecture
------------
* :func:`is_inside_zellij` / :func:`is_zellij_available` — environment detection.
* :class:`ZellijPaneBackend` — implements :class:`PaneBackend` via ``zellij cli``.
* Auto-registered in :class:`BackendRegistry` when Zellij is detected.

CLI usage examples (``zellij cli``)::

    # Create a new pane (returns no ID, but we track via pane title)
    zellij cli new-pane -c "tail -f /dev/null" --name "agent-researcher"

    # List panes (parse output for pane IDs / names)
    zellij cli list-panes

    # Write to a pane by sending keys
    zellij cli write --pane-id <id> "text"

    # Close / kill a pane
    zellij cli close-pane --pane-id <id>
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from typing import Any

from opencortex.swarm.types import (
    BackendType,
    CreatePaneResult,
    PaneBackend,
    PaneBackendType,
    PaneId,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------


def is_inside_zellij() -> bool:
    """Return True if the current process is inside a Zellij session.

    Zellij sets ``$ZELLIJ`` (the socket path) for every session.
    """
    return bool(os.environ.get("ZELLIJ"))


def is_zellij_available() -> bool:
    """Return True if the ``zellij`` binary exists on PATH."""
    return shutil.which("zellij") is not None


# ---------------------------------------------------------------------------
# ZellijPaneBackend
# ---------------------------------------------------------------------------


class ZellijPaneBackend:
    """Pane management via the Zellij CLI.

    Implements the :class:`PaneBackend` protocol. Uses ``zellij cli``
    subcommands to create, write to, and close panes for teammate agents.

    Because Zellij's ``new-pane`` command does not return a pane ID, we
    identify panes by their unique title (``"oc:<agent_id>"``).  The pane
    is created with a persistent ``tail -f /dev/null`` so it stays alive
    even when there is no active output.  Agent output is forwarded by
    writing to a temporary file and using ``zellij cli write`` or by
    running a command that cats the output file.

    Limitations
    -----------
    * ``zellij cli`` does not expose a stable pane-ID API as of 0.41.
      We work around this by querying ``list-panes`` and matching on titles.
    * ``write_to_pane`` uses ``zellij cli write-chars`` which simulates
      typing — this may be slow for very large outputs.
    """

    type: BackendType = "zellij"
    _pane_backend_type: PaneBackendType = "zellij"

    _LOG_DIR = "/tmp/opencortex_panes"

    def __init__(self) -> None:
        self._panes: dict[PaneId, dict[str, Any]] = {}
        # Maps agent_id -> pane_id for quick lookup
        self._agent_panes: dict[str, PaneId] = {}
        self._is_first_teammate: bool = True
        os.makedirs(self._LOG_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # PaneBackend protocol — properties
    # ------------------------------------------------------------------

    @property
    def display_name(self) -> str:
        return "Zellij"

    @property
    def supports_hide_show(self) -> bool:
        # Zellij doesn't have a clean hide/show like tmux break-pane
        return False

    # ------------------------------------------------------------------
    # PaneBackend protocol — availability
    # ------------------------------------------------------------------

    async def is_available(self) -> bool:
        return is_zellij_available()

    async def is_running_inside(self) -> bool:
        return is_inside_zellij()

    # ------------------------------------------------------------------
    # PaneBackend protocol — pane lifecycle
    # ------------------------------------------------------------------

    async def create_teammate_pane_in_swarm_view(
        self,
        name: str,
        color: str | None = None,
    ) -> CreatePaneResult:
        """Create a new Zellij pane for a teammate.

        The pane runs ``tail -f /dev/null`` to stay alive and is titled
        ``oc:<name>`` for later identification.

        Args:
            name: Teammate display name (used as pane title).
            color: Ignored (Zellij does not support per-pane colors yet).

        Returns:
            :class:`CreatePaneResult` with the pane identifier.
        """
        is_first = self._is_first_teammate
        pane_title = f"oc:{name}"
        pane_id = pane_title  # Use title as stable ID

        # Create a log file for this agent's output
        safe_name = name.replace("/", "_").replace(" ", "_")
        log_path = os.path.join(self._LOG_DIR, f"agent_{safe_name}.log")
        # Touch the file so tail -f works immediately
        with open(log_path, "w") as f:
            pass

        # Build the command: tail -f on the log file keeps pane alive and shows output
        cmd = f"tail -f {log_path}"

        # Determine split direction
        direction = "Down" if is_first else "Right"

        zellij_cmd = [
            "zellij", "cli", "new-pane",
            "-c", cmd,
            "--name", pane_title,
            "-d", direction,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *zellij_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
        except FileNotFoundError:
            logger.error("[ZellijBackend] zellij binary not found")
            raise RuntimeError("zellij is not installed")

        self._panes[pane_id] = {
            "name": name,
            "title": pane_title,
            "color": color,
            "is_first": is_first,
            "status": "running",
            "log_path": log_path,
        }
        self._agent_panes[name] = pane_id

        if is_first:
            self._is_first_teammate = False

        logger.info(
            "[ZellijBackend] Created pane %s for %s (first=%s)",
            pane_id, name, is_first,
        )
        return CreatePaneResult(pane_id=pane_id, is_first_teammate=is_first)

    async def send_command_to_pane(
        self,
        pane_id: PaneId,
        command: str,
        *,
        use_external_session: bool = False,
    ) -> None:
        """Send a command to the given pane.

        Uses ``zellij cli run --pane-id`` or falls back to writing
        chars via ``write-chars``.
        """
        # First, kill the existing tail process, then run the actual command
        # We use write-chars to send Ctrl+C then the command
        try:
            # Send Ctrl+C to stop tail, then the command
            await self._write_chars(pane_id, "\x03")  # Ctrl+C
            await asyncio.sleep(0.1)
            await self._write_chars(pane_id, command + "\n")
        except Exception as exc:
            logger.warning("[ZellijBackend] send_command_to_pane failed: %s", exc)

    async def set_pane_border_color(
        self,
        pane_id: PaneId,
        color: str,
        *,
        use_external_session: bool = False,
    ) -> None:
        """Set pane border color — not supported by Zellij CLI yet."""
        logger.debug("[ZellijBackend] set_pane_border_color: not supported, ignoring")

    async def set_pane_title(
        self,
        pane_id: PaneId,
        name: str,
        color: str | None = None,
        *,
        use_external_session: bool = False,
    ) -> None:
        """Update the stored title for a pane.

        Zellij does not support renaming panes via CLI, so we update
        our internal tracking only.
        """
        if pane_id in self._panes:
            self._panes[pane_id]["title"] = f"oc:{name}"
            self._panes[pane_id]["name"] = name

    async def enable_pane_border_status(
        self,
        window_target: str | None = None,
        *,
        use_external_session: bool = False,
    ) -> None:
        """Enable pane border status — Zellij shows names by default."""
        pass

    async def rebalance_panes(
        self,
        window_target: str,
        has_leader: bool,
    ) -> None:
        """Rebalance panes — Zellij auto-balances by default."""
        pass

    async def kill_pane(
        self,
        pane_id: PaneId,
        *,
        use_external_session: bool = False,
    ) -> bool:
        """Kill / close a Zellij pane.

        Tries ``zellij cli close-pane`` with the pane title. Falls back
        to sending ``exit`` via write-chars.
        """
        meta = self._panes.get(pane_id)
        if meta is None:
            return False

        try:
            # Try to find the actual numeric pane ID via list-panes
            numeric_id = await self._find_pane_id_by_title(meta["title"])
            if numeric_id:
                proc = await asyncio.create_subprocess_exec(
                    "zellij", "cli", "close-pane", "--pane-id", numeric_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
            else:
                # Fallback: send exit command
                await self._write_chars(pane_id, "exit\n")
        except Exception as exc:
            logger.warning("[ZellijBackend] kill_pane failed: %s", exc)
            return False

        # Clean up tracking and log file
        name = meta.get("name")
        log_path = meta.get("log_path")
        self._panes.pop(pane_id, None)
        if name:
            self._agent_panes.pop(name, None)
        if log_path:
            try:
                os.remove(log_path)
            except OSError:
                pass

        logger.info("[ZellijBackend] Killed pane %s", pane_id)
        return True

    async def hide_pane(
        self,
        pane_id: PaneId,
        *,
        use_external_session: bool = False,
    ) -> bool:
        """Hide pane — not supported by Zellij."""
        return False

    async def show_pane(
        self,
        pane_id: PaneId,
        target_window_or_pane: str,
        *,
        use_external_session: bool = False,
    ) -> bool:
        """Show pane — not supported by Zellij."""
        return False

    def list_panes(self) -> list[PaneId]:
        """Return all tracked pane IDs."""
        return list(self._panes.keys())

    # ------------------------------------------------------------------
    # Extended API — output streaming
    # ------------------------------------------------------------------

    async def write_output(
        self,
        agent_name: str,
        text: str,
    ) -> None:
        """Write output text to the pane belonging to *agent_name*.

        Appends text directly to the agent's log file. The pane is running
        ``tail -f`` on this file, so the output appears automatically.
        """
        pane_id = self._agent_panes.get(agent_name)
        if pane_id is None:
            logger.debug(
                "[ZellijBackend] No pane for agent %s, skipping output",
                agent_name,
            )
            return

        meta = self._panes.get(pane_id)
        log_path = meta.get("log_path") if meta else None
        if log_path:
            try:
                with open(log_path, "a") as f:
                    f.write(text)
                    f.flush()
            except OSError as exc:
                logger.warning("[ZellijBackend] Failed to write log file %s: %s", log_path, exc)
        else:
            # Fallback to write-chars if no log path
            await self._write_chars(pane_id, text)

    async def mark_completed(
        self,
        agent_name: str,
        summary: str = "",
    ) -> None:
        """Mark the pane for *agent_name* as completed.

        Writes a completion banner and updates internal status.
        """
        pane_id = self._agent_panes.get(agent_name)
        if pane_id is None:
            return

        if pane_id in self._panes:
            self._panes[pane_id]["status"] = "completed"

        # Write completion banner to log file
        banner = f"\n\n✅ Agent '{agent_name}' completed."
        if summary:
            banner += f"\n📋 {summary}"
        banner += "\n"
        meta = self._panes.get(pane_id)
        log_path = meta.get("log_path") if meta else None
        if log_path:
            try:
                with open(log_path, "a") as f:
                    f.write(banner)
                    f.flush()
            except OSError:
                pass

    def get_pane_status(self, agent_name: str) -> str | None:
        """Return the status of the pane for *agent_name*."""
        pane_id = self._agent_panes.get(agent_name)
        if pane_id is None:
            return None
        meta = self._panes.get(pane_id)
        return meta.get("status") if meta else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _write_chars(self, pane_id: PaneId, text: str) -> None:
        """Write characters to a pane via ``zellij cli write-chars``.

        If a numeric pane ID cannot be determined, falls back to writing
        to the pane identified by title.
        """
        meta = self._panes.get(pane_id)
        title = meta["title"] if meta else pane_id

        numeric_id = await self._find_pane_id_by_title(title)

        cmd = ["zellij", "cli", "write-chars"]
        if numeric_id:
            cmd.extend(["--pane-id", numeric_id])
        cmd.append(text)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
        except Exception as exc:
            logger.debug("[ZellijBackend] write-chars failed: %s", exc)

    async def _find_pane_id_by_title(self, title: str) -> str | None:
        """Parse ``zellij cli list-panes`` to find the numeric ID for *title*.

        Returns the pane ID as a string, or None if not found.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "zellij", "cli", "list-panes",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace")

            # Parse output — format varies by Zellij version
            # Look for lines containing our title
            for line in output.splitlines():
                if title in line:
                    # Try to extract numeric ID (first field in many versions)
                    parts = line.split()
                    if parts:
                        # First part is often the pane ID
                        candidate = parts[0].strip("()")
                        if candidate.isdigit():
                            return candidate
            return None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Convenience singleton
# ---------------------------------------------------------------------------

_zellij_backend: ZellijPaneBackend | None = None


def get_zellij_backend() -> ZellijPaneBackend:
    """Return the process-wide ZellijPaneBackend singleton."""
    global _zellij_backend
    if _zellij_backend is None:
        _zellij_backend = ZellijPaneBackend()
    return _zellij_backend
