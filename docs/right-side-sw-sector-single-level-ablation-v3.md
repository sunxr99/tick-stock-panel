# Right-side SW Sector Single-Level Ablation V3

**Final status: `NO_STABLE_DIFFERENCE`**

## 1. Frozen contract

This exploratory frozen random-12 ablation keeps the Wyckoff candidate pools, forward labels, Top150, VP, RiskBucket, and every RS formula/benchmark/weight unchanged. Each group reuses the frozen snapshot Legacy SW1 `RSScore`; no SW2/SW3 RS is calculated or used.

Only SectorStrength level changes: A = `SW1`; D = `SW2`; E = `SW3`. Each group is `Opportunity = 0.40 × SectorScore + 0.60 × LegacyRSScore`. Sector Strength V1.1 and the `unique_members >= 8` gate are frozen. No fallback, zero-fill, dynamic weighting, or parameter scan is applied.

Dates (12): 2025-12-15, 2025-12-18, 2026-01-30, 2026-02-26, 2026-03-10, 2026-03-26, 2026-04-13, 2026-05-12, 2026-05-21, 2026-06-17, 2026-07-20, 2026-08-10.

## 2. Common-universe coverage

Main comparison uses only rows with valid, N>=8 SW1/SW2/SW3 SectorStrength and a valid frozen Legacy RS score. Thus A/D/E use exactly the same per-date candidate universe. `INSUFFICIENT_MEMBERS`, missing mapping, and ambiguous mapping remain fail-closed diagnostics, never zero scores.

| signal date | frozen candidates | SW1 valid | SW1 <8 | SW1 missing | SW1 ambiguous | SW1 coverage | SW2 valid | SW2 <8 | SW2 missing | SW2 ambiguous | SW2 coverage | SW3 valid | SW3 <8 | SW3 missing | SW3 ambiguous | SW3 coverage | common sector | common rankable | common coverage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-12-15 | 985 | 980 | 0 | 1 | 4 | 99.49% | 974 | 5 | 1 | 5 | 98.88% | 899 | 79 | 1 | 6 | 91.27% | 899 | 899 | 91.27% |
| 2025-12-18 | 1003 | 1002 | 0 | 0 | 1 | 99.90% | 993 | 6 | 0 | 4 | 99.00% | 903 | 95 | 0 | 5 | 90.03% | 903 | 903 | 90.03% |
| 2026-01-30 | 689 | 688 | 0 | 0 | 1 | 99.85% | 683 | 4 | 0 | 2 | 99.13% | 631 | 54 | 0 | 4 | 91.58% | 631 | 631 | 91.58% |
| 2026-02-26 | 735 | 733 | 0 | 0 | 2 | 99.73% | 728 | 4 | 0 | 3 | 99.05% | 669 | 62 | 0 | 4 | 91.02% | 669 | 669 | 91.02% |
| 2026-03-10 | 847 | 847 | 0 | 0 | 0 | 100.00% | 845 | 1 | 0 | 1 | 99.76% | 800 | 45 | 0 | 2 | 94.45% | 800 | 800 | 94.45% |
| 2026-03-26 | 1112 | 1106 | 0 | 0 | 6 | 99.46% | 1094 | 11 | 0 | 7 | 98.38% | 1014 | 89 | 0 | 9 | 91.19% | 1014 | 1014 | 91.19% |
| 2026-04-13 | 1111 | 1110 | 0 | 0 | 1 | 99.91% | 1106 | 3 | 0 | 2 | 99.55% | 1036 | 73 | 0 | 2 | 93.25% | 1036 | 1036 | 93.25% |
| 2026-05-12 | 1046 | 1044 | 0 | 0 | 2 | 99.81% | 1041 | 3 | 0 | 2 | 99.52% | 983 | 59 | 0 | 4 | 93.98% | 983 | 983 | 93.98% |
| 2026-05-21 | 972 | 970 | 0 | 0 | 2 | 99.79% | 968 | 2 | 0 | 2 | 99.59% | 918 | 51 | 0 | 3 | 94.44% | 918 | 918 | 94.44% |
| 2026-06-17 | 915 | 913 | 0 | 0 | 2 | 99.78% | 913 | 0 | 0 | 2 | 99.78% | 867 | 45 | 0 | 3 | 94.75% | 867 | 867 | 94.75% |
| 2026-07-20 | 1088 | 1085 | 0 | 0 | 3 | 99.72% | 1059 | 21 | 0 | 8 | 97.33% | 950 | 127 | 0 | 11 | 87.32% | 950 | 950 | 87.32% |
| 2026-08-10 | 825 | 824 | 0 | 0 | 1 | 99.88% | 812 | 7 | 0 | 6 | 98.42% | 755 | 63 | 0 | 7 | 91.52% | 755 | 755 | 91.52% |

