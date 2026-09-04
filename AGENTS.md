# AI 开发入口

## 项目简介

Tick Stock Panel（TSP）是 A 股数据、选股、监控、分析与回测面板。后端以 FastAPI、Polars、DuckDB/Parquet 为主；前端为 React、TypeScript、Vite 与 TanStack Query。

## 必读与任务导航

1. 每项开发、调试或审查任务先阅读本文件 `AGENTS.md`。
2. 再阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
3. 先查询现有 Understand Anything 图谱（`.ua/knowledge-graph.json`），再根据任务查 [`docs/ai-context/index.md`](docs/ai-context/index.md)，只加载命中的 Context。
4. 涉及二开、扩展点或上游兼容时，额外阅读 [`docs/secondary-development.md`](docs/secondary-development.md)。文中“按需扩展”的示例不是现成 API，必须用代码确认。

## 项目地图

| 区域 | 入口/职责 |
| --- | --- |
| 后端应用 | `backend/app/main.py`：FastAPI 生命周期、路由与扩展装载 |
| HTTP 接口 | `backend/app/api/`：薄 API/SSE 层；业务编排在 `services/` |
| 数据边界 | `backend/app/data_providers/`、`backend/app/tickflow/`、Parquet 仓库 |
| 计算与领域 | `backend/app/indicators/`、`strategy/`、`backtest/`、`services/` |
| 前端 | `frontend/src/router.tsx`、`pages/`、`components/`、`lib/api.ts`、`lib/queryKeys.ts` |
| 扩展 | `backend/app/extensions/`、`frontend/src/extensions/`、`*/custom/` |
| 测试 | `backend/tests/`、`backend/tests/backtest/` |

## AI 上下文与检索规则

- 先索引，后读取；先静态分析，后语义分析；只读完成当前任务必需的最小范围。每次任务开始时，不重新“学习整个项目”。
- Understand Anything 已完成本项目的全量图谱。涉及整体架构、模块/领域关系或已有项目知识时，优先查询该图谱；不要为理解任务重新全量扫描源码。
- 确定性信息（文件定位、类/方法/符号定义、引用、调用、继承、实现）优先使用 Serena：先 `get_symbols_overview` / `find_symbol`，再按需用 `find_referencing_symbols`、`find_implementations`。不要用大范围源码阅读替代静态分析。
- LLM 仅在理解具体业务语义、复杂实现逻辑、设计取舍、修改代码或验证修改影响时读取源码；先由图谱和 Serena 缩小范围，再读取相关文件、类、方法与测试。
- 禁止无目的扫描整个仓库、逐文件阅读，或将可由 Serena 动态取得的类、方法和调用关系复制进本文件或 Context。

### 默认工作顺序

```text
用户需求
  → AGENTS.md / CONTRIBUTING.md
  → Understand Anything 查询已有项目知识
  → Serena 定位模块、符号、引用与调用链
  → 确定最小影响范围
  → LLM 读取必要源码
  → 设计 / 修改
  → Serena 检查影响
  → 执行相关测试
```

### 图谱与长期知识

- 日常改动后优先使用 Understand Anything 的增量更新；仅在大规模架构调整或图谱明显失效时考虑完整 `/understand`。
- [`docs/ai-context/index.md`](docs/ai-context/index.md) 只记录稳定、高价值的长期知识。无法由静态代码推导的架构决策、业务约束和设计原因可按需写入其中；不要将其变成项目百科。

## 构建、启动与验证

```powershell
# Windows 开发启动（会占用/清理目标端口）
.\dev.ps1

cd backend
uv run --frozen pytest tests/path/to/test_x.py -q
uv run --frozen ruff check app/path.py tests/path.py

cd ..\frontend
pnpm build

cd ..
git diff --check
git status --short --branch
```

macOS/Linux 使用 `./dev.sh`。默认后端端口为 `3018`，前端端口为 `3011`。

## 必须遵守的约定

- 通用数据能力必须经 Provider 标准化与能力路由；不得绕过仓库/服务层直接访问某个数据源。
- 金融数据必须区分比例单位、前复权/原始价、交易日与北京时间；改动跨边界时以测试证明口径。
- API 保持薄层；复用既有类型、查询键、缓存和组件。写路径要检查持久化、内存缓存、generation/SSE 与前端失效链路。
- 不覆盖既有未提交改动；不自动提交、推送、合并、删除或批量迁移。以实际验证结果为完成标准。
