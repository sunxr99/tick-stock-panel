# Volume Profile V1：VP-first 随机五日再分析

> 本报告只复用既有五个 signal-date Parquet 的 VP 结果；没有重新计算 Volume Profile、没有读取分钟分区、没有重放 Wyckoff，也没有改变任何正式评分规则。唯一改变是统计母样本从 Sector/RS Top30% 改回 ALL_WYCKOFF，再叠加 Sector/RS 分层。

## 固定样本与口径

- 信号日：2026-02-02、2026-02-03、2026-02-05、2026-02-10、2026-02-24。
- 母样本：2,824 条 ALL_WYCKOFF 股票×signal-date 观测，1,518 个 unique symbol，5 个 signal date。
- 收益：信号日收盘后产生、下一交易日开盘进入、T+N 收盘退出；超额收益 = 股票收益 - `000001.SH` 同窗口收益。
- VP 主结果仅使用 `quality=FULL`、`data_granularity=MINUTE_1M`、`fallback_used=false`；VP20 与 VP60 永不合并。
- `mean/median excess`、MAE、MFE 均为百分比；PF 为正超额收益总和 / 负超额收益绝对值总和。`INSUFFICIENT` 表示 n<20 或 unique signal dates<=2。

## 已落盘字段审计

- 已保存：`vp20_position, vp20_acceptance, vp20_poc_state, vp20_value_area_state, vp20_extension, vp60_position, vp60_acceptance, vp60_poc_state, vp60_value_area_state, vp60_extension, vp20_distance_to_poc_pct, vp20_distance_to_vah_pct, vp20_distance_to_poc_atr, vp20_distance_to_vah_atr, sector_score, sector_phase, rs_score, rs_state`。
- 未保存：`sector_percentile, narrowing_flag, rs_percentile, rs_change_1d, rs_change_3d, sector_score_change_1d, sector_score_change_3d`。
- `sector_percentile` 与 `rs_percentile` 未落盘；本报告仅以同一 signal_date 内的冻结 score 横截面排名在内存中生成五档 level。
- `narrowing_flag`、`rs_change_1d`、`rs_change_3d` 与 Sector score change 未落盘，且不能只由当前快照安全推导；因此不伪造这些分组。`rs_state` 和 `sector_phase` 仍可直接研究。

## 读前结论

- **VP20 Position：PARTIALLY_SUPPORTED（仅描述性）。** `ABOVE_VAH` 的 T+3/T+5/T+10/T+20 mean excess 为 0.34%/0.44%/2.19%/1.58%，高于 `BELOW_VAL` 的 0.04%/-0.22%/0.17%/-2.06%；但两者中位数多数为负，不能升级为入场规则。
- **Acceptance：PRESELECTION_EFFECT_NOT_SUPPORTED（本五日）。** 在 ALL_WYCKOFF 中，VP20 Accepted 的 T+1/3/5/10/20 mean excess 全部低于 Unaccepted；原 Sector/RS Top30% 中方向也相同。VP60 的 ALL_WYCKOFF 方向同样一致，而 Top30% 的 Accepted 只有 17 条，仍为 INSUFFICIENT。故前 30% 预筛选会改变幅度和样本组成，但本五日没有出现“全体正向、Top30% 反向”的翻转。
- **RS/Sector 成熟度：PARTIALLY_SUPPORTED。** VP20 Accepted 的 RS HIGH 组（44 条）在 T+1/3/5/10/20 均低于 MID_HIGH（48 条）；Sector HIGH 的 Accepted 组（32 条）也弱于部分中间层。但它们来自同一五日窗口，不能排除市场环境或重复股票解释。
- **严格 Acceptance 是否确认过晚：PARTIALLY_SUPPORTED。** 只含 `price > VAH + POC_RISING` 的 VP20 B 组（256 条）没有复现严格 D 组（116 条）的明显弱势；但 A--D 是重叠集合，不能据此替换或放宽正式 Acceptance。
- **Extension：UNAVAILABLE FOR INFERENCE。** 已落盘标签全为 `VP_NORMAL`，但这是实现顺序问题：`VolumeProfileEngine._contextualize` 在设置 `position_context` 前调用 `_extension_state`，后者因此总按非 `ABOVE_VAH` 返回 NORMAL。连续 distance 字段仍由 Profile 原始价格计算而来，可以只读展示；历史 extension 标签不能用于本报告的有效性结论。本轮未修改该实现，也未重跑 VP。

## VP20：先在 ALL_WYCKOFF 做 Position 与 Acceptance 研究

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VP20 Position: ABOVE_VAH | 1150 | 712 | 5 | T+1 | 0.12% | -0.46% | 43.39% | 1.08 | -2.70% | 3.75% |  |
| VP20 Position: ABOVE_VAH | 1149 | 711 | 5 | T+3 | 0.34% | -0.53% | 46.04% | 1.13 | -4.69% | 6.88% |  |
| VP20 Position: ABOVE_VAH | 1147 | 710 | 5 | T+5 | 0.44% | -1.04% | 44.46% | 1.12 | -6.04% | 9.66% |  |
| VP20 Position: ABOVE_VAH | 1145 | 710 | 5 | T+10 | 2.19% | -0.89% | 46.29% | 1.49 | -8.28% | 14.23% |  |
| VP20 Position: ABOVE_VAH | 1146 | 712 | 5 | T+20 | 1.58% | -2.77% | 41.88% | 1.24 | -12.58% | 19.48% |  |
| VP20 Position: BELOW_VAL | 263 | 200 | 5 | T+1 | -0.03% | -0.22% | 39.92% | 0.94 | -0.93% | 1.67% |  |
| VP20 Position: BELOW_VAL | 263 | 200 | 5 | T+3 | 0.04% | -0.09% | 45.25% | 1.04 | -1.64% | 3.08% |  |
| VP20 Position: BELOW_VAL | 263 | 200 | 5 | T+5 | -0.22% | -0.52% | 41.44% | 0.86 | -2.27% | 4.03% |  |
| VP20 Position: BELOW_VAL | 262 | 199 | 5 | T+10 | 0.17% | -0.49% | 44.27% | 1.08 | -3.31% | 6.40% |  |
| VP20 Position: BELOW_VAL | 263 | 200 | 5 | T+20 | -2.06% | -3.72% | 31.94% | 0.57 | -7.64% | 8.54% |  |
| VP20 Position: WITHIN_VALUE | 1406 | 989 | 5 | T+1 | 0.25% | -0.17% | 47.87% | 1.24 | -1.94% | 3.05% |  |
| VP20 Position: WITHIN_VALUE | 1401 | 986 | 5 | T+3 | 0.15% | -0.49% | 44.90% | 1.07 | -3.49% | 5.47% |  |
| VP20 Position: WITHIN_VALUE | 1400 | 985 | 5 | T+5 | 0.21% | -1.31% | 40.50% | 1.07 | -4.74% | 7.60% |  |
| VP20 Position: WITHIN_VALUE | 1400 | 985 | 5 | T+10 | 1.49% | -0.74% | 46.57% | 1.41 | -6.67% | 11.32% |  |
| VP20 Position: WITHIN_VALUE | 1404 | 988 | 5 | T+20 | 0.78% | -2.77% | 41.38% | 1.13 | -10.74% | 16.08% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+1 | -0.41% | -1.06% | 40.52% | 0.78 | -3.31% | 3.40% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+3 | -0.90% | -2.05% | 35.34% | 0.74 | -5.70% | 6.13% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+5 | -2.40% | -3.10% | 31.03% | 0.52 | -7.51% | 7.57% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+10 | -0.78% | -3.01% | 34.48% | 0.88 | -10.42% | 12.85% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+20 | -1.90% | -6.28% | 31.03% | 0.79 | -14.89% | 18.31% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1034 | 669 | 5 | T+1 | 0.18% | -0.44% | 43.71% | 1.12 | -2.63% | 3.79% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1033 | 668 | 5 | T+3 | 0.48% | -0.36% | 47.24% | 1.19 | -4.57% | 6.96% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1031 | 667 | 5 | T+5 | 0.76% | -0.68% | 45.97% | 1.21 | -5.87% | 9.90% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1029 | 667 | 5 | T+10 | 2.53% | -0.55% | 47.62% | 1.59 | -8.04% | 14.39% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1030 | 669 | 5 | T+20 | 1.97% | -2.41% | 43.11% | 1.31 | -12.32% | 19.61% |  |

