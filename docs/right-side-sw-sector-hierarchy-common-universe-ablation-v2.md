# Right-side SW Sector Hierarchy Common-Universe Ablation V2

**Final status: `SW1_ONLY_PREFERRED`**

## 1. Experiment contract

This is an exploratory frozen random-12 ablation. Wyckoff candidate pools, forward labels, Top150 size, VP, RiskBucket and every RS input/formula/benchmark/weight remain unchanged. Each group uses the same frozen Legacy SW1 `RSScore`; no SW2/SW3 RS is calculated or used.

The only tested variable is Sector composition, with no parameter scan: A = `SW1`; B = `0.70 × SW1 + 0.30 × SW2`; C = `0.60 × SW1 + 0.30 × SW2 + 0.10 × SW3`. For all groups `Opportunity = 0.40 × SectorScore + 0.60 × LegacyRSScore`.

All three Sector Strength calls retain their frozen V1.1 formula and a fixed `unique_members >= 8` gate. An undersized group is `INSUFFICIENT_MEMBERS`, never a zero score. Dates (12): 2025-12-15, 2025-12-18, 2026-01-30, 2026-02-26, 2026-03-10, 2026-03-26, 2026-04-13, 2026-05-12, 2026-05-21, 2026-06-17, 2026-07-20, 2026-08-10.

## 2. Common eligible universe coverage

`common sector eligible` means valid gated SW1/SW2/SW3 Sector Strength. `common eligible` additionally requires an already-required, unchanged Legacy RS score, so an RS data gap removes the row identically from A/B/C rather than changing any group’s candidate pool.

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

No date has fewer than 150 common rankable candidates.

## 3. SW1/SW2/SW3 member-count statistics

| level | mean industries/date | mean members | median | p25 | p75 | min | max | mean industries <8/date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SW1 | 31.0 | 188.99 | 136.00 | 93.00 | 176.00 | 31 | 634 | 0.00 |
| SW2 | 131.0 | 44.85 | 29.00 | 14.00 | 52.00 | 1 | 277 | 9.00 |
| SW3 | 338.0 | 17.42 | 11.00 | 6.00 | 21.00 | 1 | 145 | 111.25 |

Membership ambiguity is fail-closed rather than first-row resolved: mean ambiguous resolved membership symbols/date (SW1/SW2/SW3) = 23.50 / 39.50 / 52.00. Stable SW codes are the calculation keys; names are display-only.

## 4. A/B/C Top150 performance

| group | horizon | n | mean return | median return | mean excess | median excess | positive rate | mean MAE | mean MFE | equal-weight portfolio return | portfolio MDD | beat benchmark dates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A · SW1 | T+5 | 1793 | 1.56% | -0.11% | 1.00% | -0.86% | 49.19% | -6.97% | 9.90% | 1.55% | -3.25% | 7/12 |
| A · SW1 | T+10 | 1789 | 1.93% | -0.24% | 1.88% | -0.57% | 48.80% | -9.49% | 14.71% | 1.93% | -5.52% | 8/12 |
| A · SW1 | T+20 | 1783 | 5.22% | -1.03% | 4.48% | -2.44% | 47.45% | -12.91% | 23.76% | 5.19% | -8.84% | 6/12 |
| B · SW1+SW2 | T+5 | 1794 | 1.49% | -0.23% | 0.93% | -1.01% | 48.38% | -6.98% | 9.85% | 1.48% | -3.28% | 7/12 |
| B · SW1+SW2 | T+10 | 1790 | 1.87% | -0.37% | 1.82% | -0.85% | 48.16% | -9.51% | 14.67% | 1.87% | -5.44% | 8/12 |
| B · SW1+SW2 | T+20 | 1785 | 5.10% | -1.03% | 4.36% | -2.55% | 47.34% | -12.98% | 23.67% | 5.08% | -8.84% | 6/12 |
| C · SW1+SW2+SW3 | T+5 | 1795 | 1.50% | -0.20% | 0.94% | -1.00% | 48.64% | -6.96% | 9.85% | 1.49% | -3.24% | 7/12 |
| C · SW1+SW2+SW3 | T+10 | 1791 | 1.90% | -0.31% | 1.84% | -0.84% | 48.46% | -9.50% | 14.66% | 1.90% | -5.38% | 8/12 |
| C · SW1+SW2+SW3 | T+20 | 1786 | 5.01% | -0.90% | 4.28% | -2.47% | 47.70% | -12.98% | 23.52% | 5.00% | -8.77% | 6/12 |

## 5. Date-level comparison

Return wins/ties/losses compare same-date equal-weight portfolio terminal returns. Positive ΔMDD is healthier because it is closer to zero.

