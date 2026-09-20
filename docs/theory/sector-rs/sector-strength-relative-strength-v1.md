# Sector Strength 与 Relative Strength V1

## 状态与边界

Sector Strength V1.1 是当前冻结 baseline；RelativeStrengthEngine V1 是其后的独立、
只读研究输出。两者均不做 Candidate Pool 硬过滤、交易信号或参数优化。

本阶段没有修改 Wyckoff V2、旧 Wyckoff L2/L3、Dow 或 Volume Profile。候选池阈值和
回测归因属于后续阶段，不能由这里的 score 直接推导。

实现入口：

- `backend/app/services/rps_rotation.py`：Sector Strength V1.1；
- `backend/app/services/relative_strength.py`：RelativeStrengthEngine V1；
- `backend/app/api/rps.py`：只读历史查询接口。

## 数据与共同口径

所有收益均来自 `KlineRepository.get_enriched_range` 的标准化日频
`symbol / date / change_pct`。`change_pct` 是小数制，且由 enriched 的前复权价格体系产生。
窗口按实际 enriched 交易日而非自然日计算，并只使用 `as_of` 当日及此前数据；任一窗口内
缺失交易日、停牌或非有限值都会使该窗口不可用，不会前填或回填。

统一基准为 `all_stock_equal_weight`：在成员映射 join 之前，对同一 enriched 股票池当日所有
有效股票的 `change_pct` 等权平均，再在窗口内复合。它替代仅覆盖上海市场的 `000001.SH`，并
同时供 Sector Strength 与 Stock RS 使用。RS V1 要求基准窗口内每日至少有 2 只有效股票。

行业成员优先由申万 `index_member_all` 的有效区间加载，并复用同一套稳定 ID 与代码解析规则；
行业支持申万一级/二级/三级，当前查询和指定 `as_of` 的历史查询使用同一申万口径。申万文件
不可用时才回退到扩展快照，并应在数据质量中标记回退。概念仍由 `ExtConfigStore` 的同花顺
当前快照加载，允许一只股票多概念归属，但没有概念历史成员区间。

### 当前成员口径决策（2026-09-11）

当前阶段明确采用**申万行业成员 + 同花顺概念成员**来描述当前/近期板块与个股强弱。申万
行业可用于点时历史查询；同花顺概念仍是当前快照，只适合看盘和人工复核，不能直接作为
概念历史收益因子或无 survivorship 的策略结论。

因此，行业结果可按申万 `in_date/out_date` 解析历史成员；概念结果仍定义为“今天这一篮子
股票过去 N 个交易日的表现”，而不是“历史某日官方概念的真实成分表现”。`ext_gn_ths` 会
继续提供概念当前快照；同时应保留每次快照的抓取日期、来源和分类版本。

若后续进入概念维度的严格历史验证或 Candidate Pool 回测，仍必须取得同花顺（或同一固定
taxonomy）的概念历史成员及调入调出有效日期，并让 Sector 与 RS 共用按 `as_of` 解析的成员
关系。行业维度虽然已有申万区间，仍需补齐点时上市/退市、ST、停牌与可交易性数据。

### 申万历史成员区间（2026-09-12）

已通过 Tushare `index_member_all` 拉取并落库最近三年的申万行业成员区间：
`data/sector_membership_history/sw_memberships.parquet`，覆盖 `2023-09-12` 至
`2026-09-12`，保留供应商 `in_date/out_date`，数据源标记为
`tushare_sw_index_member_all`、分类版本 `SW2021`。该文件由
`backend/scripts/pull_sw_membership_history.py` 可重复更新，读取入口为
`resolve_sw_history`；它与原有当前同花顺快照文件分离，不会覆盖概念成员。

脚本会保留申万一级/二级/三级路径，查询时通过 `level=1/2/3` 展开；它不能当作同花顺
概念历史成员，也不改变冻结公式。使用该数据进行历史研究时，仍需单独处理上市/退市、
ST、停牌和可交易性，报告应明确标注 `SW2021` 口径和本地覆盖区间。若本地文件仍是旧版
仅一级路径，需要重新执行拉取脚本后才可使用二级/三级历史结果。

## Sector Strength V1.1

每个 `SectorStrengthResult` 是单日、单个行业或概念板块。原始字段保留 3/5/10/20 日板块
等权复合收益和相对全市场收益，并保留上涨占比与当日 `>= 3%` 强势股占比。

每个因子先在当日板块横截面转换为 0--100 的并列值共享 percentile：

```text
RelativeMomentum =
  0.20 * P(relative_return_3d)
+ 0.25 * P(relative_return_5d)
+ 0.25 * P(relative_return_10d)
+ 0.30 * P(relative_return_20d)

Breadth =
  0.70 * P(up_ratio)
+ 0.30 * P(strong_stock_ratio)

Persistence = min(persistence_days, 20) / 20 * 100

SectorStrengthScore =
  0.55 * RelativeMomentum
+ 0.30 * Breadth
+ 0.15 * Persistence
```

