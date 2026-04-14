"""Hook configuration schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


from pydantic import BaseModel, Field, field_validator
import re


_DANGEROUS_CMD_PATTERNS = re.compile(
    r"\b(rm\s+-rf|rm\s+-r\s+/|curl.*\|\s*(sh|bash)|wget.*\|\s*(sh|bash)|"
    r"python\s+-c\s+['\"]|perl\s+-e\s+['\"]|eval\s+['\"]|"
    r"chmod\s+777|mkfs|dd\s+if=|>:\s*/dev/|shutdown|reboot)"
)


class CommandHookDefinition(BaseModel):
    """A hook that executes a shell command."""

    type: Literal["command"] = "command"
    command: str
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = False

    @field_validator("command")
    @classmethod
    def _validate_command(cls, v: str) -> str:
        if _DANGEROUS_CMD_PATTERNS.search(v):
            raise ValueError(f"Dangerous command pattern detected: {v}")
        return v


class PromptHookDefinition(BaseModel):
    """A hook that asks the model to validate a condition."""

    type: Literal["prompt"] = "prompt"
    prompt: str
    model: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = True


class HttpHookDefinition(BaseModel):
    """A hook that POSTs the event payload to an HTTP endpoint."""

    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = False


class AgentHookDefinition(BaseModel):
    """A hook that performs a deeper model-based validation."""

    type: Literal["agent"] = "agent"
    prompt: str
    model: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=1200)
    matcher: str | None = None
    block_on_failure: bool = True


HookDefinition = (
    CommandHookDefinition
    | PromptHookDefinition
    | HttpHookDefinition
    | AgentHookDefinition
)
