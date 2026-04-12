# OpenCortex Architecture Report

> Generated: 2026-04-11 | Version: 0.1.5  
> This document provides a comprehensive overview of the OpenCortex codebase architecture.

---

## 1. Project Overview

**OpenCortex** is an open-source, modular AI-powered coding assistant CLI. It provides an interactive REPL and headless print mode for software engineering tasks — reading code, editing files, running shell commands, searching codebases, and orchestrating multi-agent workflows.

### Design Principles

- **Tool-first**: The agent communicates through a well-defined set of tools rather than free-form shell access
- **Provider-agnostic**: Supports Anthropic, OpenAI-compatible, GitHub Copilot, and Codex backends
- **Extensible**: Skills, plugins, hooks, MCP servers, and channels can all be added without modifying core code
- **Secure**: Layered permission system with sensitive-path protection, sandbox integration, and optional security validation layer

### Entry Points

| Entry Point | Command | Description |
|---|---|---|
| `python -m opencortex` | `oh` / `opencortex` | Typer CLI — launches interactive REPL or print mode |
| HTTP API | `oh serve` | FastAPI-based REST API with session management |
| A2A Server | Programmatic | Agent-to-Agent protocol server for inter-agent communication |

---

## 2. Module Dependency Graph

```
                           ┌─────────────┐
                           │   cli.py    │  (Typer CLI entry point)
                           └──────┬──────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              ┌──────────┐  ┌──────────┐  ┌──────────────┐
              │ ui/app   │  │commands/ │  │ api_server/  │
              └────┬─────┘  └────┬─────┘  └──────┬───────┘
                   │              │               │
          ┌────────┘              │               │
          ▼                       ▼               ▼
    ┌─────────────┐       ┌──────────────┐  ┌──────────┐
    │ ui/runtime  │◄─────►│  engine/     │  │   a2a/   │
    └──────┬──────┘       │ query_engine │  └────┬─────┘
           │              └──────┬───────┘       │
           │                     │               │
    ┌──────┴──────┐       ┌──────┴───────┐       │
    │   state/    │       │    api/      │◄──────┘
    └─────────────┘       │  (clients)   │
                          └──────┬───────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
        ┌──────────┐      ┌───────────┐      ┌──────────┐
        │  tools/  │      │   mcp/    │      │  auth/   │
        └────┬─────┘      └─────┬─────┘      └──────────┘
             │                  │
    ┌────────┼────────┐        │
    ▼        ▼        ▼        ▼
┌────────┐┌──────┐┌───────┐┌──────────┐
│security││perms ││ hooks ││ plugins/ │
└────────┘└──────┘└───────┘└────┬─────┘
                               │
                          ┌────┴────┐
                          │ skills/ │
                          └─────────┘

  Cross-cutting modules (used everywhere):
  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌────────┐
  │  config/ │  │  memory/ │  │ orchestration│  │ swarm/ │
  └──────────┘  └──────────┘  └──────────────┘  └────────┘

  External integration modules:
  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌────────┐
  │channels/ │  │  bridge/ │  │    i18n      │  │themes/ │
  └──────────┘  └──────────┘  └──────────────┘  └────────┘
```

### Dependency Summary (textual)

1. **CLI** (`cli.py`) → orchestrates everything; depends on `ui/`, `commands/`, `config/`
2. **UI** (`ui/`) → assembles `RuntimeBundle` via `ui/runtime.py`, which wires together `engine/`, `api/`, `tools/`, `mcp/`, `hooks/`, `plugins/`, `skills/`, `permissions/`, `security/`, `state/`, `memory/`
3. **Engine** (`engine/`) → core agentic loop; depends on `api/` (for LLM calls), `tools/` (tool execution), `permissions/` (gate-keeping), `hooks/` (lifecycle events), `security/` (validation), `services/compact/` (auto-compaction)
4. **API** (`api/`) → LLM provider clients; depends on `auth/` (credential handling), `engine/messages` (message models)
5. **Tools** (`tools/`) → 40+ built-in tools; depend on `mcp/`, `tasks/`, `swarm/`, `config/`, `skills/`
6. **Channels** (`channels/`) → chat platform adapters; depend on `engine/` (via `ChannelBridge`), `config/schema`
7. **Plugins/Skills** → depend on `swarm/agent_definitions` (shared parsing), `mcp/types`
8. **Config** → standalone; depended on by nearly every module
9. **Memory** → depends on `config/paths`
10. **Swarm** → multi-agent orchestration; depends on `tasks/`, `config/`, `platforms/`

---