`persistence_days` 是 `RelativeMomentum` percentile 连续不低于 75 的交易日数。最终
`rank` 和 `percentile` 基于 `SectorStrengthScore`，不再只按 20 日相对收益。`rank_std_5d`
用于区分持续强势与单日冲榜；`data_quality` 包含基准、缺失窗口、覆盖率与成员快照限制。

## RelativeStrengthEngine V1

调用方必须显式传入 Sector Strength 产出的稳定 `sector_id`；引擎在全市场计算 Market RS，
只对这些板块范围内的成员输出结果。它一次读取 enriched 日频数据，同时派生个股、市场和
板块收益，不读取或改写策略、候选池或持久化数据。

股票与板块收益均使用 3/5/10/20/60 日精确交易日复合收益：

```text
vs_market_Nd = stock_return_Nd - all_stock_equal_weight_return_Nd
vs_sector_Nd = stock_return_Nd - sector_equal_weight_return_Nd

MarketRS =
  0.15 * P_market(vs_market_3d)
+ 0.20 * P_market(vs_market_5d)
+ 0.25 * P_market(vs_market_10d)
+ 0.30 * P_market(vs_market_20d)
+ 0.10 * P_market(vs_market_60d)

SectorRS = 同一权重的 P_sector(vs_sector_3d/5d/10d/20d/60d)

RSScore = 0.40 * MarketRS + 0.60 * SectorRS
```

`market_rank` / `market_percentile` 是全市场有效股票的 MarketRS 横截面排名；
`sector_rank` / `sector_percentile` 是所属选定板块中 SectorRS 的横截面排名。所有原始收益、
五周期相对收益、两个子分数、最终分数和数据质量均保留在 `RelativeStrengthResult` 中。

每条 `RelativeStrengthResult` 对应一个 `(symbol, sector_id)` 上下文，同时以 `sector_ids`
保留该股票所有被选中的归属。因此多概念股票输出多条结果，而不是任选一个概念。板块完整
有效成员少于 2 只时，不生成板块总分或板块排名；新股、停牌和基准不足通过
`data_quality` 与 `unavailable_reason` fail-closed 地暴露。完全缺失的所选成员映射没有可构造的
股票上下文，因此接口返回空结果。

## 动态状态层（不改变 V1.1 / V1 分数）

动态状态层只消费上述冻结结果，绝不回写 `SectorStrengthScore`、`MarketRS`、`SectorRS` 或
`RSScore`。它为每条结果增加“强度的变化、内部扩散、价格延展、确定性状态”，供看盘、人工
复核与后续候选池研究读取，而不产生买卖指令或新的总分。

Sector 新增 `score_change_1d/3d`、`percentile_change_1d/3d`、`score_slope_3d/5d`、
`rank_slope_3d`（正的 rank 变化/斜率表示排名提升），以及 `up_ratio`、
`strong_stock_ratio` 的 1/3 日变化。`breadth_state` 使用固定三日阈值：上涨成员占比同时
增加至少 5 个百分点、强势成员占比同时增加至少 2 个百分点为 `EXPANDING`；两者分别减少同等
幅度为 `CONTRACTING`；其余为 `STABLE`。

Sector Extension 保留 `return_20d_percentile`、`distance_from_ma20`、
`distance_from_ma60` 与 `consecutive_up_days`。其中均线距离从板块等权日收益复合成的指数计算，
而非引入新的外部板块指数。四个同日横截面 percentile 等权平均为 `extension_score`；
`<70 / 70--<85 / 85--<95 / >=95` 依次为 `NORMAL / ELEVATED / EXTENDED / EXTREME`。
四项任一不可用时不生成延展分，`data_quality.state_missing_components` 会明确指出。

Sector `phase` 及 `phase_reasons` 采用固定描述条件，不依据未来收益调参：

```text
EMERGING:     percentile >= 50，3 日 score >= +5、排名提升 >= 3，且 Breadth EXPANDING
ACCELERATING: percentile >= 80，满足相同改善条件，且 Breadth EXPANDING
LEADING:      percentile >= 80，Breadth 非 CONTRACTING，Extension 为 NORMAL/ELEVATED
EXHAUSTED:    percentile >= 80，Extension 为 EXTENDED/EXTREME，score_change_3d <= 0，
              且 Breadth 不是 EXPANDING
FADING:       score_change_3d <= -5、排名下降 >= 3，且 Breadth CONTRACTING
```

RS 新增 `rs_change_1d/3d`、`market_rs_change_3d`、`sector_rs_change_3d`、
`market_rank_change_3d`、`sector_rank_change_3d`，以及与 Sector 相同口径的个股延展原始字段、
`rs_extension_score` 与 `rs_extension_state`。RS 状态同样是固定解释规则：高分定义为
`RSScore >= 80`；高分且 3 日变化 `>= +3` 为 `HIGH_AND_RISING`，`<= -3` 为
`HIGH_AND_FALLING`，其余为 `HIGH_AND_FLAT`；非高分但变化 `>= +5` 为 `RISING`，其余为
`LOW`。高分且 Extension 为 `EXTENDED/EXTREME` 时优先标记 `EXTENDED`。具体触发条件总是由
`state_reasons` 输出。

