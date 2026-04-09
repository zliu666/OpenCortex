"""FastAPI application for the OpenCortex HTTP API bridge."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from opencortex.cli import __version__
from opencortex.config import load_settings
from opencortex.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from opencortex.ui.runtime import build_runtime, close_runtime, handle_line, start_runtime

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


@app.get("/status", response_model=StatusResponse)
async def get_status():
    settings = load_settings()
    return StatusResponse(
        status="ok",
        version=__version__,
        model=settings.model,
        active_sessions=session_manager.active_count,
    )


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
    return {"status": "deleted", "session_id": session_id}
