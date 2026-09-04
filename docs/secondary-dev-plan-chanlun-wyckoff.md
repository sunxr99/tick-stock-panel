# 二次开发工作计划：czsc 缠论画图 + 威科夫选股

> 适用仓库：tick-stock-panel（TSP）
> 目标：① 接入 czsc（缠中说禅）做缠论画图；② 接入 WyckoffTradingAgent 的威科夫选股策略
> 分级依据：[docs/secondary-development.md](./secondary-development.md) 的 L1/L2/L3
> 数据口径红线：[CONTRIBUTING.md](../CONTRIBUTING.md) §3
> 使用场景：**纯个人本地自用，不分发、不商用、不对他人提供网络服务**

---

## 1. 结论总览

| 需求 | 可行性 | 难度 | 落地级别 | 是否改核心源码 |
| :--- | :--- | :--- | :--- | :--- |
| czsc 缠论画图 | ✅ 可行 | ★★ 中 | L2（后端路由 + 前端插槽） | 否（理想）/ 少量（若主图叠加） |
| 威科夫选股 | ✅ 可行（可移植源码） | ★★ 中 | L1（自定义策略文件） | 否 |
| （可选）缠论买点选股 | ✅ 可行 | ★★★ 高 | L1/L2 | 否 |

**License 结论（已按「个人自用」重新评估）**：
- **czsc** 是 Apache-2.0，与 TSP 的 MIT 兼容，可安全引入，无任何限制。
- **WyckoffTradingAgent 是 AGPL-3.0**，但其义务触发点是「**分发**」和「**对外提供网络服务**」，与「是否商用」无关。纯本地自用、不分发、不部署给他人，即使直接移植/参考其源码也**不触发合规义务**。唯一约束：**将来若要把这个改动开源、fork 出去或分享给别人**，届时才需要「白盒重写」或把整体按 AGPL 开源。因此本方案允许直接移植/参考其 `core/` 源码，但会在代码注释中标注来源，便于将来开源时快速定位替换。

---

## 2. 外部工具调研结论

### 2.1 czsc（waditu/czsc，缠中说禅技术分析工具）

- 协议：Apache-2.0（可引入）。
- 核心能力：
  - `CZSC(bars)` 自动识别 **分型(FX)/笔(BI)/线段/中枢(ZS)**；对象有 `bi_list`、`zs_list` 等。
  - `BarGenerator` 做 K 线合成（1m→5m→30m→日线），可多级别联立。
  - `format_standard_kline(df, freq)` 把标准 OHLCV DataFrame 转成 `RawBar` 列表（入参结构：symbol/dt/open/high/low/close/vol/amount）。
  - 画图：`czsc.utils.plotting.lightweight.plot_czsc(c, output="html")` 输出**自包含 HTML**（底层是 TradingView lightweight-charts，与 TSP 前端图表栈同源）。
- 工程要点：
  - 1.0.x 起缠论核心算法迁到 Rust（PyO3 扩展 `czsc._native`），PyPI 提供 wheel，正常无需本地 Rust 工具链；需 **Python ≥ 3.10**（TSP 要求 ≥ 3.11，满足）。
  - **API 高频迭代、跨版本可能不兼容**：必须 `uv` 锁定版本，不追最新。
  - 纯分析库，不含行情源、不含交易；输入数据由我们本地仓库提供。

### 2.2 WyckoffTradingAgent（YoungCan-Wang）

- 协议：AGPL-3.0；**个人本地自用可不触发义务**（见 §1）。
- 与 TSP 高度同源：数据也走 TickFlow，便于口径对齐与字段映射。
- 「威科夫选股」本质是多层漏斗（Wyckoff Funnel），源码在 `core/wyckoff_engine.py`：
  - L1 垃圾剥离 → L2 六通道强弱甄别（主升/点火/潜伏/吸筹/地量/护盘）→ L2.5 Markup 识别（MA50 上穿 MA200 等）→ L3 板块共振 → L4 微观狙击（Spring 终极震仓假突破 / LPS 缩量回踩 / SOS 放量点火 / EVR 高位放量不跌）→ AI 双轨研判。
- 落地策略：**直接移植/参考其 `core/wyckoff_engine.py` 与 `README_STRATEGY.md` 的规则**，改写成 TSP 策略文件。注意两点：
  - 其引擎是「AI 智能体 + 漏斗」混合体，选股规则与 LLM 调用/CLI/Supabase 深度耦合；移植时要**剥离出纯规则计算部分**（只取量价/均线/RS/ATR 等指标判定），AI 研判层可复用 TSP 已有的 AI 分析能力，不搬其 Agent 框架。
  - 数据源字段对齐：其基于 TickFlow 日线，字段名与 TSP `enriched` 表基本一致，但单位/复权口径仍需逐字段核对（CONTRIBUTING §3）。

---

## 3. 集成架构设计（对齐 TSP 扩展点）

### 3.1 czsc 缠论画图（L2）

