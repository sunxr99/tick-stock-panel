# Right-Side Top150 VP Next-Day Intraday Research V1

## Frozen execution contract

Uses the completed random-12 Top150 snapshots without rerunning Wyckoff, Sector/RS, VP, or changing RiskBucket. D close determines the risk route; D+1 Open buys an equal-weight group; D+1 Close sells. `HIGH` and `EXTREME` are never filtered or re-ranked.

D+1 High is **not** an executable exit price. It is reported only as constituent MFE. Portfolio MFE/MAE use synchronized 1-minute close NAV, because different stocks peak at different minutes. No fees, slippage, limit-up/down execution, or intraday liquidity model is included; this is a descriptive path study, not a tradable strategy.

## Coverage

| signal date | entry date | Top150 | UNKNOWN | minute partition |
| --- | --- | --- | --- | --- |
| 2025-12-15 | 2025-12-16 | 150 | 1 | present |
| 2025-12-18 | 2025-12-19 | 150 | 1 | present |
| 2026-01-30 | 2026-02-02 | 150 | 0 | present |
| 2026-02-26 | 2026-02-27 | 150 | 0 | present |
| 2026-03-10 | 2026-03-11 | 150 | 1 | present |
| 2026-03-26 | 2026-03-27 | 150 | 0 | present |
| 2026-04-13 | 2026-04-14 | 150 | 0 | present |
| 2026-05-12 | 2026-05-13 | 150 | 2 | present |
| 2026-05-21 | 2026-05-22 | 150 | 2 | present |
| 2026-06-17 | 2026-06-18 | 150 | 0 | present |
| 2026-07-20 | 2026-07-21 | 150 | 0 | present |
| 2026-08-10 | 2026-08-11 | 150 | 0 | present |

## 12-date summary

| portfolio | dates | mean stocks | mean close return | median close return | mean excess | median excess | positive close | mean close-path MFE | mean close-path MAE | mean high-to-close pullback | mean constituent high MFE | mean constituent low MAE | positive MFE rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B0 ALL_KNOWN_TOP150 | 12 | 149.33 | 1.03% | 1.21% | 0.74% | 0.35% | 66.67% | 1.80% | -0.77% | -0.77% | 4.33% | -2.87% | 95.09% |
| B2 HIGH | 12 | 36.75 | 1.04% | 1.45% | 0.76% | 0.70% | 66.67% | 1.98% | -0.89% | -0.93% | 4.56% | -2.97% | 95.73% |
| B3 EXTREME | 12 | 40.17 | 1.24% | 0.77% | 0.95% | 0.25% | 58.33% | 2.00% | -1.05% | -0.75% | 4.71% | -3.32% | 91.44% |
| B4 HIGH+EXTREME | 12 | 76.92 | 1.13% | 1.06% | 0.85% | 0.51% | 66.67% | 1.90% | -0.75% | -0.76% | 4.57% | -3.08% | 93.37% |

## Date-level results

| signal date | entry date | B0 close | B2 HIGH close | B3 EXTREME close | B4 close | HIGH high MFE | EXTREME high MFE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-12-15 | 2025-12-16 | -1.39% | -1.33% | 0.61% | -0.30% | 3.88% | 4.49% |
| 2025-12-18 | 2025-12-19 | 1.60% | 2.22% | -0.15% | 1.34% | 5.51% | 5.65% |
| 2026-01-30 | 2026-02-02 | -2.63% | -2.66% | -2.21% | -2.39% | 3.86% | 2.80% |
| 2026-02-26 | 2026-02-27 | 2.55% | 1.98% | 2.14% | 2.08% | 4.50% | 4.21% |
| 2026-03-10 | 2026-03-11 | 0.38% | 0.92% | -0.07% | 0.50% | 4.53% | 4.04% |
| 2026-03-26 | 2026-03-27 | 1.35% | 2.32% | -0.21% | 1.27% | 5.61% | 3.90% |
| 2026-04-13 | 2026-04-14 | 1.06% | 0.77% | 0.94% | 0.86% | 3.64% | 3.62% |
| 2026-05-12 | 2026-05-13 | 5.16% | 5.37% | 5.17% | 5.22% | 7.54% | 7.37% |
| 2026-05-21 | 2026-05-22 | 3.14% | 2.52% | 4.42% | 3.41% | 4.97% | 6.04% |
| 2026-06-17 | 2026-06-18 | 2.54% | 2.95% | 3.99% | 3.53% | 5.90% | 6.66% |
| 2026-07-20 | 2026-07-21 | -0.72% | -1.36% | 1.43% | -0.76% | 1.96% | 4.07% |
| 2026-08-10 | 2026-08-11 | -0.71% | -1.17% | -1.21% | -1.18% | 2.82% | 3.68% |

## Relative to all known-risk Top150

For MAE, a positive delta is healthier because it is closer to zero.

| comparison | metric | matched dates | group better | B0 better | mean Δ | median Δ |
| --- | --- | --- | --- | --- | --- | --- |
| B2 vs B0 | close return | 12 | 6 | 6 | 0.01% | 0.01% |
| B2 vs B0 | close-path MAE | 12 | 2 | 6 | -0.11% | -0.02% |
| B2 vs B0 | constituent high MFE | 12 | 7 | 5 | 0.23% | 0.27% |
| B3 vs B0 | close return | 12 | 6 | 6 | 0.21% | -0.06% |
| B3 vs B0 | close-path MAE | 12 | 3 | 6 | -0.27% | -0.13% |
| B3 vs B0 | constituent high MFE | 12 | 7 | 5 | 0.38% | 0.13% |
| B4 vs B0 | close return | 12 | 6 | 6 | 0.10% | 0.01% |
| B4 vs B0 | close-path MAE | 12 | 5 | 3 | 0.03% | 0.00% |
| B4 vs B0 | constituent high MFE | 12 | 8 | 4 | 0.24% | 0.13% |

## Interpretation boundary

This report can establish whether HIGH/EXTREME have more next-day upward excursion and whether that excursion survives to the close. It cannot claim that a trader can sell at the daily high. A real intraday exit test requires a pre-declared executable sell rule, which is intentionally outside this frozen experiment.