# 当前行业 / 板块强度能力审计

> **实施状态更新（2026-09-10）**：本审计的主体内容记录的是 Sector Strength / Stock RS
> 实现前的能力基线。当前已在 `rps_rotation` 中实现并冻结 Sector Strength V1.1，且已新增
> 独立的 RelativeStrengthEngine V1 与只读查询接口。最终公式、DTO、数据限制和调用方式见
> [Sector Strength 与 Relative Strength V1](../theory/sector-rs/sector-strength-relative-strength-v1.md)。
> 本次实现没有改动 Wyckoff V2、旧 L2/L3，也没有接入 Candidate Pool 或交易信号。

## 实现前结论摘要

当前项目**没有**一个名为 `SectorStrengthScore`、`SectorRank` 或
`SectorPercentile` 的统一、可供选股链路消费的日频输出。已有能力覆盖了三种不同
语义：

1. 日内的行业/概念涨幅聚合与告警；
2. 以单日平均涨跌幅为基础的板块轮动展示，以及以涨停梯队为基础的主线识别；
3. 旧 Wyckoff 漏斗内、仅针对已通过 L2 候选的行业/概念共振过滤。

它们不能直接等价为“全市场、多周期、可持续的板块强度”。尤其是现行 Wyckoff
L3 的输入范围、时间窗口和返回语义都不同于预期的 Sector Strength；Wyckoff V2
本身是独立 research/diagnostic 链路，本审计不建议将其规则、阈值、Spring/LPS
定义或参数并入本次后续设计。

本文件为只读审计结果；未修改业务代码、策略和 Wyckoff V2。

## 审计范围与口径

审计以当前工作区源码和测试为准，并检查了已有 `.ua/knowledge-graph.json` 作为定位
索引。图谱基线为 2026-09-04，早于当前工作区未提交变更，因此不以图谱内容替代
源码事实。

核心入口包括：

- `backend/app/services/rps_rotation.py`、`concept_rotation_analyzer.py`、
  `market_mainline.py`；
- `backend/app/services/market_overview_builder.py`、`regime_builder.py`、
  `sector_monitor.py`；
- `backend/app/indicators/pipeline.py`、`backend/app/services/abnormal_moves.py`；
- `backend/app/wyckoff/funnel.py`、`layer2_strength.py`、`layer3_resonance.py`，及
  `backend/app/strategy/engine.py`、`backend/app/services/screener.py` 的实际注入；
- `backend/app/backtest/regime_alignment.py`、策略评分/监控规则、对应 API、前端和测试。

除特别说明外，个股 `change_pct`、`momentum_*` 均为小数制；`amount` 为元；
`turnover_rate` 在 enriched 中为百分数值。行业/概念成员关系来自扩展数据快照，
并非历史成分版本。

## 现有能力总表

