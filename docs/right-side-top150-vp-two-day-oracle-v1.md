# Right-Side Top150 VP Two-Day Oracle Excursion V1

## Status: ORACLE_UPPER_BOUND

This is not a tradable backtest. Each return is calculated as `D+2 High / D+1 Low - 1`, which uses two prices unavailable at the time of entry and exit. It measures only the theoretical two-session low-to-high excursion after a frozen D-close Top150 and VP route.

No Wyckoff, OpportunityScore, Top150 size, VP state, or risk bucket is recalculated. HIGH and EXTREME remain routes, not filters or scores.

## Coverage

| signal date | D+1 low date | D+2 high date | Top150 | UNKNOWN |
| --- | --- | --- | --- | --- |
| 2025-12-15 | 2025-12-16 | 2025-12-17 | 150 | 1 |
| 2025-12-18 | 2025-12-19 | 2025-12-22 | 150 | 1 |
| 2026-01-30 | 2026-02-02 | 2026-02-03 | 150 | 0 |
| 2026-02-26 | 2026-02-27 | 2026-03-02 | 150 | 0 |
| 2026-03-10 | 2026-03-11 | 2026-03-12 | 150 | 1 |
| 2026-03-26 | 2026-03-27 | 2026-03-30 | 150 | 0 |
| 2026-04-13 | 2026-04-14 | 2026-04-15 | 150 | 0 |
| 2026-05-12 | 2026-05-13 | 2026-05-14 | 150 | 2 |
| 2026-05-21 | 2026-05-22 | 2026-05-25 | 150 | 2 |
| 2026-06-17 | 2026-06-18 | 2026-06-22 | 150 | 0 |
| 2026-07-20 | 2026-07-21 | 2026-07-22 | 150 | 0 |
| 2026-08-10 | 2026-08-11 | 2026-08-12 | 150 | 0 |

## 12-date theoretical space

| portfolio | dates | mean stocks | mean oracle return | median oracle return | mean stock median | positive rate | mean P25 | mean P75 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B0 ALL_KNOWN_TOP150 | 12 | 149.33 | 8.02% | 6.98% | 6.44% | 97.32% | 3.86% | 10.77% |
| B1 LOW | 12 | 31.17 | 7.73% | 7.30% | 6.19% | 98.70% | 4.13% | 9.76% |
| B2 HIGH | 12 | 36.75 | 8.05% | 7.27% | 6.87% | 97.53% | 4.05% | 10.31% |
| B3 EXTREME | 12 | 40.17 | 8.86% | 7.73% | 7.07% | 94.34% | 4.23% | 12.00% |
| B4 HIGH+EXTREME | 12 | 76.92 | 8.38% | 7.19% | 7.04% | 95.89% | 4.01% | 11.06% |

## Date-level theoretical space

| signal date | D+1 low date | D+2 high date | B0 | B1 LOW | B2 HIGH | B3 EXTREME | B4 HIGH+EXTREME |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-12-15 | 2025-12-16 | 2025-12-17 | 6.10% | 5.80% | 6.91% | 6.79% | 6.85% |
| 2025-12-18 | 2025-12-19 | 2025-12-22 | 7.51% | 7.48% | 8.39% | 6.06% | 7.53% |
| 2026-01-30 | 2026-02-02 | 2026-02-03 | 6.83% | 9.04% | 7.90% | 5.84% | 6.64% |
| 2026-02-26 | 2026-02-27 | 2026-03-02 | 8.74% | 9.73% | 7.62% | 9.14% | 8.49% |
| 2026-03-10 | 2026-03-11 | 2026-03-12 | 6.14% | 5.81% | 5.89% | 6.90% | 6.32% |
| 2026-03-26 | 2026-03-27 | 2026-03-30 | 5.97% | 5.89% | 5.85% | 7.15% | 6.39% |
| 2026-04-13 | 2026-04-14 | 2026-04-15 | 7.13% | 7.13% | 6.82% | 8.31% | 7.60% |
| 2026-05-12 | 2026-05-13 | 2026-05-14 | 11.64% | 9.25% | 11.15% | 12.06% | 11.83% |
| 2026-05-21 | 2026-05-22 | 2026-05-25 | 12.82% | 10.35% | 12.32% | 14.29% | 13.24% |
| 2026-06-17 | 2026-06-18 | 2026-06-22 | 11.47% | 10.28% | 11.34% | 13.33% | 12.44% |
| 2026-07-20 | 2026-07-21 | 2026-07-22 | 5.48% | 5.29% | 5.95% | 9.69% | 6.75% |
| 2026-08-10 | 2026-08-11 | 2026-08-12 | 6.45% | 6.66% | 6.41% | 6.72% | 6.51% |

## Relative to all known-risk Top150

| comparison | matched dates | group larger space | B0 larger space | mean Δ oracle space | median Δ oracle space |
| --- | --- | --- | --- | --- | --- |
| B1 vs B0 | 12 | 4 | 8 | -0.30% | -0.14% |
| B2 vs B0 | 12 | 4 | 8 | 0.02% | -0.13% |
| B3 vs B0 | 12 | 10 | 2 | 0.83% | 0.73% |
| B4 vs B0 | 12 | 10 | 2 | 0.36% | 0.30% |

## Interpretation boundary

A larger oracle excursion does not justify a buy-low/sell-high strategy. The next research step, if authorized, must freeze an observable entry and exit rule before running it; it must not select or tune that rule from this table.