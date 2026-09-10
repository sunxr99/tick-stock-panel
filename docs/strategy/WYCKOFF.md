# WyckoffTradingAgent 源码研究

## 结论先行

该仓库不是一套完整、确定性的 Wyckoff A-E/吸筹/派发引擎。可复用的确定性核心集中在 `core/wyckoff_structure.py`：交易区间、Spring、SOS、LPS、EVR；大量叙事、Phase、推荐和解释来自 `agents/`、`cli/`、`workflows/`、`core/prompts.py` 的 LLM/工作流层，默认不迁移。

| 能力 | 判定 |
|---|---|
| Trading Range、Spring、SOS、LPS、EVR | 确定性算法（且当前为 observation-only shadow） |
| Accum_A/B/C、Markup | 简化诊断标签；不是完整 Phase A-E 状态机 |
| Accumulation、Distribution、PS/SC/AR/ST、BC、UT/UTAD、SOW、LPSY | 未见完整确定性实现；不得声称已有算法 |
| Volume、价格变化、ATR、区间测试 | 特征和触发条件 |
| 自然语言阶段解释/投资建议 | LLM/Agent 判断 |

## 当前 TSP 的实际计算规则

本节以当前项目 `backend/app/wyckoff/wyckoff_structure.py` 与
`backend/app/wyckoff/config.py` 为准，而非以变量名称或传统 Wyckoff 定义推断。
计算输入为日线 OHLCV；单只股票少于 60 根 K 线时，不计算结构触发。

### 1. Trading Range（交易区间）

区间候选使用最近 90 根 K 线，且排除最新一根 K（`exclude_last=1`）；实际候选至少要有
40 根。这样最新日的价格和成交量不会参与“事前”区间的构造，随后才用最新 K 线检测信号。

- 支撑位：优先取最近 5 个摆动低点的中位数（至少有 2 个摆动低点）；不足时取候选区间的
  10% 分位低价。
- 阻力位：同理，优先取最近 5 个摆动高点的中位数；不足时取 90% 分位高价。
- 摆动点：使用 3 根 K 的左右窗口确认局部高/低点。
- 宽度：`(resistance - support) / support` 必须在 4% 到 45% 之间。45% 是当前配置
  `spring_tr_max_range=30%` 经过实现中的容许放大后得到的实际限值。
- 漂移：候选第一根与最后一根 close 的变化不得超过 18%。
- 测试次数：low 落在 `support × 1.035` 以下、high 落在 `resistance × 0.965` 以上的次数，
  两侧都至少为 2。

`quality_score` 仅描述这个区间的几何质量：

`0.45 × 测试分 + 0.35 × 宽度分 + 0.20 × 低漂移分`

其中测试分最多按 6 次测试归一化；理想宽度为 `clamp(ATR% × 4, 6%, 40%)`。该分数目前
没有最低门槛，也不参与最终候选排序。

### 2. 最新 K 线触发的四类信号

以下规则都在已找到交易区间后，对最新一根日 K 执行（LPS 会额外查看最近 3 根 K）。它们是
**形态触发**，不是自动下单或已确认买点。

| 信号 | 当前精确条件 | 当前触发分数 |
|---|---|---|
| SOS | `close ≥ resistance × 0.99`；当日涨幅 `pct_chg ≥ 6%`；最新成交量 / 前 20 根平均成交量 `≥ 3.0` | `量比 + max((close - resistance) / resistance × 100, 0) + quality_score` |
| Spring | `min(前一日 low, 当日 low) ≤ support × 0.995`；`close > support × 1.005`；`close < mid + width × 0.25`（即处于区间下方约 75%）；最新成交量 / 前 5 根平均成交量 `≥ 1.3` | `(close - support) / width × 100 + quality_score` |
| LPS | 最近 3 根 low 的最小值 `≤ support + width × 0.35`；最新 `close > support`；最近 3 根内最高成交量 / 其前 60 根最高成交量 `≤ 0.65` | `1 - 量比 + quality_score` |
| EVR | 开关启用；最新成交量 / 前 20 根平均成交量 `≥ 1.8`；`close ≤ mid`；当日涨跌幅在 `[-2%, 2%]`；`close ≥ support × 0.98` | `量比 + quality_score` |