| 能力 / 模块 | 实际职责 | 主要输入 | 周期 | 输出与公式 | 是否进入候选池 |
| --- | --- | --- | --- | --- | --- |
| Sector Monitor | 日内告警，不做日频强度排名 | 实时个股/指数 `change_pct`，扩展数据成员关系 | 当日涨跌；1/3/5/10/15 分钟 | 板块涨跌 = 有效成员 `change_pct` 的简单均值；分钟动量 = 当前均值 - 窗口前均值 | 否，仅触发通知 |
| Dashboard / Overview 板块排行 | 单日领涨/领跌展示 | 最新 enriched 的 `change_pct`、`amount`、成员关系 | 1 日 | `avg_pct = mean(member change_pct)`；按其排序；输出 `up_count/down_count/amount/leader` | 否 |
| RPS Rotation | 多日“每日涨幅名次矩阵”展示 | `symbol,date,change_pct`、成员关系 | 请求 7--30 日，默认 12 日 | 每日每板块 `mean(change_pct)` 后降序排位 | 否 |
| Theme / Concept Rotation AI | 将轮动矩阵解释为主线、新晋、退潮 | RPS Rotation + Overview | 最近 3 日和请求窗口 | 排名稳定度、首末排名差的规则信号；结果供提示词/AI 文案 | 否 |
| Market Mainline | 涨停梯队意义上的日频主线 | `consecutive_limit_ups, amount`、成员关系、ST 名单 | 1 日；可跨窗口汇总持续性 | 截面 rank 归一后四因子加权为 0--100 主线分 | 否，研究/展示 |
| Market Regime / Phase | 全市场风险环境和情绪阶段 | 全市场 enriched、上证指数、连板梯队 | 1 日；phase 使用约 5 日 EMA 与 2 日确认 | 4 子分加权环境分；phase 是另一套离散状态 | 回测时可作 T-1 硬 entry gate；无板块过滤 |
| 个股 Momentum / Deviation | 个股绝对动量及相对交易所基准偏离 | 复权 `close`、指数日线 | 5/10/20/30/60 日；偏离 3/10/30 日 | `close_t / close_t-N - 1`；`deviate_N = stock_mom_N - benchmark_mom_N` | 可被通用策略评分使用；不是板块 RS |
| Wyckoff L2 | 旧漏斗内个股对大盘 RS + 全市场 RPS | 个股历史、上证指数历史、全市场候选历史 | RS 10/3 日；RPS 50/120 日；斜率 10 日 | 相对大盘累计收益差；全市场收益 percentile | 是，旧漏斗硬层，保持冻结 |
| Wyckoff L3 | 旧漏斗内行业/概念共振 | L2 候选、L1 基数、候选历史、可选映射 | 20/5/3 日 | 候选集内个股强度 percentile 的 `0.4/0.3/0.3` 加权及分组分位筛选 | 是，带 fail-open fallback，保持冻结 |

## 各模块输入、公式与硬软边界

### 1. Sector Monitor：实时板块监控

实现位于 `backend/app/services/sector_monitor.py` 和
`backend/app/strategy/monitor.py`。

- 行业/概念成员由 `ExtConfigStore` 中字段名或标签含“概念/theme/行业/sector”识别；
  行业会展开为一、二、三级路径。指数使用核心指数及本地指数表。
- 有效板块要求成员数不少于 5，且实时有效报价覆盖率不少于 80%。这不是强度过滤，
  而是防止不完整报价形成错误告警的有效性门槛。
- 快照字段有：`change_pct`、`coverage_ratio`、有效/总成员数、上涨/下跌家数和单一
  日内领涨股。行业/概念的 `change_pct` 是有效成员涨跌幅的等权简单平均，未按市值、
  成交额或自由流通市值加权。
- 可选动量窗口严格是 **1、3、5、10、15 分钟**；公式为当前板块均值减去窗口前
  容忍 90 秒误差的历史均值。没有日频 1/3/5/10/20 日板块动量。
- 规则只在“从不满足变为满足”时发出事件，支持上涨/下跌阈值；它不改变任何策略
  score、候选排序或股票池。

结论：这是应复用的**实时观察/告警数据边界**，不是后续 Sector Strength 的评分
引擎。

### 2. Dashboard 的行业/概念强弱：单日等权涨幅榜

`market_overview_builder._dimension_rank` 从最新 enriched 读取个股
`change_pct`、`amount` 等字段，再按成员映射聚合；API 是
`GET /api/overview/market`。

每个板块输出 `name,count,avg_pct,up_count,down_count,amount,leader`，其中：

```text
avg_pct = Σ valid_member.change_pct / valid_member_count
```

领涨/领跌仅按 `avg_pct` 取前 5；`amount` 只是求和后展示，**没有**参与排序或分数。
`up_count/down_count` 也没有折为板块 Breadth 分数。这是 1 日横截面，不记录上期名次、
历史排名变化或持续性。

该模块另计算全市场 `amount.total/avg`、个股量比均值、强势上涨股数量等，并把前 3
概念和前 3 行业中最大的 `avg_pct` 与覆盖率组成 Dashboard 的“主线雷达”维度：

```text
mainline_score = 0.65 * linear_score(mainline_avg, -0.5%, 3%)
               + 0.35 * linear_score(mainline_cover_pct, 1%, 12%)
```

这只是 Dashboard 情绪雷达的一个显示分量；不持久化、不是板块输出，也不进入选股。
`api/overview.py` 中仍保留一份旧的私有聚合辅助函数，但实际 `_build_overview` 已委托
给 `market_overview_builder`，属于应清理的重复实现候选。

