"""Built-in tool registration."""

from opencortex.tools.ask_user_question_tool import AskUserQuestionTool
from opencortex.tools.agent_tool import AgentTool
from opencortex.tools.bash_tool import BashTool
from opencortex.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from opencortex.tools.brief_tool import BriefTool
from opencortex.tools.config_tool import ConfigTool
from opencortex.tools.cron_create_tool import CronCreateTool
from opencortex.tools.cron_delete_tool import CronDeleteTool
from opencortex.tools.cron_list_tool import CronListTool
from opencortex.tools.cron_toggle_tool import CronToggleTool
from opencortex.tools.enter_plan_mode_tool import EnterPlanModeTool
from opencortex.tools.enter_worktree_tool import EnterWorktreeTool
from opencortex.tools.exit_plan_mode_tool import ExitPlanModeTool
from opencortex.tools.exit_worktree_tool import ExitWorktreeTool
from opencortex.tools.file_edit_tool import FileEditTool
from opencortex.tools.file_read_tool import FileReadTool
from opencortex.tools.file_write_tool import FileWriteTool
from opencortex.tools.glob_tool import GlobTool
from opencortex.tools.grep_tool import GrepTool
from opencortex.tools.list_mcp_resources_tool import ListMcpResourcesTool
from opencortex.tools.lsp_tool import LspTool
from opencortex.tools.mcp_auth_tool import McpAuthTool
from opencortex.tools.mcp_tool import McpToolAdapter
from opencortex.tools.notebook_edit_tool import NotebookEditTool
from opencortex.tools.read_mcp_resource_tool import ReadMcpResourceTool
from opencortex.tools.remote_trigger_tool import RemoteTriggerTool
from opencortex.tools.send_message_tool import SendMessageTool
from opencortex.tools.skill_tool import SkillTool
from opencortex.tools.sleep_tool import SleepTool
from opencortex.tools.task_create_tool import TaskCreateTool
from opencortex.tools.task_get_tool import TaskGetTool
from opencortex.tools.task_list_tool import TaskListTool
from opencortex.tools.task_output_tool import TaskOutputTool
from opencortex.tools.task_stop_tool import TaskStopTool
from opencortex.tools.task_update_tool import TaskUpdateTool
from opencortex.tools.team_create_tool import TeamCreateTool
from opencortex.tools.team_delete_tool import TeamDeleteTool
from opencortex.tools.todo_write_tool import TodoWriteTool
from opencortex.tools.tool_search_tool import ToolSearchTool
from opencortex.tools.web_fetch_tool import WebFetchTool
from opencortex.tools.web_search_tool import WebSearchTool


def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    """Return the default built-in tool registry."""
    registry = ToolRegistry()
    for tool in (
        BashTool(),
        AskUserQuestionTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        NotebookEditTool(),
        LspTool(),
        McpAuthTool(),
        GlobTool(),
        GrepTool(),
        SkillTool(),
        ToolSearchTool(),
        WebFetchTool(),
        WebSearchTool(),
        ConfigTool(),
        BriefTool(),
        SleepTool(),
        EnterWorktreeTool(),
        ExitWorktreeTool(),
        TodoWriteTool(),
        EnterPlanModeTool(),
        ExitPlanModeTool(),
        CronCreateTool(),
        CronListTool(),
        CronDeleteTool(),
        CronToggleTool(),
        RemoteTriggerTool(),
        TaskCreateTool(),
        TaskGetTool(),
        TaskListTool(),
        TaskStopTool(),
        TaskOutputTool(),
        TaskUpdateTool(),
        AgentTool(),
        SendMessageTool(),
        TeamCreateTool(),
        TeamDeleteTool(),
    ):
        registry.register(tool)
    if mcp_manager is not None:
        registry.register(ListMcpResourcesTool(mcp_manager))
        registry.register(ReadMcpResourceTool(mcp_manager))
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    return registry


__all__ = [
    "BaseTool",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    "create_default_tool_registry",
]
