"""Context Layer - Hierarchical summary to prevent context bloat."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
import json
import hashlib


@dataclass
class ContextLevel0:
    """Level 0: Full raw output (stored externally, never in context)."""

    output_id: str  # Unique ID for retrieval
    content_type: str  # "tool_output", "thinking", "chat_history"
    content: str
    metadata: Dict = field(default_factory=dict)


@dataclass
class ContextLevel1:
    """Level 1: Working summary (passed to main agent via A2A Message Part)."""

    summary_id: str
    source_level0_ids: List[str]  # IDs of L0 items this summarizes
    summary: str  # What was done + brief result
    tool_calls: List[Dict] = field(default_factory=list)  # [{"tool": "bash", "command": "ls", "lines": 20}]
    metadata: Dict = field(default_factory=dict)


@dataclass
class ContextLevel2:
    """Level 2: Final conclusion (passed as Task Artifact)."""

    task_id: str
    conclusion: str  # One-sentence result
    success: bool
    key_metrics: Dict = field(default_factory=dict)  # {"files_created": 3, "bugs_fixed": 2}


class ContextLayer:
    """Manages hierarchical context compression."""

    def __init__(self, storage_path: str = "/tmp/opencortex_context"):
        self.storage_path = storage_path
        self._l0_cache: Dict[str, ContextLevel0] = {}

    def store_l0(self, content: str, content_type: str, metadata: Optional[dict] = None) -> str:
        """Store Level 0 content, return ID."""
        output_id = self._generate_id(content_type, content)

        l0 = ContextLevel0(
            output_id=output_id,
            content_type=content_type,
            content=content,
            metadata=metadata or {}
        )

        self._l0_cache[output_id] = l0

        # Persist to disk (Phase 2: implement actual storage)
        # For now, just in-memory

        return output_id

    def generate_l1(
        self,
        l0_ids: List[str],
        summary: str,
        tool_calls: Optional[List[Dict]] = None
    ) -> ContextLevel1:
        """Generate Level 1 summary from L0 items."""
        summary_id = self._generate_id("l1", f"{l0_ids}{summary}")

        return ContextLevel1(
            summary_id=summary_id,
            source_level0_ids=l0_ids,
            summary=summary,
            tool_calls=tool_calls or []
        )

    def generate_l2(
        self,
        task_id: str,
        conclusion: str,
        success: bool,
        key_metrics: Optional[dict] = None
    ) -> ContextLevel2:
        """Generate Level 2 final conclusion."""
        return ContextLevel2(
            task_id=task_id,
            conclusion=conclusion,
            success=success,
            key_metrics=key_metrics or {}
        )

    def retrieve_l0(self, output_id: str) -> Optional[ContextLevel0]:
        """Retrieve Level 0 content by ID (on-demand)."""
        return self._l0_cache.get(output_id)

    def _generate_id(self, content_type: str, content: str) -> str:
        """Generate unique ID."""
        hash_val = hashlib.md5(content.encode()).hexdigest()[:12]
        timestamp = int(datetime.timestamp(datetime.utcnow()))
        return f"{content_type}_{timestamp}_{hash_val}"


# Helper: Generate summary from tool output
def summarize_tool_output(tool_name: str, command: str, output: str, max_lines: int = 50) -> dict:
    """Summarize tool output for Level 1."""
    lines = output.strip().split("\n")
    total_lines = len(lines)

    if total_lines <= max_lines:
        # Full output is small enough, don't summarize
        return {
            "tool": tool_name,
            "command": command,
            "lines": total_lines,
            "truncated": False,
            "summary": output
        }

    # Large output, summarize
    head = "\n".join(lines[:max_lines // 2])
    tail = "\n".join(lines[-max_lines // 2:])
    skipped = total_lines - max_lines

    return {
        "tool": tool_name,
        "command": command,
        "lines": total_lines,
        "truncated": True,
        "summary": f"{head}\n\n... [skipped {skipped} lines] ...\n\n{tail}"
    }


# Import datetime
from datetime import datetime