### 3. Sector Rotation / RPS Rotation：名称是 RPS，计算不是传统多周期 RPS

`rps_rotation.build_rps_rotation` 和 `GET /api/rps/rotation` 支持概念或行业（行业可取
1/2/3 级）。它读取最近 7--30 个交易日（默认 12）个股 `change_pct`，对每个日期独立
计算：

```text
daily_board_return[d, board] = mean(member change_pct[d])
daily_rank[d, board] = descending_rank(daily_board_return[d, board])
```

它返回 `dates` 与 `{date: [[member, avg_pct], ...]}` 的矩阵，而非每个板块一条带
`score/rank/percentile/change` 的稳定 DTO。没有把 3/5/10/20 日收益复合，也没有相对
大盘收益、成交额、Breadth、强势股渗透率或名次变化字段。

`concept_rotation_analyzer._compute_rotation_signals` 是消费该矩阵的解释层：

- “持续领涨”：最近最多 3 日平均排名 <= 10 且最新 <= 10；
- “新晋”：最早排名 > 30、最新 <= 20、提升至少 20 名；
- “退潮”：最早 <= 10、最新 > 30、下降至少 20 名；
- “机构式稳定”：全窗口 rank 标准差 <= 5 且平均名次 <= 20；
- “游资式轮动”：rank 标准差 >= 20。

这些是供 AI 报告的启发式标签，并没有作为可靠、版本化的程序化板块筛选输出。它应
保留为解释/展示层，不能直接当作硬过滤。

### 4. Theme 与 Mainline：不是同一概念

项目不存在独立的 `Theme` 引擎或 Theme score。当前 “theme” 仅是概念成员字段的一种
识别别名；实际承载 Theme 的是概念映射、RPS Rotation 和 AI 解释。

`market_mainline.compute_mainline_range` 的 Mainline 则是完全不同的涨停梯队定义。它从
enriched 窄扫 `date,symbol,consecutive_limit_ups,amount`，按概念或二级行业聚合：

- `limit_up_count`：连板数 >= 1 的股票数；
- `ge2_count`：连板数 >= 2 的股票数；
- `max_boards`、`boards_sum`；
- `rungs_filled`：>=2 连板的不同档位数量；
- `leader_symbol`：按连板数、成交额降序的第一只。

每个交易日先剔除 `limit_up_count < 3` 的板块。对剩余板块，在**当日截面**分别做
average-rank 的 0--1 归一化：

```text
mainline_score = 100 * (
  0.35 * rank_norm(limit_up_count)
+ 0.25 * rank_norm(max_boards)
+ 0.25 * rank_norm(rungs_filled)
+ 0.15 * rank_norm(ge2_count)
)
```

再按此分数给出当日 `rank`，只持久化前 30。成员数上下限、名称黑名单和 ST 排除发生在
聚合前，属于**主线统计样本过滤**，不是股票池过滤。`/api/regime/mainline` 的窗口汇总
有 `top1_days`、`avg_score`、`max_boards`；阶段摘要则按窗口内 top5 天数和分数和选
主导主线。因此项目已有有限的主线持续性指标，但尚未有连续排名变化、分数变化、
持续天数或衰减后的统一板块 strength 输出。

注意：成员关系是当前扩展数据快照回看历史，因此历史主线有归属漂移风险；服务也会在
缺映射时返回空。这一事实不允许被伪装成严格的历史板块因子。

### 5. Market Regime、Breadth、流动性

`regime_builder` 是全市场日频环境，不是板块强度。它聚合全市场 enriched 的
`change_pct,amount,signal_limit_up,signal_limit_down,signal_broken_limit_up,
consecutive_limit_ups,close,ma20`，再合入上证指数日收益。

其 0--100 环境分为：