## VP60：先在 ALL_WYCKOFF 做 Position 与 Acceptance 研究

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VP60 Position: ABOVE_VAH | 1565 | 832 | 5 | T+1 | 0.36% | -0.21% | 47.80% | 1.26 | -2.58% | 3.89% |  |
| VP60 Position: ABOVE_VAH | 1561 | 831 | 5 | T+3 | 0.37% | -0.56% | 45.80% | 1.14 | -4.59% | 7.00% |  |
| VP60 Position: ABOVE_VAH | 1558 | 830 | 5 | T+5 | 0.68% | -0.86% | 45.38% | 1.19 | -5.86% | 9.75% |  |
| VP60 Position: ABOVE_VAH | 1556 | 829 | 5 | T+10 | 2.34% | -0.58% | 47.75% | 1.53 | -7.99% | 14.32% |  |
| VP60 Position: ABOVE_VAH | 1559 | 832 | 5 | T+20 | 1.27% | -2.76% | 42.27% | 1.19 | -12.34% | 19.58% |  |
| VP60 Position: BELOW_VAL | 157 | 116 | 5 | T+1 | -0.16% | -0.24% | 40.13% | 0.70 | -0.90% | 1.43% |  |
| VP60 Position: BELOW_VAL | 157 | 116 | 5 | T+3 | -0.07% | -0.17% | 45.22% | 0.93 | -1.50% | 2.77% |  |
| VP60 Position: BELOW_VAL | 157 | 116 | 5 | T+5 | -0.51% | -0.67% | 35.67% | 0.67 | -2.12% | 3.64% |  |
| VP60 Position: BELOW_VAL | 157 | 116 | 5 | T+10 | -0.19% | -0.66% | 42.04% | 0.90 | -3.27% | 5.54% |  |
| VP60 Position: BELOW_VAL | 157 | 116 | 5 | T+20 | -1.85% | -4.45% | 31.85% | 0.58 | -7.71% | 7.62% |  |
| VP60 Position: WITHIN_VALUE | 1077 | 750 | 5 | T+1 | -0.06% | -0.33% | 42.53% | 0.94 | -1.71% | 2.48% |  |
| VP60 Position: WITHIN_VALUE | 1075 | 748 | 5 | T+3 | 0.00% | -0.33% | 44.74% | 1.00 | -3.02% | 4.55% |  |
| VP60 Position: WITHIN_VALUE | 1075 | 748 | 5 | T+5 | -0.24% | -1.30% | 38.51% | 0.91 | -4.28% | 6.39% |  |
| VP60 Position: WITHIN_VALUE | 1074 | 747 | 5 | T+10 | 0.90% | -0.91% | 44.51% | 1.27 | -6.17% | 9.70% |  |
| VP60 Position: WITHIN_VALUE | 1077 | 750 | 5 | T+20 | 0.54% | -2.84% | 39.65% | 1.10 | -10.11% | 13.99% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 44 | 39 | 5 | T+1 | -0.81% | -0.67% | 43.18% | 0.60 | -3.19% | 3.07% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 44 | 39 | 5 | T+3 | -0.70% | -0.53% | 47.73% | 0.78 | -5.12% | 5.63% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 44 | 39 | 5 | T+5 | -0.29% | -1.87% | 38.64% | 0.93 | -6.10% | 8.18% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 44 | 39 | 5 | T+10 | -0.82% | -3.68% | 40.91% | 0.86 | -8.96% | 11.35% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 43 | 38 | 5 | T+20 | -1.59% | -6.03% | 41.86% | 0.80 | -12.98% | 15.60% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1521 | 817 | 5 | T+1 | 0.40% | -0.21% | 47.93% | 1.29 | -2.56% | 3.91% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1517 | 816 | 5 | T+3 | 0.40% | -0.56% | 45.75% | 1.15 | -4.57% | 7.04% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1514 | 815 | 5 | T+5 | 0.71% | -0.85% | 45.57% | 1.20 | -5.85% | 9.80% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1512 | 814 | 5 | T+10 | 2.43% | -0.49% | 47.95% | 1.56 | -7.96% | 14.41% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1516 | 817 | 5 | T+20 | 1.36% | -2.76% | 42.28% | 1.20 | -12.32% | 19.69% |  |

## ALL_WYCKOFF 与 Sector/RS Top30% 的直接对照

Top30% 只用于判断预筛选是否改变 VP 结论，不是新候选阈值。

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+1 | -0.41% | -1.06% | 40.52% | 0.78 | -3.31% | 3.40% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+3 | -0.90% | -2.05% | 35.34% | 0.74 | -5.70% | 6.13% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+5 | -2.40% | -3.10% | 31.03% | 0.52 | -7.51% | 7.57% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+10 | -0.78% | -3.01% | 34.48% | 0.88 | -10.42% | 12.85% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 116 | 109 | 5 | T+20 | -1.90% | -6.28% | 31.03% | 0.79 | -14.89% | 18.31% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1034 | 669 | 5 | T+1 | 0.18% | -0.44% | 43.71% | 1.12 | -2.63% | 3.79% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1033 | 668 | 5 | T+3 | 0.48% | -0.36% | 47.24% | 1.19 | -4.57% | 6.96% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1031 | 667 | 5 | T+5 | 0.76% | -0.68% | 45.97% | 1.21 | -5.87% | 9.90% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1029 | 667 | 5 | T+10 | 2.53% | -0.55% | 47.62% | 1.59 | -8.04% | 14.39% |  |
| VP20 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1030 | 669 | 5 | T+20 | 1.97% | -2.41% | 43.11% | 1.31 | -12.32% | 19.61% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 43 | 43 | 5 | T+1 | -0.62% | -1.05% | 39.53% | 0.70 | -3.36% | 3.12% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 43 | 43 | 5 | T+3 | -1.85% | -2.89% | 30.23% | 0.55 | -5.88% | 5.60% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 43 | 43 | 5 | T+5 | -2.99% | -3.66% | 25.58% | 0.44 | -8.08% | 6.79% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 43 | 43 | 5 | T+10 | 0.22% | -1.08% | 41.86% | 1.04 | -10.82% | 12.60% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 43 | 43 | 5 | T+20 | -4.06% | -8.01% | 30.23% | 0.60 | -16.02% | 15.86% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 409 | 338 | 5 | T+1 | 0.05% | -0.50% | 42.54% | 1.03 | -2.53% | 3.72% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 409 | 338 | 5 | T+3 | 0.14% | -0.77% | 46.70% | 1.05 | -4.66% | 6.70% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 409 | 338 | 5 | T+5 | 0.76% | -0.53% | 46.94% | 1.21 | -5.92% | 9.87% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 409 | 338 | 5 | T+10 | 2.26% | -1.06% | 45.97% | 1.47 | -8.18% | 14.53% |  |
| VP20 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 405 | 335 | 5 | T+20 | 1.32% | -3.36% | 41.73% | 1.19 | -12.65% | 19.81% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 44 | 39 | 5 | T+1 | -0.81% | -0.67% | 43.18% | 0.60 | -3.19% | 3.07% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 44 | 39 | 5 | T+3 | -0.70% | -0.53% | 47.73% | 0.78 | -5.12% | 5.63% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 44 | 39 | 5 | T+5 | -0.29% | -1.87% | 38.64% | 0.93 | -6.10% | 8.18% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 44 | 39 | 5 | T+10 | -0.82% | -3.68% | 40.91% | 0.86 | -8.96% | 11.35% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_ACCEPTED | 43 | 38 | 5 | T+20 | -1.59% | -6.03% | 41.86% | 0.80 | -12.98% | 15.60% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1521 | 817 | 5 | T+1 | 0.40% | -0.21% | 47.93% | 1.29 | -2.56% | 3.91% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1517 | 816 | 5 | T+3 | 0.40% | -0.56% | 45.75% | 1.15 | -4.57% | 7.04% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1514 | 815 | 5 | T+5 | 0.71% | -0.85% | 45.57% | 1.20 | -5.85% | 9.80% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1512 | 814 | 5 | T+10 | 2.43% | -0.49% | 47.95% | 1.56 | -7.96% | 14.41% |  |
| VP60 ALL_WYCKOFF: ABOVE_VAH_UNACCEPTED | 1516 | 817 | 5 | T+20 | 1.36% | -2.76% | 42.28% | 1.20 | -12.32% | 19.69% |  |
| VP60 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 17 | 15 | 5 | T+1 | 0.21% | -0.11% | 47.06% | 1.17 | -2.02% | 3.49% | INSUFFICIENT |
| VP60 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 17 | 15 | 5 | T+3 | -0.53% | 0.80% | 64.71% | 0.77 | -3.98% | 4.85% | INSUFFICIENT |
| VP60 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 17 | 15 | 5 | T+5 | 1.19% | 0.19% | 52.94% | 1.35 | -4.75% | 8.19% | INSUFFICIENT |
| VP60 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 17 | 15 | 5 | T+10 | 0.96% | -3.13% | 47.06% | 1.24 | -6.82% | 11.07% | INSUFFICIENT |
| VP60 Sector/RS Top30%: ABOVE_VAH_ACCEPTED | 16 | 14 | 5 | T+20 | 2.32% | -1.15% | 43.75% | 1.48 | -9.08% | 14.75% | INSUFFICIENT |
| VP60 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 570 | 449 | 5 | T+1 | 0.27% | -0.19% | 48.07% | 1.19 | -2.54% | 3.86% |  |
| VP60 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 570 | 449 | 5 | T+3 | -0.06% | -1.46% | 42.81% | 0.98 | -4.81% | 6.84% |  |
| VP60 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 570 | 449 | 5 | T+5 | -0.01% | -1.35% | 44.21% | 1.00 | -6.25% | 9.48% |  |
| VP60 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 570 | 449 | 5 | T+10 | 1.84% | -1.17% | 45.26% | 1.36 | -8.57% | 14.28% |  |
| VP60 Sector/RS Top30%: ABOVE_VAH_UNACCEPTED | 567 | 447 | 5 | T+20 | -0.58% | -5.36% | 37.92% | 0.93 | -13.48% | 18.91% |  |

## VP20 Acceptance × RS strength level