## 3. Module Reference

### 3.1 `cli` — CLI Entry Point

**Files:** `cli.py`, `__main__.py`

| Component | Description |
|---|---|
| `typer.Typer` app | Main CLI application with sub-commands: `mcp`, `plugin`, `auth`, `provider`, `cron`, `serve` |
| `run_repl()` | Launches interactive React TUI or backend-only mode |
| `run_print_mode()` | Non-interactive: submit prompt, stream output, exit |

### 3.2 `config` — Configuration System

**Files:** `__init__.py`, `schema.py`, `settings.py`, `paths.py`

| Class/Function | Description |
|---|---|
| `Settings` (Pydantic model) | Top-level settings: API keys, model, permissions, hooks, memory, MCP servers, sandbox, security, dual-model, UI options |
| `PermissionSettings` | Permission mode, allowed/denied tools, path rules, denied commands |
| `SandboxSettings` | OS-level network and filesystem restrictions via `srt` sandbox-runtime |
| `SecuritySettings` | AgentSys security layer toggle and model config |
| `DualModelSettings` | Primary + execution model routing configuration |
| `MemorySettings` | Memory system toggle, max files, max entrypoint lines |
| `load_settings()` / `save_settings()` | JSON-based persistence at `~/.opencortex/settings.json` |
| `paths.py` | XDG-like directory resolution: config, data, logs, sessions, tasks, feedback, cron, per-project |

Settings resolution order: CLI args → env vars → config file → defaults.

### 3.3 `api` — LLM Provider Clients

**Files:** `__init__.py`, `client.py`, `openai_client.py`, `copilot_client.py`, `codex_client.py`, `provider.py`, `registry.py`, `errors.py`, `usage.py`, `copilot_auth.py`

| Class | Description |
|---|---|
| `AnthropicApiClient` | Native Anthropic SDK wrapper with retry logic, OAuth support, and Claude attribution |
| `OpenAICompatibleClient` | OpenAI-compatible REST client (DashScope, DeepSeek, Gemini, MiniMax, Zhipu, custom endpoints). Handles message/tool format conversion between Anthropic and OpenAI schemas |
| `CopilotClient` | GitHub Copilot client wrapping `OpenAICompatibleClient` with Copilot-specific headers |
| `CodexApiClient` | OpenAI Codex subscription client using `chatgpt.com/backend-api/codex/responses` |
| `ProviderManager` | Preset provider profiles (Zhipu, MiniMax) + custom providers from `providers.json` |
| `ProviderRegistry` (`registry.py`) | 20+ provider specs with auto-detection by model name, API key prefix, or base URL keyword |
| `detect_provider()` | Runtime provider inference for UI/capability hints |
| `UsageSnapshot` | Token usage tracking (input + output) |
| Error hierarchy | `OpenCortexApiError` → `AuthenticationFailure`, `RateLimitFailure`, `RequestFailure` |

### 3.4 `engine` — Core Agentic Loop

**Files:** `__init__.py`, `query_engine.py`, `query.py`, `messages.py`, `stream_events.py`, `model_router.py`, `provider_manager.py`, `cost_tracker.py`

| Class/Function | Description |
|---|---|
| `QueryEngine` | Owns conversation history + tool-aware model loop. Manages submit/continue, model/client switching, security layer |
| `run_query()` | The core agentic loop: stream model response → execute tools → feed results back → repeat until done. Includes auto-compaction, Judge Agent for turn extension, and concurrent multi-tool execution |
| `QueryContext` | Shared context for a query run (API client, tools, permissions, hooks, security) |
| `ConversationMessage` | Pydantic model for user/assistant messages with content blocks |
| `ContentBlock` | Union type: `TextBlock`, `ImageBlock`, `ToolUseBlock`, `ToolResultBlock` |
| `StreamEvent` | Union type: `AssistantTextDelta`, `AssistantTurnComplete`, `ToolExecutionStarted/Completed`, `ErrorEvent`, `StatusEvent` |
| `ModelRouter` | Dual-model routing with task-type detection, complexity heuristics, budget control, and fallback logic |
| `CostTracker` | Per-session and per-model token usage aggregation |

### 3.5 `tools` — Built-in Tools

**Files:** `base.py`, `__init__.py`, plus 38 tool implementation files

