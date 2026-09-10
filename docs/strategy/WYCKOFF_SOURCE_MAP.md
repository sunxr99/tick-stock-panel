# WyckoffTradingAgent 迁入源映射（第 1 天）

本文件记录上游 `reference/WyckoffTradingAgent/WyckoffTradingAgent-main` 的静态入口与 TSP 接入边界。它不是对上游能力的重新宣称；所有未列为确定性模块的 Agent/LLM 输出都不进入本次领域核心。

## 完整确定性漏斗入口

上游 `core/wyckoff_engine.py::run_funnel` 是 L1--L4 的组合入口。其输入为：

```text
all_symbols + 每只股票的日线 DataFrame + 基准指数 DataFrame
+ 名称/市值/行业映射
+ 可选概念、概念热度、主题雷达、财务与主题成员映射
-> FunnelResult(L1/L2/L3、触发器、阶段、退出风险、候选条目)
```

因此完整漏斗不能先被包装成单股票的 `filter_history` 文件：后者没有全市场 RPS、基准、行业/概念横截面与市值输入。TSP 将新增独立领域服务承载漏斗；策略接口只消费该服务产生的候选与历史信号。

## 上游模块与迁入分组

| 分组 | 上游模块 | 用途 | TSP 落点 | 第 1 天结论 |
| --- | --- | --- | --- | --- |
| 基础数学 | `core/_price_math.py` | 日期排序、摆动点、收益/回撤、量价辅助 | `backend/app/wyckoff/_price_math.py` | 已迁入，保留来源与 AGPL-3.0 标注 |
| 市场规则 | `core/cn_boards.py`、`core/limit_move.py`、`core/trend_drawdown_risk.py` | A 股板块波动、ST/涨跌幅语义、回撤风险 | `backend/app/wyckoff/` + TSP instrument 适配 | 三个模块均已迁入并单测；后续接入时仍需逐字段核对 TSP 的板块、名称和原始价口径 |
| L1--L4 | `core/wyckoff_engine.py`、`core/layer2_strength.py` | L1 过滤、八通道、RPS/RS、L3 共振、L4 与阶段/退出 | `backend/app/wyckoff/engine.py` | `run_funnel` 是完整确定性主入口；需拆除外部数据读取 |
| 候选与风控 | `core/candidate_*.py`、`core/price_targets.py`、`core/main_force_signal.py` | 候选条目、排序、风险/目标价、主力特征 | `backend/app/wyckoff/` | 迁入，但交易执行仍由 TSP 回测/策略层负责 |
| 主题/主线 | `core/theme_*.py`、`core/mainline_engine.py`、`core/concept_filters.py` | 概念热度、主题归一、主线候选 | TSP 行业/概念适配后迁入 | 依赖 TSP 现有板块/概念数据的可用性；缺失时必须返回明确降级状态 |
| 动态结构 | `core/wyckoff_structure.py`、`core/wyckoff_events.py` | Trading Range、Spring/SOS/LPS/EVR、简化阶段、可解释事件 | `backend/app/wyckoff/` + 个股分析 API | 两个模块与其配置均已迁入并单测；上游结构信号保持 observation-only，首版不直接变成交易指令 |
| L2 强弱 | `core/layer2_strength.py` | 基准对齐 RS、全市场 RPS、主升/潜伏/吸筹等八通道 | `backend/app/wyckoff/layer2_strength.py` | 纯计算核心与八通道已迁入、单测；诊断文案和实际全市场上下文装配待随策略后端接入 |
| L3 共振 | `core/wyckoff_engine.py` 的 Layer 3 纯计算段 | 概念优先、行业兜底的共振筛选；板块样本数/强度动态阈值 | `backend/app/wyckoff/layer3_resonance.py` | 已迁入、单测；实际行业/概念映射和热点主线需由专用策略后端装配 |
| 漏斗编排 | `core/wyckoff_engine.py` 的 `run_funnel` 主链 | 一致市场快照下的 L1→L2→L3→L4 编排与结果快照 | `backend/app/wyckoff/funnel.py` | 已迁入纯领域编排并单测；策略引擎的专用后端、上下文装配与结果持久化待接入 |

## 明确排除

不迁入 `agents/`、`cli/`、`web/`、`desktop/`、`mcp_server.py`、`workflows/` 的调度/写库部分、`integrations/` 的上游数据拉取与 Supabase 访问、LLM prompt/报告、账号/持仓/通知。

`workflows/funnel_layers.py` 只作为上游调用顺序参考：它证明完整路径为 L1 → L2 → L3 → L4 + structure shadow，但不作为 TSP 运行时依赖。

## TSP 适配契约

| 上游输入 | TSP 提供者 | 适配要求 |
| --- | --- | --- |
| 单票 OHLCV | `KlineRepository` / enriched | `date/open/high/low/close/volume/amount`；价格与同一分析窗口保持前复权一致 |
| 全市场历史 | enriched history | 每个 `as_of` 只能读取当日及以前交易日；默认至少 320 个交易日 |
| 基准指数 | `KlineRepository.get_daily_asset(..., asset_type='index')` | 指数代码、交易日与个股窗口对齐；缺失时 L2 RS/大盘依赖项 fail-closed 或显式降级 |
| 名称、市值、ST、板块 | TSP instruments / 元数据服务 | 不从上游文件或外部 SDK取数；单位和历史可得性必须验证 |
| 行业/概念/热度 | TSP 现有扩展数据与服务 | 完整 L3/主线仅在数据存在时启用；不能用空映射伪造“板块共振” |

## 迁入原则

1. 每个复制文件的模块注释写明上游仓库、相对路径、AGPL-3.0 与本地自用范围。
2. 迁入目录只允许依赖 pandas、numpy 和 TSP 明确提供的 Adapter；禁止直接导入 `core.*`、`integrations.*`、上游 SDK 或云端配置。
3. 首次迁入先保持上游阈值；参数化、优化和提升到正式候选均在 TSP 历史回放有证据后另行进行。
4. 任何结构信号都保存 `event_time`、`confirmation_time`、`status` 与证据，且在相同 `as_of` 重放时结果稳定。