这里的“前 N 根”均不含最新触发日。SOS 没有额外要求“昨日收盘在阻力下方”，因此它识别的是
当前仍位于或已经站在阻力附近的放量强势日，而不保证是首次刚突破的那一天。LPS 也不是完整的
“SOS 后回踩确认”状态机：现实现只检查价格靠近区间下部、守住支撑及近期缩量。

代码没有 Spring Test、Shakeout、UTAD、SOW、LPSY 或完整 A–E 阶段序列的确定性规则。所有
信号应在日 K 收盘后才视为有效；盘中显示只是未闭合 K 的暂态结果。

### 3. 阶段标签不等于过滤或信号

当前 `stage_map` 的标签是简化位置诊断：close 在阻力之上为 `Markup`；否则命中 Spring/LPS
为 `Accum_C`；再否则价格位于支撑至区间宽度 35% 内为 `Accum_B`；其余为 `Accum_A`。
它不是完整 Wyckoff Phase A–E，也不会单独过滤候选。

### 4. 当前有没有评分体系？

有局部数值，但**没有统一的 Wyckoff 评分、排序或交易评分体系**：

- `TradingRange.quality_score` 是区间质量分；只作为信号分数的一个加项，不设阈值、不用于排序。
- SOS、Spring、LPS、EVR 各自会产生 `trigger score`，但量纲不同：SOS/EVR 主要是量比，
  Spring 是价格回收幅度，LPS 是缩量程度。因此这些分数不能跨信号直接比较，也没有归一化为
  0–100 分。
- 当前漏斗最终返回的是通过 L3 的候选集合；L4 信号只写入 `wyckoff_signals`/
  `wyckoff_trigger` 供展示。引擎给最终 Wyckoff 行的 `score=1.0` 只是“属于最终集合”的占位标记，
  不是优先级、胜率、仓位或买入评分。

因此，当前列表的默认顺序不应被理解为 Wyckoff 强弱排名。若未来需要评分，应另行设计并验证：
区间质量、信号类型/新鲜度、突破或回收确认、量能、相对强度、止损距离及回测结果等应有统一口径；
这不属于当前四类信号的既有计算。

## V2 独立事件引擎

自 2026-09-06 起，项目新增 `backend/app/wyckoff/v2/` 作为与旧观察器并行的独立引擎。它不读取
`wyckoff_structure` 的 signal、stage 或 score 输出；旧模块仍保留为对照和历史兼容层。V2 当前为
`parallel_diagnostics`，`affects_formal_selection=false`，因此不会改变 L1-L3 漏斗的候选数量。

V2 对每个事件日仅使用该日之前的 K 线建立交易区间，冻结当时的 support、Creek（resistance）、
ATR 容差和边界；后续回放不会移动这些参照物。默认只回放足以覆盖区间和最长事件链的最近历史窗口，
不会把未来 K 线用于早期事件判定。

- Range：使用 4-12 ATR 宽度、45% 百分比安全上限、ATR/价格自适应的边界容差，以及至少两次
  支撑/阻力测试。
- Spring：以 ATR 穿透、收盘位置 CLV 判断，区分 `SPRING_HIGH_EFFORT` 和
  `SPRING_LOW_SUPPLY`。当日仅产生 `spring_aggressive` **预警**；后续供应测试满足低点、量能、振幅和
  CLV 条件后才产生 `spring_standard`；收盘突破 Test high 后才产生 `spring_conservative`。
- SOS：要求前日仍在 Creek 附近或之下、close 超过 Creek 至少 0.3 ATR、当日振幅至少 1.2 ATR、
  CLV 至少 0.70、成交量在自身历史窗口处于至少 80% 分位。下一个闭合 K 未跌回 Creek 才成为
  `SOS_CONFIRMED`。
- LPS：只允许由 `SOS_CONFIRMED` 作为 parent；围绕该 SOS 冻结的 Creek 回踩，检查回撤深度、
  相对 SOS 的缩量和局部转强。跌回 Creek 下方的失效线会标记 `LPS_FAILED`，不会继续保留为信号。
- EVR：拆成 `EVR_BULLISH_ABSORPTION` 与 `EVR_BEARISH_DISTRIBUTION` 两类观察证据，不作为默认
  多头或入场信号。

### V2 信号 状态和入场的逐项解析

V2 的 `Event`（结构事实）、`State`（该事实的后续状态）与 `Entry`（风险偏好对应的介入点）是
三个独立字段。下表中的数值来自 `wyckoff/v2/config.py` 的研究默认值；它们不是传统 Wyckoff 的
固定教条，也尚未用作漏斗准入阈值。

