# Right-Side Top150 VP D+1 Open to D+2 Close V1

## Frozen execution contract

D close selects the frozen Top150 and its existing VP RiskBucket. The equal-weight portfolio buys at each constituent's D+1 Open and sells at D+2 Close. This is a two-session, executable-price research return; no fees, slippage, limit-price, suspension, or liquidity execution model is included.

No Wyckoff, OpportunityScore, Top150 size, VP state, or risk bucket is recalculated. UNKNOWN is excluded from every formal group. The frozen benchmark labels use a different horizon, so this focused comparison reports raw portfolio returns rather than mismatched excess returns.

## Coverage

| signal date | entry D+1 | exit D+2 | Top150 | UNKNOWN |
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

## 12-date summary

| portfolio | dates | mean stocks | mean return | median date return | mean stock median | positive rate | loss rate | mean P25 | mean P75 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B0 ALL_KNOWN_TOP150 | 12 | 149.33 | 1.62% | 0.63% | 0.66% | 54.44% | 45.17% | -2.50% | 4.89% |
| B1 LOW | 12 | 31.17 | 1.68% | 1.78% | 1.19% | 58.94% | 40.57% | -1.59% | 4.54% |
| B2 MEDIUM | 12 | 41.25 | 1.64% | 0.75% | 0.31% | 51.64% | 47.88% | -2.31% | 4.35% |
| B3 HIGH | 12 | 36.75 | 1.36% | 1.50% | 0.44% | 54.41% | 45.37% | -2.85% | 4.40% |
| B4 EXTREME | 12 | 40.17 | 1.72% | 0.47% | 0.69% | 53.71% | 46.29% | -3.43% | 5.48% |

## Date-level returns

| signal date | entry D+1 | exit D+2 | B0 all | B1 LOW | B2 MEDIUM | B3 HIGH | B4 EXTREME |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-12-15 | 2025-12-16 | 2025-12-17 | -1.71% | -2.37% | -1.71% | -1.77% | -0.79% |
| 2025-12-18 | 2025-12-19 | 2025-12-22 | 1.85% | 2.83% | 1.93% | 1.74% | -2.48% |
| 2026-01-30 | 2026-02-02 | 2026-02-03 | 0.40% | 3.02% | -1.18% | 1.42% | -0.29% |
| 2026-02-26 | 2026-02-27 | 2026-03-02 | 2.35% | 4.50% | 4.84% | 1.83% | 1.69% |
| 2026-03-10 | 2026-03-11 | 2026-03-12 | -1.02% | -0.64% | -0.17% | -1.41% | -1.59% |
| 2026-03-26 | 2026-03-27 | 2026-03-30 | -0.19% | 0.21% | 0.91% | -1.97% | -1.91% |
| 2026-04-13 | 2026-04-14 | 2026-04-15 | 0.29% | 0.68% | -0.50% | 0.15% | 1.01% |
| 2026-05-12 | 2026-05-13 | 2026-05-14 | 4.21% | 1.99% | 5.17% | 3.24% | 4.54% |
| 2026-05-21 | 2026-05-22 | 2026-05-25 | 6.38% | 3.61% | 6.41% | 5.75% | 8.00% |
| 2026-06-17 | 2026-06-18 | 2026-06-22 | 5.66% | 4.42% | 3.21% | 5.20% | 8.49% |
| 2026-07-20 | 2026-07-21 | 2026-07-22 | 0.61% | 0.37% | 0.17% | 1.58% | 3.99% |
| 2026-08-10 | 2026-08-11 | 2026-08-12 | 0.66% | 1.57% | 0.60% | 0.54% | -0.07% |

## Relative to all known-risk Top150

| comparison | matched dates | group return wins | B0 wins | mean Δ return | median Δ return |
| --- | --- | --- | --- | --- | --- |
| B1 vs B0 | 12 | 7 | 5 | 0.06% | 0.39% |
| B2 vs B0 | 12 | 6 | 6 | 0.01% | 0.01% |
| B3 vs B0 | 12 | 2 | 10 | -0.27% | -0.26% |
| B4 vs B0 | 12 | 6 | 6 | 0.09% | -0.12% |

## Boundary

This is not a claim that any RiskBucket should receive trading priority. It is a fixed, two-session comparison on the existing random-12 sample only.