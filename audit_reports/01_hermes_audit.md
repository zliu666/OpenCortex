# 🐙 海星掌柜（Hermes）审查报告 — OpenCortex 代码审查

> **审查者**: 海星掌柜 (Hermes Agent)  
> **审查时间**: 2026-04-13  
> **审查视角**: 从 Hermes 架构经验出发，对比 OpenCortex 的错误恢复、并发安全、安全层设计  
> **代码规模**: 240个Python文件，核心模块约35个

---

## 一、总览

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构清晰度 | ⭐⭐⭐⭐ | 模块分层合理，engine/hooks/security/swarm/orchestration 职责边界明确 |
| 错误恢复 | ⭐⭐⭐ | RecoveryChain 设计好，但 query.py 的 gather 缺乏异常隔离 |
| 安全层 | ⭐⭐⭐ | 5层防线（Hook→工具查找→参数校验→权限→安全层）完整，但 user_query 空缺 |
| 并发安全 | ⭐⭐ | 关键 gather 缺少 return_exceptions，LifecycleManager 无边界保护 |
| 代码质量 | ⭐⭐⭐⭐ | 无 bare except，except:pass 较多但多在合理的清理代码中 |

---

## 二、发现的问题（按严重程度排序）

### 🔴 P0 — 高危（必须修复）

#### 2.1 `asyncio.gather` 缺少 `return_exceptions=True`

**文件**: `engine/query.py` 第183行  
**问题**: 多工具并发执行时，如果任何一个工具抛出异常，`asyncio.gather` 会立即取消所有其他工具的执行。

```python
# 当前代码（危险）
results = await asyncio.gather(*[_run(tc) for tc in tool_calls])
```

**对比**: 同一代码库中，`channels/manager.py:186`、`orchestration/engine.py:99`、`swarm/in_process.py:690`、`swarm/team_lifecycle.py:668` **全部**使用了 `return_exceptions=True`。只有 query.py 没有。

**影响**: 一个工具崩溃 = 整轮工具结果全部丢失 + 用户看到不可理解的错误。

**修复方案**:
```python
results = await asyncio.gather(
    *[_run(tc) for tc in tool_calls], 
    return_exceptions=True
)
# 然后处理每个 result，如果是 Exception 则包装为 ToolResultBlock(is_error=True)
```

**Hermes 对比**: Hermes 的 `delegate_task` 天然隔离——子 agent 崩溃不影响主 agent。

---

#### 2.2 SecurityLayer 的 `user_query` 始终为空字符串

**文件**: `engine/query.py` 第290-291行  
**问题**: 安全层的 `check_tool_call()` 接收 `user_query` 参数用于判断工具调用是否符合用户意图，但实际传入的是空字符串。

```python
user_query = ""  # ← 永远为空
sec_result = await security_layer.check_tool_call(
    tool_name=tool_name,
    tool_args=tool_input,
    tool_description=tool_desc,
    user_query=user_query,  # ← 传空值
    call_history="",
)
```

**影响**: 安全层无法判断工具调用是否偏离用户意图，相当于 Validator 这个安全组件**形同虚设**。攻击者可以通过 prompt injection 让 LLM 调用任意工具，因为 validator 没有 user_query 作为评判依据。

**修复方案**: 从 messages 中提取第一条用户消息作为 user_query：
```python
user_query = ""
for msg in messages:
    if msg.role == "user" and isinstance(msg.content, str):
        user_query = msg.content[:500]
        break
```

---

### 🟡 P1 — 中等（应当修复）

#### 2.3 Judge Agent 异常时默认允许继续

**文件**: `engine/query.py` 第471-473行  
**问题**: Judge Agent 调用失败时，默认返回 `True`（继续执行）。

```python
except Exception as exc:
    log.warning("[JudgeAgent] Error calling judge, defaulting to continue: %s", exc)
    return True  # ← 默认继续 = 可能无限循环
```

**风险**: 配合 `_MAX_JUDGE_EXTENSIONS = 5` 和 `turn_count = 0` 重置，如果 judge 总是失败并默认 continue，agent 最多可以跑 `200 * 6 = 1200` 轮。

**修复方案**: 默认应返回 `False`（安全失败）：
```python
return False  # 安全失败：无法判断时宁可不继续
```

---

#### 2.4 Judge Agent 硬编码模型名

**文件**: `engine/query.py` 第453行  
**问题**: Judge 使用的模型 `glm-5-turbo` 硬编码在代码中。

```python
model="glm-5-turbo",  # ← 硬编码
```

**影响**: 不同环境/提供商可能没有这个模型，judge 功能直接失效（每次都走 except 分支）。

**修复方案**: 从 QueryContext 或配置中读取：
```python
model=context.model,  # 或 settings.judge_model
```

---

#### 2.5 `AgentLifecycleManager._events` 无限增长

**文件**: `swarm/lifecycle.py` 第52行、第73-76行  
**问题**: 每次 `update_state()` 调用都会向 `_events` 列表追加事件，没有任何修剪机制。

```python
self._events: list[AgentEvent] = []
# ...
self._events.append(AgentEvent(...))  # ← 只增不减
```

**影响**: 长时间运行的 agent（如 cron 任务）会导致内存持续增长。

**修复方案**: 限制 `_events` 最大长度，或使用 `collections.deque(maxlen=1000)`：
```python
self._events: deque[AgentEvent] = deque(maxlen=1000)
```

---

#### 2.6 Hook 参数注入存在潜在的 `$ARGUMENTS` 替换漏洞

