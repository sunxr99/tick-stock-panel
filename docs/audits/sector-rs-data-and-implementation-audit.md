# Sector Strength / RS 数据与实现审计

## 审计结论

**结论：先修复并重跑，不进入下一策略模块。**

2024 的“RS Top 10% 明显弱于 Bottom 50%”不是 percentile/rank 方向反转造成的：源代码、合成算例、十个真实日期的 Top/Bottom 样本均确认，高 RS 确实代表过去跑赢市场和所属行业更多。2023 的冻结复跑也呈现同方向的 RS Top 表现较差，故不能把 2024 视为单一年度偶然结果。

但严肃历史结论仍被两个数据质量问题阻断：

1. 行业成员关系只有当前 `ext_hy_ths` 快照，没有 `membership_as_of` 或历史归属；用其回看 2023/2024 存在不可量化的归属漂移与 survivorship bias。
2. 当前成员映射曾同时保留带交易所后缀和裸代码两种 key，导致 `member_count`/`coverage_ratio` 的分母错误约翻倍。该 bug 不改变当时实际 join 后的等权收益或 RS 排名，却使当时 coverage/data-quality 解释失真；该实现问题现已修复，历史审计结论保留。

因此，当前证据支持“冻结的短中期动量/RS 在该当前成员快照口径下有明显追涨或过度延展风险”，但不足以最终证明因子本身没有 edge，也不允许进入 Dow、Volume Profile、Wyckoff、CZSC 或任何策略组合阶段。

### 数据补充（2026-09-12）

已新增独立的申万行业历史成员区间：
`data/sector_membership_history/sw_memberships.parquet`，覆盖 `2023-09-12` 至
`2026-09-12`，保留 Tushare `index_member_all` 的 `in_date/out_date`，并由
`resolve_sw_history` 按 `as_of` 读取。Sector / RS 的行业路径现在优先使用申万一级/二级/三级
成员区间，概念路径仍使用同花顺当前快照。该补充不改变本报告之前基于同花顺当前快照的
历史统计；如需更新结论，必须使用申万口径重新运行完整验证，并在结果中明确标注 `SW2021`。

## A. 已确认实现正确

### 收益、相对收益与排名

| 输出 | 源码位置 | 数学定义 | 方向 |
| --- | --- | --- | --- |
| 日收益 | `backend/app/indicators/pipeline.py:505` | `r_t = close_t / close_(t-1) - 1` | 正值更强 |
| N 日收益 | `rps_rotation._window_return`（约 205 行） | `R_N(t)=Π(1+r_d)-1`, `d=t-N+1..t` | 正值更强 |
| 全市场基准 | `rps_rotation._market_daily_returns`（约 239 行） | 每日有效股票 `mean(r_t)` 后按同一 N 日窗口复合 | 正值更强 |
| 板块日收益 | `rps_rotation.build_sector_strength`（约 346 行） | 当日有效成员 `mean(r_t)` | 等权；正值更强 |
| 个股 vs 市场 | `relative_strength.build_relative_strength:221-230` | `R_stock,N - R_market,N` | 值越大越强 |
| 个股 vs 板块 | `relative_strength.build_relative_strength:260-283` | `R_stock,N - R_sector,N` | 值越大越强 |
| percentile / rank | `rps_rotation._rank_values:217-236` | 按数值降序；第一名 percentile `100`，末名 `0` | 值越大，rank 越小、percentile 越高 |
| MarketRS | `relative_strength._weighted_score:146-149` | `.15P(vm3)+.20P(vm5)+.25P(vm10)+.30P(vm20)+.10P(vm60)` | 值越大越强 |
| SectorRS | 同上及 `relative_strength:254-283` | 同一权重，对板块内 `vs_sector` percentile 加权 | 值越大越强 |
| RSScore | `relative_strength:302-305` | `.40*MarketRS + .60*SectorRS` | 值越大越强 |
| Sector Score | `rps_rotation.build_sector_strength:438-459` | `.55*RelativeMomentum + .30*Breadth + .15*Persistence` | 值越大越强 |

手工可计算例子：若 A/B/C 的同窗口 `vs_market` 为 `12%/4%/-2%`，`_rank_values` 生成 A/B/C 的 rank 为 `1/2/3`、percentile 为 `100/50/0`。若某股在 3/5/10/20/60 日的市场 percentile 为 `100/100/50/50/0`，则 `MarketRS=62.5`；若 `SectorRS=80`，则 `RSScore=.4*62.5+.6*80=73`。不存在把强值反向为低分的第二次排序。

