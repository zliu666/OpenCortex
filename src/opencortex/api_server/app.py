"""FastAPI application for the OpenCortex HTTP API bridge."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from typing import Optional

from fastapi import FastAPI, HTTPException, Request

from opencortex.cli import __version__
from opencortex.config import load_settings
from opencortex.tools import create_default_tool_registry
from opencortex.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from opencortex.ui.runtime import build_runtime, close_runtime, handle_line, start_runtime
from opencortex.a2a.agent_card import DEFAULT_AGENT_CARD
from opencortex.a2a.task_manager import TaskManager, TaskStatus
from opencortex.a2a.context_layer import ContextLayer, summarize_tool_output
from opencortex.a2a.executor import TaskExecutor
from opencortex.mcp import create_mcp_app

from opencortex.engine.token_stats import global_token_stats

from .models import (
    ErrorResponse,
    QueryRequest,
    QueryResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionMessageRequest,
    SessionMessageResponse,
    StatusResponse,
    ToolCallInfo,
    UsageInfo,
)
from .session_manager import Session, SessionManager

logger = logging.getLogger("opencortex.api_server")

session_manager = SessionManager()

# A2A components (Phase 1: A2A Bridge)
task_manager = TaskManager()
context_layer = ContextLayer()
task_executor = TaskExecutor(task_manager, context_layer)


async def _noop_permission(tool_name: str, reason: str) -> bool:
    return True


async def _noop_ask(question: str) -> str:
    return ""


async def _run_query(bundle, prompt: str) -> tuple[str, UsageInfo, list[ToolCallInfo]]:
    """Run a query and collect results."""
    collected_text = ""
    usage = UsageInfo()
    tool_calls: list[ToolCallInfo] = []

    async def _print_system(message: str) -> None:
        pass

    async def _render_event(event: StreamEvent) -> None:
        nonlocal collected_text, usage, tool_calls
        if isinstance(event, AssistantTextDelta):
            collected_text += event.text
        elif isinstance(event, AssistantTurnComplete):
            pass  # text already collected via deltas
        elif isinstance(event, ToolExecutionStarted):
            tool_calls.append(ToolCallInfo(
                tool_name=event.tool_name,
                tool_input=event.tool_input if isinstance(event.tool_input, (str, dict)) else str(event.tool_input),
            ))
        elif isinstance(event, ToolExecutionCompleted):
            # Update the matching tool call with output
            for tc in reversed(tool_calls):
                if tc.tool_name == event.tool_name and tc.output is None:
                    tc.output = event.output if isinstance(event.output, str) else str(event.output)
                    tc.is_error = event.is_error
                    break
        elif isinstance(event, ErrorEvent):
            logger.warning("Error event: %s", event.message)

    async def _clear_output() -> None:
        pass

    await handle_line(
        bundle,
        prompt,
        print_system=_print_system,
        render_event=_render_event,
        clear_output=_clear_output,
    )

    # Try to extract usage from engine cost tracker
    total = bundle.engine.total_usage
    if total:
        usage.input_tokens = getattr(total, "input_tokens", 0)
        usage.output_tokens = getattr(total, "output_tokens", 0)

    return collected_text.strip(), usage, tool_calls


async def _record_usage(usage: UsageInfo, model: str = "unknown", session_id: str = "", task_type: str = "query") -> None:
    """Record token usage to global stats (best-effort, never blocks)."""
    try:
        await global_token_stats.record(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            model=model,
            session_id=session_id,
            task_type=task_type,
        )
    except Exception:
        logger.debug("Failed to record token stats", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("OpenCortex API server started (v%s)", __version__)
    yield
    # Cleanup sessions
    for sid in list(session_manager._sessions):
        session_manager.remove(sid)
    logger.info("OpenCortex API server stopped")


app = FastAPI(
    title="OpenCortex API",
    version=__version__,
    lifespan=lifespan,
)


# A2A Routes (Phase 1: A2A Bridge)
@app.get("/a2a/agent-card")
async def a2a_get_agent_card():
    """Get Agent Card (A2A standard)."""
    return DEFAULT_AGENT_CARD.to_dict()


@app.post("/a2a/tasks")
async def a2a_create_task(request: Request):
    """Create and execute a new task (A2A standard + QueryEngine integration)."""
    try:
        body = await request.json()
        prompt = body.get("prompt", "")
        model = body.get("model", "glm-4-flash")
        max_tokens = body.get("max_tokens", 16384)
        temperature = body.get("temperature", 0.7)
        max_turns = body.get("max_turns", 50)
        stream = body.get("stream", False)

        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")

        task = task_manager.create_task(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature
        )

        if stream:
            # Return task ID, client polls /a2a/tasks/{id}/stream for SSE
            return {**task.to_dict(), "stream_url": f"/a2a/tasks/{task.task_id}/stream"}
        else:
            # Execute synchronously (Phase 2: background execution)
            result = await task_executor.execute_task(
                task_id=task.task_id,
                prompt=prompt,
                model=model,
                max_turns=max_turns,
            )
            # Return updated task
            updated = task_manager.get_task(task.task_id)
            return {**updated.to_dict(), "execution": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/a2a/tasks/{task_id}/stream")
async def a2a_stream_task(task_id: str, request: Request):
    """Stream task execution via SSE (A2A standard)."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in (TaskStatus.SUBMITTED,):
        raise HTTPException(status_code=400, detail=f"Task status is {task.status.value}, cannot stream")

    from sse_starlette.sse import EventSourceResponse

    async def event_generator():
        async for event in task_executor.stream_task(
            task_id=task_id,
            prompt=task.prompt,
            model=task.model,
            max_turns=task.max_turns,
        ):
            yield event

    return EventSourceResponse(event_generator())