RS level 根据同一 signal_date 内 `rs_score` 升序百分位生成：HIGH=80~100%（强），LOW=0~20%。

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ABOVE_VAH_ACCEPTED × LOW | 0 | 0 | 0 | T+1 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 0 | 0 | 0 | T+3 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 0 | 0 | 0 | T+5 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 0 | 0 | 0 | T+10 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 0 | 0 | 0 | T+20 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 4 | 4 | 1 | T+1 | 0.70% | 0.73% | 50.00% | 1.53 | -3.10% | 3.75% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 4 | 4 | 1 | T+3 | -1.27% | -0.42% | 50.00% | 0.63 | -5.19% | 6.53% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 4 | 4 | 1 | T+5 | -2.33% | -1.39% | 25.00% | 0.18 | -5.53% | 6.53% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 4 | 4 | 1 | T+10 | 5.58% | 1.69% | 50.00% | 3.34 | -6.72% | 14.95% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 4 | 4 | 1 | T+20 | 11.25% | 7.25% | 50.00% | 4.02 | -9.00% | 28.56% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 20 | 19 | 5 | T+1 | 0.34% | -0.51% | 35.00% | 1.26 | -2.14% | 2.64% |  |
| ABOVE_VAH_ACCEPTED × MID | 20 | 19 | 5 | T+3 | -0.36% | -0.46% | 45.00% | 0.82 | -3.56% | 5.22% |  |
| ABOVE_VAH_ACCEPTED × MID | 20 | 19 | 5 | T+5 | -1.75% | -2.36% | 40.00% | 0.53 | -4.86% | 6.47% |  |
| ABOVE_VAH_ACCEPTED × MID | 20 | 19 | 5 | T+10 | 3.87% | -0.86% | 45.00% | 1.98 | -7.30% | 12.75% |  |
| ABOVE_VAH_ACCEPTED × MID | 20 | 19 | 5 | T+20 | 1.44% | -3.30% | 25.00% | 1.30 | -11.02% | 20.23% |  |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 48 | 47 | 5 | T+1 | -0.37% | -1.14% | 43.75% | 0.81 | -3.19% | 3.44% |  |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 48 | 47 | 5 | T+3 | -0.51% | -2.11% | 37.50% | 0.85 | -5.90% | 6.05% |  |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 48 | 47 | 5 | T+5 | -1.16% | -2.00% | 35.42% | 0.74 | -7.49% | 8.00% |  |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 48 | 47 | 5 | T+10 | -0.61% | -2.41% | 33.33% | 0.90 | -9.96% | 13.47% |  |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 48 | 47 | 5 | T+20 | -1.77% | -7.15% | 33.33% | 0.80 | -15.17% | 17.87% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 44 | 43 | 5 | T+1 | -0.90% | -1.86% | 38.64% | 0.57 | -3.98% | 3.66% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 44 | 43 | 5 | T+3 | -1.53% | -2.73% | 27.27% | 0.63 | -6.50% | 6.58% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 44 | 43 | 5 | T+5 | -4.06% | -4.07% | 22.73% | 0.36 | -8.92% | 7.69% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 44 | 43 | 5 | T+10 | -3.65% | -3.98% | 29.55% | 0.53 | -12.73% | 12.00% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 44 | 43 | 5 | T+20 | -4.76% | -9.31% | 29.55% | 0.58 | -16.92% | 16.97% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 10 | 10 | 2 | T+1 | -2.29% | -1.95% | 10.00% | 0.00 | -2.48% | 0.95% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × LOW | 10 | 10 | 2 | T+3 | -2.10% | -1.95% | 20.00% | 0.14 | -4.32% | 1.96% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × LOW | 10 | 10 | 2 | T+5 | -0.80% | -2.60% | 20.00% | 0.76 | -5.39% | 4.52% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × LOW | 10 | 10 | 2 | T+10 | -5.12% | -6.27% | 30.00% | 0.29 | -9.91% | 6.01% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × LOW | 10 | 10 | 2 | T+20 | -3.44% | -2.47% | 20.00% | 0.49 | -12.01% | 6.55% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 78 | 71 | 5 | T+1 | -0.81% | -0.49% | 25.64% | 0.32 | -1.71% | 1.61% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 78 | 71 | 5 | T+3 | -0.10% | 0.15% | 53.85% | 0.94 | -2.82% | 3.45% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 78 | 71 | 5 | T+5 | -0.87% | -1.46% | 34.62% | 0.72 | -4.09% | 5.00% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 78 | 71 | 5 | T+10 | 1.73% | -0.80% | 46.15% | 1.48 | -6.05% | 8.91% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 78 | 71 | 5 | T+20 | 2.94% | -0.50% | 47.44% | 1.68 | -9.16% | 12.74% |  |
| ABOVE_VAH_UNACCEPTED × MID | 228 | 202 | 5 | T+1 | 0.08% | -0.28% | 43.86% | 1.06 | -2.20% | 3.16% |  |
| ABOVE_VAH_UNACCEPTED × MID | 228 | 202 | 5 | T+3 | 0.22% | -0.03% | 49.56% | 1.10 | -3.92% | 5.74% |  |
| ABOVE_VAH_UNACCEPTED × MID | 228 | 202 | 5 | T+5 | 0.88% | 0.25% | 51.32% | 1.31 | -5.00% | 8.64% |  |
| ABOVE_VAH_UNACCEPTED × MID | 228 | 202 | 5 | T+10 | 2.95% | 1.10% | 54.39% | 1.88 | -6.87% | 13.17% |  |
| ABOVE_VAH_UNACCEPTED × MID | 227 | 201 | 5 | T+20 | 4.56% | -0.98% | 48.02% | 1.95 | -10.50% | 19.43% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 342 | 289 | 5 | T+1 | 0.24% | -0.29% | 47.95% | 1.17 | -2.55% | 3.88% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 342 | 289 | 5 | T+3 | 0.37% | -0.79% | 43.86% | 1.15 | -4.34% | 6.67% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 342 | 289 | 5 | T+5 | 0.32% | -1.45% | 42.98% | 1.09 | -5.68% | 9.28% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 339 | 287 | 5 | T+10 | 2.29% | -1.35% | 45.43% | 1.57 | -7.79% | 13.70% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 342 | 289 | 5 | T+20 | 1.89% | -2.12% | 44.74% | 1.31 | -12.21% | 19.40% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 376 | 255 | 5 | T+1 | 0.45% | -0.51% | 44.41% | 1.27 | -3.17% | 4.62% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 375 | 254 | 5 | T+3 | 0.92% | -0.14% | 48.27% | 1.33 | -5.55% | 8.84% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 373 | 252 | 5 | T+5 | 1.46% | -0.47% | 48.53% | 1.35 | -6.96% | 12.40% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 374 | 253 | 5 | T+10 | 2.85% | -0.78% | 46.26% | 1.55 | -9.36% | 17.14% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 373 | 253 | 5 | T+20 | 0.40% | -4.77% | 38.34% | 1.05 | -14.21% | 21.71% |  |

## VP60 Acceptance × RS strength level

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ABOVE_VAH_ACCEPTED × LOW | 2 | 2 | 1 | T+1 | -3.86% | -3.86% | 0.00% | 0.00 | -4.40% | 1.11% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 2 | 2 | 1 | T+3 | -4.61% | -4.61% | 0.00% | 0.00 | -6.68% | 3.26% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 2 | 2 | 1 | T+5 | -8.02% | -8.02% | 0.00% | 0.00 | -10.18% | 3.26% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 2 | 2 | 1 | T+10 | -16.57% | -16.57% | 0.00% | 0.00 | -18.86% | 3.26% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 2 | 2 | 1 | T+20 | -18.42% | -18.42% | 0.00% | 0.00 | -22.46% | 3.26% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 6 | 6 | 3 | T+1 | -2.67% | -2.94% | 33.33% | 0.19 | -4.34% | 1.95% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 6 | 6 | 3 | T+3 | -5.34% | -7.79% | 33.33% | 0.13 | -6.91% | 2.10% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 6 | 6 | 3 | T+5 | -6.50% | -8.82% | 33.33% | 0.01 | -7.70% | 2.29% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 6 | 6 | 3 | T+10 | -6.55% | -5.05% | 33.33% | 0.12 | -10.66% | 5.33% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 6 | 6 | 3 | T+20 | -7.78% | -11.50% | 33.33% | 0.30 | -15.73% | 10.57% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 11 | 11 | 5 | T+1 | -0.38% | 0.14% | 54.55% | 0.83 | -2.64% | 3.71% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 11 | 11 | 5 | T+3 | -2.40% | -2.92% | 45.45% | 0.49 | -5.57% | 5.27% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 11 | 11 | 5 | T+5 | -1.26% | 0.44% | 54.55% | 0.73 | -6.55% | 6.71% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 11 | 11 | 5 | T+10 | -0.55% | 2.52% | 54.55% | 0.92 | -9.04% | 9.45% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 11 | 11 | 5 | T+20 | -1.12% | -0.88% | 45.45% | 0.79 | -10.50% | 12.43% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 14 | 14 | 5 | T+1 | -0.40% | -0.35% | 35.71% | 0.63 | -2.84% | 2.84% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 14 | 14 | 5 | T+3 | 2.38% | 1.02% | 71.43% | 3.30 | -3.62% | 6.71% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 14 | 14 | 5 | T+5 | -0.25% | -1.87% | 28.57% | 0.90 | -4.76% | 8.98% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 14 | 14 | 5 | T+10 | -4.19% | -3.99% | 28.57% | 0.31 | -8.56% | 10.52% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 14 | 14 | 5 | T+20 | -6.88% | -9.12% | 28.57% | 0.31 | -14.17% | 12.97% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 11 | 9 | 5 | T+1 | -0.19% | 0.25% | 54.55% | 0.90 | -3.36% | 3.70% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 11 | 9 | 5 | T+3 | 0.32% | -1.24% | 36.36% | 1.12 | -5.30% | 6.99% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 11 | 9 | 5 | T+5 | 5.44% | -0.42% | 45.45% | 3.08 | -5.74% | 12.75% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 11 | 9 | 5 | T+10 | 9.17% | 2.87% | 54.55% | 6.15 | -6.67% | 19.05% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 10 | 8 | 4 | T+20 | 12.37% | 3.41% | 70.00% | 4.46 | -10.52% | 28.27% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × LOW | 33 | 32 | 5 | T+1 | -0.75% | -0.69% | 33.33% | 0.41 | -1.94% | 1.73% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 33 | 32 | 5 | T+3 | -0.82% | -1.18% | 33.33% | 0.55 | -3.39% | 3.08% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 33 | 32 | 5 | T+5 | 0.87% | -1.78% | 39.39% | 1.35 | -4.32% | 6.13% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 33 | 32 | 5 | T+10 | -0.01% | 1.06% | 57.58% | 1.00 | -6.52% | 9.69% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 33 | 32 | 5 | T+20 | -0.58% | -2.55% | 30.30% | 0.89 | -10.23% | 12.95% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 192 | 169 | 5 | T+1 | 0.66% | -0.05% | 50.00% | 1.78 | -1.70% | 3.20% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 192 | 169 | 5 | T+3 | 0.07% | -0.06% | 49.48% | 1.04 | -3.34% | 5.16% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 192 | 169 | 5 | T+5 | 0.31% | -1.04% | 44.27% | 1.10 | -4.50% | 7.43% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 192 | 169 | 5 | T+10 | 3.72% | 1.38% | 56.25% | 2.27 | -6.11% | 12.19% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 192 | 169 | 5 | T+20 | 3.86% | 0.82% | 51.56% | 1.80 | -9.48% | 18.62% |  |
| ABOVE_VAH_UNACCEPTED × MID | 347 | 297 | 5 | T+1 | 0.16% | -0.10% | 47.84% | 1.13 | -2.26% | 3.29% |  |
| ABOVE_VAH_UNACCEPTED × MID | 347 | 297 | 5 | T+3 | 0.66% | -0.46% | 46.11% | 1.31 | -4.00% | 6.33% |  |
| ABOVE_VAH_UNACCEPTED × MID | 347 | 297 | 5 | T+5 | 1.11% | -0.30% | 47.55% | 1.38 | -5.05% | 9.09% |  |
| ABOVE_VAH_UNACCEPTED × MID | 347 | 297 | 5 | T+10 | 3.49% | 0.86% | 52.45% | 2.07 | -6.90% | 14.01% |  |
| ABOVE_VAH_UNACCEPTED × MID | 345 | 296 | 5 | T+20 | 3.24% | -0.94% | 47.54% | 1.61 | -10.93% | 19.94% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 445 | 350 | 5 | T+1 | 0.44% | 0.04% | 50.79% | 1.32 | -2.47% | 3.99% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 445 | 350 | 5 | T+3 | 0.11% | -0.95% | 44.27% | 1.04 | -4.40% | 6.72% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 444 | 349 | 5 | T+5 | 0.11% | -0.94% | 44.82% | 1.03 | -5.73% | 9.03% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 441 | 347 | 5 | T+10 | 1.57% | -1.39% | 44.22% | 1.36 | -7.78% | 13.30% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 445 | 350 | 5 | T+20 | 0.89% | -2.94% | 40.45% | 1.13 | -12.35% | 18.75% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 504 | 305 | 5 | T+1 | 0.50% | -0.45% | 45.63% | 1.30 | -3.23% | 4.67% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 500 | 303 | 5 | T+3 | 0.68% | -0.64% | 46.20% | 1.22 | -5.67% | 8.78% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 498 | 301 | 5 | T+5 | 1.12% | -0.80% | 45.78% | 1.25 | -7.14% | 12.13% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 499 | 302 | 5 | T+10 | 2.13% | -1.85% | 44.29% | 1.37 | -9.67% | 16.84% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 501 | 304 | 5 | T+20 | -0.37% | -5.89% | 37.52% | 0.96 | -14.51% | 21.23% |  |

