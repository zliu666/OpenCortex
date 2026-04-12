# OpenCortex MCP Server 文档

## 1. MCP 协议简介

### 什么是 MCP？

**MCP（Model Context Protocol）** 是由 Anthropic 推出的开放标准协议，用于在 AI 模型和外部工具/数据源之间建立统一的通信桥梁。MCP 的核心设计目标是：

- **标准化**：为 AI 助手与外部系统的交互提供统一协议
- **可扩展**：支持任意数量和类型的工具服务器
- **双向通信**：支持工具调用和资源读取

### 为什么使用 MCP？

| 传统方式 | MCP 方式 |
|---------|---------|
| 每个工具需要独立 SDK | 统一协议，所有 MCP 服务器通用 |
| 代码耦合严重 | 解耦架构，服务器独立演进 |
| 难以扩展 | 新增工具只需实现 MCP 协议 |
| 调试困难 | 标准化接口便于诊断 |

MCP 让 OpenCortex 能够：
- 调用本地外部工具（文件系统、Git、Shell 命令等）
- 连接远程 API 服务
- 访问 MCP 生态中的数千种工具

---

## 2. OpenCortex MCP Server 架构

### 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenCortex Agent                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Tool Registry │  │ MCP Manager │  │  LLM Integration    │ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
└─────────┼────────────────┼───────────────────┼────────────┘
          │                │                   │
          ▼                ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                  MCP Client Manager                           │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  list_tools()  │  call_tool()  │  read_resource()      │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────┬───────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  MCP Server 1  │    │  MCP Server 2  │    │  MCP Server N  │
│  (stdio)        │    │  (HTTP)        │    │  (WebSocket)   │
└───────────────┘    └───────────────┘    └───────────────┘
```

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `McpClientManager` | `src/opencortex/mcp/client.py` | 管理所有 MCP 连接、调用工具、读取资源 |
| `McpStdioServerConfig` | `src/opencortex/mcp/types.py` | stdio 传输配置（命令启动子进程） |
| `McpHttpServerConfig` | `src/opencortex/mcp/types.py` | HTTP 传输配置（连接 HTTP 服务器） |
| `McpWebSocketServerConfig` | `src/opencortex/mcp/types.py` | WebSocket 传输配置 |
| `McpConnectionStatus` | `src/opencortex/mcp/types.py` | 服务器连接状态 |
| `load_mcp_server_configs` | `src/opencortex/mcp/config.py` | 从设置和插件加载配置 |
| `mcp_server` | `src/opencortex/mcp_server/__init__.py` | OpenCortex 自己的 MCP 服务器（对外暴露工具） |

### 连接流程

1. **配置加载**：从 `~/.opencortex/settings.json` 和插件读取 MCP 服务器配置
2. **连接建立**：根据传输类型（stdio/http/ws）建立连接
3. **工具发现**：调用 `initialize` 获取服务器提供的工具列表
4. **状态跟踪**：每个服务器状态记录在 `McpConnectionStatus`
5. **工具调用**：通过 `call_tool()` 执行远程工具

---

## 3. 支持的 Tools 列表

### OpenCortex 内置工具

所有内置工具都通过 `create_default_tool_registry()` 注册，可通过 MCP 访问：

#### 文件操作工具

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `read_file` | `path`, `offset` (可选), `limit` (可选) | 读取文件内容，返回带行号文本 |
| `write_file` | `path`, `content`, `create_directories` (可选) | 写入文件，支持创建目录 |
| `file_edit` | `file_path`, `old_text`, `new_text` | 替换文件中的文本 |
| `glob` | `pattern`, `root` (可选), `limit` (可选) | 按 glob 模式列出文件 |
| `grep` | `pattern`, `root` (可选), `file_glob` (可选), `case_sensitive` (可选), `limit` (可选) | 正则表达式搜索文件内容 |

#### Shell 工具

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `bash` | `command`, `cwd` (可选), `timeout_seconds` (可选) | 执行 Shell 命令 |

#### 代码智能工具

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `lsp` | `operation`, `file_path`, `symbol` (可选), `line` (可选), `character` (可选), `query` (可选) | 代码符号查找、跳转定义、引用、悬停信息 |

#### Web 工具

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `web_search` | `query`, `max_results` (可选), `search_url` (可选) | 网页搜索 |
| `web_fetch` | `url`, `max_chars` (可选) | 获取网页内容 |

#### 任务管理工具

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `task_create` | `type`, `description`, `command` (可选), `prompt` (可选), `model` (可选) | 创建后台任务 |
| `task_get` | `task_id` | 获取任务详情 |
| `task_list` | `status` (可选) | 列出任务 |
| `task_stop` | `task_id` | 停止任务 |
| `task_output` | `task_id`, `max_bytes` (可选) | 获取任务输出 |
| `task_update` | `task_id`, `description` (可选), `progress` (可选), `status_note` (可选) | 更新任务 |

#### Git 工作树工具

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `enter_worktree` | `branch`, `path` (可选), `create_branch` (可选), `base_ref` (可选) | 创建 git worktree |
| `exit_worktree` | `path` | 移除 git worktree |

#### Cron 调度工具

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `cron_create` | `name`, `schedule`, `command`, `cwd` (可选), `enabled` (可选) | 创建定时任务 |
| `cron_delete` | `name` | 删除定时任务 |
| `cron_list` | - | 列出所有定时任务 |
| `cron_toggle` | `name`, `enabled` | 启用/禁用定时任务 |
| `remote_trigger` | `name`, `timeout_seconds` (可选) | 立即触发定时任务 |

#### 团队协作工具

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `team_create` | `name`, `description` (可选) | 创建团队 |
| `team_delete` | `name` | 删除团队 |
| `send_message` | `task_id`, `message` | 向 Agent 发送消息 |
| `agent` | `description`, `prompt`, `subagent_type` (可选), `model` (可选), `command` (可选), `team` (可选), `mode` (可选) | 启动 Agent |

#### 其他工具

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `config` | `action`, `key` (可选), `value` (可选) | 读取/更新设置 |
| `skill` | `name` | 读取 Skill 内容 |
| `tool_search` | `query` | 搜索可用工具 |
| `brief` | `text`, `max_chars` (可选) | 压缩文本 |
| `sleep` | `seconds` | 暂停执行 |
| `todo_write` | `item`, `checked` (可选), `path` (可选) | 写入 TODO |
| `enter_plan_mode` | - | 进入计划模式 |
| `exit_plan_mode` | - | 退出计划模式 |
| `ask_user_question` | `question` | 向用户提问 |
| `mcp_auth` | `server_name`, `mode`, `value`, `key` (可选) | 配置 MCP 服务器认证 |
| `list_mcp_resources` | - | 列出所有 MCP 资源 |
| `read_mcp_resource` | `server`, `uri` | 读取 MCP 资源 |

### MCP 服务器配置类型

#### Stdio 配置（子进程）

```python
{
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
    "env": {"KEY": "value"},  # 可选，环境变量
    "cwd": "/path"           # 可选，工作目录
}
```

#### HTTP 配置

```python
{
    "type": "http",
    "url": "http://localhost:8080/mcp",
    "headers": {"Authorization": "Bearer token"}  # 可选
}
```

#### WebSocket 配置

```python
{
    "type": "ws",
    "url": "ws://localhost:8080/mcp",
    "headers": {"Authorization": "Bearer token"}  # 可选
}
```

---

## 4. 配置方法

### 4.1 通过 CLI 管理 MCP 服务器

```bash
# 列出所有配置的 MCP 服务器
opencortex mcp list

