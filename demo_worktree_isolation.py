#!/usr/bin/env python3
"""
Demonstration script for Worker Agent Worktree Isolation.

This script shows how worker agents are automatically isolated using git worktrees.
"""

import asyncio
from pathlib import Path
from opencortex.swarm.subprocess_backend import SubprocessBackend
from opencortex.swarm.types import TeammateSpawnConfig


async def demo_worktree_isolation():
    """Demonstrate worktree isolation for worker agents."""

    print("=" * 70)
    print("Worker Agent Worktree Isolation Demo")
    print("=" * 70)
    print()

    # Create backend
    backend = SubprocessBackend()
    print("✓ Created SubprocessBackend")
    print()

    # Get the current git repository (assuming we're in the opencortex repo)
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print("❌ Not in a git repository. Demo requires a git repo.")
        return

    repo_root = Path(result.stdout.strip())
    print(f"📁 Working in git repository: {repo_root}")
    print()

    # Demonstrate git root detection
    print("1. Testing git root detection:")
    git_root = await backend._find_git_root(repo_root)
    print(f"   ✓ Detected git root: {git_root}")
    print()

    # Show what worktrees would be created
    print("2. Simulating agent spawning:")
    test_agents = [
        ("worker", "team-a", "Write documentation"),
        ("tester", "team-a", "Run tests"),
        ("reviewer", "team-b", "Review PR"),
    ]

    for name, team, prompt in test_agents:
        slug = f"{team}/{name}"
        worktree_path = backend._worktree_manager.base_dir / slug.replace("/", "+")
        print(f"   - Agent: {name}@{team}")
        print(f"     Worktree slug: {slug}")
        print(f"     Worktree path: {worktree_path}")
        print(f"     Task: {prompt}")
        print()

    # List existing worktrees (if any)
    print("3. Checking existing worktrees:")
    worktrees = await backend._worktree_manager.list_worktrees()
    if worktrees:
        print(f"   Found {len(worktrees)} existing worktrees:")
        for wt in worktrees:
            print(f"   - {wt.slug} at {wt.path}")
    else:
        print("   No existing worktrees found")
    print()

    print("=" * 70)
    print("Demo complete!")
    print()
    print("Key features:")
    print("  ✓ Automatic worktree creation for agents in git repos")
    print("  ✓ Each agent gets isolated filesystem access")
    print("  ✓ Automatic cleanup on agent shutdown")
    print("  ✓ Graceful fallback when worktrees can't be created")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(demo_worktree_isolation())