No date has fewer than 150 common eligible stocks.

## 3. SW1/SW2/SW3 sample-size statistics

| level | mean industries/date | mean members | median | p25 | p75 | min | max | mean industries <8/date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SW1 | 31.0 | 188.99 | 136.00 | 93.00 | 176.00 | 31 | 634 | 0.00 |
| SW2 | 131.0 | 44.85 | 29.00 | 14.00 | 52.00 | 1 | 277 | 9.00 |
| SW3 | 338.0 | 17.42 | 11.00 | 6.00 | 21.00 | 1 | 145 | 111.25 |

Mean ambiguous resolved membership symbols/date (SW1/SW2/SW3) = 23.50 / 39.50 / 52.00. Stable SW codes are the calculation keys; ambiguity is fail-closed.

## 4. A/D/E Top150 performance

| group | horizon | n | mean return | median return | mean excess | median excess | positive rate | mean MAE | mean MFE | equal-weight portfolio return | portfolio MDD | beat benchmark dates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A · SW1 | T+5 | 1793 | 1.56% | -0.11% | 1.00% | -0.86% | 49.19% | -6.97% | 9.90% | 1.55% | -3.25% | 7/12 |
| A · SW1 | T+10 | 1789 | 1.93% | -0.24% | 1.88% | -0.57% | 48.80% | -9.49% | 14.71% | 1.93% | -5.52% | 8/12 |
| A · SW1 | T+20 | 1783 | 5.22% | -1.03% | 4.48% | -2.44% | 47.45% | -12.91% | 23.76% | 5.19% | -8.84% | 6/12 |
| D · SW2 | T+5 | 1794 | 1.30% | -0.26% | 0.74% | -1.21% | 48.16% | -6.99% | 9.66% | 1.29% | -3.16% | 7/12 |
| D · SW2 | T+10 | 1791 | 1.71% | -0.37% | 1.66% | -0.91% | 47.96% | -9.50% | 14.29% | 1.70% | -5.19% | 8/12 |
| D · SW2 | T+20 | 1785 | 4.33% | -0.97% | 3.60% | -2.60% | 47.84% | -13.03% | 22.90% | 4.32% | -8.71% | 6/12 |
| E · SW3 | T+5 | 1796 | 1.22% | -0.33% | 0.66% | -1.22% | 48.00% | -7.08% | 9.65% | 1.22% | -3.26% | 7/12 |
| E · SW3 | T+10 | 1795 | 1.67% | -0.37% | 1.61% | -0.85% | 48.19% | -9.60% | 14.30% | 1.66% | -5.09% | 8/12 |
| E · SW3 | T+20 | 1789 | 4.25% | -1.03% | 3.51% | -2.53% | 47.57% | -13.05% | 22.72% | 4.24% | -8.43% | 6/12 |

## 5. Date-level comparison

Return wins/ties/losses compare same-date equal-weight terminal portfolio returns. Positive ΔMDD is healthier because it is closer to zero.

| comparison | horizon | matched dates | return wins/ties/losses | mean Δ return | median Δ return | healthier MDD dates | mean Δ MDD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D vs A | T+5 | 12 | 5/0/7 | -0.26% | -0.08% | 7/12 | 0.09% |
| D vs A | T+10 | 12 | 6/0/6 | -0.22% | -0.24% | 11/12 | 0.33% |
| D vs A | T+20 | 12 | 4/0/8 | -0.86% | -0.73% | 6/12 | 0.13% |
| E vs A | T+5 | 12 | 6/0/6 | -0.34% | -0.07% | 5/12 | -0.01% |
| E vs A | T+10 | 12 | 6/0/6 | -0.27% | -0.06% | 10/12 | 0.44% |
| E vs A | T+20 | 12 | 3/0/9 | -0.95% | -0.70% | 9/12 | 0.41% |
| E vs D | T+5 | 12 | 5/0/7 | -0.08% | -0.09% | 5/12 | -0.10% |
| E vs D | T+10 | 12 | 3/0/9 | -0.04% | -0.13% | 9/12 | 0.10% |
| E vs D | T+20 | 12 | 6/0/6 | -0.09% | -0.13% | 10/12 | 0.28% |