# 添加 MCP 服务器（stdio 类型）
opencortex mcp add my-server '{"type":"stdio","command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","/tmp"]}'

# 添加 MCP 服务器（HTTP 类型）
opencortex mcp add remote-server '{"type":"http","url":"http://localhost:8080/mcp","headers":{"Authorization":"Bearer token"}}'

# 删除 MCP 服务器
opencortex mcp remove my-server
```

### 4.2 通过配置文件

编辑 `~/.opencortex/settings.json`：

```json
{
    "mcp_servers": {
        "filesystem": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
        },
        "github": {
            "type": "http",
            "url": "http://localhost:8080/mcp",
            "headers": {
                "Authorization": "Bearer your-token-here"
            }
        }
    }
}
```

### 4.3 通过代码配置

```python
from opencortex.mcp import McpClientManager, McpStdioServerConfig, McpHttpServerConfig

# 创建配置
configs = {
    "local-files": McpStdioServerConfig(
        type="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    ),
    "remote-api": McpHttpServerConfig(
        type="http",
        url="http://localhost:8080/mcp",
        headers={"Authorization": "Bearer token"}
    )
}

# 创建并连接
manager = McpClientManager(configs)
await manager.connect_all()

# 查看状态
for status in manager.list_statuses():
    print(f"{status.name}: {status.state}")

# 调用工具
result = await manager.call_tool("local-files", "list_directory", {"path": "/tmp"})
print(result)

# 关闭连接
await manager.close()
```

### 4.4 通过插件配置

插件可以提供 MCP 服务器配置：

```yaml
# plugin.yaml
name: my-plugin
version: 1.0.0
mcpServers:
  my-plugin-server:
    type: stdio
    command: python
    args: ["./mcp_server.py"]
```

---

## 5. 客户端调用示例

### 5.1 使用 curl 调用 MCP HTTP 服务器

MCP HTTP 服务器遵循流式 HTTP 协议。以下是直接使用 MCP 协议调用工具的示例：

```bash
# 调用 MCP 协议的 initialize 端点
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {
        "name": "my-client",
        "version": "1.0.0"
      }
    }
  }'

# 调用工具
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "bash",
      "arguments": {
        "command": "echo hello"
      }
    }
  }'

# 列出可用工具
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/list",
    "params": {}
  }'

# 读取资源
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "resources/read",
    "params": {
      "uri": "file:///path/to/resource"
    }
  }'