## VP20 Acceptance × Sector strength level

Sector level 同样按当日 `sector_score` 横截面生成；HIGH=80~100%（强）。

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ABOVE_VAH_ACCEPTED × LOW | 21 | 21 | 5 | T+1 | -1.45% | -1.43% | 38.10% | 0.21 | -2.94% | 2.74% |  |
| ABOVE_VAH_ACCEPTED × LOW | 21 | 21 | 5 | T+3 | -3.67% | -3.98% | 19.05% | 0.19 | -6.03% | 4.54% |  |
| ABOVE_VAH_ACCEPTED × LOW | 21 | 21 | 5 | T+5 | -4.44% | -3.57% | 28.57% | 0.24 | -8.63% | 5.62% |  |
| ABOVE_VAH_ACCEPTED × LOW | 21 | 21 | 5 | T+10 | -3.10% | -2.48% | 28.57% | 0.37 | -10.36% | 9.18% |  |
| ABOVE_VAH_ACCEPTED × LOW | 21 | 21 | 5 | T+20 | -2.53% | -7.04% | 28.57% | 0.70 | -15.76% | 13.62% |  |
| ABOVE_VAH_ACCEPTED × MID_LOW | 21 | 20 | 5 | T+1 | -0.17% | -1.75% | 38.10% | 0.91 | -3.65% | 3.79% |  |
| ABOVE_VAH_ACCEPTED × MID_LOW | 21 | 20 | 5 | T+3 | -0.69% | -0.58% | 47.62% | 0.78 | -5.58% | 6.36% |  |
| ABOVE_VAH_ACCEPTED × MID_LOW | 21 | 20 | 5 | T+5 | -2.57% | -1.83% | 28.57% | 0.36 | -6.81% | 7.33% |  |
| ABOVE_VAH_ACCEPTED × MID_LOW | 21 | 20 | 5 | T+10 | -0.75% | -1.08% | 38.10% | 0.82 | -9.31% | 10.94% |  |
| ABOVE_VAH_ACCEPTED × MID_LOW | 21 | 20 | 5 | T+20 | -2.23% | -2.74% | 28.57% | 0.67 | -13.88% | 16.71% |  |
| ABOVE_VAH_ACCEPTED × MID | 18 | 18 | 5 | T+1 | 0.20% | 0.03% | 55.56% | 1.16 | -3.22% | 3.62% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 18 | 18 | 5 | T+3 | 3.78% | 0.91% | 50.00% | 4.19 | -4.36% | 9.13% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 18 | 18 | 5 | T+5 | 1.50% | -1.64% | 44.44% | 1.39 | -6.06% | 12.34% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 18 | 18 | 5 | T+10 | 5.00% | 3.00% | 50.00% | 2.15 | -8.78% | 18.94% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 18 | 18 | 5 | T+20 | 6.25% | -3.41% | 44.44% | 1.93 | -12.76% | 28.15% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 24 | 24 | 5 | T+1 | -0.98% | -2.50% | 33.33% | 0.57 | -3.49% | 2.60% |  |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 24 | 24 | 5 | T+3 | -1.93% | -2.35% | 33.33% | 0.38 | -5.46% | 3.76% |  |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 24 | 24 | 5 | T+5 | -1.10% | -1.98% | 29.17% | 0.63 | -6.31% | 4.92% |  |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 24 | 24 | 5 | T+10 | 2.50% | -1.53% | 37.50% | 1.55 | -9.13% | 13.60% |  |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 24 | 24 | 5 | T+20 | 4.29% | -2.23% | 45.83% | 1.66 | -12.67% | 22.28% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 32 | 32 | 5 | T+1 | 0.20% | -0.23% | 40.62% | 1.11 | -3.23% | 4.05% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 32 | 32 | 5 | T+3 | -1.08% | -2.70% | 31.25% | 0.75 | -6.51% | 7.10% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 32 | 32 | 5 | T+5 | -4.13% | -5.02% | 28.12% | 0.43 | -8.96% | 8.31% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 32 | 32 | 5 | T+10 | -4.98% | -8.02% | 25.00% | 0.54 | -13.04% | 12.54% |  |
| ABOVE_VAH_ACCEPTED × HIGH | 32 | 32 | 5 | T+20 | -10.49% | -11.14% | 15.62% | 0.24 | -17.77% | 14.07% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 177 | 162 | 5 | T+1 | -0.40% | -0.89% | 40.11% | 0.74 | -2.66% | 3.40% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 177 | 162 | 5 | T+3 | -0.30% | -0.58% | 44.07% | 0.88 | -4.45% | 6.27% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 176 | 161 | 5 | T+5 | -0.78% | -1.32% | 42.05% | 0.80 | -6.04% | 8.36% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 176 | 161 | 5 | T+10 | 1.58% | -1.39% | 42.05% | 1.40 | -8.01% | 12.13% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 175 | 161 | 5 | T+20 | 0.75% | -2.48% | 42.86% | 1.13 | -12.33% | 16.78% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 223 | 208 | 5 | T+1 | 0.64% | -0.47% | 43.05% | 1.48 | -2.48% | 3.98% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 223 | 208 | 5 | T+3 | 1.70% | 0.70% | 55.61% | 1.86 | -4.12% | 7.57% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 223 | 208 | 5 | T+5 | 1.83% | -0.33% | 47.53% | 1.57 | -5.38% | 10.87% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 221 | 206 | 5 | T+10 | 5.05% | 1.23% | 55.66% | 2.58 | -7.45% | 15.29% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 222 | 208 | 5 | T+20 | 2.12% | -2.16% | 44.14% | 1.39 | -11.62% | 19.20% |  |
| ABOVE_VAH_UNACCEPTED × MID | 179 | 169 | 5 | T+1 | 0.46% | -0.21% | 46.93% | 1.34 | -2.55% | 4.19% |  |
| ABOVE_VAH_UNACCEPTED × MID | 179 | 169 | 5 | T+3 | 0.39% | -0.77% | 43.58% | 1.15 | -4.50% | 7.45% |  |
| ABOVE_VAH_UNACCEPTED × MID | 179 | 169 | 5 | T+5 | 0.74% | -0.68% | 46.37% | 1.22 | -5.71% | 9.75% |  |
| ABOVE_VAH_UNACCEPTED × MID | 179 | 169 | 5 | T+10 | 4.22% | -0.12% | 49.16% | 2.11 | -7.65% | 15.81% |  |
| ABOVE_VAH_UNACCEPTED × MID | 178 | 168 | 5 | T+20 | 4.29% | -1.20% | 47.19% | 1.76 | -11.20% | 22.45% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 192 | 191 | 5 | T+1 | 0.65% | -0.12% | 48.96% | 1.54 | -2.39% | 3.81% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 192 | 191 | 5 | T+3 | 1.11% | -0.00% | 50.00% | 1.49 | -4.20% | 7.47% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 191 | 190 | 5 | T+5 | 1.84% | 0.03% | 50.26% | 1.67 | -5.14% | 10.39% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 190 | 189 | 5 | T+10 | 4.12% | 2.14% | 56.84% | 2.19 | -7.17% | 14.88% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 192 | 191 | 5 | T+20 | 5.96% | -0.73% | 47.40% | 2.16 | -11.02% | 21.67% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 263 | 221 | 5 | T+1 | -0.36% | -0.70% | 40.68% | 0.79 | -2.98% | 3.62% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 262 | 220 | 5 | T+3 | -0.43% | -1.15% | 42.75% | 0.85 | -5.37% | 6.22% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 262 | 220 | 5 | T+5 | 0.10% | -1.51% | 43.89% | 1.02 | -6.82% | 9.85% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 263 | 221 | 5 | T+10 | -1.27% | -2.76% | 36.88% | 0.80 | -9.48% | 13.81% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 263 | 221 | 5 | T+20 | -1.83% | -6.03% | 36.50% | 0.79 | -14.58% | 18.40% |  |

