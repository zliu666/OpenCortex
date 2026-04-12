# Hermes Agent 深度架构分析 vs OpenCortex

> 分析日期：2026-04-11
> 分析范围：Hermes Agent (813 Python 文件, ~46MB) vs OpenCortex (230 Python 文件, ~3.6MB)

---

## 目录

1. [Hermes 核心架构拆解](#1-hermes-核心架构拆解)
2. [对比分析表](#2-对比分析表)
3. [关键发现和建议](#3-关键发现和建议)

---

## 1. Hermes 核心架构拆解

### 1.1 Agent 核心 (agent/)

#### A. 上下文引擎 — `agent/context_engine.py` (184行)

**设计理念**：抽象基类 + 插件化替换，这是整个上下文管理的核心抽象层。

```python
class ContextEngine(ABC):
    # 核心接口
    @abstractmethod def update_from_response(usage)     # 从 API 响应更新 token 计数
    @abstractmethod def should_compress(prompt_tokens)   # 判断是否需要压缩
    @abstractmethod def compress(messages, current_tokens) -> messages  # 执行压缩

    # 可选：工具暴露
    def get_tool_schemas()       # 引擎可暴露工具给 agent（如 lcm_grep）
    def handle_tool_call()       # 处理工具调用

    # 生命周期
    def on_session_start()       # 会话开始
    def on_session_end()         # 会话真正结束（不是每轮）
    def on_session_reset()       # /new 或 /reset

    # 模型切换
    def update_model()           # 切换模型时更新 context_length 和 threshold
```

**关键设计**：
- **策略模式**：通过 `config.yaml` 的 `context.engine` 选择引擎，默认 `compressor`，支持第三方（如 LCM）
- **工具暴露**：引擎可以向 agent 暴露额外工具（LCM 引擎暴露 `lcm_grep`、`lcm_describe`）
- **生命周期钩子**：区分 session 真正结束 vs 每轮结束
- **模型切换支持**：`update_model()` 动态调整 threshold

**OpenCortex 对应**：`services/compact/__init__.py` (492行) — 无抽象层，直接实现 microcompact + full compact，没有引擎替换能力。

---

#### B. 上下文压缩器 — `agent/context_compressor.py` (766行)

**算法**：
1. **Tool Output Pruning**（廉价预扫）：替换旧 tool 结果为占位符，用 token budget 代替固定消息数
2. **Head/Tail 保护**：保护前 N 条消息（system prompt + 首轮）+ 尾部 token budget
3. **结构化 LLM 摘要**：使用辅助模型（便宜/快速）生成摘要
4. **迭代摘要更新**：多次压缩时保留前次摘要，增量更新

**核心参数**：
```python
threshold_percent: float = 0.50     # 压缩触发阈值
protect_first_n: int = 3            # 保护前 N 条
tail_token_budget: int              # 尾部 token 预算
max_summary_tokens: int             # 最大摘要 token（context_length * 5%，上限 12K）
summary_target_ratio: float = 0.20  # 摘要目标比例
```

**对比 OpenCortex**：
- OpenCortex 有 microcompact（清除旧 tool 结果）和 full compact（LLM 摘要）
- 但缺少：迭代摘要更新、token-budget tail 保护、按比例缩放的摘要预算
- OpenCortex 的摘要提示词更详细（Claude Code 风格），但引擎架构更简单

---

#### C. Anthropic 适配器 — `agent/anthropic_adapter.py` (1410行)

**覆盖范围极广**：
- 3 种认证方式：API Key (`sk-ant-api*`)、OAuth (`sk-ant-oat*`/JWT)、Claude Code credentials
- 自动检测 Claude Code 版本（防止 OAuth 拒绝旧版本）
- Thinking budget 配置（xhigh/high/medium/low）
- Fast mode beta 支持（Opus 4.6 ~2.5x 吞吐）
- 每个模型独立的最大输出 token 限制表（Claude 3 到 4.6 全覆盖）
- MiniMax Anthropic 兼容端点适配

**OpenCortex 对应**：`api/client.py`、`api/provider.py` — 通用 API 客户端，没有深度适配特定提供商

---

#### D. 辅助客户端 — `agent/auxiliary_client.py` (2485行)

**这是最令人印象深刻的模块之一**。一个统一的辅助 LLM 路由器，解决所有"旁路任务"的模型选择问题。

**支持的任务类型**：
- 文本任务：上下文压缩、session 搜索、web 提取、vision 分析
- 多模态/视觉任务

**路由链（文本）**：
```
OpenRouter → Nous Portal → Custom endpoint → Codex OAuth → Native Anthropic → Direct providers (z.ai/Kimi/MiniMax) → None
```

**支付耗尽自动降级**：HTTP 402 或信用额度错误时，自动尝试下一个提供商。

**OpenCortex 对应**：`engine/model_router.py` — 简单的模型路由，没有多提供商降级链和支付耗尽处理

---

#### E. 凭证池 — `agent/credential_pool.py` (1319行)

**企业级多凭证管理**：
- 4 种选择策略：`fill_first`、`round_robin`、`random`、`least_used`
- 凭证状态追踪：`ok`、`exhausted`，含错误码、冷却时间
- 429/402 自动冷却（1小时），支持提供商特定重置时间戳
- Provider-specific 运行时 URL 解析（Nous 使用 `inference_base_url`）
- 持久化 JSON 存储，支持自定义端点

**OpenCortex 对应**：`auth/manager.py` — 基础认证管理，无多凭证池

---

#### F. ACP 客户端 — `agent/copilot_acp_client.py`

**将 GitHub Copilot ACP 包装为 OpenAI 兼容后端**：
- JSON-RPC over stdio 协议
- 消息格式转换（OpenAI → ACP prompt）
- 从文本中提取 tool calls（`<tool_call {...}>` 格式）
- 900秒超时，支持环境变量配置

**OpenCortex 对应**：`api/copilot_client.py` — 类似功能但更简单

---

#### G. 错误分类器 — `agent/error_classifier.py` (809行)

**结构化的 API 错误分类体系**：

```
FailoverReason 枚举：
├── auth / auth_permanent      # 认证（瞬时 vs 永久）
├── billing / rate_limit       # 计费/限流
├── overloaded / server_error  # 服务端
├── timeout                    # 传输
├── context_overflow / payload_too_large  # 上下文/载荷
├── model_not_found            # 模型
├── format_error               # 请求格式
├── thinking_signature / long_context_tier  # Anthropic 特定
└── unknown                    # 兜底
```

**每个分类带恢复提示**：`retryable`、`should_compress`、`should_rotate_credential`、`should_fallback`

**OpenCortex 对应**：`api/errors.py` — 简单的错误定义，无分类恢复策略

---

#### H. 显示系统 — `agent/display.py`

**Skin-aware 终端渲染**：
- 皮肤系统（`skin_engine`）支持亮/暗主题
- Diff 渲染（从皮肤获取颜色，支持 ANSI 256色）
- 工具预览（一行摘要工具调用参数）
- 文件编辑快照 + diff 生成
- Emoji 系统（每工具可配）

**OpenCortex 对应**：`themes/` 模块 — 有主题系统但缺少 diff 渲染和工具预览

---

### 1.2 状态管理

#### `hermes_state.py` (1238行) — SQLite + FTS5

**核心设计**：
- **SQLite WAL 模式**：支持并发读 + 单写（gateway 多平台场景）
- **FTS5 全文搜索**：跨所有 session 消息的快速搜索
- **Schema 版本迁移**：6 个版本，自动迁移
- **写竞争优化**：应用层随机 jitter 重试（20-150ms），打破 SQLite 内置确定性退避的 convoy 效应
- **Session 链**：压缩触发时通过 `parent_session_id` 链分割 session
- **成本追踪**：input/output/cache_read/cache_write/reasoning tokens + billing info
- **定期 WAL checkpoint**：每 50 次写操作尝试 PASSIVE checkpoint

```sql
-- 核心表结构
sessions: id, source, user_id, model, system_prompt, parent_session_id,
          started_at, ended_at, title, billing_*, cost_*
messages: id, session_id, role, content, tool_call_id, tool_calls,
          tool_name, timestamp, token_count, finish_reason, reasoning
messages_fts: FTS5 全文搜索虚拟表
```

**OpenCortex 对应**：`engine/state_store.py` (40行) — 极简的内存 Observable Store，无持久化

---

### 1.3 工具系统

#### 工具规模对比

| | Hermes | OpenCortex |
|---|---|---|
| 工具 Python 文件 | 69 个 | 43 个 |
| 工具注册方式 | 单例 `registry.register()` 在模块级别 | `BaseTool` 子类 + `ToolRegistry` |

**Hermes 工具注册表** (`tools/registry.py`)：
- 每个 ToolEntry 包含：name, toolset, schema, handler, check_fn, requires_env, is_async, description, emoji, max_result_size_chars
- 工具集 (toolset) 分组 + 按条件启用/禁用
- 动态工具（MCP 发现）支持 deregister/register

**Hermes 独有的工具**（OpenCortex 缺少）：
- `browser_camofox.py` — 反指纹浏览器（Camoufox Firefox fork + C++ 指纹伪装）
- `browser_providers/` — 4 个浏览器后端（browser_use, browserbase, camofox, firecrawl）
- `code_execution_tool.py` — 代码执行沙箱
- `environments/` — 8 种执行环境（local, docker, modal, daytona, ssh, singularity...）
- `homeassistant_tool.py` — 智能家居控制
- `image_generation_tool.py` — 图像生成
- `mixture_of_agents_tool.py` — MoA（混合专家）
- `rl_training_tool.py` — 强化学习训练
- `transcription_tools.py` — 语音转文字
- `tts_tool.py` — 文字转语音
- `voice_mode.py` — 语音模式
- `web_tools.py` — 网页搜索/提取
- `vision_tools.py` — 视觉分析
- `url_safety.py` — URL 安全检查
- `tirith_security.py` — 安全扫描
- `osv_check.py` — 开源漏洞检查

---

#### 浏览器自动化 — `tools/browser_camofox.py` (592行)

**Camofox 方案**：
- 基于 Camoufox（Firefox fork + C++ 指纹伪装）
- REST API 接口（独立 Node.js 服务）
- Session 管理（per-task 隔离）
- 持久化 profile（跨重启保持浏览器状态）
- VNC 支持（可视化调试）
- Identity 管理（反指纹）

**OpenCortex 对应**：`tools/browser_tool.py` (251行) — Playwright headless Chromium，基础功能

---

#### 权限审批 — `tools/approval.py` (916行)

**多层安全系统**：
- 26+ 种危险命令模式检测（rm -rf /, fork bomb, pipe to shell, git force push...）
- Context-var 感知的 session 隔离（gateway 多线程安全）
- 智能审批（LLM 辅助判断低风险命令）
- 永久白名单（config.yaml 持久化）
- Sensitive write target 检测（SSH 路径、.env 文件、/etc/）

**OpenCortex 对应**：`permissions/checker.py` (146行) — 基础权限检查

---

### 1.4 网关 (gateway/)

#### `gateway/config.py` (1064行)

**企业级多平台配置**：

```
Platform 枚举：18 个平台
├── LOCAL, TELEGRAM, DISCORD, WHATSAPP, SLACK, SIGNAL
├── MATTERMOST, MATRIX, HOMEASSISTANT, EMAIL, SMS
├── DINGTALK, API_SERVER, WEBHOOK, FEISHU, WECOM
└── WEIXIN, BLUEBUBBLES
```

- `HomeChannel`：每个平台的默认投递目标
- `SessionResetPolicy`：4 种模式（daily/idle/both/none），含通知配置
- `PlatformConfig`：每个平台的独立配置（token、API key、home channel）
- 消息长度限制 + 回复线程模式

#### `gateway/delivery.py` (100行)

**灵活的消息投递路由**：
- 格式：`"telegram"` → home channel，`"telegram:123456"` → specific chat
- 支持 `origin`（回源）、`local`（本地文件）
- 自动截断到平台限制（4000 chars）

**OpenCortex 对应**：`channels/` 模块 — 13 个平台实现，结构更规范但功能相当

---

### 1.5 MCP 和插件

#### `mcp_serve.py` (867行)

**Hermes 作为 MCP Server**：
- 向 Claude Code/Cursor/Codex 暴露对话工具
- 9+1 工具：conversations_list, conversation_get, messages_read, attachments_fetch, events_poll, events_wait, messages_send, permissions_list_open, permissions_respond + channels_list
- 基于 FastMCP

**OpenCortex 对应**：`mcp/client.py` (259行) — 仅 MCP Client，无 MCP Server 能力

---

#### 插件系统 (`plugins/`)

**Hermes 插件结构**：
```
plugins/
├── context_engine/     # 上下文引擎插件接口
└── memory/             # 记忆插件（7 个实现！）
    ├── byterover/      # ByteRover 记忆
    ├── hindsight/      # Hindsight 记忆
    ├── holographic/    # 全息记忆（含 store/retrieval/holographic）
    ├── honcho/         # Honcho 记忆（含 CLI/client/session）
    ├── mem0/           # Mem0 记忆
    ├── openviking/     # OpenViking 记忆
    ├── retaindb/       # RetainDB 记忆
    └── supermemory/    # SuperMemory 记忆
```

**OpenCortex 对应**：`plugins/` — 有 plugin.json manifest 加载，但无插件类型分类

---

### 1.6 技能系统

**Hermes 技能规模**：78 个 SKILL.md，分 15+ 个类别

| 类别 | 技能数 | 示例 |
|------|--------|------|
| software-development | 6 | plan, systematic-debugging, TDD |
| creative | 8 | ascii-art, excalidraw, manim-video, p5js |
| mlops | 16 | vllm, llama-cpp, axolotl, unsloth |
| github | 6 | code-review, issues, pr-workflow |
| research | 5 | arxiv, blogwatcher, polymarket |
| productivity | 5 | google-workspace, notion, linear |
| apple | 4 | notes, reminders, findmy, imessage |
| gaming | 2 | minecraft, pokemon |
| smart-home | 1 | openhue |
| social-media | 1 | xitter |

**每个技能包含**：
- `SKILL.md` — 核心技能定义（prompt）
- `references/` — 参考文档（多文件）
- `scripts/` — 辅助脚本
- `templates/` — 模板文件

**OpenCortex 对应**：`skills/` — 框架完整（registry/loader/types/bundled/extractor/generator），但内置技能数量较少

---

## 2. 对比分析表

| 维度 | OpenCortex | Hermes | 差距评级 |
|------|-----------|--------|----------|
| **整体规模** | 230 py files, 3.6MB | 813 py files, 46MB | 🔴 3.5x |
| **状态管理** | 内存 Observable Store (40行) | SQLite + FTS5 + WAL + Schema迁移 (1238行) | 🔴 严重不足 |
| **上下文管理** | microcompact + full compact (492行) | 可插拔引擎 + 迭代摘要 + token budget (950行) | 🟡 架构可用，缺少高级特性 |
| **模型适配** | 通用 API client | Anthropic 深度适配 + 每模型输出限制 (1410行) | 🟡 可用但不够深 |
| **辅助客户端** | model_router | 7级降级链 + 支付耗尽处理 (2485行) | 🔴 严重不足 |
| **凭证管理** | auth/manager | 多凭证池 + 4种策略 + 冷却 (1319行) | 🔴 严重不足 |
| **工具系统** | 43个工具, BaseTool 抽象 | 69个工具, 工具集分组 + 条件启用 | 🟡 功能可用，数量差距 |
| **浏览器操作** | Playwright headless (251行) | 4后端 + Camofox反指纹 (592行) | 🟡 基础可用 |
| **MCP支持** | Client only (259行) | Client + Server (867行) | 🟡 缺 Server |
| **技能系统** | 框架完整 + 少量技能 | 78个技能 + references + scripts | 🟡 框架好，内容少 |
| **多平台网关** | 13个渠道实现 | 18个平台 + 投递路由 + Session重置策略 | 🟢 相当 |
| **插件系统** | manifest 加载 | 类型分类（context_engine/memory 7种） | 🟡 可用 |
| **错误处理** | api/errors.py | 结构化分类 + 恢复策略 (809行) | 🔴 严重不足 |
| **权限审批** | permissions/checker (146行) | 26+危险模式 + LLM辅助审批 (916行) | 🔴 严重不足 |
| **显示系统** | themes/ | Skin引擎 + Diff渲染 + 工具预览 | 🟡 可用 |
| **安全** | security/ 模块 | url_safety + tirith + osv_check | 🟡 覆盖更广 |
| **记忆系统** | 完整（decay/dream/memdir/tiered_store） | 7种第三方记忆插件 | 🟢 各有特色 |
| **Swarm/编排** | 完整（swarm/ + orchestration/） | delegate_tool + mixture_of_agents | 🟢 OpenCortex 更强 |
| **A2A协议** | 完整 A2A 实现 | 无 | 🟢 OpenCortex 独有 |
| **Hooks系统** | 完整 hooks 系统 | 无独立 hooks | 🟢 OpenCortex 独有 |

**差距评级说明**：
- 🔴 严重不足：缺少核心能力
- 🟡 可用但需加强：有基础框架，缺少高级特性
- 🟢 相当或领先：功能完整

---

## 3. 关键发现和建议

### 3.1 Hermes 最值得学习的 3 个设计

#### ① 可插拔上下文引擎 (Context Engine Plugin)

**为什么重要**：这是解决"长对话 token 管理不同方案"的最佳架构。不同的使用场景需要不同的上下文策略：
- 短任务：简单裁剪
- 长开发会话：结构化摘要 + 迭代更新
- 知识密集型：LCM（Latent Context Model）构建 DAG

**Hermes 做法**：
```python
# 通过 config.yaml 选择引擎
context:
  engine: "compressor"  # 或 "lcm" 或自定义插件名

# 引擎可以暴露工具给 agent
def get_tool_schemas() -> List[Dict]:  # 如 lcm_grep
def handle_tool_call(name, args) -> str:
```

**学习建议**：在 OpenCortex 的 `services/compact/` 基础上引入 `ContextEngine` ABC，保持现有 microcompact/full compact 作为默认实现。

---

#### ② 辅助客户端降级链 (Auxiliary Client Fallback Chain)

**为什么重要**：旁路任务（压缩、搜索、提取、视觉分析）不应该占用主模型配额。Hermes 设计了一个 7 级降级链，确保即使主要提供商挂了，辅助任务仍然可以完成。

```
OpenRouter → Nous Portal → Custom → Codex OAuth → Anthropic → Direct → None
```

**关键特性**：
- 支付耗尽自动降级（402 → 下一个提供商）
- 文本 vs 视觉任务独立路由
- Per-task 覆盖配置（`auxiliary.vision.provider`）
- 统一接口，消费者无需关心后端

**学习建议**：在 `engine/model_router.py` 中引入降级链，至少支持 OpenRouter → Custom → 主提供商的 3 级降级。

---

#### ③ 结构化错误分类 + 自动恢复 (Error Classifier)

**为什么重要**：生产环境中 API 错误是最常见的问题。没有分类，所有错误都当"重试"处理，浪费时间和配额。

**Hermes 做法**：
```python
class ClassifiedError:
    reason: FailoverReason       # 分类原因
    retryable: bool              # 是否可重试
    should_compress: bool        # 是否需要压缩上下文
    should_rotate_credential: bool  # 是否需要轮换凭证
    should_fallback: bool        # 是否需要切换提供商
```

这意味着：`context_overflow` → 压缩（不重试），`billing` → 轮换凭证，`timeout` → 重建客户端 + 重试。

**学习建议**：在 `api/errors.py` 中引入错误分类器，至少覆盖：auth、billing、rate_limit、context_overflow、timeout、server_error 六大类。

---

### 3.2 OpenCortex 最需要补强的 3 个方面

#### ① 持久化状态存储（优先级：最高）

**现状**：`engine/state_store.py` 仅 40 行，内存中的 Observable Store，进程退出即丢失。

**需要补强**：
- SQLite WAL 模式持久化（参考 Hermes 的 `hermes_state.py`）
- Session + Message 两表设计
- FTS5 全文搜索（跨会话搜索历史对话）
- Schema 版本迁移机制
- 写竞争处理（多进程/多线程场景）

**预估工作量**：~800 行核心代码

---

#### ② 错误分类与自动恢复（优先级：高）

**现状**：`api/errors.py` 只有简单错误定义，无分类恢复策略。

**需要补强**：
- `FailoverReason` 枚举（auth/billing/rate_limit/context_overflow/timeout/server_error）
- `ClassifiedError` 数据类（含 retryable/should_compress/should_fallback 标志）
- 提供商特定的错误模式匹配（Anthropic thinking signature、OpenAI rate limit...）
- 在 query loop 中集成自动恢复逻辑

**预估工作量**：~500 行核心代码

---

#### ③ 多凭证管理与降级链（优先级：高）

**现状**：`auth/manager.py` 单凭证管理，`engine/model_router.py` 简单路由。

**需要补强**：
- `CredentialPool`：多凭证存储 + 选择策略（round_robin/least_used）
- 凭证状态追踪（ok/exhausted + 冷却时间）
- 辅助客户端降级链（至少 3 级）
- 支付耗尽自动降级
- 持久化凭证存储

**预估工作量**：~600 行核心代码

---

### 3.3 改进路线图

#### Phase 1：基础补强（2-3 周）

```
Week 1: 持久化状态存储
├── SQLite SessionDB（WAL 模式）
├── sessions + messages 表
├── Schema 迁移机制
└── 基础 CRUD + 查询

Week 2-3: 错误分类 + 自动恢复
├── FailoverReason 枚举
├── ClassifiedError 数据类
├── Provider-specific 模式匹配
└── Query loop 集成
```

#### Phase 2：上下文引擎 + 凭证管理（2-3 周）

```
Week 4-5: 可插拔上下文引擎
├── ContextEngine ABC（参考 Hermes）
├── 迁移现有 compact 为默认引擎
├── 迭代摘要更新
└── Token-budget tail 保护

Week 6: 多凭证管理
├── CredentialPool 实现
├── 4种选择策略
├── 冷却机制
└── 持久化存储
```

#### Phase 3：高级特性（3-4 周）

```
Week 7-8: 辅助客户端降级链
├── 辅助模型路由器
├── 3-5 级降级链
├── 支付耗尽处理
└── Per-task 配置

Week 9-10: 工具生态扩充
├── 安全工具集（url_safety, osv_check）
├── 多媒体工具（image gen, tts, stt）
├── 增强权限审批（危险命令检测 + LLM辅助）
└── MCP Server 能力
```

#### Phase 4：技能生态 + 浏览器（持续）

```
Ongoing:
├── 技能库扩充（目标 30+ SKILL.md）
├── 浏览器后端多样化（Camofox 支持）
├── 插件类型分类（context_engine/memory/...）
└── 皮肤系统增强
```

---

### 3.4 OpenCortex 的独特优势（不应放弃）

1. **Swarm/编排系统**：完整的 agent 编排框架，Hermes 没有。这是 OpenCortex 的核心差异化。
2. **A2A 协议**：完整的 Agent-to-Agent 实现，行业标准对接能力。
3. **Hooks 系统**：生命周期钩子 + 热重载，可扩展性更强。
4. **记忆系统**：decay（衰减）/dream（整合）/memdir（目录结构）/tiered_store（分层存储），设计比 Hermes 的第三方插件更统一。
5. **模块化架构**：每个模块职责清晰（a2a/api/auth/bridge/channels/config/engine/hooks/...），比 Hermes 的扁平结构更易维护。

---

### 附录：关键代码行数对比

| 模块 | OpenCortex | Hermes |
|------|-----------|--------|
| 状态管理 | 40 | 1,238 |
| 上下文压缩 | 492 | 766 |
| 模型适配 | ~200 | 1,410 |
| 辅助客户端 | ~150 | 2,485 |
| 凭证管理 | ~100 | 1,319 |
| 错误处理 | ~80 | 809 |
| 浏览器工具 | 251 | 592 |
| 权限审批 | 146 | 916 |
| MCP | 259 | 867 |
| 网关配置 | ~200 | 1,064 |
| **总计** | **~1,918** | **~9,566** |

> **结论**：OpenCortex 在架构模块化和前沿特性（Swarm/A2A/Hooks/Memory）上有独特优势，但在生产必需的基础设施（状态持久化、错误恢复、凭证管理、上下文引擎）上需要重点补强。建议按照 Phase 1-4 路线图逐步实施，优先解决状态持久化和错误恢复这两个"刚需"问题。
