# 多模型协作需求评估报告

> 日期：2026-04-09
> 模型：GLM-5.1（最强模型）

---

## 一、需求理解

**核心诉求**：多模型 AI 协作，不同模型负责不同子任务，形成"同福工厂"式流水线。

**举例场景**：
- 生成网页 → GLM 写代码（HTML/CSS/JS），MiniMax 生成图片资源
- GLM-5V 看设计稿 → 拆解任务 → 智谱写前端，MiniMax 生成素材
- GLM-5V 看图复刻 → 分析布局 → 智谱写代码，MiniMax 补充视觉资源

**涉及模型能力**：

| 模型 | 强项 | 角色 |
|------|------|------|
| GLM-5.1 | 编程、推理、规划 | 总工程师（代码、架构、逻辑） |
| GLM-5V-Turbo | 多模态 Coding（看图→代码，Design2Code 94.8分） | 视觉理解（看设计稿、截图分析） |
| MiniMax-M2.7 | 文本生成快 | 快速执行（搜索、格式化） |
| MiniMax Hailuo 2.3 | 视频生成 | 视频素材 |
| MiniMax Music 2.5 | 音乐生成 | 背景音乐 |
| MiniMax TTS | 语音合成 | 配音 |
| MiniMax 图片生成 | 图片/海报 | 视觉素材 |

---

## 二、现有架构分析

### 当前双路由架构

```
用户请求 → ModelRouter → { primary: GLM-5.1, execution: MiniMax-M2.7 }
                              ↓
                        QueryEngine → ToolRegistry(37工具)
```

**已有能力**：
- ✅ 双模型路由（primary + execution）
- ✅ AgentDefinition（每个 Agent 可指定 model、tools、skills）
- ✅ TeamRegistry（多 Agent 协作）
- ✅ MCP Server（工具暴露）
- ✅ A2A Bridge（外部调度）
- ✅ Swarm（Worker Agent 隔离）
- ✅ 上下文三级分层

**缺失能力**：
- ❌ 多模型子任务编排（一个任务拆给多个模型协作）
- ❌ 模型间结果传递（MiniMax 生成图片 → GLM 引用图片路径）
- ❌ 按内容类型路由（图片生成→MiniMax，代码→GLM）
- ❌ 流水线定义（step1→step2→step3 指定不同模型）

---

## 三、方案设计：三阶段演进

### Phase A：内容类型路由器（2-3天）

**核心思路**：在现有 ModelRouter 基础上，增加"内容类型感知"路由。

```python
# 新增 ContentAwareRouter
class ContentType(Enum):
    CODE = "code"           # → GLM-5.1
    IMAGE = "image"         # → MiniMax 图片生成 API
    VIDEO = "video"         # → MiniMax Hailuo API
    MUSIC = "music"         # → MiniMax Music API
    VOICE = "voice"         # → MiniMax TTS API
    VISUAL_ANALYSIS = "visual"  # → GLM-5V-Turbo
    TEXT = "text"           # → GLM-5.1 或 MiniMax-M2.7

class ContentAwareRouter:
    def route(self, task: str, agent: AgentDefinition) -> ModelRoute:
        # 1. 解析任务中的内容类型需求
        # 2. 匹配到对应模型
        # 3. 返回路由决策
```

**改动范围**：
- `model_router.py`：增加 ContentType 枚举和路由逻辑
- `settings.py`：增加多模型配置（MiniMax API key、GLM-5V 配置）
- 新增 `tools/minimax_tools.py`：封装 MiniMax 多模态 API 为 OpenCortex 工具

**关键**：MiniMax 多模态能力通过**工具（Tool）**暴露，不是通过模型路由。

### Phase B：任务编排引擎（3-4天）

**核心思路**：引入 Pipeline/Workflow 概念，一个用户任务可拆成多个步骤。