## VP60 Acceptance × Sector strength level

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ABOVE_VAH_ACCEPTED × LOW | 8 | 7 | 4 | T+1 | -0.85% | -0.78% | 50.00% | 0.54 | -3.35% | 3.26% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 8 | 7 | 4 | T+3 | -3.69% | -3.16% | 12.50% | 0.11 | -5.99% | 3.92% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 8 | 7 | 4 | T+5 | 1.85% | -0.08% | 50.00% | 1.73 | -6.55% | 7.86% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 8 | 7 | 4 | T+10 | 0.39% | -1.49% | 37.50% | 1.18 | -6.89% | 13.02% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 7 | 6 | 4 | T+20 | 0.97% | 3.37% | 71.43% | 1.36 | -11.35% | 20.60% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 8 | 7 | 4 | T+1 | 1.51% | 0.01% | 50.00% | 6.94 | -1.66% | 3.56% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 8 | 7 | 4 | T+3 | 4.49% | 2.53% | 62.50% | 4.18 | -2.48% | 8.96% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 8 | 7 | 4 | T+5 | 4.02% | 3.89% | 62.50% | 3.25 | -2.90% | 10.97% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 8 | 7 | 4 | T+10 | 7.95% | 3.27% | 87.50% | 21.29 | -3.02% | 13.61% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_LOW | 8 | 7 | 4 | T+20 | -3.26% | -2.10% | 25.00% | 0.42 | -6.41% | 13.67% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 4 | 4 | 3 | T+1 | -0.16% | -0.79% | 50.00% | 0.87 | -1.92% | 3.31% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 4 | 4 | 3 | T+3 | 1.58% | 1.93% | 75.00% | 1.72 | -4.52% | 6.53% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 4 | 4 | 3 | T+5 | -2.50% | -3.19% | 25.00% | 0.43 | -5.33% | 7.81% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 4 | 4 | 3 | T+10 | -5.39% | -8.16% | 25.00% | 0.25 | -9.67% | 7.81% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID | 4 | 4 | 3 | T+20 | -6.40% | -6.64% | 50.00% | 0.22 | -13.75% | 11.80% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 9 | 9 | 4 | T+1 | 0.29% | 0.85% | 66.67% | 1.21 | -3.10% | 3.46% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 9 | 9 | 4 | T+3 | 0.08% | 1.25% | 77.78% | 1.05 | -3.83% | 6.15% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 9 | 9 | 4 | T+5 | -0.34% | -1.38% | 44.44% | 0.89 | -4.91% | 7.84% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 9 | 9 | 4 | T+10 | 4.57% | -3.70% | 44.44% | 2.56 | -7.71% | 13.05% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × MID_HIGH | 9 | 9 | 4 | T+20 | 12.69% | 4.14% | 77.78% | 5.84 | -9.43% | 23.42% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 15 | 14 | 4 | T+1 | -2.86% | -2.87% | 20.00% | 0.19 | -4.33% | 2.42% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 15 | 14 | 4 | T+3 | -2.94% | -5.65% | 33.33% | 0.42 | -6.98% | 4.22% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 15 | 14 | 4 | T+5 | -3.11% | -7.29% | 20.00% | 0.49 | -8.48% | 7.17% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 15 | 14 | 4 | T+10 | -8.17% | -14.37% | 20.00% | 0.31 | -13.79% | 9.17% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH | 15 | 14 | 4 | T+20 | -9.19% | -14.20% | 13.33% | 0.37 | -19.18% | 10.63% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × LOW | 264 | 227 | 5 | T+1 | -0.01% | -0.58% | 43.18% | 0.99 | -2.62% | 3.71% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 264 | 227 | 5 | T+3 | 0.11% | -0.89% | 42.80% | 1.04 | -4.52% | 6.87% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 263 | 227 | 5 | T+5 | 0.56% | -0.84% | 44.87% | 1.15 | -5.89% | 9.27% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 262 | 226 | 5 | T+10 | 2.07% | -1.39% | 44.27% | 1.48 | -7.85% | 13.67% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 263 | 226 | 5 | T+20 | 0.79% | -2.63% | 41.44% | 1.12 | -12.04% | 17.97% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 333 | 291 | 5 | T+1 | 0.61% | -0.56% | 44.14% | 1.44 | -2.58% | 4.03% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 333 | 291 | 5 | T+3 | 1.34% | 0.21% | 51.95% | 1.58 | -4.45% | 7.40% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 333 | 291 | 5 | T+5 | 1.59% | -0.74% | 46.85% | 1.47 | -5.56% | 10.46% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 331 | 290 | 5 | T+10 | 5.23% | 0.92% | 54.68% | 2.58 | -7.30% | 15.59% |  |
| ABOVE_VAH_UNACCEPTED × MID_LOW | 331 | 291 | 5 | T+20 | 2.57% | -2.08% | 43.50% | 1.46 | -11.36% | 20.10% |  |
| ABOVE_VAH_UNACCEPTED × MID | 282 | 250 | 5 | T+1 | 0.72% | 0.08% | 52.84% | 1.65 | -2.41% | 4.18% |  |
| ABOVE_VAH_UNACCEPTED × MID | 281 | 249 | 5 | T+3 | 0.90% | -0.16% | 47.69% | 1.42 | -3.96% | 7.67% |  |
| ABOVE_VAH_UNACCEPTED × MID | 281 | 249 | 5 | T+5 | 1.32% | -0.49% | 48.04% | 1.43 | -5.29% | 10.24% |  |
| ABOVE_VAH_UNACCEPTED × MID | 281 | 249 | 5 | T+10 | 4.68% | 1.20% | 55.16% | 2.37 | -7.15% | 16.14% |  |
| ABOVE_VAH_UNACCEPTED × MID | 281 | 249 | 5 | T+20 | 3.85% | -0.63% | 48.75% | 1.66 | -10.93% | 22.75% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 276 | 268 | 5 | T+1 | 0.87% | 0.39% | 54.71% | 1.79 | -2.30% | 3.82% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 274 | 267 | 5 | T+3 | 0.38% | -0.77% | 44.89% | 1.16 | -4.15% | 6.96% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 272 | 265 | 5 | T+5 | 1.08% | -0.29% | 47.06% | 1.36 | -5.30% | 9.59% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 272 | 265 | 5 | T+10 | 3.03% | 0.35% | 51.84% | 1.83 | -7.50% | 14.01% |  |
| ABOVE_VAH_UNACCEPTED × MID_HIGH | 275 | 268 | 5 | T+20 | 4.07% | -2.30% | 42.91% | 1.67 | -11.82% | 21.32% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 366 | 290 | 5 | T+1 | -0.11% | -0.27% | 45.90% | 0.93 | -2.83% | 3.81% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 365 | 289 | 5 | T+3 | -0.61% | -1.60% | 41.37% | 0.81 | -5.50% | 6.38% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 365 | 289 | 5 | T+5 | -0.72% | -1.98% | 41.92% | 0.85 | -6.92% | 9.40% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 366 | 290 | 5 | T+10 | -2.01% | -3.07% | 36.07% | 0.69 | -9.59% | 12.82% |  |
| ABOVE_VAH_UNACCEPTED × HIGH | 366 | 290 | 5 | T+20 | -3.29% | -6.52% | 36.34% | 0.65 | -14.83% | 17.03% |  |