### 十个固定真实样本日 sanity check

下表是每个样本日按实际 `rs_score` 取 Top 20 / Bottom 20 后的均值。`r20`、`vm20`、`vs20` 分别为过去 20 日个股收益、vs-market、vs-sector；样本日覆盖 2024 各季度与 `weak/lean_weak/lean_strong/strong` 状态。

| Date | Regime | Top r20 | Bottom r20 | Top vm20 | Bottom vm20 | Top vs20 | Bottom vs20 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2024-01-31 | weak | 24.47% | -35.37% | 43.26% | -16.59% | 37.83% | -15.93% |
| 2024-02-28 | weak | 56.86% | -21.70% | 60.89% | -17.67% | 59.64% | -17.07% |
| 2024-03-29 | strong | 73.19% | -17.09% | 70.28% | -19.99% | 69.83% | -20.07% |
| 2024-04-30 | lean_weak | 49.22% | -19.23% | 50.45% | -18.00% | 49.62% | -18.65% |
| 2024-05-31 | lean_strong | 47.55% | -21.51% | 48.52% | -20.54% | 47.80% | -17.80% |
| 2024-06-28 | lean_strong | 38.90% | -27.43% | 46.31% | -20.02% | 43.67% | -18.90% |
| 2024-07-31 | strong | 77.40% | -20.53% | 76.23% | -21.71% | 75.03% | -20.89% |
| 2024-08-30 | strong | 51.68% | -20.90% | 54.20% | -18.39% | 53.63% | -18.71% |
| 2024-09-30 | strong | 104.57% | 2.75% | 78.56% | -23.26% | 74.51% | -21.99% |
| 2024-11-29 | strong | 124.42% | -11.41% | 115.18% | -20.65% | 112.68% | -19.27% |

这十日的自动检查结果：Top 的过去收益、vs-market 与 vs-sector 均总体显著高于 Bottom；未发现任何“Top RS 记录在全部 10 个 `vs_market/vs_sector` 窗口都弱于某 Bottom RS 记录”的严格支配异常（0 条）。完整的每日期 20 Top + 20 Bottom 字段明细、以及每日期 Sector Top/Bottom 明细由下述可复现脚本输出。

### 交易日与未来标签对齐

- signal `as_of=t` 使用的 N 日窗口是 `t-N+1..t`，包含信号日收盘，不含任何 `t+1` 数据；`_window_return` 缺任一交易日即返回 `None`，不会前填。
- benchmark、stock 与 sector 都使用同一 `dates` 序列和同一窗口边界。
- 前向收益是 `t+1..t+N` 的日收益复合，见验证脚本 `backend/scripts/run_sector_rs_independent_validation.py:_forward_metrics`；没有把 signal 日重复计入标签。
- 停牌/缺失的任一窗口使对应收益不可用；前向测试从该 horizon 分母移除，不把停牌日当作 0 收益。
- percentile 每日从当日横截面重算；没有跨日混合 percentile。

随机价序列与除权附近抽查亦支持此对齐：例如 `300561.SZ`、`300822.SZ`、`603366.SH`、`920855.BJ` 在 2024-08-01 至 2024-11-29 的前复权与原始价日收益一致，前复权因子在该段不变；`920855.BJ` 的 30% 单日涨幅保留为真实日涨幅。

## B. 已发现代码 Bug

| 文件 / 函数 | Bug | 影响 |
| --- | --- | --- |
| `backend/app/services/market_overview_builder.py:_symbol_keys` 与 `backend/app/services/rps_rotation.py:_load_concept_map_df/build_sector_strength` | `_symbol_keys` 同时产出 `600000.SH` 和 `600000`；映射表去重后仍有两种不同字符串。`build_sector_strength` 先以全部 key 计算 `member_count`，再只以带后缀股票面板 join。 | 2024 一级行业映射为 11,134 key，实际可 join 股票为 5,333；5,801 个裸代码 key 永远不会 join。`coverage_ratio` 约为实际值的一半，`data_quality.status` 被错误标为 partial。 |