| 类别 | 事件或状态 | 当前判定 | 对结果的含义 |
|---|---|---|---|
| Spring | `SPRING_HIGH_EFFORT` | low 低于 support，但穿透不超过 `1.5 ATR`；close 回到 support 上方；`CLV ≥ 0.60`；成交量 / 前 20 根中位量 `≥ 1.30` | 放量吸收型 Spring 候选；当日仅生成 `spring_aggressive` 预警，不是确认买点。 |
| Spring | `SPRING_LOW_SUPPLY` | 与上述价格及 CLV 条件相同，且量比 `≤ 0.80` | 低供应枯竭型 Spring 候选。 |
| Spring | `SPRING_NEUTRAL` | 与上述价格及 CLV 条件相同，且量比在 `(0.80, 1.30)` | 中等量能 Spring；单独保留统计，不能错误称为低供应。 |
| Spring | `WAIT_TEST` | Spring 后尚未出现有效 Test，最长观察 10 根闭合 K | 只表示等待验证，不是买点。若 low 跌破 Spring low 减冻结容差，转 `SPRING_FAILED`。 |
| Spring | `TEST_VALID` | Test low 不低于 Spring low 减容差，且距冻结 support 不超过 `1 ATR`；Test 量 / 前 20 根中位量 `≤ 0.80`；HIGH_EFFORT/NEUTRAL 还要求 Test 量低于 Spring 量；Test 振幅不高于 Spring 振幅的 80%；close 守住 support；`CLV ≥ 0.55` | 供应测试成立；产生 `spring_standard` 标准介入。LOW_SUPPLY 不强制 Test 量低于已很低的 Spring 量。 |
| Spring | `SPRING_CONFIRMED` | `TEST_VALID` 后的收盘突破 Test high | 产生 `spring_conservative` 保守确认/加仓信号；成本更高、确认更强。 |
| SOS | `SOS_DETECTED` | 前日 close 不高于 Creek 加容差；当日 `close - Creek ≥ 0.3 ATR`、振幅 `≥ 1.2 ATR`、`CLV ≥ 0.70`、成交量处于自身前 120 根至少 80% 分位 | 真正突破 Creek 的候选事件；本身不直接生成 Entry。 |
| SOS | `SOS_CONFIRMED` | 后续闭合 K 的 close 未跌回 Creek，且在最长 5 根观察期内确认 | 冻结该 SOS 的 Creek；它是后续 LPS 的唯一合法 parent。若 close 跌回 Creek 减容差，转 `SOS_FAILED`。 |
| LPS | `LPS_CANDIDATE` | 已有 `SOS_CONFIRMED`；20 根 K 内回踩至冻结 Creek 上方 `1 ATR` 范围 | 只是开始跟踪回踩，不能把普通区间下跌叫作 LPS。 |
| LPS | `SUPPLY_TEST` | 回踩低点距 Creek 不超过 `2 ATR`，回踩期成交量中位数 / SOS 当日量 `≤ 0.65`，且 / 当日之前 20 根中位量 `≤ 0.90`，并且未有效收盘跌破失效线 | 同时相对突破日和自身正常量收缩的供给测试；仍需转强。 |
| LPS | `LPS_CONFIRMED` | `SUPPLY_TEST` 后 close 突破最近 3 根回踩 K 的最高价 | 产生 `lps_standard` 标准介入。若 close 跌破 Creek 减 `0.5 ATR` 的候选失效价，转 `LPS_FAILED`。 |
| EVR | `EVR_BULLISH_ABSORPTION` | 量 / 前 20 根中位量 `≥ 1.8`，价格结果 `≤ 0.5 ATR`，靠近 support，且 `CLV ≥ 0.60` | 低位吸收证据，只观察，不产生买入 Entry。 |
| EVR | `EVR_BEARISH_DISTRIBUTION` | 同样高 effort、低 result，但靠近 resistance 且 `CLV ≤ 0.40` | 高位派发证据，不应被解释为多头信号。 |

其中 `CLV = (close - low) / (high - low)`；越接近 1 表示收盘越靠近日内高点。所有事件均以
闭合日 K 计算。事件 ID 为 `symbol:event_type:detected_date`，同一条事件链用 `parent_event_id`
关联，避免滚动重算时每天制造一条新的 LPS。