| Tool | File | Description |
|---|---|---|
| `BaseTool` / `ToolRegistry` | `base.py` | Abstract base class and registry for all tools |
| `BashTool` | `bash_tool.py` | Shell command execution (sandbox-aware) |
| `FileReadTool` | `file_read_tool.py` | Read file contents with offset/limit |
| `FileWriteTool` | `file_write_tool.py` | Create/overwrite files |
| `FileEditTool` | `file_edit_tool.py` | String replacement editing |
| `NotebookEditTool` | `notebook_edit_tool.py` | Jupyter notebook cell editing |
| `GlobTool` | `glob_tool.py` | File pattern matching |
| `GrepTool` | `grep_tool.py` | Regex content search |
| `LspTool` | `lsp_tool.py` | Code intelligence (symbols, definitions, references, hover) |
| `WebSearchTool` | `web_search_tool.py` | Web search with compact results |
| `WebFetchTool` | `web_fetch_tool.py` | Single page fetching |
| `AskUserQuestionTool` | `ask_user_question_tool.py` | Interactive follow-up questions |
| `AgentTool` | `agent_tool.py` | Spawn sub-agent tasks |
| `SendMessageTool` | `send_message_tool.py` | Send follow-up to running agents |
| `TeamCreateTool` / `TeamDeleteTool` | `team_*.py` | In-memory team management |
| `TaskCreateTool` / `TaskGetTool` / `TaskListTool` / `TaskStopTool` / `TaskOutputTool` / `TaskUpdateTool` | `task_*.py` | Background task lifecycle management |
| `CronCreate/List/Delete/Toggle/RemoteTrigger` | `cron_*.py` | Cron job management |
| `EnterWorktreeTool` / `ExitWorktreeTool` | `worktree_*.py` | Git worktree management |
| `EnterPlanModeTool` / `ExitPlanModeTool` | `*_plan_mode_tool.py` | Permission mode switching |
| `McpToolAdapter` | `mcp_tool.py` | Adapter for MCP server tools |
| `McpAuthTool` | `mcp_auth_tool.py` | MCP server auth configuration |
| `ListMcpResourcesTool` / `ReadMcpResourceTool` | `mcp_resource_*.py` | MCP resource access |
| `SkillTool` | `skill_tool.py` | Load skill instructions |
| `ToolSearchTool` | `tool_search_tool.py` | Search available tools by name/description |
| `ConfigTool` | `config_tool.py` | Read/update settings |
| `BriefTool` | `brief_tool.py` | Text shortening |
| `SleepTool` | `sleep_tool.py` | Short-duration pause |
| `TodoWriteTool` | `todo_write_tool.py` | Markdown checklist append |

`create_default_tool_registry()` registers all 38 built-in tools plus any MCP-provided tools.

### 3.6 `permissions` — Permission System

**Files:** `__init__.py`, `checker.py`, `modes.py`

| Component | Description |
|---|---|
| `PermissionMode` (enum) | `DEFAULT` (confirm mutations), `PLAN` (block mutations), `FULL_AUTO` (allow all) |
| `PermissionChecker` | Evaluates tool calls: sensitive-path protection (hardcoded `.ssh`, `.aws`, `.gnupg`, etc.), explicit allow/deny lists, path rules, command deny patterns, mode-based logic |
| `SENSITIVE_PATH_PATTERNS` | Always-denied credential paths that cannot be overridden by user config |

### 3.7 `security` — Security Layer (AgentSys)

**Files:** `__init__.py`, `security_layer.py`, `validator.py`, `sanitizer.py`, `privilege.py`, `sandbox.py`, `prompts.py`

| Component | Description |
|---|---|
| `SecurityLayer` | Orchestrates Validator + Sanitizer + PrivilegeAssignor. Each can be independently toggled |
| `ToolCallValidator` | LLM-based pre-execution check: is this tool call safe and necessary? |
| `ToolResultSanitizer` | LLM-based post-execution: remove injected instructions from tool output |
| `ToolPrivilegeAssignor` | Classifies tool privilege levels (e.g., Command vs. Read) |
| `SandboxRuntime` | Adapter for `srt` sandbox-runtime CLI — OS-level network/filesystem isolation |

### 3.8 `hooks` — Lifecycle Hooks

**Files:** `__init__.py`, `schemas.py`, `executor.py`, `loader.py`, `events.py`, `types.py`, `hot_reload.py`

| Component | Description |
|---|---|
| `HookDefinition` | Union of `CommandHookDefinition`, `PromptHookDefinition`, `HttpHookDefinition`, `AgentHookDefinition` |
| `HookExecutor` | Dispatches matching hooks for lifecycle events |
| `HookReloader` | Hot-reload hook definitions from disk on change |
| Hook types | **Command**: run shell command. **HTTP**: POST to endpoint. **Prompt**: LLM validation (fast). **Agent**: LLM validation (thorough) |