该 bug **不改变**本次 Sector 日等权收益、relative return、Breadth、Sector Score 或 RS：这些值都由 join 后的唯一 `(symbol,date)` 计算；本次验证也没有按 coverage 阈值剔除样本。它不能解释 RS Top/Bottom 的反转。后续已在 `rps_rotation.py` 统一成员代码并增加去重回归测试；从修复后的快照起，coverage 可重新作为数据质量字段解释。

## C. 已发现数据问题

### 成员关系与 survivorship（阻断性）

- 来源是当前 `data/ext_data/ext_hy_ths/part.parquet` 的 `ext_hy_ths` snapshot；`relative_strength.py:327` 明确输出 `membership_as_of=None`、`membership_source=current_ext_snapshot`。
- 仓库没有历史成员表、行业变更有效日期或退市历史主数据，不能取得任一 2023/2024 的真实 `membership_as_of`。
- 当前验证中所有 5,333 个实际股票 key 都能映射到当前一级行业；这不能证明当时归属正确，反而说明回测完全依赖当前快照。
- 2024 数据内有 100 只股票首次出现于该年，其中 62 只在 6 月或之后；它们会在上市前存在于当前成员分母中，但没有价格行，60 日不足者不会生成完整 RS。无法量化已退市股票是否在当前快照中遗漏，因为没有历史上市/退市 universe。

严重程度：**高**。它不必然造成 RS 排名方向反转，但足以否定“严格、可交易、无 survivorship 的历史验证”结论。

### 复权与 `change_pct`

- enriched `close` 是前复权价，`raw_close` 是原始价；生产 `change_pct` 由前复权相邻收盘计算，口径在 `pipeline.py:505`。
- 2024-01-01 至 2024-12-02 共发现 4,595 次复权因子变动，覆盖 3,943 只股票；其中绝对变动大于 5%/10%/20% 的事件为 547/395/387 次。
- 这不自动等同于数据错误。除权配股日原始价可出现约 -50% 跳变，而前复权收益应保持连续；例如 `300856.SZ` 于 2024-05-17 原始收益约 -49.73%，前复权收益约 +2.46%。因此本次 Sector 与 RS 的日收益口径彼此一致。
- 但复权因子来自数据源且没有逐事件 corporate-action 审计；对极端因子变动仍缺独立供应商交叉验证。严重程度为**中**，需要在重跑前抽样核验，而不是把 raw/adjusted 差异直接视为错误。

### 股票池与可交易性

