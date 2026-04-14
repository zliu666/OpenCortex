"""Global process registry for cleanup on exit."""
from __future__ import annotations

import atexit
import logging
import os
import signal
import sys

log = logging.getLogger(__name__)

_registered_pids: set[int] = set()


def register_pid(pid: int) -> None:
    """Register a child process PID for cleanup."""
    _registered_pids.add(pid)


def unregister_pid(pid: int) -> None:
    """Unregister a PID after normal cleanup."""
    _registered_pids.discard(pid)


def get_registered_pids() -> set[int]:
    """Return all registered PIDs."""
    return set(_registered_pids)


def cleanup_all() -> None:
    """Kill all registered child processes. Called on exit."""
    for pid in list(_registered_pids):
        try:
            if os.path.exists(f"/proc/{pid}"):
                os.kill(pid, signal.SIGTERM)
                log.debug("Sent SIGTERM to child process %d", pid)
        except ProcessLookupError:
            pass
        except PermissionError:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        except Exception as exc:
            log.warning("Failed to cleanup process %d: %s", pid, exc)
        _registered_pids.discard(pid)


def setup_cleanup_handlers() -> None:
    """Register atexit and signal handlers for process cleanup."""
    atexit.register(cleanup_all)
    signal.signal(signal.SIGTERM, lambda s, f: (cleanup_all(), sys.exit(0)))
    signal.signal(signal.SIGINT, lambda s, f: (cleanup_all(), sys.exit(0)))