```

### 5.2 Python 客户端示例

```python
import asyncio
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp import StdioServerParameters

async def main():
    # HTTP 方式连接
    async with streamable_http_client("http://localhost:8080/mcp") as (read_stream, write_stream, get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            # 列出工具
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools]}")
            
            # 调用工具
            result = await session.call_tool("bash", {"command": "pwd"})
            print(result.content)

    # stdio 方式连接
    params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        env={"NODE_ENV": "production"}
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            # ... use session

asyncio.run(main())
```

### 5.3 Claude Desktop 集成

在 `~/.claude_desktop_config.json` 中配置：

```json
{
  "mcpServers": {
    "opencortex": {
      "command": "uv",
      "args": ["run", "opencortex", "serve"],
      "env": {
        "ANTHROPIC_API_KEY": "your-api-key"
      }
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/username"]
    }
  }
}
```

---

## 6. 与 OpenClaw 集成

### 什么是 OpenClaw？

OpenClaw 是项目的调度层，负责多 Agent 协作和任务调度。MCP Server 模块与 OpenClaw 通过 A2A（Agent-to-Agent）协议进行集成。

### 集成架构

```
┌─────────────────────────────────────────────────────────────┐
│                      OpenClaw (调度层)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Agent Pool   │  │ Task Queue  │  │  Communication Hub   │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────┬───────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  OpenCortex A  │ │  OpenCortex B   │ │  OpenCortex N   │
│  (MCP Client)   │ │  (MCP Client)   │ │  (MCP Client)   │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

### 集成方式

#### 方式 1: 通过 Swarm Agent 定义

在 Agent 定义文件中使用 `mcpServers` 字段：

```yaml
# agent-definition.yaml
name: my-agent
description: An agent with MCP capabilities
mcpServers:
  - name: filesystem
    type: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
  - name: github
    type: http
    url: http://localhost:8080/mcp
requiredMcpServers:
  - filesystem  # 必须存在的服务器
```

#### 方式 2: 编程方式

```python
from opencortex.swarm.agent_definitions import AgentDefinition, has_required_mcp_servers

# 定义 Agent
agent = AgentDefinition(
    name="code-reviewer",
    description="Review code changes",
    mcp_servers=[
        {"name": "github", "type": "http", "url": "http://mcp-server:8080/mcp"}
    ],
    required_mcp_servers=["github"]
)

# 检查 MCP 服务器是否满足要求
available_servers = ["github", "filesystem"]
if has_required_mcp_servers(agent, available_servers):
    print("Agent requirements satisfied")
```

#### 方式 3: MCP Auth 配置

OpenClaw 可以通过 MCP Auth 工具动态配置认证：

```python
from opencortex.tools import McpAuthTool

# 配置 Bearer Token 认证
auth_tool = McpAuthTool()
await auth_tool.execute(
    McpAuthToolInput(
        server_name="github",
        mode="bearer",
        value="ghp_xxxxxxxxxxxx"
    )
)

# 配置 Header 认证
await auth_tool.execute(
    McpAuthToolInput(
        server_name="api",
        mode="header",
        value="secret-key",
        key="X-API-Key"
    )
)

# 配置环境变量
await auth_tool.execute(
    McpAuthToolInput(
        server_name="custom",
        mode="env",
        value="CUSTOM_API_TOKEN",
        key="MY_SERVICE_TOKEN"
    )
)
```

### OpenClaw 集成命令

```bash
# 通过 CLI 配置 OpenClaw 调度的 Agent 所需的 MCP 服务器
opencortex mcp add openclaw-github \
  '{"type":"http","url":"http://github-mcp:8080","headers":{"Authorization":"Bearer token"}}'

# 验证配置
opencortex mcp list
```

### A2A 协议通信

OpenCortex Agent 通过 MCP 与 OpenClaw 通信：

1. **任务创建**：`task_create` 工具创建由 OpenClaw 调度的任务
2. **消息传递**：`send_message` 工具向 OpenClaw 调度下的 Agent 发送消息
3. **状态同步**：OpenClaw 接收 `task_update` 通知同步任务状态

```python
# 创建由 OpenClaw 调度的任务
result = await mcp_manager.call_tool("task_create", "opencortex", {
    "type": "local_agent",
    "description": "Code review task",
    "prompt": "Review the recent commits in this repository"
})
# OpenClaw 调度该任务到合适的 OpenCortex 实例

# 向运行中的 Agent 发送消息
await mcp_manager.call_tool("send_message", "opencortex", {
    "task_id": "agent-123",
    "message": "Please focus on security-related changes"
})
```

---

## 附录：MCP 协议版本

| 协议版本 | OpenCortex 支持 |
|---------|----------------|
| 2024-11-05 | ✅ 支持 |
| 2024-10-07 | ✅ 支持 |

---

## 参考链接

- [MCP 官方文档](https://modelcontextprotocol.io/)
- [Anthropic MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Servers 生态](https://github.com/modelcontextprotocol/servers)
