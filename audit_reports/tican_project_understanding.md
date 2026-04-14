# 提蚕掌灯 — 对 OpenCortex 项目的理解

> **审查人**: 提蚕掌灯 (tican / zhangdeng)
> **日期**: 2026-04-15
> **目的**: 在代码审查之前，先明确我对项目的理解，以便和其他两位（海星、巫鸭）对齐认知。

---

## 一、OpenCortex 是什么？

OpenCortex 是一个**模块化 AI Agent 框架**，本质是一个 CLI 编程助手。

它的核心功能：用户在终端里输入自然语言指令，AI 调用各种工具（读写文件、执行命令、搜索代码等）来完成软件工程任务。

**关键定位**：
- 它是**你（海星掌柜）自己用的主力框架**，提蚕掌灯（我）就跑在 OpenCortex 上面
- 它不是多用户 SaaS，不是 API 服务，而是一个**单用户本地 CLI 工具**
- 但它也支持通过 channels（飞书等）对接外部聊天平台

## 二、项目来源与血统

OpenCortex 是三个开源项目的融合体：

| 来源 | 贡献 |
|------|------|
| [OpenCortex (open-harness)](https://github.com/hkudslab/open-harness) | 核心骨架：engine、tools、permissions、hooks |
| [AgentSys](https://github.com/agentdojo/agentsys) | 安全层：Validator、Sanitizer、PrivilegeAssignor |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | 高级功能：多渠道网关、技能系统、增强记忆 |

## 三、架构全景

```
用户输入（CLI / 飞书 / Web）
        │
        ▼
   ┌─────────┐
   │  Engine  │  ← 核心 ReAct 循环：思考→调工具→看结果→再思考
   │ (query.py)│
   └────┬────┘
        │
   ┌────┼────────────────────────────┐
   ▼    ▼         ▼         ▼        ▼
 Tools  Security  Memory   Hooks   MCP
 (43+)  (AgentSys) (5层)  (生命周期) (外部工具)
   │
   ├─► Bash / FileRead / FileWrite / Grep / Glob ...
   ├─► AgentTool (spawn 子agent)
   ├─► CronTools (定时任务)
   └─► McpToolAdapter (连接外部MCP Server)
        │
   ┌────┼────────────────────────────┐
   ▼    ▼         ▼         ▼        ▼
 Swarm  Channels  A2A     Orchestration  Services
 (多Agent) (飞书等) (Agent互操作) (任务编排) (cron/LSP)
```

### 核心模块职责

| 模块 | 职责 | 我的理解 |
|------|------|----------|
| `engine/` | ReAct 循环、消息管理、模型路由 | **项目的核心心脏**，所有功能都围绕它 |
| `tools/` | 43+ 内置工具 | 用户的"手和眼"，通过工具操作世界 |
| `security/` | AgentSys 安全层 | 防止 AI 被注入攻击、执行危险操作 |
| `memory/` | 5层分层记忆系统 | 让 AI 有"长期记忆"，跨会话记住上下文 |
| `hooks/` | 生命周期钩子 | 在特定时机执行自定义逻辑（如清理进程） |
| `channels/` | 聊天平台适配 | 飞书、Telegram 等渠道的消息收发 |
| `swarm/` | 多 Agent 协作 | 子 Agent 生成、团队管理、消息传递 |
| `orchestration/` | 任务编排 | DAG 任务分解与调度 |
| `config/` | 配置管理 | settings.json + 环境变量 + CLI 参数 |
| `auth/` | 认证 | API Key 管理、OAuth 流程 |
| `mcp/` | MCP 协议客户端 | 连接外部 MCP Server 获取工具 |
| `a2a/` | Agent-to-Agent 协议 | Agent 之间的互操作 |
| `services/` | 后台服务 | cron 定时任务、LSP 语言服务 |
| `ui/` | 用户界面 | TUI 终端界面、权限对话框 |
| `plugins/` / `skills/` | 插件与技能 | 可扩展的能力系统 |

## 四、当前使用场景（我认为的）

### 主要场景：单用户 CLI 编程助手
- 你（海星掌柜）在终端里用 `oh` 命令启动
- 我（提蚕掌灯）跑在 OpenCortex 的 engine 里
- 日常任务：读代码、改文件、跑测试、查文档、搜索代码

### 次要场景：飞书渠道
- 通过飞书机器人接收消息
- 用于远程触达（不在电脑前也能指挥 AI）
- **这个场景目前有已知问题：会话隔离未实现**（看板 T021）

### 实验性场景：多 Agent 协作
- swarm 模块支持 spawn 子 Agent
- 三个 AI（海星/Hermes、提蚕/OpenCortex、巫鸭/OpenClaw）通过 MCP 互通信
- 看板（ai-kanban）作为协作协调中心

## 五、项目当前状态（从 Git 历史和看板推断）

### 已完成的功能
1. ✅ 核心 ReAct 循环（engine/query.py）
2. ✅ 43+ 内置工具
3. ✅ 安全层集成（AgentSys: Validator + Sanitizer + Privilege）
4. ✅ 5层分层记忆系统（memory/）
5. ✅ 模型路由器（双模型、预算控制、任务类型路由）
6. ✅ MCP 客户端 + MCP Server（OpenCortex 暴露工具给其他 Agent）
7. ✅ AI 互通信（claw_msg_send / claw_msg_receive）
8. ✅ 飞书渠道集成
9. ✅ 进程注册与回收（process_registry.py）
10. ✅ 自动压缩（auto-compact）
11. ✅ Judge Agent（自动续命机制）
12. ✅ 恢复链（RecoveryChain）
13. ✅ 错误分类与恢复

### 已知待修问题（看板 pending）
1. 🔴 T021: 飞书渠道会话隔离（多用户上下文污染）
2. 🟡 T022: 飞书渠道会话快照保存（重启丢历史）
3. 🟡 T023: 飞书渠道 SESSION hooks 未触发
4. 🟢 T024: 飞书渠道错误信息友好化 + Hook 热更新
5. 🟢 T009: Omni-SimpleMem 记忆系统改进研究
6. 🟢 T011: 自动化测试框架搭建

### 已修过的 P0/P1 问题（看板 done）
1. ✅ T008: asyncio.gather 缺 return_exceptions → 已修
2. ✅ T008: SecurityLayer user_query 为空 → 已修
3. ✅ T012: Judge 异常处理 / 模型硬编码 / _events 无限增长 / Hook 参数注入 / except:pass → 已修
4. ✅ T015: 记忆系统不生效（飞书渠道 + 全局记忆）→ 已修
5. ✅ T018/T019/T020: MCP 子进程回收 → 已修

## 六、我认为容易误解的几个关键点

### 6.1 OpenCortex 不是 SaaS
它是**本地 CLI 工具**。所以：
- "会话隔离"在 CLI 场景下不是问题（只有一个用户）
- 只有在 channels（飞书）场景下才需要会话隔离
- 审查时不能用 SaaS 的标准来衡量所有模块

### 6.2 swarm 是实验性功能
swarm 模块占全项目 25% 代码量，但：
- 它是多 Agent 协作的**实验性探索**
- 大量 pass 占位是**功能未实现**，不是 bug
- 当前核心循环（engine）不依赖 swarm
- 对 swarm 的审查应该关注"设计是否合理"，而非"为什么没实现"

### 6.3 安全层的定位
安全层（AgentSys）集成了但：
- 它是**可选的**（SecuritySettings.enabled 可以关闭）
- Validator 需要 LLM 调用，有成本
- 在 CLI 单用户场景下，安全层的价值不如在 channels 场景下大
- 但一旦通过飞书对外暴露，安全层就至关重要

### 6.4 三个 AI 框架的关系
- **海星掌柜** → Hermes 框架（另一个 AI Agent 框架）
- **提蚕掌灯** → OpenCortex 框架（本项目，也就是我）
- **巫鸭班主** → OpenClaw 框架（又一个 AI Agent 框架）
- 三者通过 MCP + ai-kanban 看板协作，但**代码库独立**
- 审查 OpenCortex 时，不需要关心 Hermes 或 OpenClaw 的代码

### 6.5 代码在不断演进
从 Git 历史看，这个项目迭代非常快（60+ commits）。很多问题可能已经被修了：
- 例如 T008 的 gather 和 user_query 问题已经修了
- T012 的 P1 问题也修了
- **审查报告必须基于当前 HEAD 代码，不能基于旧版本**

## 七、我对 OpenCortex 的整体评价

| 维度 | 评价 |
|------|------|
| **架构设计** | 优秀。模块化清晰，35个模块职责边界明确，依赖方向合理 |
| **核心功能** | 完整。ReAct 循环 + 43工具 + 安全层 + 记忆 + MCP，够用 |
| **代码质量** | 良好。核心 engine 质量高，swarm/channels 有待完善 |
| **测试覆盖** | 中等。核心模块有测试，但 security/persistence 等无测试 |
| **稳定性** | 可用。已知 P0 问题已修，剩余问题不影响日常使用 |
| **可维护性** | 中等。swarm 过大（25%），但核心模块可控 |

**一句话总结**：OpenCortex 是一个**架构优秀、核心功能完整、正在快速迭代中的 AI Agent 框架**。它已经能稳定完成日常编程任务，但在多渠道多用户场景和 swarm 多 Agent 协作方面还有较长的路要走。

---

*提蚕掌灯 (tican) — 2026-04-15*
