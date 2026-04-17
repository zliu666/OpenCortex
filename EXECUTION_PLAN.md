# OpenCortex 执行方案 v1.0

> 海星掌柜（Hermes）出品 · 2026-04-17 · 待审批

---

## 一、当前状态总结

| 维度 | 数据 |
|------|------|
| 代码量 | ~36,000行 Python，29模块，150+文件 |
| 工具数 | 43个完整实现 |
| 渠道适配器 | 9个（飞书最完整 1006行） |
| 测试 | 768通过 / 19失败 / 78测试文件 |
| 设计目标 | 10大目标，完成度 30%~95% 不等 |
| 已修复 | P0 bug 2个、P1问题 5个、SQLite持久化、会话隔离、记忆注入等 |

### 设计目标达成度

| # | 目标 | 完成度 | 关键差距 |
|---|------|--------|----------|
| 1 | Tool-first ReAct 循环 | 80% | C1 tool_use_id丢失、Judge上下文缺陷 |
| 2 | Provider-agnostic 多模型 | 70% | C3 预算控制形同虚设 |
| 3 | 插件/技能/MCP 扩展 | 90% | OAuth空壳、bundled插件空 |
| 4 | 分层权限+安全 | 60% | 5个Critical安全缺陷 |
| 5 | 多渠道 Gateway | 40% | 会话隔离缺用户维度、无背压 |
| 6 | 增强记忆 | 50% | Decay/Dream/Profile脚手架未接 |
| 7 | 轨迹+自动技能 | 10% | 仅计划文档 |
| 8 | 用户画像 | 0% | 仅计划文档 |
| 9 | 多Agent Swarm隔离 | 95% | InProcess后端有stub |
| 10 | A2A+HTTP API | 85% | 测试全502（缺服务启动） |

---

## 二、19个测试失败根因分析

### A组：Memory测试（6个）— 根因单一
**文件：** `src/opencortex/memory/paths.py:37-48`

`_is_temp_cwd()` 中 `"/tmp" in str(path)` 匹配了 pytest 的 tmp_path（如 `/tmp/pytest-xxx/`），导致 `scan_memory_files()` 跳过项目目录，所有搜索返回空。

**修复：** Easy — 区分 pytest tmp_path 与真正临时目录，或给 scan 加 `override_dirs` 参数。

### B组：6层API测试（11个）— 无服务启动
**文件：** `tests/test_progressive_6layer.py`

所有测试硬编码请求 `http://127.0.0.1:8765`，但无 pytest fixture 启动服务。另外服务端缺 `/status`、`/mcp/tools` 端点。

**修复：** Medium — 加 conftest.py 启动 fixture + 补缺失端点。

### C组：集成测试（1个）— 同B组
`test_opencortex_integration.py` 同样依赖外部服务。

### D组：UI测试（1个）— 安全层误拦截
**文件：** `src/opencortex/security/tool_classifier.py`

`ask_user_question` 工具被默认分类为 `COMMAND`（严格），导致 LLM validator 拦截。

**修复：** Easy — 将内置交互工具注册为 `INTERNAL` 类型。

---

## 三、5个 Critical Bug 详细方案

### C1: tool_use_id 丢失（并发工具调用）
- **文件：** `src/opencortex/engine/messages.py:142`
- **问题：** API 不返回 tool_use id 时，fallback `f"toolu_{uuid4().hex}"` 生成随机 id，与 ToolResultBlock 不匹配
- **修复：**
  1. `messages.py:142` — 当 id 缺失时 log.warning
  2. 在 `query.py` 并发执行时维护 `工具调用序号→result` 的映射
  3. 确保 ToolResultBlock 始终用 `tc.id`（不是 fallback id）
- **工时：** 1.5h

### C2: user_query 为空（安全层失效）
- **文件：** `src/opencortex/engine/query.py:91-109`
- **问题：** `isinstance(_c, str)` 永远 False（content 是 list[ContentBlock]），导致 _user_query 留空
- **修复：**
  1. 修正类型检测：先检查 list 再遍历提取 TextBlock.text
  2. 如果仍为空，拼接所有 user message 文本作为 fallback
  3. 安全层加 user_query 为空时的严格模式（默认拒绝）
- **工时：** 0.5h

### C3: 预算控制失效
- **文件：** `src/opencortex/engine/cost_tracker.py` 全文件
- **问题：** CostTracker 只有记账（add/total），没有预算上限检查；Settings 无预算字段
- **修复：**
  1. `settings.py` 加 `budget_limit: float = 0.0`
  2. `cost_tracker.py` 加 `exceeds_budget(limit)` 方法
  3. `query.py` 每轮循环检查预算
- **工时：** 1h

### C4: 会话隔离失效（群聊用户共享）
- **文件：** `src/opencortex/channels/bus/events.py:21-24`
- **问题：** session_key = `channel:chat_id`，同群不同用户共享引擎
- **修复：**
  1. session_key 改为 `channel:sender_id:chat_id`（含用户维度）
  2. `_engines` 加 TTL 过期清理（默认 30min）
  3. 加最大并发 session 限制（默认 100）
