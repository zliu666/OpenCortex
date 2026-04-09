"""A2A Task Executor - Integrates QueryEngine with A2A Task lifecycle."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional, Callable, AsyncIterator

from opencortex.a2a.task_manager import TaskManager, TaskStatus
from opencortex.a2a.context_layer import ContextLayer, summarize_tool_output
from opencortex.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from opencortex.ui.runtime import (
    RuntimeBundle,
    build_runtime,
    close_runtime,
    handle_line,
    start_runtime,
)

logger = logging.getLogger("opencortex.a2a.executor")


class TaskExecutor:
    """Executes A2A tasks using QueryEngine."""

    def __init__(
        self,
        task_manager: TaskManager,
        context_layer: ContextLayer,
        cwd: str = ".",
    ):
        self.task_manager = task_manager
        self.context_layer = context_layer
        self.cwd = cwd
        self._active_bundles: dict[str, RuntimeBundle] = {}
        self._cancelled_tasks: set[str] = set()

    async def execute_task(
        self,
        task_id: str,
        prompt: str,
        model: str = "glm-4-flash",
        max_turns: int | None = None,
        temperature: float = 0.7,
    ) -> dict:
        """Execute a task synchronously, return Level 1 summary."""
        task = self.task_manager.get_task(task_id)
        if not task:
            return {"error": "Task not found"}

        # Mark working
        self.task_manager.update_task(task_id, status=TaskStatus.WORKING)

        bundle = None
        try:
            bundle = await build_runtime(
                prompt=prompt,
                model=model,
                cwd=self.cwd,
                max_turns=max_turns,
                enforce_max_turns=True,
                permission_prompt=lambda tool, reason: asyncio.coroutine(lambda: True)(),
                ask_user_prompt=lambda question: asyncio.coroutine(lambda: "")(),
            )
            await start_runtime(bundle)

            # Store bundle for potential cancellation
            self._active_bundles[task_id] = bundle

            # Collect events
            collected_text = ""
            tool_calls_raw = []
            l0_ids = []

            async def _print_system(message: str) -> None:
                pass

            async def _render_event(event: StreamEvent) -> None:
                nonlocal collected_text
                if isinstance(event, AssistantTextDelta):
                    collected_text += event.text
                elif isinstance(event, ToolExecutionStarted):
                    tool_info = {
                        "tool": event.tool_name,
                        "command": str(event.tool_input)[:200] if event.tool_input else "",
                    }
                    tool_calls_raw.append(tool_info)
                elif isinstance(event, ToolExecutionCompleted):
                    # Store L0 output
                    output = event.output if isinstance(event.output, str) else str(event.output)
                    if len(output) > 100:
                        l0_id = self.context_layer.store_l0(
                            content=output,
                            content_type="tool_output",
                            metadata={"tool": event.tool_name, "is_error": event.is_error}
                        )
                        l0_ids.append(l0_id)
                        # Update tool call with truncated summary
                        for tc in reversed(tool_calls_raw):
                            if tc["tool"] == event.tool_name and "output" not in tc:
                                summary = summarize_tool_output(
                                    event.tool_name,
                                    str(event.tool_input) or "",
                                    output
                                )
                                tc["output_lines"] = summary["lines"]
                                tc["truncated"] = summary["truncated"]
                                break

            async def _clear_output() -> None:
                pass

            # Check cancellation before execution
            if task_id in self._cancelled_tasks:
                self.task_manager.update_task(task_id, status=TaskStatus.CANCELLED)
                return {"error": "cancelled"}

            await handle_line(
                bundle,
                prompt,
                print_system=_print_system,
                render_event=_render_event,
                clear_output=_clear_output,
            )

            # Check cancellation after execution
            if task_id in self._cancelled_tasks:
                self.task_manager.update_task(task_id, status=TaskStatus.CANCELLED)
                return {"error": "cancelled"}

            # Generate Level 1 summary
            tool_summaries = []
            for tc in tool_calls_raw:
                tool_summaries.append({
                    "tool": tc["tool"],
                    "command": tc.get("command", "")[:100],
                    "lines": tc.get("output_lines", 0),
                    "truncated": tc.get("truncated", False),
                })

            l1 = self.context_layer.generate_l1(
                l0_ids=l0_ids,
                summary=collected_text.strip()[:500] if collected_text else "(no output)",
                tool_calls=tool_summaries
            )

            # Generate Level 2 conclusion
            l2 = self.context_layer.generate_l2(
                task_id=task_id,
                conclusion=collected_text.strip()[:200] if collected_text else "(no output)",
                success=True,
                key_metrics={
                    "tool_calls": len(tool_calls_raw),
                    "response_chars": len(collected_text),
                    "l0_stored": len(l0_ids),
                }
            )

            # Extract usage
            total = bundle.engine.total_usage
            input_tokens = getattr(total, "input_tokens", 0) if total else 0
            output_tokens = getattr(total, "output_tokens", 0) if total else 0

            # Update task
            self.task_manager.update_task(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                response=l1.summary,
                artifact_id=task_id,  # L2 is the artifact
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

            return {
                "status": "completed",
                "l1_summary": l1.summary,
                "l2_conclusion": l2.conclusion,
                "l0_ids": l0_ids,
                "tool_calls": len(tool_calls_raw),
                "usage": {"input": input_tokens, "output": output_tokens},
            }

        except Exception as e:
            logger.exception("Task execution failed: %s", task_id)
            self.task_manager.update_task(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error_message=str(e)[:500]
            )
            return {"status": "failed", "error": str(e)[:500]}

        finally:
            if bundle and task_id in self._active_bundles:
                del self._active_bundles[task_id]
                await close_runtime(bundle)

    def cancel_execution(self, task_id: str) -> bool:
        """Cancel a running task."""
        self._cancelled_tasks.add(task_id)
        self.task_manager.cancel_task(task_id)
        # Close bundle if active
        bundle = self._active_bundles.pop(task_id, None)
        if bundle:
            # Force close
            import asyncio
            asyncio.create_task(close_runtime(bundle))
        return True

    async def stream_task(
        self,
        task_id: str,
        prompt: str,
        model: str = "glm-4-flash",
        max_turns: int | None = None,
    ) -> AsyncIterator[dict]:
        """Execute a task and yield SSE events for streaming."""
        task = self.task_manager.get_task(task_id)
        if not task:
            yield {"event": "error", "data": json.dumps({"error": "Task not found"})}
            return

        self.task_manager.update_task(task_id, status=TaskStatus.WORKING)

        bundle = None
        try:
            bundle = await build_runtime(
                prompt=prompt,
                model=model,
                cwd=self.cwd,
                max_turns=max_turns,
                enforce_max_turns=True,
                permission_prompt=lambda tool, reason: asyncio.coroutine(lambda: True)(),
                ask_user_prompt=lambda question: asyncio.coroutine(lambda: "")(),
            )
            await start_runtime(bundle)
            self._active_bundles[task_id] = bundle

            collected_text = ""
            tool_count = 0

            async def _print_system(message: str) -> None:
                pass

            async def _clear_output() -> None:
                pass

            # We can't use handle_line for streaming because render_event is sync
            # Instead, directly use engine.submit_message
            settings = bundle.current_settings()
            from opencortex.prompts import build_runtime_system_prompt
            bundle.engine.set_system_prompt(
                build_runtime_system_prompt(settings, cwd=self.cwd, latest_user_prompt=prompt)
            )

            async for event in bundle.engine.submit_message(prompt):
                if isinstance(event, AssistantTextDelta):
                    collected_text += event.text
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "text_delta", "content": event.text})
                    }
                elif isinstance(event, ToolExecutionStarted):
                    tool_count += 1
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "tool_start",
                            "tool": event.tool_name,
                            "input": str(event.tool_input)[:200] if event.tool_input else "",
                        })
                    }
                elif isinstance(event, ToolExecutionCompleted):
                    output = event.output if isinstance(event.output, str) else str(event.output)
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "tool_end",
                            "tool": event.tool_name,
                            "output_lines": len(output.split("\n")),
                            "is_error": event.is_error,
                        })
                    }
                elif isinstance(event, ErrorEvent):
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "error", "message": event.message})
                    }
                elif isinstance(event, AssistantTurnComplete):
                    pass  # Will send complete at the end

                if task_id in self._cancelled_tasks:
                    yield {"event": "message", "data": json.dumps({"type": "cancelled"})}
                    break

            # Send completion event
            total = bundle.engine.total_usage
            input_tokens = getattr(total, "input_tokens", 0) if total else 0
            output_tokens = getattr(total, "output_tokens", 0) if total else 0

            is_cancelled = task_id in self._cancelled_tasks
            final_status = "cancelled" if is_cancelled else "completed"

            yield {
                "event": "message",
                "data": json.dumps({
                    "type": "complete",
                    "status": final_status,
                    "usage": {"input": input_tokens, "output": output_tokens},
                    "tool_calls": tool_count,
                })
            }

            # Update task
            self.task_manager.update_task(
                task_id=task_id,
                status=TaskStatus.CANCELLED if is_cancelled else TaskStatus.COMPLETED,
                response=collected_text.strip()[:500],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        except Exception as e:
            logger.exception("Stream task failed: %s", task_id)
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "message": str(e)[:200]})
            }
            self.task_manager.update_task(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error_message=str(e)[:500]
            )

        finally:
            if bundle and task_id in self._active_bundles:
                del self._active_bundles[task_id]
                await close_runtime(bundle)
