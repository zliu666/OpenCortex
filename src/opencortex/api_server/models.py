"""Pydantic request/response models for the API server."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---- Requests ----

class QueryRequest(BaseModel):
    prompt: str
    model: str | None = None
    output_format: str = "json"
    cwd: str | None = None
    system_prompt: str | None = None
    max_turns: int | None = None


class SessionCreateRequest(BaseModel):
    prompt: str
    model: str | None = None
    cwd: str | None = None
    system_prompt: str | None = None
    max_turns: int | None = None


class SessionMessageRequest(BaseModel):
    prompt: str


# ---- Responses ----

class UsageInfo(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class ToolCallInfo(BaseModel):
    tool_name: str
    tool_input: str | dict | None = None
    output: str | None = None
    is_error: bool = False


class QueryResponse(BaseModel):
    status: str = "success"
    response: str = ""
    usage: UsageInfo = Field(default_factory=UsageInfo)
    tool_calls: list[ToolCallInfo] = Field(default_factory=list)


class SessionCreateResponse(BaseModel):
    session_id: str
    status: str = "success"
    response: str = ""
    usage: UsageInfo = Field(default_factory=UsageInfo)
    tool_calls: list[ToolCallInfo] = Field(default_factory=list)


class SessionMessageResponse(BaseModel):
    status: str = "success"
    response: str = ""
    usage: UsageInfo = Field(default_factory=UsageInfo)
    tool_calls: list[ToolCallInfo] = Field(default_factory=list)


class StatusResponse(BaseModel):
    status: str = "ok"
    version: str
    model: str
    active_sessions: int = 0


class ErrorResponse(BaseModel):
    status: str = "error"
    error: str