## VP20 Acceptance × RS State

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ABOVE_VAH_ACCEPTED × EXTENDED | 78 | 72 | 5 | T+1 | -0.38% | -1.06% | 42.31% | 0.80 | -3.54% | 3.63% |  |
| ABOVE_VAH_ACCEPTED × EXTENDED | 78 | 72 | 5 | T+3 | -0.57% | -1.70% | 35.90% | 0.84 | -6.18% | 6.56% |  |
| ABOVE_VAH_ACCEPTED × EXTENDED | 78 | 72 | 5 | T+5 | -2.53% | -3.21% | 32.05% | 0.56 | -8.05% | 8.18% |  |
| ABOVE_VAH_ACCEPTED × EXTENDED | 78 | 72 | 5 | T+10 | -2.31% | -5.20% | 28.21% | 0.71 | -11.52% | 13.27% |  |
| ABOVE_VAH_ACCEPTED × EXTENDED | 78 | 72 | 5 | T+20 | -3.03% | -7.34% | 28.21% | 0.70 | -15.52% | 18.70% |  |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FALLING | 1 | 1 | 1 | T+1 | -2.39% | -2.39% | 0.00% | 0.00 | -1.77% | 0.09% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FALLING | 1 | 1 | 1 | T+3 | -3.55% | -3.55% | 0.00% | 0.00 | -2.70% | 0.09% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FALLING | 1 | 1 | 1 | T+5 | -3.65% | -3.65% | 0.00% | 0.00 | -2.70% | 0.71% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FALLING | 1 | 1 | 1 | T+10 | 2.49% | 2.49% | 100.00% | — | -5.57% | 11.50% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FALLING | 1 | 1 | 1 | T+20 | -0.79% | -0.79% | 0.00% | 0.00 | -5.57% | 11.68% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FLAT | 5 | 5 | 4 | T+1 | -2.05% | -1.90% | 20.00% | 0.28 | -3.99% | 2.39% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FLAT | 5 | 5 | 4 | T+3 | -3.54% | -4.56% | 20.00% | 0.21 | -5.83% | 3.41% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FLAT | 5 | 5 | 4 | T+5 | 0.01% | 1.04% | 60.00% | 1.00 | -6.77% | 5.54% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FLAT | 5 | 5 | 4 | T+10 | 8.07% | 2.73% | 60.00% | 4.68 | -7.16% | 17.66% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_FLAT | 5 | 5 | 4 | T+20 | 17.06% | 13.12% | 60.00% | 3.63 | -13.19% | 35.24% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × HIGH_AND_RISING | 23 | 23 | 5 | T+1 | -0.17% | -0.63% | 43.48% | 0.89 | -2.86% | 3.36% |  |
| ABOVE_VAH_ACCEPTED × HIGH_AND_RISING | 23 | 23 | 5 | T+3 | -1.23% | -3.62% | 34.78% | 0.65 | -4.99% | 6.15% |  |
| ABOVE_VAH_ACCEPTED × HIGH_AND_RISING | 23 | 23 | 5 | T+5 | -2.30% | -3.30% | 21.74% | 0.34 | -6.78% | 6.73% |  |
| ABOVE_VAH_ACCEPTED × HIGH_AND_RISING | 23 | 23 | 5 | T+10 | 0.35% | -1.38% | 39.13% | 1.09 | -8.91% | 10.45% |  |
| ABOVE_VAH_ACCEPTED × HIGH_AND_RISING | 23 | 23 | 5 | T+20 | -4.41% | -7.04% | 34.78% | 0.45 | -14.92% | 13.08% |  |
| ABOVE_VAH_ACCEPTED × LOW | 5 | 5 | 3 | T+1 | 0.59% | -0.06% | 40.00% | 1.58 | -2.46% | 3.34% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 5 | 5 | 3 | T+3 | -0.32% | 1.98% | 60.00% | 0.87 | -3.80% | 6.04% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 5 | 5 | 3 | T+5 | -0.99% | -1.14% | 40.00% | 0.70 | -4.61% | 8.97% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 5 | 5 | 3 | T+10 | 0.14% | -4.36% | 40.00% | 1.04 | -5.94% | 12.11% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LOW | 5 | 5 | 3 | T+20 | -1.64% | -4.68% | 20.00% | 0.68 | -11.16% | 18.07% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × RISING | 4 | 4 | 2 | T+1 | -1.11% | -1.06% | 25.00% | 0.14 | -1.94% | 1.22% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × RISING | 4 | 4 | 2 | T+3 | -2.21% | -2.24% | 25.00% | 0.01 | -3.41% | 2.58% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × RISING | 4 | 4 | 2 | T+5 | -5.03% | -2.96% | 25.00% | 0.02 | -6.90% | 3.01% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × RISING | 4 | 4 | 2 | T+10 | 9.64% | 7.64% | 75.00% | 47.65 | -8.77% | 13.79% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × RISING | 4 | 4 | 2 | T+20 | 10.28% | 3.42% | 50.00% | 5.77 | -11.71% | 21.72% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × EXTENDED | 501 | 358 | 5 | T+1 | 0.32% | -0.37% | 46.71% | 1.21 | -2.91% | 4.18% |  |
| ABOVE_VAH_UNACCEPTED × EXTENDED | 500 | 357 | 5 | T+3 | 0.62% | -0.30% | 47.00% | 1.24 | -5.05% | 7.68% |  |
| ABOVE_VAH_UNACCEPTED × EXTENDED | 498 | 356 | 5 | T+5 | 0.41% | -1.19% | 45.58% | 1.10 | -6.56% | 10.65% |  |
| ABOVE_VAH_UNACCEPTED × EXTENDED | 496 | 355 | 5 | T+10 | 1.29% | -1.15% | 44.76% | 1.25 | -8.99% | 15.03% |  |
| ABOVE_VAH_UNACCEPTED × EXTENDED | 501 | 358 | 5 | T+20 | 0.15% | -3.45% | 39.32% | 1.02 | -13.55% | 19.55% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FALLING | 53 | 51 | 5 | T+1 | -0.08% | -0.47% | 45.28% | 0.95 | -3.20% | 3.96% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FALLING | 53 | 51 | 5 | T+3 | 0.80% | 0.34% | 52.83% | 1.30 | -5.18% | 7.07% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FALLING | 53 | 51 | 5 | T+5 | 0.95% | -0.40% | 49.06% | 1.30 | -5.87% | 9.73% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FALLING | 53 | 51 | 5 | T+10 | 3.00% | -0.05% | 49.06% | 1.88 | -8.00% | 13.41% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FALLING | 53 | 51 | 5 | T+20 | 2.67% | -4.82% | 39.62% | 1.45 | -12.23% | 20.25% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FLAT | 71 | 65 | 5 | T+1 | 1.06% | 0.41% | 52.11% | 1.75 | -2.71% | 4.94% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FLAT | 71 | 65 | 5 | T+3 | 2.31% | 0.42% | 52.11% | 1.91 | -4.58% | 9.71% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FLAT | 71 | 65 | 5 | T+5 | 4.73% | 0.20% | 50.70% | 2.58 | -5.44% | 14.40% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FLAT | 71 | 65 | 5 | T+10 | 9.42% | -1.19% | 47.89% | 3.79 | -7.55% | 20.86% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_FLAT | 68 | 62 | 5 | T+20 | 8.03% | -0.61% | 48.53% | 2.48 | -11.20% | 26.99% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_RISING | 228 | 201 | 5 | T+1 | 0.24% | -0.50% | 43.86% | 1.17 | -2.39% | 3.81% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_RISING | 228 | 201 | 5 | T+3 | 0.01% | -1.02% | 45.18% | 1.00 | -4.32% | 6.52% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_RISING | 228 | 201 | 5 | T+5 | 1.02% | -0.20% | 49.12% | 1.33 | -5.47% | 9.39% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_RISING | 228 | 201 | 5 | T+10 | 3.66% | 1.14% | 53.95% | 2.07 | -7.08% | 14.26% |  |
| ABOVE_VAH_UNACCEPTED × HIGH_AND_RISING | 227 | 200 | 5 | T+20 | 3.11% | -0.01% | 49.34% | 1.56 | -11.62% | 21.01% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 90 | 88 | 5 | T+1 | -0.56% | -0.63% | 31.11% | 0.57 | -2.11% | 2.15% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 90 | 88 | 5 | T+3 | -0.78% | -1.29% | 37.78% | 0.72 | -3.94% | 4.15% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 90 | 88 | 5 | T+5 | -0.67% | -2.19% | 34.44% | 0.81 | -5.20% | 6.35% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 90 | 88 | 5 | T+10 | 0.64% | -0.62% | 45.56% | 1.15 | -7.50% | 9.74% |  |
| ABOVE_VAH_UNACCEPTED × LOW | 90 | 88 | 5 | T+20 | 1.60% | -0.98% | 45.56% | 1.32 | -10.84% | 13.60% |  |
| ABOVE_VAH_UNACCEPTED × RISING | 91 | 84 | 5 | T+1 | -0.58% | -0.47% | 31.87% | 0.58 | -1.87% | 2.24% |  |
| ABOVE_VAH_UNACCEPTED × RISING | 91 | 84 | 5 | T+3 | 0.50% | 0.51% | 56.04% | 1.29 | -2.83% | 4.72% |  |
| ABOVE_VAH_UNACCEPTED × RISING | 91 | 84 | 5 | T+5 | 0.21% | -0.82% | 46.15% | 1.07 | -4.07% | 7.17% |  |
| ABOVE_VAH_UNACCEPTED × RISING | 91 | 84 | 5 | T+10 | 2.65% | -0.75% | 48.35% | 1.71 | -6.28% | 11.37% |  |
| ABOVE_VAH_UNACCEPTED × RISING | 91 | 84 | 5 | T+20 | 4.55% | -1.74% | 43.96% | 2.03 | -9.72% | 16.46% |  |

