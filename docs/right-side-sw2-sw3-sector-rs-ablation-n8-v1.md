# Right-side SW2 + SW3 Sector/RS ablation V1

**Final status: `SW3_INCREMENT_NOT_SUPPORTED`**

## Frozen contract

The fixed random-12 dates and their frozen Wyckoff candidate pools, forward labels, VP fields and RiskBucket fields are reused unchanged. Only Opportunity ordering is compared: Legacy is the frozen SW1 Sector/RS score; V2 is `0.40 × (0.70 × SW2SectorStrength + 0.30 × SW3SectorStrength) + 0.60 × (0.40 × MarketRS + 0.40 × SW2RS + 0.20 × SW3RS)`. No weighting scan or refit was run.

Research-only sparse gate: industries with fewer than 8 members do not emit Sector Strength or SectorRS; full SW2 and SW3 availability is required.

Dates (12): 2025-12-15, 2025-12-18, 2026-01-30, 2026-02-26, 2026-03-10, 2026-03-26, 2026-04-13, 2026-05-12, 2026-05-21, 2026-06-17, 2026-07-20, 2026-08-10.

Candidate observations: 11328. V2 unavailable or fail-closed observations: 849; they are not silently assigned an industry or an undersized sector score. The V2 Top150 therefore uses available rows only.

## Top150 outcome metrics

| group | horizon | n | mean return | median return | mean excess | median excess | positive rate | mean MAE | mean MFE | mean portfolio MDD | beat benchmark dates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Legacy | T+5 | 1795 | 1.72% | 0.00% | 1.16% | -0.67% | 49.92% | -6.83% | 9.95% | -3.10% | 7/12 |
| Legacy | T+10 | 1791 | 2.00% | -0.14% | 1.95% | -0.45% | 49.36% | -9.28% | 14.74% | -5.31% | 8/12 |
| Legacy | T+20 | 1785 | 5.47% | -0.84% | 4.73% | -2.33% | 47.79% | -12.74% | 23.89% | -8.57% | 6/12 |
| SW2 only diagnostic | T+5 | 1793 | 1.43% | -0.19% | 0.87% | -1.05% | 48.69% | -6.98% | 9.86% | -3.09% | 7/12 |
| SW2 only diagnostic | T+10 | 1790 | 1.79% | -0.40% | 1.74% | -0.87% | 48.10% | -9.48% | 14.64% | -5.12% | 8/12 |
| SW2 only diagnostic | T+20 | 1784 | 4.73% | -1.15% | 4.00% | -2.52% | 47.65% | -12.94% | 23.39% | -8.55% | 6/12 |
| SW2+SW3 V2 | T+5 | 1793 | 1.50% | -0.17% | 0.94% | -0.99% | 49.02% | -7.00% | 9.95% | -3.08% | 7/12 |
| SW2+SW3 V2 | T+10 | 1790 | 1.93% | -0.39% | 1.88% | -0.88% | 48.16% | -9.52% | 14.80% | -5.12% | 9/12 |
| SW2+SW3 V2 | T+20 | 1784 | 4.62% | -1.03% | 3.89% | -2.45% | 47.42% | -12.96% | 23.48% | -8.61% | 6/12 |

`SW2 only diagnostic` is not a tuned alternative or production candidate. It holds the official 0.40/0.60 Opportunity split and compares an SW2-only hierarchy to answer whether the fixed SW3 increment adds evidence.

## Top150 industry concentration

| group | level | mean largest industry share | mean Top3 share | mean industry count | mean missing names |
| --- | --- | --- | --- | --- | --- |
| Legacy | SW2 | 18.22% | 36.39% | 34.08 | 0.00 |
| Legacy | SW3 | 9.39% | 20.72% | 59.33 | 0.00 |
| SW2 only diagnostic | SW2 | 18.17% | 36.72% | 33.92 | 0.00 |
| SW2 only diagnostic | SW3 | 8.89% | 20.89% | 58.17 | 0.00 |
| SW2+SW3 V2 | SW2 | 16.94% | 35.28% | 35.17 | 0.00 |
| SW2+SW3 V2 | SW3 | 8.61% | 20.28% | 57.08 | 0.00 |

## Date-level V2 versus Legacy

`V2 return wins / ties / losses` compares equal-weight portfolio terminal return on the same fixed signal dates. A positive MDD difference is healthier because it is closer to zero.

| horizon | matched dates | V2 return wins / ties / losses | mean Δ return | healthier V2 MDD dates | mean Δ MDD |
| --- | --- | --- | --- | --- | --- |
| T+5 | 12 | 6/0/6 | -0.22% | 6/12 | 0.01% |
| T+10 | 12 | 6/0/6 | -0.08% | 7/12 | 0.19% |
| T+20 | 12 | 3/0/9 | -0.83% | 4/12 | -0.03% |

## Required answers

- T+10 V2 vs Legacy mean return: 1.93% vs 2.00%.
- T+10 V2 vs Legacy median excess: -0.88% vs -0.45%.
- T+10 V2 vs Legacy mean portfolio MDD: -5.12% vs -5.31%.
- T+10 SW2+SW3 vs SW2-only diagnostic mean/median excess: 1.88%/-0.88% vs 1.74%/-0.87%.
- 1–2. No: V2 does not raise T+10 Top150 mean return or median excess versus Legacy; T+5/T+20 are also shown above, so a single horizon is not selected.
- 3. No mean improvement exists to attribute to a few right-tail names. The weaker V2 mean and median together instead indicate a broad lack of return improvement in this sample.
- 4. Mixed risk: V2's constituent MAE is slightly more negative at all reported horizons, while its equal-weight portfolio MDD is shallower. The MDD improvement does not offset weaker reward metrics.
- 5. No: V2 reduces both the largest-industry and Top3 shares at SW2 and SW3, while increasing the number of represented industries. Concentration is descriptive only and never changes selection.
- 6. SW3 has a small T+10 improvement over the SW2-only diagnostic, but both are weaker than Legacy. That is not sufficient evidence for an incremental production benefit.
- 7. SW2 remains the frozen research main level by design (70% Sector, 40% RS), but this result does not support promoting either SW2-only or SW2+SW3 over Legacy.
- 8. Yes: across 12 dates, SW3 has 338 industries on average; 9.75 have fewer than 2 members and 54.83 have fewer than 5 (maximum 55). This N=8 full-hierarchy run fail-closed 849 candidate observations, confirming that sparse coverage is material.
- 9. No: do not replace Legacy under this fixed sample and these frozen weights.
- 10. Yes, hierarchy resonance remains a display/research topic only; no resonance bonus or penalty is introduced by this result.

## Decision boundary

This report's status is `SW3_INCREMENT_NOT_SUPPORTED`. It does not replace the formal Legacy strategy. A promotion decision requires the stated evidence to hold in an independently refreshed fixed sample without changing any weight.