```text
profit      = .45*S(up_pct,21,75) + .25*S(avg_pct*100,-1.2,1.3)
            + .20*S(median_pct*100,-1.2,1.3) + .10*S(strong_up_pct-strong_down_pct,-13,14)
speculation = .30*S(limit_up,35,97) + .40*S(seal_rate*100,57,75)
            + .30*S(max_consecutive,4,9)
resilience  = 100 - S(strong_down_pct,2,18)
trend       = .50*S(index_pct*100,-2.5,2.5) + .50*S(above_ma20_pct*100,22,76)
regime_score = .35*profit + .25*speculation + .20*resilience + .20*trend
```

`S(x, low, high)` 是线性映射到 0--100 并钳制。最终状态为 strong (>=70)、
lean_strong (>=55)、range (>=45)、lean_weak (>=30)、weak。它已计算的全市场
Breadth 包括上涨/下跌家数占比、>=+3% 和 <=-3% 的强弱占比、均值/中位数涨跌，
以及 MA20 上方占比；也保存 `total_amount` 和平均成交额。

情绪 `phase` 是另一套基于涨停梯队高度、宽度、晋级率与完整度的日频状态；它做约
5 日 EMA（alpha=1/3）和 2 日确认，并会被弱 `state` 否决正向 phase。它有市场级
持续性，不是行业/概念持续性。

Regime 目前可以在**回测**中按 T-1 的 `states` 或 `min_score` 禁止 entry，且数据
覆盖缺失时 fail-closed；它不影响实时 screener，也没有把板块加分或降权接入策略。

### 6. 个股 Momentum、相对大盘与流动性

enriched 已有：

```text
momentum_N = close[t] / close[t-N] - 1,  N ∈ {5,10,20,30,60}
deviate_N  = stock_momentum_N - exchange_benchmark_momentum_N,
             N ∈ {3,10,30}
```

`deviate_N` 选择上证 A/上证、深证 A/深成、北证 50/上证等交易所基准，主要服务
异常波动接近度，不是统一的 Stock RS。通用策略评分还可以使用个股量比、成交额比、
换手率比、20 日 Amihud、20 日量价相关、60 日换手 z-score 等个股因子；这些没有
按板块归集，也没有板块加分。

项目有个股成交额、换手率、5 日量比和 5/10/20/30/60 日动量，但**没有**：

- 板块成交额相对自身历史的放大；
- 板块成交额占全市场份额及份额变化；
- 板块加权成交额或流动性 score；
- 板块内上涨占比/强势股渗透率的时间序列 score。

### 7. Wyckoff L2 / L3 的实际边界（保持冻结）

旧 `wyckoff_funnel` 与 V2 research 是不同链路。L2 已有两种有价值但不可直接替代新
RelativeStrengthEngine 的计算：

- 个股 vs 上证指数：按同日期对齐的 `pct_chg` 累计收益，取 10 日与 3 日，判断
  `stock_return - benchmark_return` 是否超过现有配置阈值；
- 全市场 RPS：以调用的完整股票 universe 中的 50 日、120 日收盘收益做 percentile
  （0--100），再加 10 日收益斜率。

这说明“个股 vs 大盘 RS”已存在于旧漏斗，但它是 L2 的冻结门槛与通道条件，未产出
通用 DTO；并且不存在“个股 vs 所属行业/概念”的 RS，也不存在板块内 percentile/rank。

L3 的实际计算为：先对**已经通过 L2 的候选**计算候选内的

```text
candidate_strength = .40*pct_rank(ret20)
                   + .30*pct_rank(ret5)
                   + .30*pct_rank(ret3)
sector_strength = median(candidate_strength of L2 symbols in group)
```

再以 L2 成员数、`L2_count / L1_count` 通过率及 `sector_strength` 的配置分位数决定
保留分组/前 N 分组，并允许强个股、热概念和“不足 3 个幸存者”回退。它是硬过滤与
回退混合的旧漏斗层，不是市场全样本的 Sector Rank。

更关键的是，`StrategyEngine._run_wyckoff_funnel` 调用 `run_funnel` 时只传入
`sector_map`；`ScreenerService.build_strategy_context` 目前注入的是 Tushare
`symbol -> industry` 映射。没有传 `concept_map` 或 `hot_concepts`。所以尽管 L3
接口和单测支持概念优先/热概念，当前正式调用实际为**行业回退路径**。这不是要求
本次修复的缺陷；它是后续集成必须显式处理的事实。

