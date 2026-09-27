# TDX Sector / RS / Wyckoff 路径

## 目标与隔离

通达信路径使用 Tushare `tdx_index`、`tdx_member` 和 `tdx_daily` 已落盘的
`data/tdx_board_history_recent`，用于近期的板块共振观察。它与原有的申万/同花顺
Sector / RS 路径并存，不改写冻结的 V1/V1.1 公式，也不重写历史申万成员数据。

行业成员只从 `trade_date == as_of` 的 `tdx_member` 快照读取；没有该日快照时返回空映射，
不会使用较新的成员表回填。当前本地快照窗口仅有近期交易日，不能用来声称早期历史回测结果。

## Sector / RS

- TDX 行业共振默认且仅使用 `8810xx.TDX`--`8814xx.TDX` 的细分行业；稳定 ID 仍为
  `tdx_industry:all:<881xxxx.TDX>`。板块代码是计算键，显示名保留为 `名称 [板块代码]`，避免
  重名行业混淆。
- Sector Strength 与 Relative Strength 继续使用既有的个股 enriched 日收益、全市场等权基准、
  窗口、权重、缺日 fail-closed 和动态状态公式；替换的仅是成员关系。
- TDX `idx_type=行业板块` 没有可用的显式层级字段；产品口径明确选择 `8810xx`--`8814xx`
  的细分行业作为唯一行业集合。`8802xx` 地区板块、`8803xx/8804xx` 的平行行业集合均不进入
  行业共振。
- `GET /api/rps/sector-strength` 默认 `source=tdx` 且默认 `kind=industry`。需要旧口径时显式传
  `source=sw_ths`；TDX 返回的 `sector_id` 可直接传给 `/api/rps/relative-strength`。

## Wyckoff

`FunnelConfig.sector_source` 默认是 `tdx`。此时：

1. L3 的行业兜底输入为当日 TDX `8810xx`--`8814xx` 细分行业成员关系；缺少该日细分行业
   快照时 fail-closed，不回退到 `8803xx/8804xx` 或更新日期的成员表。
2. 如果策略显式开启 `use_concept_map`，概念优先输入和热点概念也取自当日 TDX 概念快照与
   TDX 板块行情。
3. Wyckoff 的 Sector / RS 研究上下文走 `rank_tdx_wyckoff_candidates()`。通达信无 SW2/SW3
   层级，故不伪造层级分数，而使用单一扁平行业的原有 `0.40 * Sector + 0.60 * RS` 组合；
   输出 `opportunity_score_basis=tdx_flat_best_context`、`sector_hierarchy_state=TDX_FLAT`。
4. 细分行业集合按设计用于单归属共振；若上游快照意外返回重复归属，L3 仍会保留数据原貌，
   单行研究摘要按 Sector Strength、再按 RS、最后按稳定 ID 选择一个上下文，并标注
   `tdx_context_selection=highest_sector_strength_then_rs`。

将 `sector_source` 设为 `sw_ths` 可恢复原有“同花顺概念优先 + 申万 SW1 行业兜底”路径，
且不会修改 L1/L2/L3 阈值、个股量价计算或正式候选集合之外的逻辑。