### 3.9 `mcp` — Model Context Protocol

**Files:** `__init__.py`, `client.py`, `config.py`, `types.py`

| Component | Description |
|---|---|
| `McpClientManager` | Manages MCP server connections (stdio, HTTP, WebSocket transports). Exposes tools and resources |
| `McpStdioServerConfig` / `McpHttpServerConfig` / `McpWebSocketServerConfig` | Server configuration models |
| `McpToolInfo` / `McpResourceInfo` / `McpConnectionStatus` | Runtime state models |
| `load_mcp_server_configs()` | Merges settings + plugin MCP configs |

### 3.10 `mcp_server` — MCP Server (OpenCortex as MCP)

**Files:** `__init__.py`

Exposes OpenCortex as an MCP server so other agents can use its tools.

### 3.11 `prompts` — System Prompt Assembly

**Files:** `__init__.py`, `system_prompt.py`, `context.py`, `environment.py`, `claudemd.py`

| Component | Description |
|---|---|
| `build_system_prompt()` | Base system prompt + environment info (OS, shell, git, date, Python) |
| `build_runtime_system_prompt()` | Full assembly: base + skills + CLAUDE.md + issue context + memory |
| `EnvironmentInfo` | Runtime environment detection (OS, shell, cwd, git, Python version) |

### 3.12 `memory` — Project Memory

**Files:** `__init__.py`, `manager.py`, `store.py`, `memdir.py`, `paths.py`, `scan.py`, `search.py`, `types.py`, `decay.py`, `dream.py`, `user_profile.py`

| Component | Description |
|---|---|
| `add_memory_entry()` / `remove_memory_entry()` | Create/delete `.opencortex/memory/` markdown files |
| `FtsMemoryStore` | SQLite FTS5-backed store with trigram tokenizer (CJK support) for fast full-text search |
| `find_relevant_memories()` | Search memory files by user prompt relevance |
| `load_memory_prompt()` | Load MEMORY.md index for system prompt injection |
| `MemoryDecay` / `DreamEngine` / `UserProfile` | Advanced memory features (decay scoring, memory consolidation, user preferences) |

### 3.13 `plugins` — Plugin System

**Files:** `__init__.py`, `loader.py`, `installer.py`, `schemas.py`, `types.py`, `bundled/`

| Component | Description |
|---|---|
| `PluginManifest` | Plugin metadata (name, description, version) |
| `LoadedPlugin` | Loaded plugin with contributed skills, commands, agents, hooks, MCP servers |
| `discover_plugin_paths()` | Scan user + project plugin directories |
| `load_plugins()` | Parse manifests, load skills/commands/agents/hooks from each plugin |
| `install_plugin_from_path()` / `uninstall_plugin()` | CLI-side plugin management |

### 3.14 `skills` — Skill System

**Files:** `__init__.py`, `loader.py`, `registry.py`, `types.py`, `extractor.py`, `generator.py`, `trajectory.py`, `bundled/`

| Component | Description |
|---|---|
| `SkillDefinition` | Skill data model (name, description, content, source) |
| `SkillRegistry` | Store loaded skills by name |
| `load_skill_registry()` | Discover skills from user dir, project dir, and plugins |
| Built-in skills | `commit`, `debug`, `diagnose`, `plan`, `review`, `simplify`, `test` |

### 3.15 `swarm` — Multi-Agent Orchestration

**Files:** `__init__.py`, `types.py`, `agent_definitions.py`, `coordinator_mode.py`, `guardian.py`, `in_process.py`, `lifecycle.py`, `lightweight_executor.py`, `lockfile.py`, `mailbox.py`, `message_bus.py`, `permission_sync.py`, `registry.py`, `spawn_utils.py`, `subprocess_backend.py`, `task_tier.py`, `team_lifecycle.py`, `worktree.py`, `zellij_backend.py`

| Component | Description |
|---|---|
| `AgentDefinition` | Agent metadata parsed from YAML/Markdown frontmatter (name, model, tools, effort, isolation) |
| `BackendRegistry` / `SubprocessBackend` | Backend abstraction for spawning agent processes |
| `TeammateMailbox` | File-based inter-agent message passing |
| `SwarmPermissionRequest/Response` | Permission synchronization between agents |
| `TeamRegistry` | In-memory team management |
| `Guardian` | Agent health monitoring |
| `ZellijBackend` | Zellij terminal multiplexer integration for visual pane management |

### 3.16 `tasks` — Background Task Management