## 6. Top150 overlap

| comparison | mean overlap | mean replaced | mean Jaccard |
| --- | --- | --- | --- |
| A vs D | 113.50 | 36.50 | 61.13% |
| A vs E | 107.58 | 42.42 | 56.14% |
| D vs E | 126.33 | 23.67 | 72.92% |

| signal date | comparison | overlap | replaced | Jaccard |
| --- | --- | --- | --- | --- |
| 2025-12-15 | A vs D | 112 | 38 | 59.57% |
| 2025-12-18 | A vs D | 117 | 33 | 63.93% |
| 2026-01-30 | A vs D | 129 | 21 | 75.44% |
| 2026-02-26 | A vs D | 118 | 32 | 64.84% |
| 2026-03-10 | A vs D | 118 | 32 | 64.84% |
| 2026-03-26 | A vs D | 111 | 39 | 58.73% |
| 2026-04-13 | A vs D | 102 | 48 | 51.52% |
| 2026-05-12 | A vs D | 106 | 44 | 54.64% |
| 2026-05-21 | A vs D | 113 | 37 | 60.43% |
| 2026-06-17 | A vs D | 112 | 38 | 59.57% |
| 2026-07-20 | A vs D | 102 | 48 | 51.52% |
| 2026-08-10 | A vs D | 122 | 28 | 68.54% |
| 2025-12-15 | A vs E | 104 | 46 | 53.06% |
| 2025-12-18 | A vs E | 114 | 36 | 61.29% |
| 2026-01-30 | A vs E | 119 | 31 | 65.75% |
| 2026-02-26 | A vs E | 115 | 35 | 62.16% |
| 2026-03-10 | A vs E | 113 | 37 | 60.43% |
| 2026-03-26 | A vs E | 103 | 47 | 52.28% |
| 2026-04-13 | A vs E | 98 | 52 | 48.51% |
| 2026-05-12 | A vs E | 101 | 49 | 50.75% |
| 2026-05-21 | A vs E | 104 | 46 | 53.06% |
| 2026-06-17 | A vs E | 104 | 46 | 53.06% |
| 2026-07-20 | A vs E | 98 | 52 | 48.51% |
| 2026-08-10 | A vs E | 118 | 32 | 64.84% |
| 2025-12-15 | D vs E | 128 | 22 | 74.42% |
| 2025-12-18 | D vs E | 125 | 25 | 71.43% |
| 2026-01-30 | D vs E | 135 | 15 | 81.82% |
| 2026-02-26 | D vs E | 130 | 20 | 76.47% |
| 2026-03-10 | D vs E | 126 | 24 | 72.41% |
| 2026-03-26 | D vs E | 121 | 29 | 67.60% |
| 2026-04-13 | D vs E | 125 | 25 | 71.43% |
| 2026-05-12 | D vs E | 124 | 26 | 70.45% |
| 2026-05-21 | D vs E | 119 | 31 | 65.75% |
| 2026-06-17 | D vs E | 125 | 25 | 71.43% |
| 2026-07-20 | D vs E | 120 | 30 | 66.67% |
| 2026-08-10 | D vs E | 138 | 12 | 85.19% |

## 7. Industry concentration

This is diagnostic only; sector concentration never changes selection. Values are random-12 daily means for each Top150.

| group | level | mean largest industry share | mean Top3 share | mean industry count | mean missing industries |
| --- | --- | --- | --- | --- | --- |
| A · SW1 | SW1 | 37.56% | 65.33% | 12.58 | 0.00 |
| A · SW1 | SW2 | 18.61% | 37.50% | 33.33 | 0.00 |
| A · SW1 | SW3 | 9.67% | 21.50% | 54.58 | 0.00 |
| D · SW2 | SW1 | 32.06% | 61.83% | 16.00 | 0.00 |
| D · SW2 | SW2 | 19.39% | 40.61% | 29.92 | 0.00 |
| D · SW2 | SW3 | 10.61% | 23.50% | 50.33 | 0.00 |
| E · SW3 | SW1 | 31.44% | 58.94% | 17.50 | 0.00 |
| E · SW3 | SW2 | 17.94% | 37.56% | 33.67 | 0.00 |
| E · SW3 | SW3 | 11.28% | 23.94% | 49.42 | 0.00 |

