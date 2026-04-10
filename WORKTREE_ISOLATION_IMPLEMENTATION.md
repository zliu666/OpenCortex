# Worker Agent Worktree Isolation - Implementation Summary

## Overview

Implemented automatic git worktree isolation for worker agents spawned via the SubprocessBackend in OpenCortex. This provides filesystem isolation to prevent conflicts when multiple agents work on the same repository.

## Problem Statement

Prior to this implementation:
- Multiple worker agents shared the same working directory
- File system conflicts could occur when agents wrote to the same files
- Environment variables could be polluted between agents
- No automatic cleanup of agent workspaces

## Solution

Modified `SubprocessBackend` to automatically create git worktrees for each spawned agent when running inside a git repository.

### Key Changes

#### 1. Modified File: `src/opencortex/swarm/subprocess_backend.py`

**Added attributes:**
- `_agent_worktrees`: Dict mapping agent_id to worktree_slug for tracking
- `_worktree_manager`: Instance of `WorktreeManager` for creating/removing worktrees

**Modified methods:**

`__init__()`:
- Initialize worktree tracking dictionaries
- Create WorktreeManager instance

`spawn()`:
- Detect if spawning in a git repository using `_find_git_root()`
- If in a git repo and no explicit `worktree_path` is provided:
  - Create a worktree with slug `{team}/{agent_name}`
  - Track the worktree in `_agent_worktrees`
  - Use the worktree path as the agent's working directory
- If not in a git repo or worktree creation fails:
  - Fall back to the original `cwd`
  - Log a warning when worktree creation fails
- Clean up worktree on spawn failure

`shutdown()`:
- Clean up the worktree when an agent is shut down
- Remove the worktree from tracking
- Gracefully handle cleanup failures

**New methods:**

`_find_git_root(path: Path) -> Path | None`:
- Use `git rev-parse --show-toplevel` to find the git repository root
- Return None if not inside a git repository

`_cleanup_worktree(agent_id: str, worktree_slug: str) -> None`:
- Remove the worktree using WorktreeManager
- Log success or failure
- Errors are logged but don't fail the shutdown operation

#### 2. New Test File: `tests/test_swarm/test_subprocess_backend_worktree.py`

Created comprehensive tests covering:
- Worktree creation in git repositories
- Explicit worktree_path usage
- Fallback to original cwd when not in a git repo
- Graceful handling of worktree creation failures
- Worktree cleanup on shutdown
- Multiple agents with separate worktrees
- Git root detection
- Agent task tracking

## Behavior

### Automatic Worktree Creation

When an agent is spawned in a git repository:
1. The git repository root is detected
2. A worktree is created at `~/.opencortex/worktrees/{team}+{agent_name}/`
3. The agent runs in this isolated worktree
4. The worktree is automatically cleaned up when the agent shuts down

Example:
```python
# Spawning an agent in /mnt/f/my-agent/opencortex (a git repo)
config = TeammateSpawnConfig(
    name="worker",
    team="test-team",
    prompt="do work",
    cwd="/mnt/f/my-agent/opencortex",
    parent_session_id="main",
)

# Result:
# - Worktree created at ~/.opencortex/worktrees/test-team+worker/
# - Agent runs in the worktree, not the original directory
# - Worktree removed when agent shuts down
```

### Explicit Worktree Path

If `config.worktree_path` is set explicitly, it is used directly and no automatic worktree is created:

```python
config.worktree_path = "/custom/path"
# Agent runs in /custom/path, no worktree management
```

### Non-Git Repositories

When spawning outside a git repository, the original `cwd` is used and no worktree is created.

### Error Handling

- Worktree creation failures are logged but don't fail the spawn
- The agent falls back to the original `cwd`
- Worktree cleanup failures are logged but don't fail the shutdown

## Benefits

1. **Filesystem Isolation**: Each agent has its own working directory, preventing conflicts
2. **Automatic Cleanup**: Worktrees are removed when agents shut down
3. **Git Integration**: Uses git worktrees for efficient isolation without full repo copies
4. **Backwards Compatible**: Existing code continues to work; worktrees are created automatically when possible
5. **Graceful Degradation**: Falls back to original behavior when worktrees can't be created

## Testing

All existing tests pass:
- `tests/test_swarm/` - 143 tests passed

New tests added:
- `tests/test_swarm/test_subprocess_backend_worktree.py` - 12 tests covering all scenarios

Run tests with:
```bash
cd /mnt/f/my-agent/opencortex
.venv/bin/python -m pytest tests/test_swarm/ -v
```

## Future Enhancements

Potential improvements:
1. Worktree reuse for agents with the same team/name (instead of always creating new)
2. Configurable worktree base directory
3. Persistent worktrees for long-running agents
4. Worktree statistics and monitoring
5. Cleanup of stale worktrees from crashed agents

## Files Modified

1. `src/opencortex/swarm/subprocess_backend.py` - Added worktree isolation logic
2. `tests/test_swarm/test_subprocess_backend_worktree.py` - New comprehensive tests