**Files:** `__init__.py`, `manager.py`, `types.py`, `local_agent_task.py`, `local_shell_task.py`, `stop_task.py`

| Component | Description |
|---|---|
| `BackgroundTaskManager` | Create, monitor, and manage shell/agent subprocess tasks |
| `TaskRecord` | Runtime task representation (id, type, status, output file) |
| `TaskType` | `local_bash`, `local_agent`, `remote_agent`, `in_process_teammate` |

### 3.17 `channels` — Chat Platform Integration

**Files:** `__init__.py`, `adapter.py`, `bus/events.py`, `bus/queue.py`, `impl/base.py`, `impl/manager.py`, `impl/telegram.py`, `impl/discord.py`, `impl/slack.py`, `impl/feishu.py`, `impl/dingtalk.py`, `impl/email.py`, `impl/qq.py`, `impl/matrix.py`, `impl/whatsapp.py`, `impl/mochat.py`

| Component | Description |
|---|---|
| `MessageBus` | Async queue for inbound/outbound messages |
| `BaseChannel` | Abstract adapter for chat platforms |
| `ChannelManager` | Manages multiple channel adapters |
| `ChannelBridge` | Connects MessageBus → QueryEngine for bidirectional message flow |
| Platform adapters | Telegram, Discord, Slack, Feishu, DingTalk, Email, QQ, Matrix, WhatsApp, MoChat |

### 3.18 `bridge` — Session Bridge (Deprecated → `a2a`)

**Files:** `__init__.py`, `manager.py`, `session_runner.py`, `types.py`, `work_secret.py`

Manages spawned bridge sessions for external integration. Deprecated in favor of the A2A protocol.

### 3.19 `a2a` — Agent-to-Agent Protocol

**Files:** `__init__.py`, `server.py`, `agent_card.py`, `task_manager.py`, `context_layer.py`, `executor.py`

| Component | Description |
|---|---|
| `A2AServer` | FastAPI + SSE server implementing the A2A protocol (`/a2a/agent-card`, `/a2a/tasks`) |
| `TaskManager` | Task lifecycle management (create, process, status) |
| `ContextLayer` | L1 (tool output summarization) and L2 (conversation summarization) context management |
| `TaskExecutor` | Executes tasks against the QueryEngine |

### 3.20 `orchestration` — Task Orchestration Engine

**Files:** `__init__.py`, `engine.py`, `planner.py`, `scheduler.py`, `tracker.py`, `aggregator.py`, `types.py`

| Component | Description |
|---|---|
| `OrchestrationEngine` | End-to-end task decomposition and execution |
| `TaskPlanner` | Decomposes tasks into sub-task graphs (rule-based or LLM-based) |
| `TaskScheduler` | Schedules sub-task execution with dependency management |
| `TaskTracker` | Tracks task state transitions |
| `ResultAggregator` | Aggregates results from completed sub-tasks |

### 3.21 `auth` — Authentication

**Files:** `__init__.py`, `flows.py`, `manager.py`, `storage.py`, `external.py`

| Component | Description |
|---|---|
| `ApiKeyFlow` / `BrowserFlow` / `DeviceCodeFlow` | Authentication flow strategies |
| `store_credential()` / `load_credential()` | Encrypted credential persistence |
| `external.py` | Integration with Claude Code CLI OAuth tokens and Codex subscription tokens |

### 3.22 `api_server` — HTTP API Server

**Files:** `__init__.py`, `app.py`, `models.py`, `session_manager.py`

| Component | Description |
|---|---|
| FastAPI app | REST endpoints: query, session CRUD, status, A2A bridge |
| `SessionManager` | Server-side session state management |
| `QueryRequest/Response` | API models for the query endpoint |

### 3.23 `ui` — User Interface

**Files:** `__init__.py`, `app.py`, `runtime.py`, `react_launcher.py`, `backend_host.py`, `textual_app.py`, `input.py`, `output.py`, `permission_dialog.py`, `protocol.py`

| Component | Description |
|---|---|
| `RuntimeBundle` | Shared runtime assembly: API client, MCP, tools, engine, hooks, state, commands |
| `build_runtime()` | Factory for `RuntimeBundle` — the central wiring point |
| `launch_react_tui()` | Launches the React-based terminal UI |
| `run_backend_host()` | Headless backend mode for external UI connections |

### 3.24 `commands` — Slash Commands

**Files:** `__init__.py`, `registry.py`

| Component | Description |
|---|---|
| `SlashCommand` | Command registration (name, description, handler) |
| `CommandRegistry` | Registry for all slash commands |
| `create_default_command_registry()` | Registers 50+ built-in commands |