## 8. Rank-change examples

Positive rank change means the pure SW2/SW3 Sector level moved the stock upward against A in the complete common eligible ranking. Examples are largest rank moves only and were not selected by forward return.

| comparison | signal date | stock | SW1 | SW2 | SW3 | SW1 strength | SW2 strength | SW3 strength | Legacy RS | opp A | opp D | opp E | rank A | rank D | rank E | rank change |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D vs A | 2026-07-20 | 600006.SH | 汽车 | 商用车 | 商用载货车 | 21.97 | 70.89 | 70.48 | 79.30 | 56.37 | 75.93 | 75.77 | 724 | 211 | 254 | 513 |
| D vs A | 2026-07-20 | 600375.SH | 汽车 | 商用车 | 商用载货车 | 21.97 | 70.89 | 70.48 | 71.34 | 51.59 | 71.16 | 71.00 | 825 | 325 | 411 | 500 |
| D vs A | 2026-07-20 | 000951.SZ | 汽车 | 商用车 | 商用载货车 | 21.97 | 70.89 | 70.48 | 70.94 | 51.35 | 70.92 | 70.76 | 827 | 331 | 415 | 496 |
| D vs A | 2026-06-17 | 000672.SZ | 建筑材料 | 水泥 | 水泥制造 | 91.32 | 25.87 | 41.16 | 86.03 | 88.15 | 61.97 | 68.08 | 75 | 751 | 631 | -676 |
| D vs A | 2025-12-15 | 300518.SZ | 商贸零售 | 互联网电商 | 电商服务 | 69.83 | 17.93 | 23.01 | 85.08 | 78.98 | 58.22 | 60.25 | 72 | 639 | 605 | -567 |
| D vs A | 2025-12-15 | 300128.SZ | 电力设备 | 电池 | 锂电专用设备 | 50.73 | 7.42 | 7.66 | 87.38 | 72.72 | 55.40 | 55.50 | 193 | 704 | 704 | -511 |
| E vs A | 2026-07-20 | 000830.SZ | 基础化工 | 化学原料 | 煤化工 | 20.35 | 52.05 | 85.98 | 74.88 | 53.07 | 65.75 | 79.32 | 803 | 501 | 159 | 644 |
| E vs A | 2026-07-20 | 000990.SZ | 基础化工 | 化学原料 | 煤化工 | 20.35 | 52.05 | 85.98 | 81.73 | 57.18 | 69.86 | 83.43 | 701 | 357 | 90 | 611 |
| E vs A | 2026-05-12 | 002640.SZ | 商贸零售 | 互联网电商 | 跨境电商 | 18.77 | 43.92 | 66.31 | 92.80 | 63.19 | 73.25 | 82.20 | 751 | 505 | 175 | 576 |
| E vs A | 2026-06-17 | 000672.SZ | 建筑材料 | 水泥 | 水泥制造 | 91.32 | 25.87 | 41.16 | 86.03 | 88.15 | 61.97 | 68.08 | 75 | 751 | 631 | -556 |
| E vs A | 2026-05-12 | 002580.SZ | 电力设备 | 电池 | 蓄电池及其他电池 | 72.94 | 52.20 | 18.79 | 97.09 | 87.43 | 79.13 | 65.77 | 105 | 318 | 650 | -545 |
| E vs A | 2025-12-15 | 300518.SZ | 商贸零售 | 互联网电商 | 电商服务 | 69.83 | 17.93 | 23.01 | 85.08 | 78.98 | 58.22 | 60.25 | 72 | 639 | 605 | -533 |

## 9. Point-in-time limitation

The SW2021 membership store has available effective intervals but lacks complete historical exits. This is therefore an exploratory frozen random-12 result, not a long-horizon point-in-time proof of a preferred industry hierarchy.

## 10. Final decision

- T+10 mean excess A/D/E: 1.88% / 1.66% / 1.61%.
- T+10 median excess A/D/E: -0.57% / -0.91% / -0.85%.
- Any preferred result, including A, must meet the predeclared two-horizon excess, risk, and date-majority rule against its relevant pure-level rival; no model is preferred from a return-only comparison.
- Decision: `NO_STABLE_DIFFERENCE`. The Sector hierarchy study is now closed; this result does not change the formal Legacy strategy or authorize further hierarchy, weight, or N-threshold tuning.
