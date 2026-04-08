# Hermes 择优融合方案

## 源码分析总结

### Hermes 亮点评估

1. **轨迹追踪（trajectory）** — 保存对话为 JSONL（ShareGPT 格式）。逻辑简单，可快速适配。
2. **自动技能生成** — Hermes 实际上没有自动从轨迹生成技能的代码。轨迹只是保存，不用于技能生成。需要我们自行设计。
3. **用户画像** — Hermes 有 USER.md 文件式存储，但无自动学习逻辑（靠用户手动写）。需要我们自行设计。
4. **增强记忆（FTS5）** — Hermes 用文件系统 + 正则搜索，没有 SQLite FTS5。需要我们自行设计。
5. **技能商店** — 丰富的 hub 系统（GitHub auth、quarantine、security scan），但依赖链太重，不适合直接搬。

### 实际可行融合项

| 功能 | 来源 | 方案 |
|------|------|------|
| 轨迹追踪 | Hermes trajectory.py 适配 | JSONL 格式保存工具调用轨迹到 data/trajectories/ |
| 自动技能生成 | 自行设计 | 从高频轨迹模式提取可复用技能模板 |
| FTS5 增强记忆 | 自行设计 | SQLite FTS5 替换当前的文件正则搜索 |
| 用户画像 | 自行设计 | 从交互历史自动学习偏好，存储为结构化数据 |
| 技能商店 | 不搬 | 依赖链过重，留后续 |

## 新增/修改文件清单

### 新增
- `src/opencortex/memory/store.py` — SQLite FTS5 记忆存储
- `src/opencortex/memory/fts.py` — FTS5 索引和搜索
- `src/opencortex/trajectory/` — 轨迹追踪模块
  - `__init__.py`
  - `recorder.py` — 轨迹记录
  - `skill_extractor.py` — 从轨迹提取技能模式
- `src/opencortex/profile/` — 用户画像模块
  - `__init__.py`
  - `learner.py` — 偏好学习
  - `store.py` — 画像存储

### 修改
- `src/opencortex/memory/__init__.py` — 导出新模块
- `src/opencortex/memory/search.py` — 增加基于 FTS 的搜索方法
- `src/opencortex/memory/manager.py` — 集成 FTS 存储

### 测试
- `tests/test_trajectory.py`
- `tests/test_memory_fts.py`
- `tests/test_profile.py`
- `tests/test_skill_extractor.py`

## 影响评估
- 所有新功能为**增量添加**，不修改现有 API 接口
- memory/search.py 保持向后兼容，FTS 作为可选增强
- skills 模块不修改，技能生成通过 registry.register 注入
