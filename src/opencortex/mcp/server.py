"""MCP Server - Exposes OpenCortex tools via Model Context Protocol."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from opencortex.tools import create_default_tool_registry
from opencortex.tools.base import ToolExecutionContext, ToolResult
from opencortex.tools.browser_tool import (
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserSnapshotTool,
)
from opencortex.config import load_settings

logger = logging.getLogger("opencortex.mcp.server")

# Create MCP server
mcp_server = FastMCP(name="opencortex")


def _create_context(cwd: str = ".") -> ToolExecutionContext:
    """Create tool execution context."""
    return ToolExecutionContext(cwd=Path(cwd).resolve())


async def register_tools_from_registry(mcp: FastMCP, cwd: str = "."):
    """Register all OpenCortex tools as MCP tools."""
    settings = load_settings()
    registry = create_default_tool_registry()
    context = _create_context(cwd)

    registered = 0
    for tool in registry.list_tools():
        try:
            schema = tool.to_api_schema()
            tool_name = tool.name
            tool_desc = tool.description
            input_model = tool.input_model

            # Create a closure to capture tool and context
            async def execute_tool(**kwargs) -> str:
                try:
                    args = input_model(**kwargs)
                    result = await tool.execute(args, context)
                    return result.output
                except Exception as e:
                    return f"Error: {str(e)}"

            # Register with MCP
            mcp.tool(name=tool_name, description=tool_desc)(execute_tool)
            registered += 1
        except Exception as e:
            logger.warning("Failed to register tool %s: %s", tool.name, e)

    logger.info("Registered %d MCP tools from OpenCortex registry", registered)
    return registered


# Register built-in tools manually (core set)

@mcp_server.tool()
async def bash(command: str) -> str:
    """Execute a shell command. Returns the output."""
    registry = create_default_tool_registry()
    context = _create_context()
    for tool in registry.list_tools():
        if tool.name == "bash":
            args = tool.input_model(command=command)
            result = await tool.execute(args, context)
            return result.output
    return "Error: bash tool not found"


@mcp_server.tool()
async def read_file(file_path: str) -> str:
    """Read file contents. Returns the file text."""
    registry = create_default_tool_registry()
    context = _create_context()
    for tool in registry.list_tools():
        if tool.name == "read_file":
            args = tool.input_model(file_path=file_path)
            result = await tool.execute(args, context)
            return result.output
    return "Error: read_file tool not found"


@mcp_server.tool()
async def write_file(file_path: str, content: str) -> str:
    """Write content to a file. Creates the file if it doesn't exist."""
    registry = create_default_tool_registry()
    context = _create_context()
    for tool in registry.list_tools():
        if tool.name == "write_file":
            args = tool.input_model(file_path=file_path, content=content)
            result = await tool.execute(args, context)
            return result.output
    return "Error: write_file tool not found"


@mcp_server.tool()
async def edit_file(file_path: str, old_text: str, new_text: str) -> str:
    """Edit a file by replacing old_text with new_text."""
    registry = create_default_tool_registry()
    context = _create_context()
    for tool in registry.list_tools():
        if tool.name == "file_edit":
            args = tool.input_model(file_path=file_path, old_text=old_text, new_text=new_text)
            result = await tool.execute(args, context)
            return result.output
    return "Error: file_edit tool not found"


@mcp_server.tool()
async def list_files(directory: str = ".") -> str:
    """List files in a directory."""
    import os
    try:
        entries = os.listdir(directory)
        return "\n".join(sorted(entries))
    except Exception as e:
        return f"Error: {e}"


# Browser automation tools
@mcp_server.tool()
async def browser_navigate(url: str) -> str:
    """Navigate to a URL in the browser."""
    tool = BrowserNavigateTool()
    args = tool.input_model(url=url)
    result = await tool.execute(args, _create_context())
    return result.output


@mcp_server.tool()
async def browser_screenshot(full_page: bool = False) -> str:
    """Take a screenshot of the current page."""
    tool = BrowserScreenshotTool()
    args = tool.input_model(full_page=full_page)
    result = await tool.execute(args, _create_context())
    return result.output


@mcp_server.tool()
async def browser_click(selector: str) -> str:
    """Click an element on the page."""
    tool = BrowserClickTool()
    args = tool.input_model(selector=selector)
    result = await tool.execute(args, _create_context())
    return result.output


@mcp_server.tool()
async def browser_type(selector: str, text: str, delay_ms: int = 0) -> str:
    """Type text into an element."""
    tool = BrowserTypeTool()
    args = tool.input_model(selector=selector, text=text, delay_ms=delay_ms)
    result = await tool.execute(args, _create_context())
    return result.output


@mcp_server.tool()
async def browser_snapshot(max_length: int = 8000) -> str:
    """Get the accessibility tree of the current page."""
    tool = BrowserSnapshotTool()
    args = tool.input_model(max_length=max_length)
    result = await tool.execute(args, _create_context())
    return result.output


def create_mcp_app(cwd: str = ".") -> FastMCP:
    """Create and configure the MCP server."""
    register_tools_from_registry(mcp_server, cwd)
    return mcp_server
