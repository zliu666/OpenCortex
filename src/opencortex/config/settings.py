"""Settings model and loading logic for OpenCortex.

Settings are resolved with the following precedence (highest first):
1. CLI arguments
2. Environment variables (ANTHROPIC_API_KEY, OPENHARNESS_MODEL, etc.)
3. Config file (~/.opencortex/settings.json)
4. Defaults
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from opencortex.hooks.schemas import HookDefinition
from opencortex.mcp.types import McpServerConfig
from opencortex.permissions.modes import PermissionMode


class PathRuleConfig(BaseModel):
    """A glob-pattern path permission rule."""

    pattern: str
    allow: bool = True


class PermissionSettings(BaseModel):
    """Permission mode configuration."""

    mode: PermissionMode = PermissionMode.DEFAULT
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    path_rules: list[PathRuleConfig] = Field(default_factory=list)
    denied_commands: list[str] = Field(default_factory=list)


class SandboxNetworkSettings(BaseModel):
    """OS-level network restrictions."""
    allowed_domains: list[str] = Field(default_factory=list)
    denied_domains: list[str] = Field(default_factory=list)


class SandboxFilesystemSettings(BaseModel):
    """OS-level filesystem restrictions."""
    allow_read: list[str] = Field(default_factory=list)
    deny_read: list[str] = Field(default_factory=list)
    allow_write: list[str] = Field(default_factory=lambda: ["."])
    deny_write: list[str] = Field(default_factory=list)


class SandboxSettings(BaseModel):
    """Sandbox-runtime integration settings."""
    enabled: bool = False
    fail_if_unavailable: bool = False
    enabled_platforms: list[str] = Field(default_factory=list)
    network: SandboxNetworkSettings = Field(default_factory=SandboxNetworkSettings)
    filesystem: SandboxFilesystemSettings = Field(default_factory=SandboxFilesystemSettings)


class MemorySettings(BaseModel):
    """Memory system configuration."""

    enabled: bool = True
    max_files: int = 5
    max_entrypoint_lines: int = 200


class Settings(BaseModel):
    """Main settings model for OpenCortex."""

    # API configuration
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 16384
    base_url: str | None = None
    api_format: str = "anthropic"  # "anthropic" or "openai"
    provider_keys: dict[str, str] = Field(default_factory=dict)  # per-provider API keys

    # Behavior
    system_prompt: str | None = None
    permission: PermissionSettings = Field(default_factory=PermissionSettings)
    hooks: dict[str, list[HookDefinition]] = Field(default_factory=dict)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    enabled_plugins: dict[str, bool] = Field(default_factory=dict)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)

    # UI
    theme: str = "default"
    language: str = "en"  # "en" or "zh"
    output_style: str = "default"
    vim_mode: bool = False
    voice_mode: bool = False
    fast_mode: bool = False
    effort: str = "medium"
    passes: int = 1
    verbose: bool = False

    def resolve_api_key(self) -> str:
        """Resolve API key with precedence: instance value > env var > empty.

        Returns the API key string. Raises ValueError if no key is found.
        """
        if self.api_key:
            return self.api_key

        # 智谱 API Key
        zhipu_key = os.environ.get("ZHIPU_API_KEY", "")
        if zhipu_key:
            return zhipu_key

        # MiniMax API Key
        minimax_key = os.environ.get("MINIMAX_API_KEY", "")
        if minimax_key:
            return minimax_key

        env_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if env_key:
            return env_key

        # Also check OPENAI_API_KEY for openai-format providers
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            return openai_key

        raise ValueError(
            "No API key found. Set ZHIPU_API_KEY, MINIMAX_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY "
            "environment variable, or configure api_key in ~/.opencortex/settings.json"
        )

    def merge_cli_overrides(self, **overrides: Any) -> Settings:
        """Return a new Settings with CLI overrides applied (non-None values only)."""
        updates = {k: v for k, v in overrides.items() if v is not None}
        return self.model_copy(update=updates)


def _apply_env_overrides(settings: Settings) -> Settings:
    """Apply supported environment variable overrides over loaded settings."""
    updates: dict[str, Any] = {}
    
    # 模型名：支持智谱 GLM、MiniMax
    model = (
        os.environ.get("ZHIPU_MODEL")
        or os.environ.get("MINIMAX_MODEL")
        or os.environ.get("ANTHROPIC_MODEL") 
        or os.environ.get("OPENHARNESS_MODEL")
    )
    if model:
        updates["model"] = model

    # Base URL：支持智谱、MiniMax
    base_url = (
        os.environ.get("ZHIPU_BASE_URL")
        or os.environ.get("MINIMAX_BASE_URL")
        or os.environ.get("ANTHROPIC_BASE_URL") 
        or os.environ.get("OPENHARNESS_BASE_URL")
    )
    if base_url:
        updates["base_url"] = base_url

    max_tokens = os.environ.get("OPENHARNESS_MAX_TOKENS")
    if max_tokens:
        updates["max_tokens"] = int(max_tokens)

    # API Key：支持智谱、MiniMax
    api_key = (
        os.environ.get("ZHIPU_API_KEY")
        or os.environ.get("MINIMAX_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY") 
        or os.environ.get("OPENAI_API_KEY")
    )
    if api_key:
        updates["api_key"] = api_key

    api_format = os.environ.get("OPENHARNESS_API_FORMAT")
    if api_format:
        updates["api_format"] = api_format

    if not updates:
        return settings
    return settings.model_copy(update=updates)


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from config file, merging with defaults.

    Args:
        config_path: Path to settings.json. If None, uses the default location.

    Returns:
        Settings instance with file values merged over defaults.
    """
    if config_path is None:
        from opencortex.config.paths import get_config_file_path

        config_path = get_config_file_path()

    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        return _apply_env_overrides(Settings.model_validate(raw))

    return _apply_env_overrides(Settings())


def save_settings(settings: Settings, config_path: Path | None = None) -> None:
    """Persist settings to the config file.

    Args:
        settings: Settings instance to save.
        config_path: Path to write. If None, uses the default location.
    """
    if config_path is None:
        from opencortex.config.paths import get_config_file_path

        config_path = get_config_file_path()

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        settings.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
