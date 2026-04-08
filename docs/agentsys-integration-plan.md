# AgentSys 安全层集成方案

> 日期：2026-04-09
> 状态：方案设计，待 review

---

## 一、背景

### AgentSys 是什么

AgentSys 是一个学术论文项目，提供三层 AI Agent 安全防线：

| 层 | 组件 | 作用 |
|---|------|------|
| **第1层：Validator（验证器）** | `AgentSysValidator` | 用 LLM 判断工具调用是否安全+必要，返回 True/False |
| **第2层：Sanitizer（净化器）** | `AgentSysSanitizer` | 检测并移除工具返回值中的注入指令 |
| **第3层：PrivilegeAssignor（权限分配器）** | `AgentSysPrivilegeAssignor` | 将工具分类为 Query（只读）或 Command（写入），对外部数据返回的工具结果派遣 Worker Agent 隔离处理 |

### 为什么需要集成

OpenCortex 当前的权限系统只有：
- 敏感路径保护（SSH/AWS 密钥等）
- 工具白名单/黑名单
- 三种模式（default/plan/full_auto）
- 用户确认弹窗

**缺少的能力**：
1. 无法检测 prompt injection（恶意指令藏在工具返回值里）
2. 无法对工具调用做"必要性"判断
3. 外部数据（邮件、网页等）返回后直接暴露给主 Agent

---

## 二、核心问题：AgentSys 依赖 agentdojo

AgentSys 的代码基于 `agentdojo` 框架（港大的 AI Agent 安全评测框架），大量 import 了这个库：

```python
from agentdojo.agent_pipeline import AgentPipeline, PipelineConfig
from agentdojo.functions_runtime import FunctionsRuntime, TaskEnvironment
from agentdojo.models import MODEL_PROVIDERS, ModelsEnum
from agentdojo.task_suite import task_suite
```

**OpenCortex 不用 agentdojo，用的是自己的 engine/query_engine + tools 系统。**

所以不能直接 import AgentSys 代码，需要**提取安全层核心逻辑**，适配到 OpenCortex 的架构。

---

## 三、集成方案

### 方案：提取 + 适配（推荐）

不引入 agentdojo 依赖，只提取 AgentSys 的三个安全组件的核心逻辑（prompt + 判断逻辑），用 OpenCortex 自身的 API client 来调用 LLM 做安全判断。

### 架构位置

在 `permissions/checker.py` 的 `evaluate()` 方法之后，`engine/query_engine.py` 的工具执行循环中，插入安全检查层：

```
用户消息 → QueryEngine → LLM 生成工具调用
                                ↓
                    ┌─── PermissionChecker（现有）───┐
                    │  敏感路径/黑白名单/模式检查      │
                    └────────────┬──────────────────┘
                                 ↓
                    ┌─── AgentSysSecurityLayer（新增）──┐
                    │  1. Validator: 调用必要吗？         │
                    │  2. 执行工具                        │
                    │  3. Sanitizer: 返回值有注入吗？     │
                    │  4. PrivilegeAssignor: 需要隔离吗？ │
                    └────────────┬────────────────────┘
                                 ↓
                        返回安全的结果给 LLM
```

### 具体文件结构

```
src/opencortex/security/
├── __init__.py
├── validator.py       # 从 AgentSys 提取，适配 OpenCortex API
├── sanitizer.py       # 从 AgentSys 提取，适配 OpenCortex API
├── privilege.py       # 从 AgentSys 提取，适配 OpenCortex API
├── security_layer.py  # 串联三个组件的主入口
└── prompts.py         # 所有安全相关的 prompt 模板
```

### 三个组件的适配方式

#### 1. Validator（验证器）

**AgentSys 原版**：用 agentdojo 的 LLM pipeline
**OpenCortex 适配**：用 `api/client.py` 的 `stream_message()` 一次性获取判断

```python
# validator.py 伪代码
class ToolCallValidator:
    async def validate(self, tool_name, tool_args, user_query, call_history) -> bool:
        prompt = VALIDATOR_QUERY_TEMPLATE.format(...)
        response = await self.api_client.stream_message(
            messages=[system_prompt, user_prompt],
            max_tokens=10  # 只需要 True/False
        )
        return "true" in response.lower()
```

**性能影响**：每次工具调用多一次 LLM 请求（~1-2秒，用快模型如 glm-5-turbo）

#### 2. Sanitizer（净化器）

**AgentSys 原版**：用 agentdojo LLM pipeline + 正则提取
**OpenCortex 适配**：用 OpenCortex API client

```python
class ToolResultSanitizer:
    async def sanitize(self, tool_result_text) -> str:
        # 让 LLM 检测返回值中的指令
        detected = await self._detect_instructions(tool_result_text)
        # 移除检测到的指令
        return self._remove_instructions(tool_result_text, detected)
```

#### 3. PrivilegeAssignor（权限分配器）

**AgentSys 原版**：LLM 分类 + Worker Agent 隔离
**OpenCortex 适配**：只做分类（Worker Agent 隔离太重，Phase 3 再考虑）

```python
class ToolPrivilegeAssignor:
    async def classify(self, tool_name, tool_description) -> str:
        # 返回 "query" 或 "command"
        response = await self.api_client.stream_message(...)
        return "query" if "A" in response else "command"
```

### 设置集成

在 `settings.py` 中添加：

```python
class SecuritySettings(BaseModel):
    """AgentSys security layer settings."""
    enabled: bool = False  # 默认关闭，用户主动开启
    validator_enabled: bool = True
    sanitizer_enabled: bool = True
    privilege_assignor_enabled: bool = True
    # 用哪个模型做安全判断（默认用当前模型，也可以指定快模型）
    security_model: str | None = None
```

---

## 四、工作量估算

| 步骤 | 预计时间 | 说明 |
|------|---------|------|
| 1. 创建 security/ 模块骨架 | 30分钟 | 文件结构 + prompts 提取 |
| 2. 实现 Validator | 1小时 | prompt 适配 + API 调用 + 测试 |
| 3. 实现 Sanitizer | 1小时 | prompt 适配 + 指令检测/移除 + 测试 |
| 4. 实现 PrivilegeAssignor | 30分钟 | prompt 适配 + 工具分类 |
| 5. 实现 SecurityLayer 串联 | 1小时 | 串联三个组件 + 配置开关 |
| 6. 集成到 QueryEngine | 1小时 | 修改工具执行循环 |
| 7. 端到端测试 | 1小时 | 注入攻击测试 + 正常用例回归 |
| **总计** | **~6小时** | |

---

## 五、风险和注意事项

1. **性能**：每个工具调用多 1-2 次 LLM 请求，用快模型缓解
2. **误判**：Validator 可能拒绝合法调用，需要可配置的开关
3. **agentdojo 不引入**：只提取逻辑，不引入新依赖
4. **默认关闭**：安全层默认不启用，用户通过 settings 开启
5. **Worker Agent 隔离**（Phase 3）：对外部数据的深度隔离，需要子 Agent 调度能力

---

## 六、待确认

1. **你同意这个方案吗？** 特别是"不引入 agentdojo 依赖"这个决定
2. **安全模型用哪个？** 建议用 glm-5-turbo（快、便宜），还是用和主模型一样的？
3. **默认关闭可以吗？** 还是默认开启？
4. **Phase 3 再做 Worker Agent 隔离可以吗？** 还是现在就要？
