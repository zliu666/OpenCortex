"""A2A Server - HTTP + SSE implementation."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
import json
import asyncio
from typing import Optional

from opencortex.a2a.agent_card import DEFAULT_AGENT_CARD
from opencortex.a2a.task_manager import TaskManager, TaskStatus
from opencortex.a2a.context_layer import ContextLayer, ContextLevel1, ContextLevel2, summarize_tool_output


class A2AServer:
    """A2A Protocol Server for OpenCortex."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765"):
        self.app = FastAPI(title="OpenCortex A2A Server", version="0.1.0")
        self.base_url = base_url
        self.task_manager = TaskManager()
        self.context_layer = ContextLayer()

        self._setup_routes()

    def _setup_routes(self):
        """Setup A2A routes."""

        @self.app.get("/a2a/agent-card")
        async def get_agent_card():
            """Get Agent Card (A2A standard)."""
            return JSONResponse(content=DEFAULT_AGENT_CARD.to_dict())

        @self.app.post("/a2a/tasks")
        async def create_task(request: Request):
            """Create a new task (A2A standard)."""
            try:
                body = await request.json()
                prompt = body.get("prompt", "")
                model = body.get("model", "glm-4-flash")
                max_tokens = body.get("max_tokens", 16384)
                temperature = body.get("temperature", 0.7)

                if not prompt:
                    raise HTTPException(status_code=400, detail="prompt is required")

                task = self.task_manager.create_task(
                    prompt=prompt,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature
                )

                # Start processing in background
                asyncio.create_task(self._process_task(task.task_id))

                return JSONResponse(content=task.to_dict(), status_code=201)

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/a2a/tasks/{task_id}")
        async def get_task(task_id: str):
            """Get task by ID (A2A standard)."""
            task = self.task_manager.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            return JSONResponse(content=task.to_dict())

        @self.app.get("/a2a/tasks")
        async def list_tasks(
            limit: int = 100,
            status: Optional[str] = None
        ):
            """List tasks (A2A standard)."""
            status_filter = None
            if status:
                try:
                    status_filter = TaskStatus(status)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

            tasks = self.task_manager.list_tasks(limit=limit, status_filter=status_filter)
            return JSONResponse(content={"tasks": [t.to_dict() for t in tasks]})

        @self.app.delete("/a2a/tasks/{task_id}")
        async def cancel_task(task_id: str):
            """Cancel a task (A2A standard)."""
            success = self.task_manager.cancel_task(task_id)
            if not success:
                raise HTTPException(status_code=404, detail="Task not found or cannot be cancelled")
            return JSONResponse(content={"status": "cancelled"})

        @self.app.post("/a2a/messages")
        async def send_message(request: Request):
            """Send a message (non-streaming, A2A standard)."""
            try:
                body = await request.json()
                task_id = body.get("task_id")
                content = body.get("content", "")

                if not task_id:
                    raise HTTPException(status_code=400, detail="task_id is required")

                # For now, just echo back (Phase 2: integrate with QueryEngine)
                return JSONResponse(content={
                    "message_id": f"msg_{task_id}",
                    "task_id": task_id,
                    "response": f"Echo: {content}"
                })

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/a2a/stream")
        async def stream_message(request: Request):
            """Stream a message (SSE, A2A standard)."""
            try:
                body = await request.json()
                task_id = body.get("task_id")

                async def event_generator():
                    """Yield SSE events."""
                    yield {"event": "message", "data": json.dumps({"type": "thinking", "content": "Starting..."})}

                    # Phase 2: Integrate with QueryEngine
                    # For now, just echo
                    yield {"event": "message", "data": json.dumps({"type": "text", "content": "Streaming response..."})}
                    yield {"event": "message", "data": json.dumps({"type": "complete", "usage": {"input": 10, "output": 20}})}

                return EventSourceResponse(event_generator())

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

    async def _process_task(self, task_id: str):
        """Process a task (background)."""
        # Phase 2: Integrate with QueryEngine
        # For now, just mark as completed
        await asyncio.sleep(1)

        task = self.task_manager.get_task(task_id)
        if task:
            # Generate Level 1 summary
            l1 = self.context_layer.generate_l1(
                l0_ids=[],
                summary=f"Processed: {task.prompt[:50]}...",
                tool_calls=[]
            )

            # Generate Level 2 conclusion
            l2 = self.context_layer.generate_l2(
                task_id=task_id,
                conclusion="Task completed",
                success=True
            )

            self.task_manager.update_task(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                response=l1.summary,
                artifact_id=l2.task_id,
                input_tokens=10,
                output_tokens=20
            )


def create_app(base_url: str = "http://127.0.0.1:8765") -> FastAPI:
    """Create A2A FastAPI app."""
    server = A2AServer(base_url)
    return server.app