### V2 P0 实现记录和研究回测

2026-09-06 已完成 P0，且仍保持 `parallel_diagnostics`：

- Test 和 LPS 的双基准成交量、Test 相对冻结支撑的位置约束、Spring 三分类均在
  `backend/app/wyckoff/v2/config.py` 集中配置；业务代码不含散落的研究阈值。
- `TradingRangeSnapshot` 会冻结 event 当时的 support、Creek、ATR、容差与区间质量；Spring、SOS、
  LPS 的事件和 Entry 都可回溯到这些冻结值及其 parent event。
- `backend/app/wyckoff/v2/backtest.py::run_event_backtest` 可对完整历史 OHLCV 回放，按
  `spring_aggressive`、`spring_standard`、`spring_conservative`、`lps_standard` 分别输出
  T+1/3/5/10/20 收益、MFE、MAE、正收益率（定义为 `return > 0`）、均值/中位数/P25/P75/标准差、
  Profit Factor 与 Spring 后续状态。日线信号在收盘后才可知，故统一按
  **下一交易日开盘价**入场；T+N 仍以信号日计，T+1 即下一交易日收盘。报告明确标示尚未计入手续费、
  滑点和涨跌停不可成交处理。每个 Entry 的每个观察周期还单列 `invalidation_hit_rate`，即该周期内是否
  触及该 Entry 冻结失效价；它与“收益为负”的失败定义分开报告。它只产生研究报告，不影响选股。
- 全市场研究使用 `backend/scripts/run_wyckoff_v2_research.py`。脚本从前复权
  `kline_daily_enriched` 读取数据，按 symbol 小批加载，再交给 `run_event_backtest_frames` 逐只回放，
  不会构造全市场 Pandas 字典而耗尽内存。示例：
  `uv run --frozen python scripts/run_wyckoff_v2_research.py --start 2025-09-05 --end 2026-09-04 --batch-size 100`。
  报告只写入 `data/research/`，不改策略缓存或参数。

#### 2025-09-05 至 2026-09-04 一年全市场研究结果

这是 **range_id / 基准 / taxonomy 升级前的历史基线**：2026-09-06 曾用上述脚本在 5,556 只股票上完成一次前复权日线回放，报告保存为
`data/research/wyckoff_v2_event_backtest_2025-09-05_2026-09-04.json`。所有 Entry 均在信号日后的
下一交易日开盘入场；未计手续费、滑点、涨跌停不可成交，也未相对基准或随机样本做超额收益比较，因而
**不能据此直接形成实盘策略**。此外，本次使用的是当前重建的前复权价格；下一轮严格样本外研究须按
交易日可得的复权因子重建 point-in-time 价格序列，以排除公司行为调整带来的潜在前视影响。

| Entry | 样本数 | T+1 平均收益 / 胜率 / 失效价触发 | T+5 平均收益 / 胜率 / 失效价触发 | T+20 平均收益 / 胜率 / 失效价触发 |
|---|---:|---|---|---|
| `spring_aggressive` | 5,469 | `0.03% / 47% / 4%` | `0.27% / 49% / 31%` | `1.44% / 51% / 59%` |
| `spring_standard` | 963 | `-0.07% / 42% / 2%` | `-0.15% / 44% / 25%` | `1.43% / 49% / 57%` |
| `spring_conservative` | 589 | `0.27% / 47% / 1%` | `0.43% / 49% / 15%` | `2.47% / 53% / 42%` |
| `lps_standard` | 50 | `0.56% / 60% / 0%` | `-1.61% / 41% / 18%` | `-3.65% / 33% / 57%` |

`Spring` 状态链的失败率为 `77.62%`（5,469 个 Spring 中 4,245 个在后续 Test 观察期最终转为
`SPRING_FAILED`），`SOS` 为 `12.13%`，`LPS` 为 `60.05%`。这不是“次日交易亏损率”：例如激进
Spring 的 T+1 收益胜率约 47%，但在随后观察期仍可能跌破 Spring 失效价。界面和评估必须分别呈现
“收益为负”“触及失效价”“事件状态失败”，禁止把三者混为一个“失败率”。

