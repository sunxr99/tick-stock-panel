# Sector / RS + Volume Profile 随机五日联合研究

## 结论

**INSUFFICIENT。** 本次结果不足以把 VP 接入正式 `final_rank_score`，也不足以声明
Sector / RS + VP 的联合排序有效。它是一个可复现的、小样本探索：用于检查 VP
上下文能否在既有 Wyckoff 候选和既有 Sector / RS 排名内提供额外区分，而不是正式
策略回测或参数选择。

最重要的观察是：在本样本的 Sector / RS 前 30% 候选中，VP20 的
`ABOVE_VAH_ACCEPTED`（43 条）在所有 T+1--T+20 期限均没有优于
`ABOVE_VAH_UNACCEPTED`（409 条）；方向甚至在 T+3/T+5/T+20 相反。这个结果
反直觉，但样本仅 5 个信号日且 Accepted 极少，**不能**据此反转 Acceptance 的
含义或调节 VP 规则。VP60 Accepted 仅 17 条，也不能下结论。

此外，五日中所有 VP20/VP60 样本的 `vp_*_extension` 都是 `VP_NORMAL`，所以本轮
无法检验 VP 上行延展状态是否具备风险识别价值；这不是“延展没有风险”的结论。

## 冻结口径

- 候选池：每日全部通过当前 Wyckoff 筛选的 `ALL_WYCKOFF`；没有先截取 Top20。
- Sector / RS：复用冻结的 `research_context_score` 与每日 `research_context_rank`，
  本报告将每日 rank 前 30% 仅作为预先声明的观察分层，**不是新的交易阈值**。
- VP：分钟 `MINUTE_RANGE_OVERLAP`，仅主统计中的 `quality=FULL`、
  `data_granularity=MINUTE_1M`、`fallback_used=false` 样本；VP20 与 VP60 分开。
- 信号/收益：信号在当日收盘后形成；下一交易日开盘进入；信号日后第 N 个交易日
  收盘退出；使用 enriched 前复权 OHLC。超额收益为股票收益减 `000001.SH` 同窗口收益。
- 没有创建 VPScore、没有改动 Wyckoff、Sector、RS、Phase、State、Extension 或
  `final_rank_score`。

## 样本与重复性

随机种子为 `20260912`，从已完成的 14 个可用信号日中无放回抽取：

`2026-02-02`、`2026-02-03`、`2026-02-05`、`2026-02-10`、`2026-02-24`。

| 项目 | 结果 |
| --- | ---: |
| ALL_WYCKOFF 观测 | 2,824 |
| 每日候选数 | 512 / 636 / 535 / 513 / 628 |
| 唯一股票 | 1,518 |
| 信号日 | 5 |
| VP20 FULL | 2,821（另有 PARTIAL 3） |
| VP60 FULL | 2,801（另有 PARTIAL 23） |
| Sector / RS 每日前 30% | 844 |

同一股票可在多个信号日再次出现，因此 2,824 条股票×日期观测不是相互独立样本；
所有均值、PF 和胜率都必须按这一限制解读。

原始分日 VP 产物位于：
`data/research/vp_context_random5_2026-02/signal_date=*.parquet`；运行状态记录在
`data/research/vp_context_random5_progress.json`。

## 市场总体与 Sector / RS 前 30%

下表为超额收益（%）；PF 为超额收益的正收益总和除以负收益绝对值总和。中位数为
单条候选的中位超额收益，而非每日组合收益。

| 组别 | n | T+1 mean / median / PF | T+3 mean / median / PF | T+5 mean / median / PF | T+10 mean / median / PF | T+20 mean / median / PF |
| --- | ---: | --- | --- | --- | --- | --- |
| ALL_WYCKOFF | 2,824 | 0.17 / -0.27 / 1.14 | 0.21 / -0.43 / 1.10 | 0.26 / -1.05 / 1.08 | 1.66 / -0.73 / 1.43 | 0.85 / -2.89 / 1.14 |
| Sector / RS 前30% | 844 | 0.10 / -0.26 / 1.08 | -0.06 / -1.08 / 0.98 | 0.36 / -0.86 / 1.10 | 1.92 / -1.09 / 1.41 | 0.10 / -4.08 / 1.01 |

本五日中，Sector / RS 前 30% 并未对 ALL_WYCKOFF 呈现跨期限、一致的超额优势。
这与既有 Sector/RS 独立验证中“不能把高静态分直接解释为未来收益”的边界一致，
但本表并不重新判定冻结指标本身。

## VP20：Sector / RS 前 30% 内的 Acceptance 对照