## 对十个问题的直接回答

1. 已有板块强度能力：日内等权涨幅/分钟变化告警、单日概念/行业平均涨幅榜、7--30
   日每日排名矩阵、涨停梯队主线 score、候选集内 L3 共振；没有统一 Sector Strength。
2. 每个模块输入见“现有能力总表”和各模块小节；核心来源是 enriched、扩展成员快照、
   指数日线/实时行情，L3 正式运行另使用 Tushare 行业元数据。
3. 现有周期：日内 1/3/5/10/15 分钟；Rotation 7--30 个交易日（默认 12）；主线
   单日并跨窗口汇总；个股动量 5/10/20/30/60 日；偏离 3/10/30 日；L2 RS 10/3、
   RPS 50/120、斜率 10 日；L3 20/5/3 日；Regime/Phase 为日频。
4. 现有 score 公式：Mainline、Regime、Dashboard mainline radar、L3 已在上文列出；
   Rotation 和 Overview 只有均值及排序，不存在综合 score。
5. 硬过滤：Monitor 有有效性门槛但只告警；Mainline 有成员/ST/最少涨停/Top30 的
   统计样本门槛；L1/L2/L3 是旧 Wyckoff 漏斗门槛及 fallback；Regime 在回测可硬拦
   entry。评分/展示：Overview、Rotation、AI Theme、Dashboard 雷达、通用策略 score。
   没有板块对个股的加分、降权或过滤。
6. Rotation 是涨幅截面与名次轨迹；Theme 是概念语义/AI 解释而非独立引擎；Mainline
   是涨停梯队的主线；L3 是漏斗候选集的共振。前两者与 Overview 的日均涨幅聚合有
   数据和职责重复；Mainline 与 L3 不应合并，因为样本和决策语义不同。
7. 不存在统一 `SectorStrengthScore/SectorRank/SectorPercentile` 输出。现有 `rank`
   分散在每日 Rotation 列、Mainline 日表、L3 内部临时选择，语义不可互换。
8. 已计算：板块单日平均收益、Rotation 的每日排名、Mainline 有有限持续性；全市场
   Breadth/上涨占比/强势股占比/总成交额。未计算：板块相对大盘收益、多周期板块
   Momentum、板块 Breadth/上涨占比 score、板块强势股渗透率、成交额放大、成交额
   市场份额变化、统一板块持续性和板块排名变化 DTO。
9. 已计算：L2 的个股 vs 上证指数 RS，以及个股 vs 传入全市场 universe 的 RPS；
   `deviate` 也有交易所基准偏离。未计算：个股 vs 所属板块 RS、板块内个股
   percentile/rank。
10. 目标链路缺的关键是：统一成员关系/快照版本、日频板块特征和结果出口、板块内
    Stock RS、明确的候选池接口，以及把前述输出交给 Wyckoff/ICT 的适配层。无需另
    起一套与 Rotation/Mainline 重叠的“板块计算宇宙”。

## A. 可以直接复用

- `market_mainline`：作为“涨停生态主线”这一独立因子，保留其日频历史、rank、
  `top1_days` 与过滤配置；不要把它误命名为全量板块强度。
- `rps_rotation` 的成员映射加载和按日 `avg_pct` 聚合：可作为 Sector Strength 的
  **return/breadth 基础特征**来源，特别是概念与分级行业映射。
- `market_overview_builder`：复用全市场 Breadth、总成交额、量比、情绪背景，作为
  Market Context；其单日行业/概念聚合可成为校验/展示视图。
- `regime_builder` 与 T-1 回测掩码：作为全市场 gate，保持与板块选择解耦。
- enriched 的个股动量、量比、成交额、换手和标准化价格口径：是后续 Stock RS 的
  输入基础。
- 现行成员关系和 `SectorMonitorService`：复用日内成员目录、覆盖率校验及实时快照，
  但仅服务盘中观察。
- Wyckoff L2/L3 和 V2：作为冻结的既有消费者/诊断，不改规则、不调参、不反向迁就
  新 DTO。

## B. 可以重构后复用