## VP20 Acceptance × Sector Phase

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ABOVE_VAH_ACCEPTED × ACCELERATING | 23 | 23 | 4 | T+1 | -1.60% | -2.86% | 26.09% | 0.45 | -4.14% | 2.79% |  |
| ABOVE_VAH_ACCEPTED × ACCELERATING | 23 | 23 | 4 | T+3 | -2.13% | -4.40% | 30.43% | 0.59 | -8.22% | 6.13% |  |
| ABOVE_VAH_ACCEPTED × ACCELERATING | 23 | 23 | 4 | T+5 | -3.43% | -4.00% | 26.09% | 0.51 | -10.30% | 7.68% |  |
| ABOVE_VAH_ACCEPTED × ACCELERATING | 23 | 23 | 4 | T+10 | -2.17% | -8.67% | 34.78% | 0.79 | -14.21% | 14.25% |  |
| ABOVE_VAH_ACCEPTED × ACCELERATING | 23 | 23 | 4 | T+20 | -2.62% | -11.96% | 34.78% | 0.79 | -17.41% | 19.80% |  |
| ABOVE_VAH_ACCEPTED × EMERGING | 25 | 25 | 5 | T+1 | -0.87% | -0.40% | 48.00% | 0.54 | -3.56% | 2.68% |  |
| ABOVE_VAH_ACCEPTED × EMERGING | 25 | 25 | 5 | T+3 | 1.61% | -0.16% | 48.00% | 2.03 | -4.79% | 6.49% |  |
| ABOVE_VAH_ACCEPTED × EMERGING | 25 | 25 | 5 | T+5 | -0.59% | -1.64% | 40.00% | 0.85 | -6.70% | 8.96% |  |
| ABOVE_VAH_ACCEPTED × EMERGING | 25 | 25 | 5 | T+10 | 2.54% | -0.29% | 44.00% | 1.56 | -10.09% | 15.11% |  |
| ABOVE_VAH_ACCEPTED × EMERGING | 25 | 25 | 5 | T+20 | 0.01% | -7.25% | 36.00% | 1.00 | -15.52% | 19.81% |  |
| ABOVE_VAH_ACCEPTED × EXHAUSTED | 0 | 0 | 0 | T+1 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × EXHAUSTED | 0 | 0 | 0 | T+3 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × EXHAUSTED | 0 | 0 | 0 | T+5 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × EXHAUSTED | 0 | 0 | 0 | T+10 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × EXHAUSTED | 0 | 0 | 0 | T+20 | — | — | — | — | — | — | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × FADING | 12 | 12 | 3 | T+1 | 4.38% | 0.64% | 58.33% | 9.40 | -2.42% | 6.88% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × FADING | 12 | 12 | 3 | T+3 | 0.96% | -3.02% | 33.33% | 1.29 | -4.38% | 10.75% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × FADING | 12 | 12 | 3 | T+5 | 3.19% | 1.30% | 50.00% | 2.45 | -5.74% | 13.20% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × FADING | 12 | 12 | 3 | T+10 | 7.02% | 1.59% | 58.33% | 3.95 | -7.04% | 20.98% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × FADING | 12 | 12 | 3 | T+20 | 8.04% | 7.85% | 58.33% | 2.84 | -10.47% | 31.96% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LEADING | 11 | 11 | 5 | T+1 | 2.09% | 1.28% | 54.55% | 6.24 | -1.72% | 4.75% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LEADING | 11 | 11 | 5 | T+3 | -0.31% | -1.68% | 36.36% | 0.87 | -3.98% | 6.07% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LEADING | 11 | 11 | 5 | T+5 | -1.90% | -3.35% | 27.27% | 0.46 | -5.05% | 6.51% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LEADING | 11 | 11 | 5 | T+10 | 0.00% | -6.89% | 27.27% | 1.00 | -7.85% | 11.54% | INSUFFICIENT |
| ABOVE_VAH_ACCEPTED × LEADING | 11 | 11 | 5 | T+20 | -9.54% | -6.52% | 0.00% | 0.00 | -14.90% | 12.68% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × ACCELERATING | 160 | 153 | 5 | T+1 | -0.69% | -0.88% | 38.12% | 0.65 | -3.28% | 3.53% |  |
| ABOVE_VAH_UNACCEPTED × ACCELERATING | 159 | 152 | 5 | T+3 | -1.06% | -2.26% | 36.48% | 0.70 | -6.59% | 5.89% |  |
| ABOVE_VAH_UNACCEPTED × ACCELERATING | 159 | 152 | 5 | T+5 | -1.54% | -2.14% | 39.62% | 0.68 | -8.00% | 8.78% |  |
| ABOVE_VAH_UNACCEPTED × ACCELERATING | 160 | 153 | 5 | T+10 | -2.37% | -3.22% | 36.88% | 0.67 | -10.89% | 12.12% |  |
| ABOVE_VAH_UNACCEPTED × ACCELERATING | 160 | 153 | 5 | T+20 | -0.38% | -5.09% | 40.62% | 0.96 | -14.66% | 17.66% |  |
| ABOVE_VAH_UNACCEPTED × EMERGING | 305 | 253 | 5 | T+1 | 0.25% | -0.20% | 47.54% | 1.20 | -2.47% | 3.62% |  |
| ABOVE_VAH_UNACCEPTED × EMERGING | 305 | 253 | 5 | T+3 | 1.52% | 0.63% | 55.08% | 1.76 | -4.05% | 7.32% |  |
| ABOVE_VAH_UNACCEPTED × EMERGING | 304 | 253 | 5 | T+5 | 1.42% | 0.19% | 50.99% | 1.48 | -5.34% | 10.59% |  |
| ABOVE_VAH_UNACCEPTED × EMERGING | 302 | 252 | 5 | T+10 | 4.65% | 2.10% | 57.62% | 2.46 | -7.71% | 15.45% |  |
| ABOVE_VAH_UNACCEPTED × EMERGING | 304 | 253 | 5 | T+20 | 4.02% | -0.64% | 47.37% | 1.80 | -12.01% | 21.08% |  |
| ABOVE_VAH_UNACCEPTED × EXHAUSTED | 2 | 2 | 1 | T+1 | 1.79% | 1.79% | 50.00% | 8.86 | -1.30% | 5.18% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × EXHAUSTED | 2 | 2 | 1 | T+3 | 3.53% | 3.53% | 50.00% | 7.48 | -3.18% | 8.96% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × EXHAUSTED | 2 | 2 | 1 | T+5 | -3.42% | -3.42% | 50.00% | 0.00 | -6.13% | 8.96% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × EXHAUSTED | 2 | 2 | 1 | T+10 | 1.36% | 1.36% | 50.00% | 1.16 | -10.73% | 18.35% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × EXHAUSTED | 2 | 2 | 1 | T+20 | 14.58% | 14.58% | 50.00% | 2.65 | -13.34% | 47.60% | INSUFFICIENT |
| ABOVE_VAH_UNACCEPTED × FADING | 67 | 67 | 4 | T+1 | 2.01% | 1.22% | 58.21% | 3.00 | -2.45% | 5.38% |  |
| ABOVE_VAH_UNACCEPTED × FADING | 67 | 67 | 4 | T+3 | -0.69% | -1.83% | 40.30% | 0.79 | -4.79% | 8.35% |  |
| ABOVE_VAH_UNACCEPTED × FADING | 66 | 66 | 4 | T+5 | -0.20% | -1.31% | 43.94% | 0.95 | -6.19% | 9.69% |  |
| ABOVE_VAH_UNACCEPTED × FADING | 66 | 66 | 4 | T+10 | 1.28% | -2.60% | 40.91% | 1.28 | -7.90% | 13.11% |  |
| ABOVE_VAH_UNACCEPTED × FADING | 67 | 67 | 4 | T+20 | 4.09% | -2.70% | 46.27% | 1.68 | -11.08% | 22.63% |  |
| ABOVE_VAH_UNACCEPTED × LEADING | 98 | 86 | 5 | T+1 | 0.67% | 0.04% | 51.02% | 1.61 | -2.11% | 3.83% |  |
| ABOVE_VAH_UNACCEPTED × LEADING | 98 | 86 | 5 | T+3 | 1.07% | 0.72% | 55.10% | 1.58 | -3.52% | 6.62% |  |
| ABOVE_VAH_UNACCEPTED × LEADING | 98 | 86 | 5 | T+5 | 1.06% | -1.00% | 45.92% | 1.31 | -4.87% | 9.58% |  |
| ABOVE_VAH_UNACCEPTED × LEADING | 98 | 86 | 5 | T+10 | 1.74% | -0.96% | 39.80% | 1.42 | -7.07% | 14.38% |  |
| ABOVE_VAH_UNACCEPTED × LEADING | 98 | 86 | 5 | T+20 | -2.15% | -5.65% | 32.65% | 0.72 | -13.26% | 16.87% |  |

## VP20 Acceptance 条件的只读拆解

A--D 是重叠的描述性集合，不是修改后的 Acceptance 规则，也不能据结果挑选较早确认条件。

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A: price > VAH | 1150 | 712 | 5 | T+1 | 0.12% | -0.46% | 43.39% | 1.08 | -2.70% | 3.75% |  |
| A: price > VAH | 1149 | 711 | 5 | T+3 | 0.34% | -0.53% | 46.04% | 1.13 | -4.69% | 6.88% |  |
| A: price > VAH | 1147 | 710 | 5 | T+5 | 0.44% | -1.04% | 44.46% | 1.12 | -6.04% | 9.66% |  |
| A: price > VAH | 1145 | 710 | 5 | T+10 | 2.19% | -0.89% | 46.29% | 1.49 | -8.28% | 14.23% |  |
| A: price > VAH | 1146 | 712 | 5 | T+20 | 1.58% | -2.77% | 41.88% | 1.24 | -12.58% | 19.48% |  |
| B: A + POC_RISING | 256 | 228 | 5 | T+1 | 0.21% | -0.14% | 48.05% | 1.13 | -2.84% | 3.85% |  |
| B: A + POC_RISING | 256 | 228 | 5 | T+3 | 0.64% | -0.39% | 46.48% | 1.27 | -4.57% | 7.15% |  |
| B: A + POC_RISING | 256 | 228 | 5 | T+5 | 0.26% | -1.22% | 43.36% | 1.07 | -6.14% | 9.76% |  |
| B: A + POC_RISING | 255 | 227 | 5 | T+10 | 1.71% | -1.27% | 45.10% | 1.34 | -8.82% | 14.74% |  |
| B: A + POC_RISING | 255 | 227 | 5 | T+20 | 0.78% | -3.91% | 38.04% | 1.11 | -13.27% | 20.18% |  |
| C: A + VALUE_AREA_RISING | 317 | 244 | 5 | T+1 | -0.09% | -0.77% | 40.06% | 0.95 | -3.15% | 3.79% |  |
| C: A + VALUE_AREA_RISING | 317 | 244 | 5 | T+3 | -0.35% | -1.37% | 40.69% | 0.89 | -5.72% | 7.12% |  |
| C: A + VALUE_AREA_RISING | 317 | 244 | 5 | T+5 | -0.35% | -1.96% | 41.96% | 0.92 | -7.18% | 9.61% |  |
| C: A + VALUE_AREA_RISING | 317 | 244 | 5 | T+10 | 0.78% | -2.55% | 39.75% | 1.14 | -9.55% | 14.78% |  |
| C: A + VALUE_AREA_RISING | 317 | 244 | 5 | T+20 | -0.52% | -4.46% | 38.49% | 0.94 | -14.39% | 20.16% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 116 | 109 | 5 | T+1 | -0.41% | -1.06% | 40.52% | 0.78 | -3.31% | 3.40% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 116 | 109 | 5 | T+3 | -0.90% | -2.05% | 35.34% | 0.74 | -5.70% | 6.13% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 116 | 109 | 5 | T+5 | -2.40% | -3.10% | 31.03% | 0.52 | -7.51% | 7.57% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 116 | 109 | 5 | T+10 | -0.78% | -3.01% | 34.48% | 0.88 | -10.42% | 12.85% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 116 | 109 | 5 | T+20 | -1.90% | -6.28% | 31.03% | 0.79 | -14.89% | 18.31% |  |