### 3.25 `state` — Application State

**Files:** `__init__.py`, `app_state.py`, `store.py`

| Component | Description |
|---|---|
| `AppState` | Shared mutable UI/session state (model, permissions, theme, cwd, provider, etc.) |
| `AppStateStore` | Reactive state store with change notification |

### 3.26 `services` — Background Services

**Files:** `__init__.py`, `cron.py`, `cron_scheduler.py`, `session_backend.py`, `session_storage.py`, `token_estimation.py`, `compact/__init__.py`, `lsp/__init__.py`, `oauth/__init__.py`

| Component | Description |
|---|---|
| `cron.py` / `cron_scheduler.py` | Cron job registry and daemon scheduler |
| `session_storage.py` | Session snapshot persistence (JSON, per-project directories) |
| `token_estimation.py` | Character-heuristic token estimation |
| `compact/` | Conversation compaction: microcompact (clear old tool results) + full LLM-based summarization + auto-compact on threshold |

### 3.27 `themes` — Theming

**Files:** `__init__.py`, `builtin.py`, `loader.py`, `schema.py`

Built-in and user-defined terminal themes.

### 3.28 `keybindings` — Key Bindings

**Files:** `__init__.py`, `default_bindings.py`, `loader.py`, `parser.py`, `resolver.py`

Configurable key bindings with conflict resolution.

### 3.29 `output_styles` — Output Formatting

**Files:** `__init__.py`, `loader.py`

Pluggable output style definitions.

### 3.30 `i18n` — Internationalization

**Files:** `i18n.py`

Command help translations for English and Chinese (简体中文). 60+ commands translated.

### 3.31 `platforms` — Platform Detection

**Files:** `platforms.py`

Detects OS (macOS, Linux, WSL, Windows) and capabilities (POSIX shell, tmux, sandbox, swarm mailbox).

### 3.32 `utils` — Utilities

**Files:** `__init__.py`, `shell.py`

`create_shell_subprocess()` — sandbox-aware shell process creation.

---

## 4. Data Flow

### 4.1 Interactive REPL Mode

```
User Input (keyboard)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  UI Layer (ui/)                                         │
│  React TUI / Textual → parse slash commands or prompts   │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  Command Dispatcher (commands/)                          │
│  If slash command → execute handler, skip engine         │
│  If prompt → forward to QueryEngine                      │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  System Prompt Assembly (prompts/)                       │
│  base prompt + environment + skills + CLAUDE.md          │
│  + issue context + memory                                │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  Query Engine (engine/query.py)                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  1. Auto-compact if approaching token limit     │    │
│  │  2. Send messages to LLM API client             │    │
│  │  3. Stream response events                      │    │
│  │     ├─ Text deltas → display to user            │    │
│  │     └─ Tool calls → execute tools               │    │
│  │  4. Permission check (permissions/)             │    │
│  │  5. Security check (security/) [optional]       │    │
│  │  6. Hook execution (hooks/)                     │    │
│  │  7. Feed tool results back to LLM               │    │
│  │  8. Repeat until LLM stops requesting tools     │    │
│  │     └─ Judge Agent: auto-extend turns if needed │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  Tool Execution (tools/)                                 │
│  38+ built-in tools + MCP-provided tools                 │
│  ├─ File operations (read, write, edit, glob, grep)     │
│  ├─ Shell execution (bash, sandbox-aware)                │
│  ├─ Code intelligence (LSP)                              │
│  ├─ Web access (search, fetch)                           │
│  ├─ Agent spawning (agent, team, task)                   │
│  ├─ Session management (cron, config, permissions)       │
│  └─ User interaction (ask_user, brief, sleep, todo)      │
└──────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  Output (ui/)                                            │
│  Stream events → formatted display in terminal           │
│  Session auto-saved to disk (services/session_storage)   │
└──────────────────────────────────────────────────────────┘
```

### 4.2 Channel Integration Flow

```
External Chat Platform (Telegram, Discord, Slack, …)
    │
    ▼
┌──────────────────────────────────────┐
│  Channel Adapter (channels/impl/)    │
│  Platform-specific webhook/polling   │
└──────────────┬───────────────────────┘
               │ InboundMessage
               ▼
┌──────────────────────────────────────┐
│  MessageBus (channels/bus/)          │
│  Async inbound/outbound queues       │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  ChannelBridge (channels/adapter.py) │
│  Consumes inbound → QueryEngine      │
│  Assembles reply → publishes outbound│
└──────────────────────────────────────┘
```