- 将 `rps_rotation` 的输出从“日期 -> 二元数组”补成稳定的内部日频特征表或 DTO；
  保留现有 API 的兼容适配，不必重写其聚合逻辑。
- 抽取 Overview 与 Rotation 共享的成员映射/每日聚合入口。`api/overview.py` 中已不走
  的私有 `_dimension_*` 实现应在后续小范围清理，避免三份成员口径漂移。
- 将 Mainline 作为 `mainline_score/mainline_rank` 的**可选特征**并入统一结果，而不是
  与 return-strength 混成一个不可解释的总分。现有 Top30 截断应保留为展示存储策略，
  不能成为统一强度全样本表的唯一数据源。
- 让 Rotation 的“排名变化/稳定性”从 AI prompt 私有规则提炼为确定性字段（例如
  `rank_change_3d`、`rank_std_window`、`persistence_days`）；AI 只消费这些字段。
- 如果未来需要 L3 感知新出口，只增加适配层输入；不要将 L3 的候选集分位数当作
  Sector Strength 公式，也不要改其当前 fallback。

## C. 真正缺失

- 一个轻量的、统一的 `SectorStrengthResult` 出口及其日频历史：至少同时给出行业和
  概念、成员数/有效覆盖、rank、percentile、前期 rank/score 变化和数据日期。
- 板块相对大盘收益：在 3/5/10/20 日等窗口计算 `sector_return - benchmark_return`。
- 板块多周期 Momentum：用复合收益而非“每天各自排名”表达。
- 板块 Breadth：上涨占比、强势股（可先使用现有 >=+3%）渗透率，以及这些指标的
  趋势/持续性。
- 板块成交额：总额、相对自身历史放大、全市场成交额份额与份额变化。Volume Profile
  不在本范围。
- `RelativeStrengthEngine`：输出 stock-vs-market、stock-vs-sector、板块内 rank 和
  percentile；本任务只定义，不实现。
- 一个明确的 `SectorStrength -> Stock RS -> candidate pool -> Wyckoff/ICT` 编排边界，
  以及对缺失成员映射、基准不足、停牌/新股数据不足的可解释状态。

## D. 不建议继续保留在核心链路

- 不要把 `concept_rotation_analyzer` 的 AI “主线/新晋/退潮”标签作为候选池硬过滤；其
  阈值是解释性启发式，且输出主要是流式文本。
- 不要把 Dashboard `mainline_score` 雷达值作为选股因子；它取前若干板块最大值且只为
  当日情绪可视化设计。
- 不要把 L3 `top_sectors` 作为新的全市场 Sector Rank，或将其与 Mainline 合并；它只
  在 L2 候选截面上计算，并有显式 minimum-survivor/missing-metadata fail-open。
- 不要将日内 Sector Monitor 的分钟动量升级为日频强度硬过滤；它服务告警且受到实时
  覆盖和缓存窗口约束。
- 后续可删除/降级 `api/overview.py` 中不再被实际 `_build_overview` 调用的私有板块
  聚合副本；先做引用检查后再删，不影响本阶段。

## 最小改造方案（建议，尚未实施）

### 原则

不创建平行的 `SectorStrengthEngine`。在 `rps_rotation` 现有“成员映射 + 日频聚合”
能力上增加一个很小的计算/结果出口即可；`market_mainline` 与 `regime_builder` 保持
各自领域职责，只作为可选输入特征。Wyckoff V2 冻结，旧漏斗 L2/L3 保持原样。

### 推荐保留、重构、新增和降级

| 类别 | 推荐 |
| --- | --- |
| 保留 | `rps_rotation` 聚合与 API 兼容层、`market_mainline`、`regime_builder`、`SectorMonitorService`、enriched 动量/量能字段、冻结的 Wyckoff L2/L3/V2 |
| 小范围重构 | 共享成员映射/日频板块聚合；为 Rotation 加结构化 rank-change/persistence；消除 Overview API 的死副本；将 Mainline 作为可选特征接入结果 |
| 最少新增 | 一个 `SectorStrengthResult`/日频计算出口；一个后续 `RelativeStrengthEngine`；一个候选池编排器或现有 Screener context 的窄适配 |
| 删除或降级 | AI Rotation 标签、Dashboard radar mainline、L3 候选集 sector rank、日内分钟变化均仅作解释/观察；Overview 死副本待引用确认后删除 |

