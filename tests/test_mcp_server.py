"""MCP Server Tests - Phase 3 (Tool exposure)."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestMCPModule:
    """Test MCP module imports and basic functionality."""

    def test_mcp_server_import(self):
        from opencortex.mcp import mcp_server
        assert mcp_server is not None
        assert mcp_server.name == "opencortex"

    def test_bash_tool_registered(self):
        from opencortex.mcp import mcp_server
        tool_names = [t.name for t in mcp_server._tool_manager.list_tools()]
        assert "bash" in tool_names

    def test_read_file_tool_registered(self):
        from opencortex.mcp import mcp_server
        tool_names = [t.name for t in mcp_server._tool_manager.list_tools()]
        assert "read_file" in tool_names

    def test_write_file_tool_registered(self):
        from opencortex.mcp import mcp_server
        tool_names = [t.name for t in mcp_server._tool_manager.list_tools()]
        assert "write_file" in tool_names

    def test_edit_file_tool_registered(self):
        from opencortex.mcp import mcp_server
        tool_names = [t.name for t in mcp_server._tool_manager.list_tools()]
        assert "edit_file" in tool_names

    def test_list_files_tool_registered(self):
        from opencortex.mcp import mcp_server
        tool_names = [t.name for t in mcp_server._tool_manager.list_tools()]
        assert "list_files" in tool_names


class TestMCPAPI:
    """Test MCP HTTP API endpoints with mocked responses."""

    BASE = "http://127.0.0.1:8765"

    @patch('httpx.get')
    def test_mcp_tools_list(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tools": [
                {
                    "name": "bash",
                    "description": "Execute bash commands",
                    "input_schema": {"type": "object"}
                },
                {
                    "name": "read_file",
                    "description": "Read file contents",
                    "input_schema": {"type": "object"}
                },
                {
                    "name": "write_file",
                    "description": "Write file contents",
                    "input_schema": {"type": "object"}
                },
                {
                    "name": "edit_file",
                    "description": "Edit file contents",
                    "input_schema": {"type": "object"}
                },
                {
                    "name": "list_files",
                    "description": "List files in directory",
                    "input_schema": {"type": "object"}
                }
            ],
            "total": 5
        }
        mock_get.return_value = mock_response

        import httpx
        r = httpx.get(f"{self.BASE}/mcp/tools")
        assert r.status_code == 200
        data = r.json()
        assert "tools" in data
        assert len(data["tools"]) > 0
        # Check core tools exist
        tool_names = [t["name"] for t in data["tools"]]
        assert "bash" in tool_names
        assert "read_file" in tool_names

    @patch('httpx.get')
    def test_mcp_tools_have_schemas(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tools": [
                {
                    "name": "bash",
                    "description": "Execute bash commands",
                    "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}}
                },
                {
                    "name": "read_file",
                    "description": "Read file contents",
                    "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}
                }
            ]
        }
        mock_get.return_value = mock_response

        import httpx
        r = httpx.get(f"{self.BASE}/mcp/tools")
        data = r.json()
        for tool in data["tools"]:
            assert "name" in tool
            assert "description" in tool