### 4.3 Multi-Agent (Swarm) Flow

```
Main Agent
    │
    ▼ AgentTool.execute()
┌──────────────────────────────────────┐
│  Agent Spawning (swarm/)             │
│  ├─ Parse AgentDefinition            │
│  ├─ Select backend (subprocess/      │
│  │   in_process/tmux/zellij)         │
│  ├─ Create worktree if needed        │
│  └─ Launch agent process/pane        │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Inter-Agent Communication           │
│  ├─ TeamMailbox (file-based)         │
│  ├─ SendMessageTool (follow-up)      │
│  └─ Permission Sync                  │
└──────────────────────────────────────┘
```

---

## 5. Feature Status

### 5.1 Implemented Features ✅

| Feature | Module | Status |
|---|---|---|
| Interactive REPL (React TUI) | `ui/` | ✅ Full |
| Non-interactive print mode | `ui/app.py` | ✅ Full |
| Multi-provider LLM support | `api/` | ✅ 20+ providers |
| Anthropic native client | `api/client.py` | ✅ Full |
| OpenAI-compatible client | `api/openai_client.py` | ✅ Full |
| GitHub Copilot OAuth | `api/copilot_client.py`, `api/copilot_auth.py` | ✅ Full |
| OpenAI Codex subscription | `api/codex_client.py` | ✅ Full |
| Dual-model routing | `engine/model_router.py` | ✅ Full |
| Auto-compaction (micro + full) | `services/compact/` | ✅ Full |
| Judge Agent (turn extension) | `engine/query.py` | ✅ Full |
| 38+ built-in tools | `tools/` | ✅ Full |
| Permission system (3 modes) | `permissions/` | ✅ Full |
| Sensitive path protection | `permissions/checker.py` | ✅ Full |
| Security layer (AgentSys) | `security/` | ✅ Full |
| Sandbox runtime integration | `security/sandbox.py` | ✅ Full |
| MCP client (stdio + HTTP) | `mcp/` | ✅ Full |
| MCP server (expose as MCP) | `mcp_server/` | ✅ Full |
| Plugin system | `plugins/` | ✅ Full |
| Skill system (7 built-in) | `skills/` | ✅ Full |
| Lifecycle hooks (4 types) | `hooks/` | ✅ Full |
| Hot-reload hooks | `hooks/hot_reload.py` | ✅ Full |
| Project memory (file + FTS) | `memory/` | ✅ Full |
| Session persistence | `services/session_storage.py` | ✅ Full |
| Background tasks (shell + agent) | `tasks/` | ✅ Full |
| Cron job scheduler | `services/cron.py` | ✅ Full |
| Chat platform channels (10) | `channels/` | ✅ Full |
| Channel bridge (bus → engine) | `channels/adapter.py` | ✅ Full |
| Multi-agent swarm (subprocess) | `swarm/` | ✅ Full |
| In-process agent teammate | `swarm/in_process.py` | ✅ Full |
| Agent mailbox (file-based) | `swarm/mailbox.py` | ✅ Full |
| Team management | `swarm/coordinator_mode.py` | ✅ Full |
| Zellij pane backend | `swarm/zellij_backend.py` | ✅ Full |
| Git worktree support | `tools/worktree_*.py` | ✅ Full |
| A2A protocol server | `a2a/` | ✅ Full |
| HTTP API server | `api_server/` | ✅ Full |
| Task orchestration engine | `orchestration/` | ✅ Full |
| Claude Code OAuth integration | `auth/external.py` | ✅ Full |
| 50+ slash commands | `commands/` | ✅ Full |
| Internationalization (en/zh) | `i18n.py` | ✅ Full |
| Platform detection | `platforms.py` | ✅ Full |
| Themes and keybindings | `themes/`, `keybindings/` | ✅ Full |
| Output styles | `output_styles/` | ✅ Full |
| LSP code intelligence | `services/lsp/`, `tools/lsp_tool.py` | ✅ Full |
| CLAUDE.md project instructions | `prompts/claudemd.py` | ✅ Full |
| Cost tracking (per-model) | `engine/cost_tracker.py` | ✅ Full |

### 5.2 Partially Implemented / Scaffolded Features 🔧