- 2024 日频面板：5,333 股票、无 `(symbol,date)` 重复行；零成交额/零成交量行已被流水线过滤为 0，因此长期停牌不会以“0 收益”留在面板，而会导致窗口缺失。
- 当前 instruments 表共 5,562 条，其中名称包含 `ST` 的 204 条（3.67%）；当前验证没有排除 ST/*ST。
- 北交所股票存在于样本（如 `920855.BJ`），不同涨跌幅制度未被单独分层；涨跌停、一字板、滑点、成交额下限和容量没有进入本次研究。
- 因没有历史 listings、delistings、风险警示状态和盘口可成交数据，无法精确统计“当日未上市/已退市遗漏/一字板不可成交”的最终占比。

## D. 因子的统计表现

### 2024 单因子诊断

Sector 原始相对动量从 3 日到 20 日均呈现高分层未来收益更差的迹象，且随窗口变长更显著。T+20 的 Top 10% / Bottom 50% mean excess：

| Factor | Top 10% | Bottom 50% | 解释 |
| --- | ---: | ---: | --- |
| `relative_return_3d` | -0.67% | +0.05% | 短期反转 |
| `relative_return_5d` | -0.97% | +0.15% | 反转增强 |
| `relative_return_10d` | -1.19% | +0.24% | 反转增强 |
| `relative_return_20d` | -1.48% | +0.22% | 最明显反转 |
| `up_ratio` | -0.70% | -0.14% | 单日宽度高潮后较弱 |
| `strong_stock_ratio` | -0.87% | -0.01% | 强势股渗透率同样追高 |
| `persistence_days` | -1.03% | +0.03% | 持续高位不是后续优势 |

`rank_std_5d` 数值高代表不稳定，按数值 Top 10% 的 T+20 mean excess 为 `-0.41%`，Bottom 50% 为 `-0.22%`；它没有提供稳定的正向说明。

RS 的单因子输出也不是“只有综合分失效”：`vs_market_3d` Top 10% 在 T+20 为 `-1.48%`，Bottom 50% 为 `+0.22%`；`vs_market_5d` 为 `-1.75%` 对 `+0.35%`。在强 Sector 内，最终 RS Top 10% T+20 为 `-2.24%`，Bottom 50% 为 `+0.22%`。因此 Market RS、Sector RS 和综合 RS 均显示出高位延展后的回撤/反转特征，而不是最终加权时才出现的问题。

### Sector 的构成现象

Sector Top 确实是过去表现强，而不是排序错。例如 2024-09-30 的 Top `非银金融` 过去 3/5/10/20 日相对市场为 `2.51%/9.43%/12.91%/15.76%`，score `84.817`、rank 1；Bottom `银行` 为 `-11.40%/-10.15%/-7.19%/-12.76%`，score `12.950`。

也观察到规则的预期但可能不利于未来收益的行为：Persistence 对连续较高 Relative Momentum 给予持续加分；Breadth 在 2024-09-30 多数行业 `up_ratio` 接近 100%，使当日高潮的差异主要由 `strong_stock_ratio` 和动量 percentile 决定。它描述的是“已经很强”，不等价于“下一阶段正在增强”。这只是诊断描述，不是修改规则的授权。

### 第二独立年份：2023 冻结复跑

2023-01-03 至 2023-12-01（222 个交易日）使用完全相同的实现、行业一级范围、Top 30% 对照、T+1..T+20 标签和无参数调整。核心 T+20 结果：

| Group / tier | Mean excess | Median excess | PF |
| --- | ---: | ---: | ---: |
| Sector Top 10% | -0.25% | -1.98% | 0.941 |
| Sector Bottom 50% | +0.11% | -1.03% | 1.033 |
| 强 Sector 内 RS Top 10% | -1.21% | -3.83% | 0.802 |
| 强 Sector 内 RS Bottom 50% | -0.06% | -1.46% | 0.984 |
| All Market | -0.00% | -1.29% | 1.000 |
| Sector | -0.18% | -1.68% | 0.955 |
| Sector + RS | -0.53% | -2.27% | 0.890 |

2023 与 2024 均显示 Sector + RS 比 Sector 更差，且强 Sector 内 RS Top 10% 明显落后低 RS 分层；方向具有跨年重复性。它可以提高“追涨/过度延展或当前因子定义不适合作为未来收益筛选”的置信度，但不能消除当前成员回溯偏差。

## 对问题的直接回答

1. **2024 负结果是否可信？** 作为当前快照、前复权 close、全样本等权口径下的诊断，可信；作为严格可交易历史证据，不可信到足以做策略决策。
2. **RS Top10% 差于 Bottom50% 是否可能是实现错误？** 排名方向错误的可能性很低：公式、十日样本和严格支配检查都否定了反转/二次反转。coverage bug 不影响该排序。
3. **是否存在追涨/过度延展？** 有强证据。高 3/5/10/20 日相对动量、strong-stock breadth、persistence 和 RS 高分层均在后续中长期表现更差；两个年份同方向。
4. **Sector Score 是否主要描述“已经很强”而非“正在增强”？** 是。它忠实表达既有的 relative momentum、当日 breadth 与持续性，但这些状态在本样本中没有转化为未来平均超额。
5. **数据问题是否足以推翻当前历史验证？** 足以阻断最终策略结论：历史成员快照缺失是高严重度；coverage 分母 bug 需修复；复权事件尚需供应商交叉检查。
6. **是否需要重新运行？** 需要。在修复 coverage 计算、取得/构造历史 `membership_as_of`、明确可交易股票池后，使用完全冻结的因子定义重跑 2023、2024 和额外独立区间。
7. **当前是否允许进入 Dow / VP 阶段？** 不允许。先修复并重跑，不进入下一策略模块。

## 可复现命令

完整的十个日期 Top/Bottom 明细、Sector Top/Bottom 明细及全部单因子 T+1..T+20 表由只读脚本生成：

```powershell
cd backend
uv run --frozen python scripts/run_sector_rs_data_implementation_audit.py --data-dir ..\data --year 2024
uv run --frozen python scripts/run_sector_rs_independent_validation.py --data-dir ..\data --start 2023-01-03 --end 2023-12-01
```

脚本：[run_sector_rs_data_implementation_audit.py](/D:/stock/myStockPanel/tick-stock-panel/backend/scripts/run_sector_rs_data_implementation_audit.py)。它只读取 Parquet 与当前成员快照，不写入数据、公式、权重、阈值或策略状态。