这次基线样本的结论是：激进 Spring 不应升级为默认买点；确认型 Spring 也尚未证明出扣除交易成本后的
稳定超额收益；LPS 样本过少且中期表现为负。下一轮应先加入交易成本、涨跌停/停牌不可成交及基准超额
收益，再用多个不重叠年份做样本外验证，之后才讨论调整识别阈值或正式接入选股。
- `run_parameter_grid` 只接受调用方显式提供的小范围参数候选，用于比较触发数、收益、MFE、MAE
  和状态分布；它不自动选择“最优”阈值，也不修改默认配置。

### V2 研究服务、事件唯一性与回测 API

`backend/app/wyckoff/v2/research_service.py` 是唯一的长期回测执行入口。它运行在后台线程，按 100 个
symbol 的 Parquet 批次加载，避免把全市场历史同时转换为 Pandas；它和正式 `StrategyEngine` 没有依赖关系。
回测开始前额外读 220 个自然日前置行情建立 Range，但只统计请求日期范围内发生的 Entry。结果持久化于
`data/research/wyckoff_v2/runs/<run_id>/`：`manifest.json`（状态）、`summary.json`（聚合报告）、
`events.json`（事件）和 `events.csv`（导出）。服务重启会将未完成任务标为 FAILED，不会伪造成功。

Range 每日重放时以 `support`、`resistance/Creek` 的 ATR 距离（各不超过 1 ATR）以及时间窗口重叠度
（至少 60%）匹配；满足条件即复用同一 `range_id`。Spring/SOS/LPS 同时保留稳定的 `event_id`、
`parent_event_id` 和 `range_id`。同一 symbol + range 的活动 Spring 链不会因滚动重算每天重复新建；
回测报告还输出 unique ranges、每 symbol/range 的事件数、5/10 日重复事件数与重复事件率。

Spring 不再有一个含混的“失败率”。报告中的 `spring_outcomes` 明确互斥为：
`HARD_INVALIDATION`（触及冻结失效价）、`TEST_TIMEOUT`（观察期未出现 Test）、`TEST_REJECTED`
（出现回测行为但供应测试未达标）、`NO_FOLLOW_THROUGH`（Test Valid 后未突破 Test High）和
`CONFIRMED`。它们分别衡量结构失效、等待不足、Test 质量和确认不足，绝不可与负收益率混称。

HTTP API：

- `POST /api/wyckoff/v2/backtest/run`：`start_date`、`end_date`、`entries`、`benchmark`、`horizons`、
  `force_recompute`，立即返回 `{run_id,status}`；
- `GET /api/wyckoff/v2/backtest/{run_id}`：RUNNING/SUCCESS/FAILED、进度、处理 symbol 数与耗时；
- `GET /api/wyckoff/v2/backtest/{run_id}/summary`：聚合报告；
- `GET /api/wyckoff/v2/backtest/{run_id}/events?offset=0&limit=100`：事件分页；
- `GET /api/wyckoff/v2/backtest/{run_id}/export`：CSV。

相同 V2 配置、日期、Entry、universe、benchmark、horizons 与 `ENGINE_VERSION` 会生成同一
`config_hash`；SUCCESS 结果在 `force_recompute=false` 时直接复用。代码版本包含在 hash 中，因此旧引擎
报告不会被新引擎误用。`all_a` 是逐信号日全 A 等权的实际 `D+1 open → T+N close` 横截面收益；
`000300.SH` 是项目本地指数行情的沪深 300 基准。超额收益为股票绝对收益减同日期、同持有期基准收益，
从不使用未来日期构造信号。

前端入口为 **回测 → Wyckoff V2**。该页面可选四类 Entry、日期、基准和强制重算，显示后台进度、
各期限均值/中位数/正收益率/超额收益、MFE/MAE/Profit Factor、Spring 分类、事件和 CSV。页面固定标注
“研究回测，不影响正式选股结果”。

#### 2023-09-01 至 2026-08-14 三年全市场 V2 报告

运行 ID 为 `e32e05d2b07d4c238a2e48fa9637b00e`，完整可复现报告位于
`data/research/wyckoff_v2/runs/e32e05d2b07d4c238a2e48fa9637b00e/summary.json`，事件明细和 CSV 位于同目录。
共回放 5,543 只股票、26,000 个事件、5,194 个有事件股票和 17,928 个独立 Range；每 symbol 事件数中位数 4、最大 23，
5/10 日重复事件为 741/1,125，10 日重复率为 4.33%。