| Feature | Module | Notes |
|---|---|---|
| MCP WebSocket transport | `mcp/client.py` | Config model exists; not yet connected in `McpClientManager.connect_all()` |
| Memory decay scoring | `memory/decay.py` | Module exists; integration degree unclear |
| Dream engine (memory consolidation) | `memory/dream.py` | Module exists; integration degree unclear |
| User profile memory | `memory/user_profile.py` | Module exists; integration degree unclear |
| Tiered memory store | `memory/tiered_store.py` | Module exists; integration degree unclear |
| Skill trajectory extraction | `skills/trajectory.py` | Module exists; integration degree unclear |
| Skill generation | `skills/generator.py` | Module exists; integration degree unclear |
| OAuth service | `services/oauth/` | Placeholder `__init__.py` |
| LSP service | `services/lsp/` | Placeholder `__init__.py` |
| AuthManager | `auth/manager.py` | Disabled — depends on `ProviderProfile` not yet merged |
| Bundled plugins | `plugins/bundled/` | Placeholder `__init__.py` |
| Bundled skills | `skills/bundled/` | Placeholder `__init__.py` |

### 5.3 Not Yet Implemented 📋

| Feature | Description |
|---|---|
| Voice mode | Shell exists in i18n, but live voice auth/streaming is not configured |
| iTerm2 pane backend | `BackendType` includes `"iterm2"` but no implementation file found |
| tmux pane backend | `PaneBackendType` includes `"tmux"` but dedicated backend file not found |
| Token cost estimation ($) | `CostTracker` tracks tokens only, not dollar costs |
| Plugin marketplace | No remote plugin repository or search |
| Multi-turn session resume from any snapshot | Current resume loads latest only |
| Image/paste multimodal input in REPL | Image reading exists in `ImageBlock`, but REPL input path unclear |
| Streaming tool execution UI | Tool execution events emitted but visual feedback depends on TUI implementation |

---

## 6. Third-Party Dependencies

### 6.1 Core Dependencies (required)

| Package | Version | Purpose |
|---|---|---|
| `anthropic` | ≥0.40.0 | Anthropic SDK for native Claude API access |
| `openai` | ≥1.0.0 | OpenAI SDK for OpenAI-compatible providers (also used by Copilot client) |
| `pydantic` | ≥2.0.0 | Data validation and serialization (settings, messages, API models) |
| `typer` | ≥0.12.0 | CLI framework with sub-commands, options, and auto-completion |
| `rich` | ≥13.0.0 | Terminal formatting and output (used by Typer) |
| `textual` | ≥0.80.0 | TUI framework for the interactive terminal application |
| `prompt-toolkit` | ≥3.0.0 | Advanced terminal input handling |
| `httpx` | ≥0.27.0 | Async HTTP client (hooks, Copilot auth, MCP HTTP transport) |
| `websockets` | ≥12.0 | WebSocket support for MCP and real-time communication |
| `mcp` | ≥1.0.0 | Model Context Protocol SDK (client + server) |
| `pyyaml` | ≥6.0 | YAML parsing for plugin manifests and agent definitions |
| `watchfiles` | ≥0.20.0 | File watching for hot-reload of hooks |
| `croniter` | ≥2.0.0 | Cron expression parsing and scheduling |
| `pyperclip` | ≥1.9.0 | Clipboard access for copy command |

### 6.2 Framework Dependencies (used by api_server and a2a)

| Package | Purpose |
|---|---|
| `fastapi` | HTTP API server and A2A protocol server |
| `sse-starlette` | Server-Sent Events for A2A streaming |
| `uvicorn` | ASGI server (implicit for FastAPI) |

### 6.3 Development Dependencies

| Package | Purpose |
|---|---|
| `pytest` | Testing framework |
| `pytest-asyncio` | Async test support |
| `pytest-cov` | Coverage reporting |
| `pexpect` | Process interaction testing |
| `ruff` | Linting and formatting |
| `mypy` | Static type checking |

### 6.4 Optional Runtime Dependencies

| Package | Purpose |
|---|---|
| `distro` | Linux distribution detection (used by `prompts/environment.py` with fallback) |
| `srt` (sandbox-runtime) | OS-level sandboxing for shell commands (external CLI tool) |

### 6.5 Python Version

Requires **Python ≥ 3.10** (targets 3.11 for type checking).

---

## 7. Codebase Statistics

| Metric | Value |
|---|---|
| Top-level modules | 32 |
| Python source files (src/) | ~150 |
| Built-in tools | 38 |
| Slash commands | 50+ |
| Supported LLM providers | 20+ |
| Chat platform adapters | 10 |
| Supported languages (i18n) | 2 (en, zh) |
| Permission modes | 3 (default, plan, full_auto) |
| Hook types | 4 (command, http, prompt, agent) |
| Agent backend types | 5 (subprocess, in_process, tmux, iterm2, zellij) |