| comparison | horizon | matched dates | return wins/ties/losses | mean Δ return | median Δ return | healthier MDD dates | mean Δ MDD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B vs A | T+5 | 12 | 6/0/6 | -0.07% | -0.01% | 5/12 | -0.03% |
| B vs A | T+10 | 12 | 6/0/6 | -0.06% | 0.01% | 8/12 | 0.08% |
| B vs A | T+20 | 12 | 5/0/7 | -0.11% | -0.21% | 8/12 | -0.00% |
| C vs A | T+5 | 12 | 4/0/8 | -0.06% | -0.06% | 6/12 | 0.01% |
| C vs A | T+10 | 12 | 4/0/8 | -0.03% | -0.08% | 9/12 | 0.14% |
| C vs A | T+20 | 12 | 4/0/8 | -0.19% | -0.30% | 8/12 | 0.07% |
| C vs B | T+5 | 12 | 7/0/5 | 0.01% | 0.03% | 7/12 | 0.03% |
| C vs B | T+10 | 12 | 6/0/6 | 0.03% | -0.01% | 6/12 | 0.06% |
| C vs B | T+20 | 12 | 6/0/6 | -0.08% | -0.09% | 8/12 | 0.07% |

## 6. Top150 overlap

| comparison | mean overlap | mean replaced | mean Jaccard |
| --- | --- | --- | --- |
| A vs B | 137.75 | 12.25 | 84.95% |
| A vs C | 134.00 | 16.00 | 80.78% |
| B vs C | 144.92 | 5.08 | 93.46% |

| signal date | comparison | overlap | replaced | Jaccard |
| --- | --- | --- | --- | --- |
| 2025-12-15 | A vs B | 136 | 14 | 82.93% |
| 2025-12-18 | A vs B | 138 | 12 | 85.19% |
| 2026-01-30 | A vs B | 142 | 8 | 89.87% |
| 2026-02-26 | A vs B | 137 | 13 | 84.05% |
| 2026-03-10 | A vs B | 143 | 7 | 91.08% |
| 2026-03-26 | A vs B | 137 | 13 | 84.05% |
| 2026-04-13 | A vs B | 135 | 15 | 81.82% |
| 2026-05-12 | A vs B | 134 | 16 | 80.72% |
| 2026-05-21 | A vs B | 135 | 15 | 81.82% |
| 2026-06-17 | A vs B | 138 | 12 | 85.19% |
| 2026-07-20 | A vs B | 138 | 12 | 85.19% |
| 2026-08-10 | A vs B | 140 | 10 | 87.50% |
| 2025-12-15 | A vs C | 132 | 18 | 78.57% |
| 2025-12-18 | A vs C | 135 | 15 | 81.82% |
| 2026-01-30 | A vs C | 138 | 12 | 85.19% |
| 2026-02-26 | A vs C | 133 | 17 | 79.64% |
| 2026-03-10 | A vs C | 141 | 9 | 88.68% |
| 2026-03-26 | A vs C | 132 | 18 | 78.57% |
| 2026-04-13 | A vs C | 131 | 19 | 77.51% |
| 2026-05-12 | A vs C | 130 | 20 | 76.47% |
| 2026-05-21 | A vs C | 133 | 17 | 79.64% |
| 2026-06-17 | A vs C | 135 | 15 | 81.82% |
| 2026-07-20 | A vs C | 132 | 18 | 78.57% |
| 2026-08-10 | A vs C | 136 | 14 | 82.93% |
| 2025-12-15 | B vs C | 146 | 4 | 94.81% |
| 2025-12-18 | B vs C | 146 | 4 | 94.81% |
| 2026-01-30 | B vs C | 146 | 4 | 94.81% |
| 2026-02-26 | B vs C | 146 | 4 | 94.81% |
| 2026-03-10 | B vs C | 147 | 3 | 96.08% |
| 2026-03-26 | B vs C | 144 | 6 | 92.31% |
| 2026-04-13 | B vs C | 142 | 8 | 89.87% |
| 2026-05-12 | B vs C | 143 | 7 | 91.08% |
| 2026-05-21 | B vs C | 146 | 4 | 94.81% |
| 2026-06-17 | B vs C | 144 | 6 | 92.31% |
| 2026-07-20 | B vs C | 144 | 6 | 92.31% |
| 2026-08-10 | B vs C | 145 | 5 | 93.55% |

## 7. Industry concentration

Diagnostic only; concentration never changes membership or ordering. Values are random-12 daily means for each Top150.

| group | level | mean largest industry share | mean Top3 share | mean industry count | mean missing industries |
| --- | --- | --- | --- | --- | --- |
| A · SW1 | SW1 | 37.56% | 65.33% | 12.58 | 0.00 |
| A · SW1 | SW2 | 18.61% | 37.50% | 33.33 | 0.00 |
| A · SW1 | SW3 | 9.67% | 21.50% | 54.58 | 0.00 |
| B · SW1+SW2 | SW1 | 36.39% | 64.78% | 13.33 | 0.00 |
| B · SW1+SW2 | SW2 | 19.28% | 38.72% | 31.75 | 0.00 |
| B · SW1+SW2 | SW3 | 10.06% | 22.28% | 52.92 | 0.00 |
| C · SW1+SW2+SW3 | SW1 | 35.67% | 64.28% | 13.75 | 0.00 |
| C · SW1+SW2+SW3 | SW2 | 19.11% | 38.83% | 32.08 | 0.00 |
| C · SW1+SW2+SW3 | SW3 | 10.44% | 22.67% | 52.50 | 0.00 |