```
本地 enriched 日K / 分钟K
   └─ 后端新增模块 backend/app/custom/chanlun.py
        ├─ APIRouter: GET /api/chan/analyze?symbol=&freq=&days=
        │    1. 从 repo.get_daily_asset / get_minute 取 OHLCV
        │    2. format_standard_kline(df, freq) → RawBar 列表
        │    3. CZSC(bars) → 提取 分型/笔/中枢/线段 坐标
        │    4. 返回结构化 JSON（供前端叠加或独立渲染）
        └─ setup(registrar): registrar.include_router(router)
   └─ 前端新增 frontend/src/custom/chanlun/extension.tsx
        ├─ slot: stock-preview.footer（个股详情对话框底部）
        │    在日K视图(view==='daily')下挂「缠论结构」面板/切换按钮
        └─ 渲染：优先 ECharts overlay（markLine=笔/段、markArea=中枢），
             或降级 iframe 嵌入 czsc 的 plot_czsc HTML
```

**两种渲染方案对比**：

| 方案 | 做法 | 优点 | 缺点 | 建议 |
| :--- | :--- | :--- | :--- | :--- |
| A. iframe 嵌入 czsc HTML | 后端 `plot_czsc(..., output="html")` 返回 HTML，前端 iframe 展示 | 开发最快、零侵入、画图最标准 | 与主图割裂、交互/主题不统一、样式隔离 | **第一阶段首选（打通验证）** |
| B. ECharts 叠加 overlay | 后端只返回笔/段/中枢 JSON，前端在 `EChartsCandlestick` 上画 markLine/markArea | 体验好、复用现有图表与交互 | 需改核心 chart 组件或自建独立 chart（L3 风险） | **第二阶段优化** |

> 关键取舍：方案 A 完全走 `stock-preview.footer` 插槽，不改核心源码，升级风险最低；方案 B 若要真正叠加到主图，需改 `EChartsCandlestick.tsx`（高冲突热点），按 L3 管理。建议：先 A 后 B，B 用「独立缠论图 + 复用数据」而非侵入核心 chart。

### 3.2 威科夫选股（L1，移植源码）

```
data/strategies/custom/wyckoff_funnel.py   （用户策略文件，引擎自动发现）
   └─ 遵循 strategy-guide.md 文件结构:
        META{id,name,params,scoring,asset_types,timeframes}
        LOOKBACK_DAYS / REQUIRED_FEATURES
        filter_history(df, params) -> pl.DataFrame   # 历史窗口结构识别
        scoring / ENTRY_SIGNALS / EXIT_SIGNALS
```

- 选股是**历史窗口量价结构识别**（吸筹/Spring/LPS/SOS 等需要 N 日上下文），不能用单日 `polars_expr`，应用 `python_history_legacy`（`filter_history`）或 `matrix_native`（`MATRIX_STRATEGY`）。
- 落地即获得 TSP 免费能力：选股页运行、评分排序、回测（T+1/费用/滑点）、监控、导出，无需改任何核心代码。
- 移植步骤：
  - **Step 1（规则剥离）**：从 `core/wyckoff_engine.py` 提取纯规则计算函数（六通道/Markup/Spring/LPS/SOS/EVR 的量价判定），丢弃 LLM/CLI/Supabase 相关调用；逐个函数标注来源行号。
  - **Step 2（字段对齐）**：将其依赖的字段（MA5/10/20/50/200、量比、RS/RPS、ATR、换手率、amount 等）映射到 TSP `enriched` 列，核对单位/复权口径。
  - **Step 3（策略封装）**：封装成 `filter_history` 策略文件，参数化阈值，配 `scoring`，AI 研判层复用 TSP 个股 AI 四维分析。

---

## 4. 分阶段工作计划

### 阶段 0：准备与验收基线（0.5 天）

- [ ] `git status` 确认工作区干净；记录当前上游 commit。
- [ ] 复现现有 dev 环境：`.\dev.ps1` 起前后端，跑一次内置策略确认数据链路正常。
- [ ] 确认数据权限：缠论日线画图走本地 `enriched` 日K（无需额外权限）；分钟级缠论需 Pro+（`Cap.KLINE_MINUTE_BATCH`）。

### 阶段 1：czsc 后端集成 + iframe 画图（L2，2-3 天）

- [ ] 在 `backend/pyproject.toml`（或 uv 依赖）加入 `czsc` 并**锁定版本**（锁一个稳定 1.0.x）。
- [ ] 新建 `backend/app/custom/chanlun.py`：
  - `setup(registrar)` 注册 `APIRouter`。
  - `GET /api/chan/analyze`：入参 `symbol/freq/days`；从 `repo` 取日K（`get_daily_asset`，注意用**前复权价**做画图，原始价做涨跌停判断——遵循 CONTRIBUTING §3.2）；`format_standard_kline` 转 RawBar；`CZSC(bars)` 提取结构。
  - 失败 fail-closed：数据不足/无结构时返回空 + 明确提示，不抛 500。
- [ ] 新建 `frontend/src/custom/chanlun/extension.tsx`：
  - `stock-preview.footer` 插槽 + `view==='daily'` 时渲染「缠论」面板，调 `/api/chan/analyze`。
  - 首版用 iframe 嵌 `plot_czsc` HTML。