| Entry | 样本 | T+1 平均 / 超额 / 正收益率 | T+5 平均 / 超额 / 正收益率 | T+20 平均 / 超额 / 正收益率 |
|---|---:|---|---|---|
| Aggressive Spring | 11,682 | `0.01% / -0.03% / 46.2%` | `0.27% / -0.14% / 46.8%` | `1.09% / -0.48% / 48.4%` |
| Standard Spring | 2,491 | `-0.04% / -0.06% / 44.3%` | `-0.22% / -0.15% / 44.5%` | `1.04% / -0.03% / 47.1%` |
| Conservative Spring | 1,666 | `0.05% / -0.01% / 45.8%` | `0.45% / 0.05% / 47.5%` | `2.15% / 0.81% / 48.9%` |
| V2 LPS Confirmed | 315 | `0.25% / 0.14% / 48.9%` | `1.16% / 0.42% / 48.9%` | `0.68% / -0.20% / 46.2%` |

Spring 后续状态为 HARD_INVALIDATION 49.09%、TEST_TIMEOUT 2.66%、TEST_REJECTED 32.76%、
NO_FOLLOW_THROUGH 1.02%、CONFIRMED 14.48%。这支持“Test 降低风险”的研究方向，但不能证明可直接交易：
保守 Spring 虽然在 T+5/T+20 平均超额为正，正收益率仍低于 50%，且本报告未计手续费、滑点、涨跌停和停牌。
因此四类 V2 Entry 均继续保持研究诊断，**不接入正式 L1–L3/L4**。

#### Historical L3 与 Legacy LPS 的数据前提

项目当前前复权行情的真实 schema 只有 OHLCV/amount/turnover 等逐日字段，不含逐日行业快照；现有
`data/metadata/tushare_sector_map.json` 是 Tushare `stock_basic` 的**当前**行业映射。因此将它倒灌到
2023/2024 的 L3 会违反 point-in-time 要求。`historical_l3` 和 Legacy LPS 对照报告在未先保存按交易日的
行业/概念成员快照前不得实现或报告；否则会制造看似精确、实则前视的数据。后续应先接入并版本化每日行业、
概念成员和当日可得元数据，再以每个信号日调用当日 L1/L2/L3 重放，最后才比较 ALL MARKET + V2 与
HISTORICAL L3 + V2，以及 Legacy LPS 与 V2 `LPS_CONFIRMED`。这不是参数问题，故本次没有修改任何阈值。

结果行中的 `wyckoff_signals` 现在只放 V2 实际 Entry；`SPRING_DETECTED`、`WAIT_TEST`、
`LPS_CANDIDATE` 等结构状态不再显示为结果表的“信号”。其中 `spring_aggressive` 是绿色/红色买点
之外的中性“Spring 预警（未确认）”，用于建立观察池；它不会出现在“仅看确认买点”筛选中。该筛选
仅保留 `spring_standard`、`spring_conservative` 和 `lps_standard`。旧 L4 形态触发保存在
`wyckoff_legacy_signals`。同时提供 `wyckoff_v2_entries`、`wyckoff_v2_events` 和
`wyckoff_v2_active_event`，其中包含 Event Type、State、Parent Event、冻结区间、失效价与原因，
用于详情/API 和后续回测。现阶段的默认排序仍不是 V2 评分排名。

### V2 P1 研究变体（不属于当前 Wyckoff 规则）

P1 在不改变 Spring candidate、Classic LPS baseline 或 L1-L4 的前提下，增加可重复的研究观察层。它们全部保留在 V2 回测结果中，不能被表述为正式买点或默认阈值。

