"""Shared runtime assembly for headless and Textual UIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from pathlib import Path
from typing import Awaitable, Callable

from opencortex.api.client import AnthropicApiClient, SupportsStreamingMessages
from opencortex.api.openai_client import OpenAICompatibleClient
from opencortex.api.provider import auth_status, detect_provider
from opencortex.bridge import get_bridge_manager
from opencortex.commands import CommandContext, CommandResult, create_default_command_registry
from opencortex.config import get_config_file_path, load_settings
from opencortex.engine import QueryEngine
from opencortex.engine.messages import ConversationMessage
from opencortex.engine.stream_events import StreamEvent
from opencortex.hooks import HookEvent, HookExecutionContext, HookExecutor, load_hook_registry
from opencortex.hooks.hot_reload import HookReloader
from opencortex.mcp.client import McpClientManager
from opencortex.mcp.config import load_mcp_server_configs
from opencortex.permissions import PermissionChecker
from opencortex.plugins import load_plugins
from opencortex.prompts import build_runtime_system_prompt
from opencortex.state import AppState, AppStateStore
from opencortex.services.session_storage import save_session_snapshot
from opencortex.tools import ToolRegistry, create_default_tool_registry
from opencortex.keybindings import load_keybindings

PermissionPrompt = Callable[[str, str], Awaitable[bool]]
AskUserPrompt = Callable[[str], Awaitable[str]]
SystemPrinter = Callable[[str], Awaitable[None]]
StreamRenderer = Callable[[StreamEvent], Awaitable[None]]
ClearHandler = Callable[[], Awaitable[None]]


@dataclass
class RuntimeBundle:
    """Shared runtime objects for one interactive session."""

    api_client: SupportsStreamingMessages
    cwd: str
    mcp_manager: McpClientManager
    tool_registry: ToolRegistry
    app_state: AppStateStore
    hook_executor: HookExecutor
    engine: QueryEngine
    commands: object
    external_api_client: bool
    session_id: str = ""

    def current_settings(self):
        """Return the latest persisted settings."""
        return load_settings()

    def current_plugins(self):
        """Return currently visible plugins for the working tree."""
        return load_plugins(self.current_settings(), self.cwd)

    def hook_summary(self) -> str:
        """Return the current hook summary."""
        return load_hook_registry(self.current_settings(), self.current_plugins()).summary()

    def plugin_summary(self) -> str:
        """Return the current plugin summary."""
        plugins = self.current_plugins()
        if not plugins:
            return "No plugins discovered."
        lines = ["Plugins:"]
        for plugin in plugins:
            state = "enabled" if plugin.enabled else "disabled"
            lines.append(f"- {plugin.manifest.name} [{state}] {plugin.manifest.description}")
        return "\n".join(lines)

    def mcp_summary(self) -> str:
        """Return the current MCP summary."""
        statuses = self.mcp_manager.list_statuses()
        if not statuses:
            return "No MCP servers configured."
        lines = ["MCP servers:"]
        for status in statuses:
            suffix = f" - {status.detail}" if status.detail else ""
            lines.append(f"- {status.name}: {status.state}{suffix}")
            if status.tools:
                lines.append(f"  tools: {', '.join(tool.name for tool in status.tools)}")
            if status.resources:
                lines.append(f"  resources: {', '.join(resource.uri for resource in status.resources)}")
        return "\n".join(lines)


async def build_runtime(
    *,
    prompt: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    api_client: SupportsStreamingMessages | None = None,
    permission_prompt: PermissionPrompt | None = None,
    ask_user_prompt: AskUserPrompt | None = None,
    restore_messages: list[dict] | None = None,
) -> RuntimeBundle:
    """Build the shared runtime for an OpenCortex session."""
    settings = load_settings().merge_cli_overrides(
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        api_format=api_format,
    )
    cwd = str(Path.cwd())
    plugins = load_plugins(settings, cwd)
    if api_client:
        resolved_api_client = api_client
    elif settings.api_format == "openai":
        resolved_api_client = OpenAICompatibleClient(
            api_key=settings.resolve_api_key(),
            base_url=settings.base_url,
        )
    else:
        resolved_api_client = AnthropicApiClient(
            api_key=settings.resolve_api_key(),
            base_url=settings.base_url,
        )
    mcp_manager = McpClientManager(load_mcp_server_configs(settings, plugins))
    await mcp_manager.connect_all()
    tool_registry = create_default_tool_registry(mcp_manager)
    provider = detect_provider(settings)
    bridge_manager = get_bridge_manager()
    app_state = AppStateStore(
        AppState(
            model=settings.model,
            permission_mode=settings.permission.mode.value,
            theme=settings.theme,
            cwd=cwd,
            provider=provider.name,
            auth_status=auth_status(settings),
            base_url=settings.base_url or "",
            vim_enabled=settings.vim_mode,
            voice_enabled=settings.voice_mode,
            voice_available=provider.voice_supported,
            voice_reason=provider.voice_reason,
            fast_mode=settings.fast_mode,
            effort=settings.effort,
            passes=settings.passes,
            mcp_connected=sum(1 for status in mcp_manager.list_statuses() if status.state == "connected"),
            mcp_failed=sum(1 for status in mcp_manager.list_statuses() if status.state == "failed"),
            bridge_sessions=len(bridge_manager.list_sessions()),
            output_style=settings.output_style,
            keybindings=load_keybindings(),
        )
    )
    hook_reloader = HookReloader(get_config_file_path())
    hook_executor = HookExecutor(
        hook_reloader.current_registry() if api_client is None else load_hook_registry(settings, plugins),
        HookExecutionContext(
            cwd=Path(cwd).resolve(),
            api_client=resolved_api_client,
            default_model=settings.model,
        ),
    )
    engine = QueryEngine(
        api_client=resolved_api_client,
        tool_registry=tool_registry,
        permission_checker=PermissionChecker(settings.permission),
        cwd=cwd,
        model=settings.model,
        system_prompt=build_runtime_system_prompt(settings, cwd=cwd, latest_user_prompt=prompt),
        max_tokens=settings.max_tokens,
        permission_prompt=permission_prompt,
        ask_user_prompt=ask_user_prompt,
        hook_executor=hook_executor,
        tool_metadata={"mcp_manager": mcp_manager, "bridge_manager": bridge_manager},
    )
    # Restore messages from a saved session if provided
    if restore_messages:
        restored = [
            ConversationMessage.model_validate(m) for m in restore_messages
        ]
        engine.load_messages(restored)

    from uuid import uuid4

    return RuntimeBundle(
        api_client=resolved_api_client,
        cwd=cwd,
        mcp_manager=mcp_manager,
        tool_registry=tool_registry,
        app_state=app_state,
        hook_executor=hook_executor,
        engine=engine,
        commands=create_default_command_registry(),
        external_api_client=api_client is not None,
        session_id=uuid4().hex[:12],
    )


async def start_runtime(bundle: RuntimeBundle) -> None:
    """Run session start hooks."""
    await bundle.hook_executor.execute(
        HookEvent.SESSION_START,
        {"cwd": bundle.cwd, "event": HookEvent.SESSION_START.value},
    )


async def close_runtime(bundle: RuntimeBundle) -> None:
    """Close runtime-owned resources."""
    await bundle.mcp_manager.close()
    await bundle.hook_executor.execute(
        HookEvent.SESSION_END,
        {"cwd": bundle.cwd, "event": HookEvent.SESSION_END.value},
    )


def sync_app_state(bundle: RuntimeBundle) -> None:
    """Refresh UI state from current settings and dynamic keybindings."""
    settings = bundle.current_settings()
    provider = detect_provider(settings)
    bundle.app_state.set(
        model=settings.model,
        permission_mode=settings.permission.mode.value,
        theme=settings.theme,
        cwd=bundle.cwd,
        provider=provider.name,
        auth_status=auth_status(settings),
        base_url=settings.base_url or "",
        vim_enabled=settings.vim_mode,
        voice_enabled=settings.voice_mode,
        voice_available=provider.voice_supported,
        voice_reason=provider.voice_reason,
        fast_mode=settings.fast_mode,
        effort=settings.effort,
        passes=settings.passes,
        mcp_connected=sum(1 for status in bundle.mcp_manager.list_statuses() if status.state == "connected"),
        mcp_failed=sum(1 for status in bundle.mcp_manager.list_statuses() if status.state == "failed"),
        bridge_sessions=len(get_bridge_manager().list_sessions()),
        output_style=settings.output_style,
        keybindings=load_keybindings(),
    )


async def handle_line(
    bundle: RuntimeBundle,
    line: str,
    *,
    print_system: SystemPrinter,
    render_event: StreamRenderer,
    clear_output: ClearHandler,
    emit: Callable[[Any], Awaitable[None]] | None = None,
) -> bool:
    """Handle one submitted line for either headless or TUI rendering."""
    if not bundle.external_api_client:
        bundle.hook_executor.update_registry(
            load_hook_registry(bundle.current_settings(), bundle.current_plugins())
        )

    parsed = bundle.commands.lookup(line)
    if parsed is not None:
        command, args = parsed
        result = await command.handler(
            args,
            CommandContext(
                engine=bundle.engine,
                hooks_summary=bundle.hook_summary(),
                mcp_summary=bundle.mcp_summary(),
                plugin_summary=bundle.plugin_summary(),
                cwd=bundle.cwd,
                tool_registry=bundle.tool_registry,
                app_state=bundle.app_state,
            ),
        )
        await _render_command_result(result, print_system, clear_output, render_event, emit)
        sync_app_state(bundle)
        return not result.should_exit

    settings = bundle.current_settings()
    bundle.engine.set_system_prompt(
        build_runtime_system_prompt(settings, cwd=bundle.cwd, latest_user_prompt=line)
    )
    try:
        async for event in bundle.engine.submit_message(line):
            await render_event(event)
    except Exception as exc:
        error_msg = str(exc)
        if "AuthenticationFailure" in type(exc).__name__ or "401" in error_msg or "403" in error_msg:
            error_msg = f"Authentication failed. Check API key for current provider.\nUse /provider to switch or /login to update key.\nDetails: {error_msg}"
        elif "429" in error_msg or "RateLimit" in type(exc).__name__:
            error_msg = f"Rate limited. Please wait and retry.\nDetails: {error_msg}"
        await print_system(f"❌ {error_msg}")
    save_session_snapshot(
        cwd=bundle.cwd,
        model=settings.model,
        system_prompt=build_runtime_system_prompt(settings, cwd=bundle.cwd, latest_user_prompt=line),
        messages=bundle.engine.messages,
        usage=bundle.engine.total_usage,
        session_id=bundle.session_id,
    )
    sync_app_state(bundle)
    return True


async def _render_command_result(
    result: CommandResult,
    print_system: SystemPrinter,
    clear_output: ClearHandler,
    render_event: StreamRenderer | None = None,
    emit: Callable[[Any], Awaitable[None]] | None = None,
) -> None:
    if result.clear_screen:
        await clear_output()
    if result.replay_messages and render_event is not None:
        from opencortex.engine.stream_events import AssistantTextDelta, AssistantTurnComplete
        from opencortex.api.usage import UsageSnapshot

        await clear_output()
        await print_system("Session restored:")
        for msg in result.replay_messages:
            if msg.role == "user":
                await print_system(f"> {msg.text}")
            elif msg.role == "assistant" and msg.text.strip():
                await render_event(AssistantTextDelta(text=msg.text))
                await render_event(AssistantTurnComplete(message=msg, usage=UsageSnapshot()))
    if result.has_select and emit is not None:
        from opencortex.ui.protocol import BackendEvent
        sel = result.select_options
        await emit(BackendEvent(
            type="select_request",
            modal={"kind": "select", "title": sel.get("title", "Select"), "submit_prefix": sel.get("prefix", "")},
            select_options=sel.get("options", []),
        ))
    if result.message and not result.replay_messages and not result.has_select:
        await print_system(result.message)