```python
# Pipeline 定义（YAML）
name: "生成网页"
steps:
  - name: "分析需求"
    model: "glm-5v-turbo"
    input: "{{user_prompt}}"
    output_var: "analysis"
  
  - name: "生成图片素材"
    tool: "minimax_image_generate"
    input: "{{analysis.image_descriptions}}"
    output_var: "image_paths"
  
  - name: "生成背景音乐"
    tool: "minimax_music_generate"
    input: "{{analysis.music_description}}"
    output_var: "music_path"
  
  - name: "编写网页代码"
    model: "glm-5.1"
    input: "{{analysis}} + 图片路径: {{image_paths}}"
    output_var: "code"
  
  - name: "部署验证"
    tool: "bash"
    input: "python -m http.server 8080"
```

**改动范围**：
- 新增 `pipeline/` 模块：Pipeline 定义、执行器、变量传递
- `agent_definitions.py`：支持 pipeline 字段
- 工具间结果传递机制

### Phase C：同福工厂（智能调度）（4-5天）

**核心思路**：GLM-5V-Turbo 作为"工头"，自动拆解任务、分配模型、组装结果。

```
用户: "帮我做一个产品落地页"
   ↓
GLM-5V-Turbo（工头）:
  分析需求 → 拆解子任务:
    1. 生成产品Banner图 → MiniMax 图片 API
    2. 生成背景音乐 → MiniMax Music API
    3. 编写HTML/CSS/JS → GLM-5.1
    4. 图片压缩优化 → bash 工具
  调度执行 → 组装最终产物
   ↓
输出: 完整的落地页项目
```

---

## 四、推荐实施路径

### 最小可行方案（MVP）：Phase A + MiniMax 工具

**为什么先做这个**：
1. 现有架构改动最小（只加工具和路由规则）
2. 立刻能用（用户说"生成图片"，直接调 MiniMax 工具）
3. 为后续 Pipeline 打基础

**具体工作**：

| 项 | 改动 | 时间 |
|---|------|------|
| MiniMax API Key 配置 | `settings.py` 增加 minimax 配置块 | 0.5h |
| MiniMax 图片生成工具 | `tools/minimax_tools.py` | 2h |
| MiniMax 音乐生成工具 | 同上 | 1h |
| MiniMax TTS 工具 | 同上 | 1h |
| 内容类型路由 | `model_router.py` 扩展 | 2h |
| GLM-5V-Turbo 集成 | `provider.py` 增加视觉模型支持 | 2h |
| 集成测试 | `tests/test_multimodal.py` | 2h |
| **合计** | | **~10h** |

### MiniMax Skills 兼容

MiniMax 官方提供了 [MiniMax Skills](https://github.com/MiniMax-AI/skills)，支持 OpenClaw 等工具。我们可以：
1. **直接安装 MiniMax Skills** 作为 OpenCortex 的 MCP 插件
2. **同时自建 tools** 做更深度集成

两条路并行不冲突。

---

## 五、架构影响评估

| 维度 | 影响 | 风险 |
|------|------|------|
| 模型路由 | 中等扩展 | 低（已有基础） |
| 工具系统 | 新增 3-4 个工具 | 低（已有 37 个） |
| 设置系统 | 增加 minimax 配置 | 低 |
| Pipeline | 全新模块 | 中（需要设计） |
| 测试覆盖 | 需要新增 | 低 |
| 向后兼容 | 完全兼容 | 无 |

---

## 六、结论

**可行性：高（8/10）**

现有 OpenCortex 架构天然支持多模型协作：
- AgentDefinition 已支持 per-agent model 指定
- ToolRegistry 已支持任意工具注册
- Swarm 已支持多 Agent 并行
- A2A 已支持外部调度

**推荐路径**：
1. **本周**：Phase A MVP（MiniMax 工具 + GLM-5V + 内容路由）← 立刻出效果
2. **下周**：Phase B Pipeline（任务编排）
3. **后续**：Phase C 同福工厂（智能调度）

**一句话**：不改架构，只加工具和路由规则，2天内出 MVP。