只比较价格处于 VAH 上方的候选；`ACCEPTED` 要求 VP 的 POC 和 Value Area 已按当前
固定定义向上迁移，`UNACCEPTED` 表示价格在 VAH 上方但价值区未满足该接受条件。

| VP20 组别 | n | T+1 mean / median / PF | T+3 mean / median / PF | T+5 mean / median / PF | T+10 mean / median / PF | T+20 mean / median / PF |
| --- | ---: | --- | --- | --- | --- | --- |
| ABOVE_VAH_ACCEPTED | 43 | -0.62 / -1.05 / 0.70 | -1.85 / -2.89 / 0.55 | -2.99 / -3.66 / 0.45 | 0.22 / -1.08 / 1.04 | -4.06 / -8.01 / 0.60 |
| ABOVE_VAH_UNACCEPTED | 409 | 0.05 / -0.50 / 1.03 | 0.14 / -0.77 / 1.05 | 0.76 / -0.53 / 1.21 | 2.27 / -1.06 / 1.47 | 1.32 / -3.36 / 1.19 |

风险路径也未支持 Accepted 组更健康：T+3 平均 MAE 为 -5.88%（Accepted）对 -4.66%
（Unaccepted），T+5 为 -8.08% 对 -5.92%，T+20 为 -16.02% 对 -12.65%。不过
Accepted 的 43 条观测覆盖仅五个日期，不能视为稳定反证；可能是当时的市场环境、
重复股票或当前 Acceptance 固定定义所致，须在更长且独立的样本检验。

## VP60：Sector / RS 前 30% 内的 Acceptance 对照

| VP60 组别 | n | T+1 mean / median / PF | T+3 mean / median / PF | T+5 mean / median / PF | T+10 mean / median / PF | T+20 mean / median / PF |
| --- | ---: | --- | --- | --- | --- | --- |
| ABOVE_VAH_ACCEPTED | 17 | 0.21 / -0.11 / 1.17 | -0.53 / 0.80 / 0.77 | 1.19 / 0.19 / 1.35 | 0.96 / -3.13 / 1.24 | 2.32 / -1.15 / 1.48 |
| ABOVE_VAH_UNACCEPTED | 573 | 0.27 / -0.21 / 1.19 | -0.07 / -1.42 / 0.98 | 0.00 / -1.34 / 1.00 | 1.87 / -1.15 / 1.37 | -0.50 / -5.29 / 0.94 |

VP60 在 T+5/T+20 的均值方向似乎较好，但 Accepted 仅 17 条，T+10 的中位数还更低。
该现象仅记录为后续样本扩展时的检查项，不能作为任何 VP 权重、加分或筛选条件。

## VP 覆盖与状态分布

| 上下文 | VP20 | VP60 |
| --- | ---: | ---: |
| WITHIN_VALUE | 1,410 | 1,093 |
| ABOVE_VAH | 1,150 | 1,574 |
| BELOW_VAL | 264 | 157 |
| ABOVE_VAH_ACCEPTED | 116 | 44 |
| ABOVE_VAH_UNACCEPTED | 1,034 | 1,530 |
| VP_NORMAL | 2,824 | 2,824 |
| VP_ELEVATED / EXTENDED / EXTREME | 0 / 0 / 0 | 0 / 0 / 0 |

因此本次可实际检验的只有位置与 Acceptance 的有限对照；不能声称已经验证了
POC/Value-Area migration、上行延展风险，或 `NARROWING + HIGH_AND_RISING + VP`
联合状态的稳定价值。

## 本轮回答

1. **VP + Sector / RS 是否有效？** 证据不足；当前小样本没有证明该联合分层优于原
   Wyckoff 候选池。
2. **VP20 Acceptance 是否提供正向区分？** 本五日不支持，且样本极少、方向反直觉，
   必须复核更多独立日期。
3. **VP60 Acceptance 是否提供正向区分？** INSUFFICIENT；17 条 Accepted 不能支持
   任何规则。
4. **Extension 能否做风险惩罚？** INSUFFICIENT；没有产生非 `VP_NORMAL` 状态。
5. **是否接入正式候选排序？** 否。继续保留 VP 为只读上下文；不得在此基础上创建
   VPScore 或修改 `final_rank_score`。

## 下一步（不在本轮执行）

在保持 VP、Sector/RS 和 Wyckoff 全部冻结的前提下，扩展到更多具有分钟 FULL 覆盖的
独立信号日；同时报告 unique symbols、unique dates、行业集中度和每只股票的重复次数。
只有在 Acceptance、Migration 或 Extension 出现跨日期、非少数股票驱动的稳定差异后，
才讨论 VP 是否应作为风险上下文或排序研究因子。
