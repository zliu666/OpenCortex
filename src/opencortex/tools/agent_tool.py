"""Tool for spawning local agent tasks."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from opencortex.swarm.agent_definitions import get_agent_definition
from opencortex.swarm.coordinator_mode import get_team_registry
from opencortex.swarm.registry import get_backend_registry
from opencortex.swarm.types import TeammateSpawnConfig
from opencortex.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class AgentToolInput(BaseModel):
    """Arguments for local agent spawning."""

    description: str = Field(description="Short description of the delegated work")
    prompt: str = Field(description="Full prompt for the local agent")
    subagent_type: str | None = Field(
        default=None,
        description="Agent type for definition lookup (e.g. 'general-purpose', 'Explore', 'worker')",
    )
    model: str | None = Field(default=None)
    command: str | None = Field(default=None, description="Override spawn command")
    team: str | None = Field(default=None, description="Optional team to attach the agent to")
    mode: str = Field(
        default="local_agent",
        description="Agent mode: local_agent, remote_agent, or in_process_teammate",
    )


class AgentTool(BaseTool):
    """Spawn a local agent subprocess."""

    name = "agent"
    description = "Spawn a local background agent task."
    input_model = AgentToolInput

    async def execute(self, arguments: AgentToolInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.mode not in {"local_agent", "remote_agent", "in_process_teammate"}:
            return ToolResult(
                output="Invalid mode. Use local_agent, remote_agent, or in_process_teammate.",
                is_error=True,
            )

        # Look up agent definition if subagent_type is specified
        agent_def = None
        if arguments.subagent_type:
            agent_def = get_agent_definition(arguments.subagent_type)

        # Dual-model routing: pick model based on agent type / task
        resolved_model = arguments.model
        execution_env = None
        if resolved_model is None and agent_def and agent_def.model:
            resolved_model = agent_def.model
        if resolved_model is None or resolved_model == "inherit":
            try:
                from opencortex.config.settings import load_settings
                from opencortex.engine.model_router import ModelRouter
                settings = load_settings()
                if settings.dual_model.enabled:
                    router = ModelRouter(settings.dual_model)
                    route = router.route(
                        agent_type=arguments.subagent_type,
                        task_description=arguments.description,
                        explicit_model=None,
                    )
                    resolved_model = route.model
                    if route.provider_key == "execution" and route.api_key:
                        execution_env = {
                            "OPENAI_API_KEY": route.api_key,
                            "OPENAI_BASE_URL": route.base_url or "",
                            "OPENHARNESS_API_FORMAT": route.api_format or "openai",
                        }
                    logger.info("Dual-model routed %s → %s (%s)",
                                arguments.subagent_type or "agent", route.model, route.provider_key)
            except Exception as exc:
                logger.debug("Dual-model routing skipped: %s", exc)

        # Resolve team and agent name for the swarm backend
        team = arguments.team or "default"
        agent_name = arguments.subagent_type or "agent"

        # Use subprocess backend so spawned agents are registered in
        # BackgroundTaskManager and are pollable by the task tools.
        # in_process tasks return asyncio-internal IDs that task tools
        # cannot query, and subprocess is always available on all platforms.
        #
        # When running inside Zellij, also create a visual pane for the agent.
        registry = get_backend_registry()
        executor = registry.get_executor("subprocess")

        zellij_pane_id = None
        try:
            from opencortex.swarm.zellij_backend import is_inside_zellij, get_zellij_backend
            _zellij_detected = is_inside_zellij()
            with open("/tmp/zellij_agent_debug.log", "a") as _dbg: _dbg.write(f"is_inside={_zellij_detected} ZELLIJ={_os.environ.get("ZELLIJ","unset")}\n")
            logger.warning("[AgentTool] is_inside_zellij=%s, env ZELLIJ=%s", _zellij_detected, os.environ.get("ZELLIJ", "(unset)"))
            if _zellij_detected:
                zellij = get_zellij_backend()
                import asyncio
                pane_result = await zellij.create_teammate_pane_in_swarm_view(
                    name=agent_name,
                    color=None,
                )
                zellij_pane_id = pane_result.pane_id
                logger.info("Created Zellij pane %s for agent %s", zellij_pane_id, agent_name)
        except Exception as exc:
            import traceback
            logger.warning("Zellij pane creation failed for agent %s: %s\n%s", agent_name, exc, traceback.format_exc())

        config = TeammateSpawnConfig(
            name=agent_name,
            team=team,
            prompt=arguments.prompt,
            cwd=str(context.cwd),
            parent_session_id="main",
            model=resolved_model,
            execution_provider_env=execution_env,
            system_prompt=agent_def.system_prompt if agent_def else None,
            permissions=agent_def.permissions if agent_def else [],
        )

        try:
            result = await executor.spawn(config)
        except Exception as exc:
            logger.error("Failed to spawn agent: %s", exc)
            return ToolResult(output=str(exc), is_error=True)

        if not result.success:
            return ToolResult(output=result.error or "Failed to spawn agent", is_error=True)

        if result.pane_id is None:
            result.pane_id = zellij_pane_id

        if arguments.team:
            get_team_registry().add_agent(arguments.team, result.task_id)

        return ToolResult(
            output=(
                f"Spawned agent {result.agent_id} "
                f"(task_id={result.task_id}, backend={result.backend_type})"
            )
        )