## VP60 Acceptance 条件的只读拆解

| 组别 | n | unique symbols | unique dates | 期限 | mean excess | median excess | positive excess | PF | MAE | MFE | 样本标记 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A: price > VAH | 1565 | 832 | 5 | T+1 | 0.36% | -0.21% | 47.80% | 1.26 | -2.58% | 3.89% |  |
| A: price > VAH | 1561 | 831 | 5 | T+3 | 0.37% | -0.56% | 45.80% | 1.14 | -4.59% | 7.00% |  |
| A: price > VAH | 1558 | 830 | 5 | T+5 | 0.68% | -0.86% | 45.38% | 1.19 | -5.86% | 9.75% |  |
| A: price > VAH | 1556 | 829 | 5 | T+10 | 2.34% | -0.58% | 47.75% | 1.53 | -7.99% | 14.32% |  |
| A: price > VAH | 1559 | 832 | 5 | T+20 | 1.27% | -2.76% | 42.27% | 1.19 | -12.34% | 19.58% |  |
| B: A + POC_RISING | 162 | 137 | 5 | T+1 | 0.17% | -0.66% | 45.06% | 1.10 | -3.02% | 3.86% |  |
| B: A + POC_RISING | 159 | 135 | 5 | T+3 | -0.95% | -2.20% | 36.48% | 0.71 | -5.40% | 6.48% |  |
| B: A + POC_RISING | 159 | 135 | 5 | T+5 | -1.01% | -2.31% | 38.99% | 0.77 | -6.84% | 8.59% |  |
| B: A + POC_RISING | 160 | 136 | 5 | T+10 | -0.87% | -3.47% | 40.00% | 0.85 | -9.36% | 12.32% |  |
| B: A + POC_RISING | 161 | 136 | 5 | T+20 | -4.67% | -8.64% | 31.06% | 0.50 | -14.03% | 15.69% |  |
| C: A + VALUE_AREA_RISING | 148 | 123 | 5 | T+1 | -0.33% | -0.21% | 47.30% | 0.80 | -3.07% | 3.29% |  |
| C: A + VALUE_AREA_RISING | 148 | 123 | 5 | T+3 | 0.09% | -0.66% | 45.95% | 1.03 | -4.99% | 6.52% |  |
| C: A + VALUE_AREA_RISING | 148 | 123 | 5 | T+5 | 0.15% | -1.83% | 39.19% | 1.04 | -6.09% | 9.30% |  |
| C: A + VALUE_AREA_RISING | 146 | 122 | 5 | T+10 | -0.09% | -2.46% | 43.15% | 0.98 | -8.71% | 12.24% |  |
| C: A + VALUE_AREA_RISING | 147 | 122 | 5 | T+20 | -0.26% | -3.51% | 39.46% | 0.96 | -13.00% | 17.09% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 44 | 39 | 5 | T+1 | -0.81% | -0.67% | 43.18% | 0.60 | -3.19% | 3.07% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 44 | 39 | 5 | T+3 | -0.70% | -0.53% | 47.73% | 0.78 | -5.12% | 5.63% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 44 | 39 | 5 | T+5 | -0.29% | -1.87% | 38.64% | 0.93 | -6.10% | 8.18% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 44 | 39 | 5 | T+10 | -0.82% | -3.68% | 40.91% | 0.86 | -8.96% | 11.35% |  |
| D: A + POC_RISING + VALUE_AREA_RISING | 43 | 38 | 5 | T+20 | -1.59% | -6.03% | 41.86% | 0.80 | -12.98% | 15.60% |  |

## Extension 连续变量分布

已落盘 `vp*_extension` 全为 `VP_NORMAL`，但上方“读前结论”已说明该标签当前不可用于推断。这里仅审计未依赖该标签的连续距离；这不改变 Extension 阈值。距离字段以前缀 `vp20_` 为准，且 DTO 中 pct 是百分数值（不再乘以 100）。

| 样本 | 字段 | n | min | P25 | P50 | P75 | P90 | P95 | P99 | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ALL_WYCKOFF / VP20 FULL | vp20_distance_to_vah_pct | 2821 | -32.28% | -5.07% | -1.03% | 3.37% | 8.45% | 12.62% | 23.68% | 50.78% |
| ALL_WYCKOFF / VP20 FULL | vp20_distance_to_poc_pct | 2821 | -24.66% | -0.22% | 4.20% | 13.14% | 25.27% | 35.97% | 64.03% | 115.16% |
| ALL_WYCKOFF / VP20 FULL | vp20_distance_to_vah_atr | 2821 | -7.89 | -1.12 | -0.23 | 0.63 | 1.45 | 1.99 | 3.34 | 7.11 |
| ALL_WYCKOFF / VP20 FULL | vp20_distance_to_poc_atr | 2821 | -7.13 | -0.05 | 0.82 | 2.12 | 3.38 | 4.15 | 5.86 | 8.95 |
| RS HIGH / VP20 FULL | vp20_distance_to_vah_pct | 567 | -14.60% | 0.00% | 6.18% | 11.90% | 19.38% | 23.68% | 33.84% | 50.78% |
| RS HIGH / VP20 FULL | vp20_distance_to_poc_pct | 567 | -10.84% | 10.01% | 18.44% | 31.32% | 48.36% | 56.75% | 87.43% | 115.16% |
| RS HIGH / VP20 FULL | vp20_distance_to_vah_atr | 567 | -3.01 | 0.00 | 0.93 | 1.83 | 2.75 | 3.33 | 4.37 | 7.11 |
| RS HIGH / VP20 FULL | vp20_distance_to_poc_atr | 567 | -2.07 | 1.44 | 2.65 | 3.78 | 4.91 | 5.75 | 7.40 | 8.95 |
| RS MID_HIGH / VP20 FULL | vp20_distance_to_vah_pct | 564 | -18.92% | -0.77% | 2.88% | 5.62% | 8.27% | 10.26% | 15.44% | 19.32% |
| RS MID_HIGH / VP20 FULL | vp20_distance_to_poc_pct | 564 | -18.50% | 5.51% | 9.59% | 16.23% | 23.17% | 31.76% | 58.71% | 99.51% |
| RS MID_HIGH / VP20 FULL | vp20_distance_to_vah_atr | 564 | -3.50 | -0.13 | 0.51 | 1.03 | 1.51 | 1.85 | 2.77 | 3.20 |
| RS MID_HIGH / VP20 FULL | vp20_distance_to_poc_atr | 564 | -3.40 | 0.89 | 1.60 | 2.60 | 3.60 | 4.15 | 5.34 | 6.10 |
| Sector HIGH / VP20 FULL | vp20_distance_to_vah_pct | 613 | -21.12% | -3.38% | -0.06% | 4.44% | 9.71% | 14.42% | 24.71% | 50.78% |
| Sector HIGH / VP20 FULL | vp20_distance_to_poc_pct | 613 | -19.03% | 0.46% | 5.68% | 14.07% | 29.89% | 42.84% | 67.65% | 115.16% |
| Sector HIGH / VP20 FULL | vp20_distance_to_vah_atr | 613 | -6.22 | -0.72 | -0.02 | 0.86 | 1.71 | 2.27 | 3.67 | 7.11 |
| Sector HIGH / VP20 FULL | vp20_distance_to_poc_atr | 613 | -4.68 | 0.10 | 1.06 | 2.34 | 3.72 | 4.68 | 6.55 | 8.95 |

## 结论与边界

1. 本报告必须与原 Top30% 研究一起阅读；只有五个日期，不能把任何单元格的收益方向升级为 VPScore、排序加减分或交易规则。
2. 对 All_Wyckoff、Top30%、不同 RS/Sector level 的 Accepted/Unaccepted 差异，仅是预筛选敏感性检查。若方向变动，同时存在市场阶段、同股重复出现和小样本效应等竞争解释。
3. `rs_change_*`、`narrowing_flag` 未在本次已落盘 Parquet 中保存，故本轮不以代理变量填补，也不宣称完成 RS Change 或 NARROWING 联合检验。
4. 已落盘 Extension 标签存在实现顺序缺陷，必须在单独修复、加入回归测试并重算相关历史 VP 后，才能研究其阈值或风险识别能力；本轮不处理该修复。
5. 当前结论：**INSUFFICIENT**。VP 应继续保持独立 Position/Risk Context，不进入 `final_rank_score`。下一次验证应扩展独立、分钟 FULL 的信号日，并保持本报告的 VP-first 母样本设计。
