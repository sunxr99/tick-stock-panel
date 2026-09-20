# SW hierarchy point-in-time and sparse-sample gate audit V1

## Pre-registered experiment gate

This audit precedes any 2023/2024 SW1/SW2/SW3 factor comparison. The research
rule is fixed in advance: an industry with fewer than eight unique members is
`insufficient_members`; it must not emit a research Sector Strength or
SectorRS result. This is a research gate only. It does not change the live
Legacy strategy, Opportunity weights, Wyckoff, VP, or RiskBucket.

The comparison may proceed only if the local SW membership store is a strict
point-in-time membership source: entry and exit intervals must support both
including constituents already present at each date and excluding constituents
which had left by that date.

## Membership-history gate: not passed

The refreshed `index_member_all` store contains 8,829 rows. All 8,829 have a
null `effective_to`; no historical exit interval was supplied. Every row also
has the same stored `membership_as_of` value (`2023-09-12`). The upstream pull
returned 8,829 `is_new=Y` rows and zero `is_new=N` rows.

`resolve_sw_history` filters `effective_from/effective_to`, so it can form an
"entered by date" view. With no exits, however, it cannot establish that a
2023/2024 constituent had not subsequently left or changed industry. Therefore
the current source fails the strict point-in-time gate for a 2023/2024 factor
claim. No performance comparison is produced from it.

## Frozen N=8 coverage audit

Counts below use unique members at six predeclared checkpoints. `lt8` is the
number of industry groups that would fail closed; `ge8` is eligible groups.

| date | level | groups | lt2 | lt5 | lt8 | ge8 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2023-01-03 | SW1 | 31 | 0 | 0 | 0 | 31 |
| 2023-01-03 | SW2 | 131 | 1 | 5 | 9 | 122 |
| 2023-01-03 | SW3 | 336 | 10 | 63 | 128 | 208 |
| 2023-06-30 | SW1 | 31 | 0 | 0 | 0 | 31 |
| 2023-06-30 | SW2 | 131 | 1 | 5 | 9 | 122 |
| 2023-06-30 | SW3 | 336 | 10 | 62 | 122 | 214 |
| 2023-12-29 | SW1 | 31 | 0 | 0 | 0 | 31 |
| 2023-12-29 | SW2 | 131 | 1 | 5 | 9 | 122 |
| 2023-12-29 | SW3 | 337 | 11 | 60 | 117 | 220 |
| 2024-01-02 | SW1 | 31 | 0 | 0 | 0 | 31 |
| 2024-01-02 | SW2 | 131 | 1 | 5 | 9 | 122 |
| 2024-01-02 | SW3 | 337 | 11 | 60 | 117 | 220 |
| 2024-06-28 | SW1 | 31 | 0 | 0 | 0 | 31 |
| 2024-06-28 | SW2 | 131 | 1 | 5 | 9 | 122 |
| 2024-06-28 | SW3 | 338 | 12 | 61 | 116 | 222 |
| 2024-12-31 | SW1 | 31 | 0 | 0 | 0 | 31 |
| 2024-12-31 | SW2 | 131 | 1 | 5 | 9 | 122 |
| 2024-12-31 | SW3 | 338 | 11 | 59 | 114 | 224 |

The N=8 gate would retain all SW1 groups, 122/131 SW2 groups, and only
208--224 SW3 groups. It is thus a meaningful sparse-sample control, not a
cosmetic filter.

## Decision

**Strict 2023/2024 hierarchy-factor validation is blocked by membership
history, not by a scoring result.** Do not use a current-membership proxy to
declare the factor reversed or repaired. Obtain a source with historical exits
or dated constituent snapshots, rerun this gate audit, then run the frozen
SW1/SW2/SW3 N=8 comparison without changing the threshold.
