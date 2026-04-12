"""MCP exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from opencortex.mcp.client import McpClientManager, McpServerNotConnectedError
    from opencortex.mcp.server import create_mcp_app, mcp_server, register_tools_from_registry
    from opencortex.mcp.types import (
        McpConnectionStatus,
        McpHttpServerConfig,
        McpJsonConfig,
        McpResourceInfo,
        McpServerConfig,
        McpStdioServerConfig,
        McpToolInfo,
        McpWebSocketServerConfig,
    )

__all__ = [
    "McpClientManager",
    "McpConnectionStatus",
    "McpServerNotConnectedError",
    "McpHttpServerConfig",
    "McpJsonConfig",
    "McpResourceInfo",
    "McpServerConfig",
    "McpStdioServerConfig",
    "McpToolInfo",
    "McpWebSocketServerConfig",
    "create_mcp_app",
    "load_mcp_server_configs",
    "mcp_server",
    "register_tools_from_registry",
]


def __getattr__(name: str):
    if name == "McpClientManager":
        from opencortex.mcp.client import McpClientManager

        return McpClientManager
    if name == "McpServerNotConnectedError":
        from opencortex.mcp.client import McpServerNotConnectedError

        return McpServerNotConnectedError
    if name == "load_mcp_server_configs":
        from opencortex.mcp.config import load_mcp_server_configs

        return load_mcp_server_configs
    if name in {"create_mcp_app", "mcp_server", "register_tools_from_registry"}:
        from opencortex.mcp import server as _server

        return {"create_mcp_app": _server.create_mcp_app, "mcp_server": _server.mcp_server, "register_tools_from_registry": _server.register_tools_from_registry}[name]
    if name in {
        "McpConnectionStatus",
        "McpHttpServerConfig",
        "McpJsonConfig",
        "McpResourceInfo",
        "McpServerConfig",
        "McpStdioServerConfig",
        "McpToolInfo",
        "McpWebSocketServerConfig",
    }:
        from opencortex.mcp.types import (
            McpConnectionStatus,
            McpHttpServerConfig,
            McpJsonConfig,
            McpResourceInfo,
            McpServerConfig,
            McpStdioServerConfig,
            McpToolInfo,
            McpWebSocketServerConfig,
        )

        return {
            "McpConnectionStatus": McpConnectionStatus,
            "McpHttpServerConfig": McpHttpServerConfig,
            "McpJsonConfig": McpJsonConfig,
            "McpResourceInfo": McpResourceInfo,
            "McpServerConfig": McpServerConfig,
            "McpStdioServerConfig": McpStdioServerConfig,
            "McpToolInfo": McpToolInfo,
            "McpWebSocketServerConfig": McpWebSocketServerConfig,
        }[name]
    raise AttributeError(name)