RS 的变化分数通过对当前 `as_of` 的精确前 1/3 个 enriched 交易日，按完全相同的冻结计算重建
历史截面后相减；不会读取未来价格。历史不足、停牌、基准不足或延展原始量不完整时状态为 `None`，
原因通过 `state_reasons` 与 `data_quality.state_status/state_missing_components` 暴露。

## Wyckoff 候选的 Sector / RS 研究上下文

Wyckoff 漏斗只决定候选集合。`backend/app/services/wyckoff_candidate_ranking.py` 会为每个
候选计算可解释的 Sector/RS 研究上下文，但**不改变 Wyckoff 默认候选顺序、不写入
`StrategyResult.scores`、不参与交易决策**。它不读取 Wyckoff `score`、事件、阶段、CZSC 或
Volume Profile 字段，也不会删除任何 Wyckoff 候选。

行业层级 V2 同时保留一级、二级、三级申万上下文。SW1 只计算、保存和展示；正式 Opportunity 由 SW2 主行业和 SW3 细分行业组成。每个层级独立调用冻结的 Sector Strength 公式，因此 SW2 的 percentile/rank 只在 SW2 横截面比较，SW3 也只在 SW3 横截面比较。

```text
sector_score_v2 = 0.70 * sw2_sector_score + 0.30 * sw3_sector_score
rs_score_v2 = 0.40 * market_rs + 0.40 * sw2_rs + 0.20 * sw3_rs
opportunity_score_v2 = 0.40 * sector_score_v2 + 0.60 * rs_score_v2

final_rank_score = strength_score
                 + sector_phase_adjustment
                 + rs_state_adjustment
                 - sector_extension_penalty
                 - rs_extension_penalty
```

固定状态映射如下，未经历史收益优化：

```text
Sector Phase: EMERGING +6, ACCELERATING +10, LEADING +5,
              EXHAUSTED -8, FADING -12
RS State:     LOW -8, RISING +5, HIGH_AND_RISING +10,
              HIGH_AND_FLAT +3, HIGH_AND_FALLING -8, EXTENDED -12
Extension:    NORMAL 0, ELEVATED 2, EXTENDED 6, EXTREME 10 (作为扣分)
```

内部状态组合会映射为 `POSITIVE_STATE`、`NEUTRAL_STATE`、`RISK_STATE` 或 `UNAVAILABLE`，仅作
中文状态标签展示，替代带行动暗示的 A/B/C 优先级。候选行保留完整的
`research_context_score`、`research_context_rank`、`ranking_reasons`、`risk_reasons`、
`ranking_status` 和 `ranking_unavailable_reason`，供后续只在 Wyckoff 候选池内进行独立验证。

`sector_score_legacy`、`rs_score_legacy`、`opportunity_score_legacy` 与 V2 分项同时保留，便于固定样本消融。缺 SW3 时不会伪造归属：使用明确标记的 `sw2_only_missing_sw3` 降级口径；缺 SW2 时才回退 Legacy，并记录 `legacy_fallback_missing_sw2`、`sw2_available`/`sw3_available` 与日志诊断。缺失不会删除 Wyckoff 候选，也不会改变其原始候选集。

### 前瞻性研究快照

每次在最新 enriched 交易日运行 Wyckoff 后，系统将候选及完整 Sector/RS 上下文写入
`data/research_snapshots/wyckoff_sector_rs/date=YYYY-MM-DD/snapshot.json`，并将同日当前行业、
概念成员写入 `data/sector_membership_history/memberships.parquet`。历史 `as_of` 请求明确跳过，
绝不以当前成员表回填历史日期。快照用于积累未来的点时研究样本，不构成既有历史回测证据。

## 只读历史验证接口

先查询指定交易日的全部板块，再将返回的稳定 ID 原样传给 RS 接口：

```text
GET /api/rps/sector-strength?as_of=YYYY-MM-DD&kind=concept
GET /api/rps/sector-strength?as_of=YYYY-MM-DD&kind=industry&level=1

GET /api/rps/relative-strength?as_of=YYYY-MM-DD
    &sector_id=concept%3Aall%3A板块A
    &sector_id=concept%3Aall%3A板块B
```

`sector_id` 可以重复传入，也可混合行业与概念。接口不做 Top-N 截断，不设置分数阈值，且不
会写入数据或触发策略。历史日期必须是 enriched 中存在的交易日；不存在时返回空结果。

真实数据抽样时，应同时检查 `market_rank`、`sector_rank`、`sector_ids`、`rs_score`、
`data_quality.status` 和 `unavailable_reason`。在冻结 Candidate Pool 规则前，应先验证多个
历史日期和多概念股票的归属、覆盖与排名行为。

## 已验证范围与后续门槛

测试覆盖收益公式、市场/板块排名、并列 percentile、多概念、行业层级、新股、停牌、NaN、
基准样本不足、成员缺失、严格交易日和无未来数据；API 测试覆盖 JSON 日期序列化、非法
`sector_id` 与重复查询参数。

当前可以进入 Candidate Pool 的研究与回测规则设计阶段，但尚未有资格直接进入实盘或策略
链路。下一阶段必须单独冻结候选规则、以历史样本验证增量价值，并保留每层拒绝原因。