## 8. Rank-change examples

Positive rank change means the refined Sector composition moved the stock upward in the complete common eligible ranking. The three largest upward and downward moves are shown for each comparison; they are explanatory examples, not selected by forward return.

| comparison | signal date | stock | SW1 | SW2 | SW3 | SW1 strength | SW2 strength | SW3 strength | sector A | sector B | sector C | Legacy RS | opp A | opp B | opp C | rank A | rank B | rank C | rank change |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B vs A | 2026-07-20 | 000550.SZ | 汽车 | 商用车 | 商用载货车 | 21.97 | 70.89 | 70.48 | 21.97 | 36.64 | 41.50 | 86.99 | 60.98 | 66.85 | 68.79 | 596 | 422 | 379 | 174 |
| B vs A | 2026-07-20 | 000913.SZ | 汽车 | 摩托车及其他 | 摩托车 | 21.97 | 68.53 | 84.55 | 21.97 | 35.93 | 42.19 | 85.65 | 60.17 | 65.76 | 68.27 | 618 | 452 | 393 | 166 |
| B vs A | 2026-07-20 | 002761.SZ | 建筑装饰 | 房屋建设Ⅱ | 房屋建设Ⅲ | 29.12 | 74.03 | 75.66 | 29.12 | 42.59 | 47.25 | 82.41 | 61.09 | 66.48 | 68.35 | 591 | 437 | 391 | 154 |
| B vs A | 2026-06-17 | 000672.SZ | 建筑材料 | 水泥 | 水泥制造 | 91.32 | 25.87 | 41.16 | 91.32 | 71.68 | 66.67 | 86.03 | 88.15 | 80.29 | 78.29 | 75 | 300 | 354 | -225 |
| B vs A | 2025-12-15 | 688819.SH | 电力设备 | 电池 | 蓄电池及其他电池 | 50.73 | 7.42 | 48.00 | 50.73 | 37.74 | 37.47 | 80.90 | 68.84 | 63.64 | 63.53 | 298 | 497 | 501 | -199 |
| B vs A | 2025-12-15 | 300648.SZ | 电力设备 | 电池 | 锂电专用设备 | 50.73 | 7.42 | 7.66 | 50.73 | 37.74 | 33.43 | 80.38 | 68.52 | 63.33 | 61.60 | 308 | 503 | 548 | -195 |
| C vs B | 2026-07-20 | 000990.SZ | 基础化工 | 化学原料 | 煤化工 | 20.35 | 52.05 | 85.98 | 20.35 | 29.86 | 36.42 | 81.73 | 57.18 | 60.98 | 63.61 | 701 | 614 | 534 | 80 |
| C vs B | 2026-07-20 | 603766.SH | 汽车 | 摩托车及其他 | 摩托车 | 21.97 | 68.53 | 84.55 | 21.97 | 35.93 | 42.19 | 93.84 | 65.09 | 70.68 | 73.18 | 455 | 311 | 245 | 66 |
| C vs B | 2026-07-20 | 600746.SH | 基础化工 | 化学原料 | 煤化工 | 20.35 | 52.05 | 85.98 | 20.35 | 29.86 | 36.42 | 93.78 | 64.41 | 68.21 | 70.84 | 476 | 381 | 316 | 65 |
| C vs B | 2026-06-17 | 600596.SH | 基础化工 | 农化制品 | 农药 | 70.05 | 23.63 | 17.46 | 70.05 | 56.13 | 50.87 | 88.23 | 80.96 | 75.39 | 73.29 | 285 | 434 | 504 | -70 |
| C vs B | 2026-05-21 | 603800.SH | 机械设备 | 专用设备 | 能源及重型设备 | 79.92 | 45.04 | 26.24 | 79.92 | 69.45 | 64.09 | 82.33 | 81.36 | 77.18 | 75.03 | 223 | 309 | 373 | -64 |
| C vs B | 2026-05-12 | 603031.SH | 电力设备 | 电池 | 蓄电池及其他电池 | 72.94 | 52.20 | 18.79 | 72.94 | 66.72 | 61.30 | 89.62 | 82.95 | 80.46 | 78.30 | 218 | 261 | 324 | -63 |

## 9. Point-in-time limitation

The current SW2021 membership store is used through its available effective intervals, but it lacks a complete historical exit record. This report therefore answers only whether finer hierarchy adds information on the current frozen random-12 data and available memberships. It does not establish a long-horizon or point-in-time proof for any hierarchy.

## 10. Final decision

- T+10 mean excess A/B/C: 1.88% / 1.82% / 1.84%.
- T+10 median excess A/B/C: -0.57% / -0.85% / -0.84%.
- Support requires (without optimizing any parameter): at least two horizons with non-worse mean and median excess, at least two with non-worse MAE and portfolio MDD, and a positive date-level return majority on at least two horizons.
- Decision: `SW1_ONLY_PREFERRED`. This is a research conclusion only; it does not replace the current Legacy production strategy and does not authorize further weight or N-threshold tuning.