- 每个 Spring 会冻结 Range、当日量价和背景特征（Range age/width/drift/quality/边界稳定性、penetration/reclaim、CLV、wick、量能分位、20/60/120 日收益、均线斜率与位置）。有效或被拒的 Test 也会写入 delay、深度、量能、spread、CLV 等特征。回测按最终 Spring 状态输出这些特征的 mean/median/p25/p75，用于描述性比较而非 ML 或硬筛选。
- Demand Confirmation 保留 `close > Test high` 基线，并并行发出 ATR、CLV、Volume、CLV+Volume 和完整 Test 结构 swing-high 变体。它们可在回测页的 Experiment Matrix 多选比较；系统不会根据结果自动选择任何一个。
- LPS 现在分为 `lps_classic_standard`（原 P0 `lps_standard` 作为兼容别名）和独立的 `lps_shallow_standard`。Shallow 要求确认 SOS 后不回旧 Range、已有最小有效 impulse、20%-50% 配置化回撤、双口径缩量和后续局部转强；它不是放宽 Classic Creek retest。
- 每次研究运行都会聚合 `TRADING_RANGE → SOS_DETECTED → SOS_HELD → SOS_CONFIRMED → Classic/Shallow candidate → SUPPLY_TEST → confirmed`，以及 `NO_PULLBACK`、`SOS_NOT_HELD`、`CREEK_INVALIDATED`、回撤/缩量失败等拒绝原因。这样 LPS 样本数低可以在报告中逐层定位，而不是凭肉眼估计。
- API 请求可传 `experiment_variants`，所有核心结果仍以 next-trading-day open 进入、按 T+N close 评估。页面默认请求 T+1 至 T+30，并提供 `report.md`、事件 CSV 和事件明细。报告还按请求时间段前 70% / 后 30% 做不随机打乱的时间切分，并以沪深 300 的当日已闭合 60 日收益标记 `BULL/SIDEWAYS/BEAR`（数据不足为 `UNCLASSIFIED`）；两者都只是分层输出，不参与筛选或参数选择。报告只是可复现实验快照；它不自动把发现升级为生产参数。

P1 仍明确不做自动网格寻优、随机切分、历史 L3 回填、机器学习、仓位/交易执行或正式 L4 接入。样本外验证应在确定少量待验证变体后按时间段执行，不能把同一历史区间的最佳结果写回默认配置。

### V2 结果缓存和强制重算

日线策略执行后会把最新结果写入 `data/user_data/strategy_cache.json`，用于页面秒开。同一交易日
点击某个已有结果的策略卡片时，前端会优先读取该缓存，因此不会默认发起全量重算。

要让 V2 使用最新代码重新计算，优先在“选股”页面顶部点击 **重载**：它会重载策略、删除该缓存文件、
清空监控引擎的内存策略结果，并重新运行当前日期的策略池。若后端无法启动或需要手工处理，先停止
后端进程，再仅删除 `data/user_data/strategy_cache.json`（以及存在时的同目录 `.tmp` 文件），然后启动
后端并点击重载。不要删除 `data/kline_daily_enriched/`，那是行情和指标数据，不是策略结果缓存。

## 删除 Agent 后

可直接复用：交易区间和四类结构触发的计算思路。可改造成规则：其 OHLCV/ATR/volume-ratio 特征。只能作为特征：stage_map、quality/trigger score。必须重写：完整 Phase A-E、累积/派发、UTAD/SOW/LPSY、事件序列和多周期语义。不值得迁移：prompt、memory、tool calling、推荐/排名工作流。

## 接入建议

日K适合筛选成熟区间/SOS风险提示，60/15分钟适合执行级 Spring/LPS，但需保留闭合K、Range建立时点、触发时点及随后失效状态。不能把 `Accum_C` 或任一 trigger 当买卖指令。

## Docs First 补充：作者产品设计与动态结构模块的差异

作者 `README.md`/`README_STRATEGY.md` 将系统设计为 L1–L5 漏斗：L4 是微观触发，L5 仍要求 AI 复核、跨日 `VALIDATED`（兼容值 `confirmed`）与 OMS 允许的次日开盘区间。因此“检测出 Spring”不是作者定义的可交易结论。

源码进一步收紧了这一点：`core/wyckoff_structure.py::build_structure_shadow` 返回 `mode='observation_only'` 和 `affects_formal_selection=False`；`workflows/funnel_layers.py::_structure_shadow` 仅比较它与 formal triggers。也就是说，动态 Trading Range/Spring/SOS/LPS/EVR 已是确定性**诊断**，但截至 reference 当前版本尚未提升为正式选股规则。

这一模块仍值得保留为后续研究对象，因为它明确避免当日泄漏：以 `exclude_last=1` 建立可在当日收盘前可见的区间，然后只用最后 K 触发。其 stage 不是完整 Wyckoff Phase：源码仅按价格位置和 spring/lps 输出 `Accum_A`、`Accum_B`、`Accum_C`、`Markup`；文档中的术语不能扩展为已实现的 A–E、Distribution、UTAD 或 SOW/LPSY 算法。