@app.get("/a2a/tasks/{task_id}")
async def a2a_get_task(task_id: str):
    """Get task by ID (A2A standard)."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@app.get("/a2a/tasks")
async def a2a_list_tasks(limit: int = 100, status: Optional[str] = None):
    """List tasks (A2A standard)."""
    status_filter = None
    if status:
        try:
            status_filter = TaskStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    tasks = task_manager.list_tasks(limit=limit, status_filter=status_filter)
    return {"tasks": [t.to_dict() for t in tasks]}


@app.delete("/a2a/tasks/{task_id}")
async def a2a_cancel_task(task_id: str):
    """Cancel a task (A2A standard)."""
    success = task_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or cannot be cancelled")
    return {"status": "cancelled"}


logger.info("A2A routes registered")


# MCP Server Routes (Phase 3: Tool exposure)
@app.get("/mcp/tools")
async def mcp_list_tools():
    """List available MCP tools."""
    settings = load_settings()
    registry = create_default_tool_registry()
    tools = []
    for tool in registry.list_tools():
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "schema": tool.to_api_schema(),
        })
    return {"tools": tools}


logger.info("MCP routes registered")


# Mount A2A Server (Phase 1: A2A Bridge)
# This must be done AFTER app is created
try:
    from opencortex.a2a.server import create_app as create_a2a_app
    a2a_app = create_a2a_app()
    app.mount("/a2a", a2a_app)
    logger.info("A2A Server mounted at /a2a")
except Exception as e:
    logger.warning(f"A2A Server not available: {e}")


@app.get("/status", response_model=StatusResponse)
async def get_status():
    settings = load_settings()
    return StatusResponse(
        status="ok",
        version=__version__,
        model=settings.model,
        active_sessions=session_manager.active_count,
    )


# ---------------------------------------------------------------------------
# Phase 0: Observability — /health & /metrics
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Comprehensive health check with dependency verification."""
    import importlib
    import platform
    import sys

    checks: dict[str, str] = {}
    deps = ["anthropic", "openai", "rich", "prompt_toolkit", "fastapi", "uvicorn", "aiosqlite"]
    for dep in deps:
        try:
            mod = importlib.import_module(dep)
            ver = getattr(mod, "__version__", "ok")
            checks[dep] = f"ok ({ver})" if isinstance(ver, str) else "ok"
        except ImportError:
            checks[dep] = "MISSING"

    # Check persistence store availability
    try:
        from opencortex.persistence.store import PersistenceStore
        checks["persistence"] = "ok"
    except Exception as e:
        checks["persistence"] = f"error: {e}"

    # Check config
    try:
        settings = load_settings()
        checks["config"] = "ok"
        configured_model = settings.model
    except Exception as e:
        checks["config"] = f"error: {e}"
        configured_model = "unknown"

    # Check API key (without revealing it)
    api_key_set = bool(settings.api_key) if "settings" in dir() else False
    checks["api_key"] = "configured" if api_key_set else "NOT SET"

    all_ok = all("ok" in v or "configured" in v for v in checks.values())

    return {
        "status": "healthy" if all_ok else "degraded",
        "version": __version__,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.system(),
        "model": configured_model,
        "active_sessions": session_manager.active_count,
        "uptime_seconds": global_token_stats.snapshot()["uptime_seconds"],
        "checks": checks,
    }