**文件**: `hooks/executor.py` 第223-229行  
**问题**: `_inject_arguments` 使用简单的 `str.replace("$ARGUMENTS", ...)` 进行模板替换。

```python
return template.replace("$ARGUMENTS", serialized)
```

**风险**: 如果 payload 中包含 `$ARGUMENTS` 字符串，会被二次替换。虽然 JSON 序列化后引号转义可以缓解，但在 `shell_escape=False` 的 prompt hook 场景下，精心构造的 payload 可能产生意外行为。

**修复方案**: 使用更安全的模板引擎（如 `string.Template` 的 `safe_substitute`）或一次性替换：
```python
from string import Template
return Template(template).safe_substitute(ARGUMENTS=serialized)
```

---

#### 2.7 `except: pass` 模式过多

**涉及文件**: 20+ 处，集中在 `auth/`、`channels/` 模块  
**问题**: 大量 `except ... : pass` 静默吞掉异常。部分合理（如清理代码），部分可能隐藏真实错误。

**重点可疑项**:
- `auth/storage.py:61` — 存储操作失败被吞掉
- `auth/storage.py:145,147` — 两层连续 pass
- `channels/adapter.py:62` — 适配器错误被吞掉

**修复方案**: 至少加 `log.debug` 记录被吞掉的异常。

---

### 🟢 P2 — 低危（建议改进）

#### 2.8 `RecoveryChain._attempts` 直接暴露内部状态

**文件**: `engine/query.py` 第148行  
**问题**: 恢复状态通知中直接访问 `recovery._attempts`（下划线前缀 = 内部属性）。

```python
f"(attempt {recovery._attempts}/{recovery._max_attempts})"
```

**修复**: 添加公开的 `attempts` property。

---

#### 2.9 auth/flows.py 中 subprocess 调用打开浏览器

**文件**: `auth/flows.py` 第82-101行  
**问题**: 使用 `subprocess.Popen` 打开 URL，虽然目的合理（OAuth 回调），但 URL 应做白名单校验。

---

#### 2.10 orchestration/engine.py 的延迟导入

**文件**: `orchestration/engine.py` 第30-33行  
**问题**: 在 `__init__` 中做延迟导入，启动时不会暴露循环依赖错误。

```python
def __init__(self):
    from .planner import TaskPlanner  # ← 延迟导入
```

**影响**: 运行时才可能发现导入问题。建议在模块级别导入或添加显式的导入检查。

---

## 三、架构对比：OpenCortex vs Hermes

| 维度 | OpenCortex | Hermes |
|------|-----------|--------|
| **并发模型** | 单进程 async（asyncio.gather） | 多进程隔离（delegate_task） |
| **错误隔离** | gather 无 return_exceptions ❌ | 子进程天然隔离 ✅ |
| **权限系统** | 5层管线（Hook→查找→校验→权限→安全层） | approval.py + 飞书卡片弹窗 |
| **安全层** | LLM-based Validator + Sanitizer + Dispatcher | Gateway approval + 飞书回调 |
| **上下文压缩** | auto_compact（微压缩 + LLM摘要） | context compaction |
| **Turn 限制** | 200轮 + Judge Agent（可续5次） | max_iterations（子agent） |
| **Hook 系统** | 4种类型（Command/HTTP/Prompt/Agent） | 无内置Hook系统 |
| **进程管理** | AgentLifecycleManager（内存中） | Gateway 进程管理 + MCP 清理 |

### 关键差异

1. **OpenCortex 的 Hook 系统更灵活**：支持命令、HTTP、LLM prompt、Agent 4种 hook 类型，比 Hermes 的静态 approval 更通用。

2. **Hermes 的错误隔离更强**：delegate_task 使用独立进程，一个崩溃不影响另一个。OpenCortex 的 gather 在修复前有级联失败风险。

3. **OpenCortex 的安全层更系统**：Validator → Sanitizer → PrivilegeAssignor → SubAgentDispatcher 四组件协同。但 user_query 空缺（P0）削弱了整体效果。

4. **Hermes 的通知机制更实用**：飞书卡片弹窗让用户实时介入，OpenCortex 缺乏同步的用户通知通道。

---

## 四、修复优先级建议

| 优先级 | 编号 | 问题 | 预估工时 |
|--------|------|------|----------|
| 🔴 P0 | 2.1 | gather 缺 return_exceptions | 15分钟 |
| 🔴 P0 | 2.2 | security_layer user_query 为空 | 10分钟 |
| 🟡 P1 | 2.3 | Judge 异常默认 continue | 5分钟 |
| 🟡 P1 | 2.4 | Judge 模型硬编码 | 5分钟 |
| 🟡 P1 | 2.5 | _events 无限增长 | 5分钟 |
| 🟡 P1 | 2.6 | Hook $ARGUMENTS 替换 | 15分钟 |
| 🟡 P1 | 2.7 | except:pass 清理 | 30分钟 |
| 🟢 P2 | 2.8-2.10 | 其他小问题 | 30分钟 |

**总计预估**: ~2小时

---

## 五、结论

OpenCortex 整体架构设计**优于 Hermes**——5层安全管线、Hook 系统、RecoveryChain、auto_compact 都是高质量设计。但有 **2个高危 Bug**（gather 异常隔离 + security_layer user_query）需要立即修复，否则会在生产环境中导致：
- 工具级联崩溃（2.1）
- 安全层形同虚设（2.2）

建议修复顺序：**2.1 → 2.2 → 2.3 → 2.4 → 其余按需**。