- **工时：** 1.5h

### C5: 背压机制缺失
- **文件：** `src/opencortex/channels/bus/queue.py:23-45`
- **问题：** outbound 用阻塞式 put 可能卡死事件循环；inbound 静默丢弃无监控
- **修复：**
  1. outbound 也改非阻塞+丢弃策略
  2. 加丢弃计数器和 log.warning
  3. 加 QueueMonitor 暴露 metrics
- **工时：** 1h

---

## 四、执行计划（5个 Phase）

### Phase 1：止血（测试修复）— 预计 3h

| # | 任务 | 工时 |
|---|------|------|
| 1.1 | 修复 `_is_temp_cwd()` — 6个memory测试 | 0.5h |
| 1.2 | 加 pytest fixture 启动 A2A 服务 | 1h |
| 1.3 | 补 `/status`、`/mcp/tools` 端点 | 0.5h |
| 1.4 | 注册 `ask_user_question` 为 INTERNAL | 0.5h |
| 1.5 | 全量测试验证（目标 787/0） | 0.5h |

**验收：** 0 failed, 787 passed

### Phase 2：Critical Bug 修复 — 预计 5.5h

| # | 任务 | 工时 |
|---|------|------|
| 2.1 | C1 tool_use_id 丢失修复 | 1.5h |
| 2.2 | C2 user_query 为空修复 | 0.5h |
| 2.3 | C3 预算控制实现 | 1h |
| 2.4 | C4 会话隔离修复（含 sender_id） | 1.5h |
| 2.5 | C5 背压机制实现 | 1h |

**验收：** 每个 bug 有对应测试用例，测试全过

### Phase 3：接通已有模块 — 预计 4h

| # | 任务 | 工时 |
|---|------|------|
| 3.1 | RecoveryChain 策略接入 query.py | 1h |
| 3.2 | CredentialPool 接入 API client | 1h |
| 3.3 | ToolClassifier 接入安全层主流程 | 0.5h |
| 3.4 | Nudge 后台审查激活 | 0.5h |
| 3.5 | /health + /metrics 端点 | 1h |

**验收：** 6个"写了没接通"模块全部接入主流程

### Phase 4：观测基础 — 预计 3h

| # | 任务 | 工时 |
|---|------|------|
| 4.1 | Token 统计模块（写入+查询+聚合） | 1h |
| 4.2 | 看门狗/健康检查（定期自检） | 1h |
| 4.3 | Doctor 自诊断命令 | 1h |

**验收：** 可通过 `/health`、`/metrics`、`/doctor` 查看框架状态

### Phase 5：进化功能（可选）— 预计 8h

| # | 任务 | 工时 |
|---|------|------|
| 5.1 | 轨迹追踪模块（trajectory） | 2h |
| 5.2 | FTS5 增强记忆（注入修复+衰减接通） | 2h |
| 5.3 | 流水线引擎（多步骤工具编排） | 2h |
| 5.4 | Cron 调度接通 | 2h |

**暂缓项：** 用户画像(0%→需大量设计)、SimpleMem集成(待论文验证)、向量检索(待需求明确)

---

## 五、不做的事（明确排除）

| 项目 | 原因 |
|------|------|
| Web Dashboard | 已有飞书看板，重复建设 |
| ACP 协议 | OpenCortex 已有 MCP，无需第二协议 |
| insights 报告 | 锦上添花，ROI 低 |
| PyInstaller 打包 | 框架还在快速迭代，打包不急 |
| 多模态输入 | 当前场景不需要 |
| 插件市场 | 用户量不够支撑 |

---

## 六、总工时与排期

| Phase | 内容 | 工时 | 依赖 |
|-------|------|------|------|
| **P1** | 止血（测试修复） | 3h | 无 |
| **P2** | Critical Bug | 5.5h | P1 |
| **P3** | 接通已有模块 | 4h | P2 |
| **P4** | 观测基础 | 3h | P2 |
| **P5** | 进化功能（可选） | 8h | P3+P4 |
| **合计** | P1~P4 必须 | **15.5h** | — |
| **合计** | P1~P5 全做 | **23.5h** | — |

### 执行方式
- 由海星掌柜（Hermes）主刀，按 Phase 顺序执行
- 每个 Phase 完成后跑全量测试确认不回归
- 每个 Phase 完成后发飞书通知进度
- 用户可随时喊停或调整优先级

---

## 七、风险与建议

1. **C4 会话隔离修复可能影响现有功能** — 修改 session_key 格式会导致旧会话"消失"（实际是换了新 key）。建议加迁移逻辑。
2. **P2 完成后框架才算"可用"** — 在 P2 之前不建议上线任何新功能。
3. **Phase 5 建议按需开启** — 不是所有进化功能都有紧迫需求，建议根据实际使用痛点决定。
4. **测试覆盖率需持续提升** — 当前 orchestration 模块 1227 行零测试，是定时炸弹。

---

> 📋 请审阅此方案。如无问题，回复"执行"即可开始。