### 推荐数据流

```text
Provider / ext_data 成员快照 + enriched 日线 + 指数日线
    -> 复用 rps_rotation 的成员归集
    -> SectorStrengthResult（日频：收益、相对收益、Breadth、成交额、rank/变化/持续性）
    -> 选择“强势或正在增强”的行业 / 概念
    -> RelativeStrengthEngine（stock vs market、stock vs sector、sector percentile）
    -> CandidatePool（保留解释字段与缺失状态）
    -> 冻结的 Wyckoff / 后续 ICT 适配器

RegimeBuilder ---------------------------------> CandidatePool 的可选全市场 gate
MarketMainline --------------------------------> SectorStrengthResult 的独立可选特征
SectorMonitorService --------------------------> 盘中展示 / 告警，不写入日频选择公式
```

### 建议的最小 DTO

`SectorStrengthResult` 应以“一日、一个 `kind + sector_id` 一条”为原则；不要只用展示
名称作稳定键。最小字段建议：

```text
as_of, kind, sector_id, name, level, source_field
member_count, valid_member_count, coverage_ratio, membership_as_of

return_1d, return_3d, return_5d, return_10d, return_20d
benchmark_return_3d/5d/10d/20d
relative_return_3d/5d/10d/20d

up_ratio, strong_stock_ratio, avg_return, median_return
amount, amount_ratio_5d, market_amount_share, market_amount_share_change_5d

rank, percentile, rank_change_1d, rank_change_3d, score_change_1d
persistence_days, rank_std_window

mainline_score?, mainline_rank?, regime_state?, data_quality, unavailable_reason
```

第一版 `score` 应只由明确、可审计的日频特征组成，并同时保留原始特征与各分项，避免
只有黑箱总分。`mainline_score` 是独立可选字段，不应替换 `relative_return` 或 Breadth。

后续 `RelativeStrengthResult` 的最小字段建议：

```text
as_of, symbol, sector_ids, benchmark_id
stock_return_3d/5d/10d/20d
vs_market_3d/5d/10d/20d
vs_sector_3d/5d/10d/20d
sector_rank, sector_percentile, market_rank, market_percentile
data_quality, unavailable_reason
```

多概念归属必须允许多个 `sector_id`，不能默默任选一个；行业可指定标准层级。成员快照
版本/日期必须随结果暴露，以避免历史回测把当前成分误当历史事实。

### 后续实现顺序

1. 先固定成员映射的稳定键、行业层级、概念多归属和快照版本口径，并为现有聚合补测试；
2. 在现有 `rps_rotation` 基础上输出无选择副作用的日频 SectorStrength 原始特征与
   rank/变化历史；先不接 Wyckoff；
3. 增加板块相对大盘、多周期收益、Breadth、成交额放大/份额和持续性，验证交易日
   对齐与数据缺失语义；
4. 定义并实现独立 `RelativeStrengthEngine`，先输出结果和测试，不改变策略权重；
5. 增加 CandidatePool 编排，接入 Regime 作为可选 gate，并保留每层输入/拒绝原因；
6. 最后再以只读适配方式让 Wyckoff/ICT 消费候选池。对旧 L2/L3 与 Wyckoff V2 的
   规则、阈值、Spring/LPS 定义不做任何改动；
7. 在新出口验证稳定后，清理 Overview 的死副本和将 AI/雷达/L3 结果明确降级为
   展示/诊断消费者。

## 最终判断

现有项目已经具备构建后续流程所需的大部分**原始数据、成员映射、单日聚合、主线和
市场环境基础**，因此不应平行重建一套 Sector Rotation/Theme/Mainline。真正需要补齐
的是把这些分散、不同语义的能力收敛为一个可解释的日频结果出口，并在其后单独实现
Stock RS。这样才能得到：

```text
Sector Strength（强 / 正在增强）
-> 板块内 Stock RS
-> 可解释候选池
-> 冻结 Wyckoff / 后续 ICT
```