- [ ] 验证：`uv run ruff check`、`pytest`、`pnpm build`；联调看笔/段/中枢是否正确叠加。

### 阶段 2：czsc ECharts 原生叠加（可选，L3 边界，2-3 天）

- [ ] 后端 `/api/chan/analyze` 返回结构化 `segments`/`pivots`/`zones` JSON（不产 HTML）。
- [ ] 前端自建独立缠论 overlay 组件（不侵入 `EChartsCandlestick` 核心），用 markLine/markArea 渲染。
- [ ] 多级别联立：日线 + 30m 双周期（依赖分钟数据权限），`BarGenerator` 合成。

### 阶段 3：威科夫选股 — 源码移植（L1，3-5 天）

- [ ] 通读 `core/wyckoff_engine.py` + `README_STRATEGY.md`，圈出纯规则函数与 LLM/CLI 耦合点。
- [ ] 对照 TSP `enriched` 表字段，逐层确认六通道/Markup/狙击所需字段是否齐备、单位/复权口径是否一致。
- [ ] 移植规则函数为 TSP 可用的 Polars 表达式/历史窗口计算（标注来源注释）。
- [ ] Step 1：用「自定义信号」在 UI 快速验证核心通道可行性。
- [ ] Step 2：写 `data/strategies/custom/wyckoff_funnel.py`（`filter_history` 后端），参数化阈值，配 `scoring`。
- [ ] 回测验证：跑策略回测（T+1/费用/滑点），核对信号日/成交日无未来函数（CONTRIBUTING §5.3）。

### 阶段 4：（可选）缠论买点选股（L1/L2，3-5 天）

- [ ] 基于 `czsc` 信号（三买/一买等）写 `filter_history` 策略或分钟策略。

### 阶段 5：加固与文档（1-2 天）

- [ ] 补齐契约测试（czsc 分析空数据/数据不足/异常路径；威科夫策略的边界与降级）。
- [ ] Docker 镜像重构建验证（czsc Rust wheel 在 Linux/amd64 可用性）。
- [ ] 更新本文档与 `docs/` 说明；标记升级兼容点（czsc 版本锁定、`custom/` 目录不随上游冲突）。
- [ ] 若将来有意开源：记录所有移植来源行号，方便届时执行「白盒重写」替换。

---

## 5. 风险与注意事项

1. **License（已降级但需留档）**：本地自用可直接移植 WyckoffTradingAgent 源码，但**代码注释标注来源**；一旦将来决定开源/分发，须先白盒重写或整体 AGPL 开源。
2. **金融口径红线**：画图用前复权价（视觉连续），涨跌停/结构关键位判断用原始价；分钟 `datetime` 必须北京时间墙钟（CONTRIBUTING §3.3）；换手率小数/百分数口径核对；威科夫移植时逐字段核对单位。
3. **czsc API 不稳定**：锁版本；升级 czsc 时重跑契约测试。
4. **性能**：缠论分析是逐标的 CPU 计算（Rust 核心较快），单股详情按需计算即可；**不要**在全市场扫描/实时热路径里对每只票跑 `CZSC`，否则违反 CONTRIBUTING §6.3。
5. **Docker 依赖**：czsc 引入后需重新构建镜像；确认目标平台 wheel 可用，否则需 Rust 工具链。
6. **扩展失败隔离**：`custom/` 后端模块加载失败只影响该扩展；`setup` 中 `include_router` 冲突会整体不注册，需保证路由前缀唯一。

---

## 6. 验证矩阵（对照 CONTRIBUTING §9）

| 改动 | 最低验证 |
| :--- | :--- |
| czsc 后端路由 | pytest：正常/空数据/数据不足/异常；ruff check |
| czsc 前端插槽 | 无注册、单注册、窄屏、`pnpm build` |
| 威科夫策略 | 参数变更、缓存失效、回测信号日/成交日、无未来函数 |
| 依赖变更（czsc） | Docker 构建、uv lock、契约测试 |
| 整体 | `git diff --check`、前后端联调、`pnpm build` |

常用命令：

```bash
cd backend
uv run --frozen pytest tests/ -q
uv run --frozen ruff check app/custom/chanlun.py

cd ../frontend
pnpm build

cd ..
git diff --check
git status --short --branch
```

---

## 7. 完成检查表

- [ ] 需求已归类 L1/L2/L3 并说明依据
- [ ] 使用的插槽/路由/基类在当前代码中真实存在（`stock-preview.footer`、`BackendExtensionRegistrar.include_router`、自定义策略目录）
- [ ] 移植 WyckoffTradingAgent 源码处已标注来源注释（本地自用合规；留档便于将来开源时替换）
- [ ] 未绕过 provider/仓库抽象，直接读本地文件或数据源
- [ ] 历史配置与旧数据可读，扩展失败不破坏主流程
- [ ] 实际执行了测试、ruff、build 并记录结果
- [ ] 最终 diff 无密钥、本地路径、调试输出