@app.get("/metrics")
async def get_metrics():
    """Token usage metrics across four dimensions."""
    stats = global_token_stats.snapshot()
    settings = load_settings()
    return {
        "status": "ok",
        "version": __version__,
        "model": settings.model,
        "active_sessions": session_manager.active_count,
        "token_stats": stats,
    }


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    bundle = None
    try:
        bundle = await build_runtime(
            prompt=req.prompt,
            model=req.model,
            cwd=req.cwd,
            system_prompt=req.system_prompt,
            max_turns=req.max_turns,
            enforce_max_turns=True,
            permission_prompt=_noop_permission,
            ask_user_prompt=_noop_ask,
        )
        await start_runtime(bundle)
        text, usage, tool_calls = await _run_query(bundle, req.prompt)
        await _record_usage(usage, model=req.model or "default", task_type="query")
        return QueryResponse(
            status="success",
            response=text,
            usage=usage,
            tool_calls=tool_calls,
        )
    except Exception as exc:
        logger.exception("Query failed")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if bundle:
            await close_runtime(bundle)


@app.post("/session", response_model=SessionCreateResponse)
async def create_session(req: SessionCreateRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    bundle = None
    try:
        bundle = await build_runtime(
            prompt=req.prompt,
            model=req.model,
            cwd=req.cwd,
            system_prompt=req.system_prompt,
            max_turns=req.max_turns,
            permission_prompt=_noop_permission,
            ask_user_prompt=_noop_ask,
        )
        await start_runtime(bundle)
        text, usage, tool_calls = await _run_query(bundle, req.prompt)
        session = session_manager.create(bundle)
        await _record_usage(usage, model=req.model or "default", session_id=session.id, task_type="session")
        return SessionCreateResponse(
            session_id=session.id,
            status="success",
            response=text,
            usage=usage,
            tool_calls=tool_calls,
        )
    except Exception as exc:
        if bundle:
            await close_runtime(bundle)
        logger.exception("Session creation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/session/{session_id}/message", response_model=SessionMessageResponse)
async def session_message(session_id: str, req: SessionMessageRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    try:
        text, usage, tool_calls = await _run_query(session.bundle, req.prompt)
        await _record_usage(usage, model=session.bundle.engine._model if hasattr(session.bundle.engine, '_model') else "default", session_id=session_id, task_type="session")
        return SessionMessageResponse(
            status="success",
            response=text,
            usage=usage,
            tool_calls=tool_calls,
        )
    except Exception as exc:
        logger.exception("Session message failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    await close_runtime(session.bundle)
    session_manager.remove(session_id)
    global_token_stats.remove_session(session_id)
    return {"status": "deleted", "session_id": session_id}
