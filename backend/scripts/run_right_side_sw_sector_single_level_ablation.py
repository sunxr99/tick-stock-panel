# ruff: noqa: RUF001  # Mathematical report notation intentionally uses multiplication signs.

"""Compare pure SW1, SW2, and SW3 Sector Strength on frozen random-12 data.

This is the final read-only Sector hierarchy experiment. It shares the prior
Common Eligible Universe, N=8 gate, fail-closed membership handling, frozen
Wyckoff pools, and frozen Legacy RSScore. Only the Sector input changes:
A = SW1, D = SW2, E = SW3.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import run_right_side_sw_sector_hierarchy_common_universe_ablation as base

from app.tickflow.repository import DataStore, KlineRepository

GROUPS = ("A · SW1", "D · SW2", "E · SW3")
SUFFIXES = ("a", "d", "e")


def _build_groups(frame: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Use exactly one valid Sector Strength level per same common universe."""
    common = frame.loc[frame["common_eligible"]].copy()
    for suffix, level in zip(SUFFIXES, base.LEVELS, strict=True):
        common[f"sector_score_{suffix}"] = pd.to_numeric(
            common[f"sw{level}_sector_score"], errors="coerce"
        )
        common[f"opportunity_{suffix}"] = (
            0.40 * common[f"sector_score_{suffix}"]
            + 0.60 * common["legacy_rs_score"]
        )
        ordered = common.sort_values(
            ["signal_date", f"opportunity_{suffix}", "symbol"],
            ascending=[True, False, True],
            kind="stable",
        )
        ranks = pd.Series(
            ordered.groupby("signal_date").cumcount().add(1).to_numpy(),
            index=ordered.index,
        )
        common[f"rank_{suffix}"] = ranks.reindex(common.index).astype(int)
    groups: dict[str, pd.DataFrame] = {}
    for name, suffix in zip(GROUPS, SUFFIXES, strict=True):
        groups[name] = pd.concat([
            day.sort_values(
                [f"opportunity_{suffix}", "symbol"],
                ascending=[False, True],
                kind="stable",
            ).head(base.TOP_N).copy()
            for _, day in common.groupby("signal_date", sort=True)
        ], ignore_index=True)
    return groups, common


def _pairwise_date_rows(portfolios: dict[str, pd.DataFrame]) -> list[list[object]]:
    rows: list[list[object]] = []
    for left, right, label in (
        (GROUPS[1], GROUPS[0], "D vs A"),
        (GROUPS[2], GROUPS[0], "E vs A"),
        (GROUPS[2], GROUPS[1], "E vs D"),
    ):
        for horizon in base.HORIZONS:
            compared = portfolios[left].query("horizon == @horizon").merge(
                portfolios[right].query("horizon == @horizon"),
                on="signal_date",
                suffixes=("_left", "_right"),
            )
            delta = compared["portfolio_return_left"] - compared["portfolio_return_right"]
            delta_mdd = compared["portfolio_mdd_left"] - compared["portfolio_mdd_right"]
            rows.append([
                label,
                f"T+{horizon}",
                len(compared),
                f"{int((delta > 0).sum())}/{int((delta == 0).sum())}/{int((delta < 0).sum())}",
                base._fmt(delta.mean(), percent=True),
                base._fmt(delta.median(), percent=True),
                f"{int((delta_mdd > 0).sum())}/{len(compared)}",
                base._fmt(delta_mdd.mean(), percent=True),
            ])
    return rows


def _overlap_rows(groups: dict[str, pd.DataFrame]) -> tuple[list[list[object]], list[list[object]]]:
    daily: list[list[object]] = []
    averages: list[list[object]] = []
    for left, right, label in (
        (GROUPS[0], GROUPS[1], "A vs D"),
        (GROUPS[0], GROUPS[2], "A vs E"),
        (GROUPS[1], GROUPS[2], "D vs E"),
    ):
        values: list[tuple[int, int, float]] = []
        for current in sorted(set(groups[left]["signal_date"]) & set(groups[right]["signal_date"])):
            left_symbols = set(groups[left].loc[groups[left]["signal_date"] == current, "symbol"])
            right_symbols = set(groups[right].loc[groups[right]["signal_date"] == current, "symbol"])
            overlap = len(left_symbols & right_symbols)
            replaced = len(left_symbols - right_symbols)
            union = len(left_symbols | right_symbols)
            jaccard = overlap / union if union else 0.0
            daily.append([current, label, overlap, replaced, base._fmt(jaccard, percent=True)])
            values.append((overlap, replaced, jaccard))
        averages.append([
            label,
            base._fmt(np.mean([item[0] for item in values])),
            base._fmt(np.mean([item[1] for item in values])),
            base._fmt(np.mean([item[2] for item in values]), percent=True),
        ])
    return daily, averages


def _rank_change_rows(
    common: pd.DataFrame,
    *,
    from_suffix: str,
    to_suffix: str,
    label: str,
) -> list[list[object]]:
    frame = common.copy()
    frame["rank_change"] = frame[f"rank_{from_suffix}"] - frame[f"rank_{to_suffix}"]
    selected = pd.concat([
        frame.sort_values(["rank_change", "symbol"], ascending=[False, True], kind="stable").head(3),
        frame.sort_values(["rank_change", "symbol"], ascending=[True, True], kind="stable").head(3),
    ])
    rows: list[list[object]] = []
    for _, row in selected.iterrows():
        rows.append([
            label,
            row["signal_date"],
            row["symbol"],
            row.get("sw1_name") or "—",
            row.get("sw2_name") or "—",
            row.get("sw3_name") or "—",
            base._fmt(row["sw1_sector_score"]),
            base._fmt(row["sw2_sector_score"]),
            base._fmt(row["sw3_sector_score"]),
            base._fmt(row["legacy_rs_score"]),
            base._fmt(row["opportunity_a"]),
            base._fmt(row["opportunity_d"]),
            base._fmt(row["opportunity_e"]),
            row["rank_a"],
            row["rank_d"],
            row["rank_e"],
            int(row["rank_change"]),
        ])
    return rows


def _preferred(
    groups: dict[str, pd.DataFrame],
    portfolios: dict[str, pd.DataFrame],
    candidate: str,
    baseline: str,
) -> bool:
    """Predeclared multi-horizon support rule; it performs no optimization."""
    excess_horizons = 0
    risk_horizons = 0
    date_majorities = 0
    for horizon in base.HORIZONS:
        candidate_metrics = base._stock_metrics(groups[candidate], horizon)
        baseline_metrics = base._stock_metrics(groups[baseline], horizon)
        if (
            candidate_metrics["mean_excess"] >= baseline_metrics["mean_excess"]
            and candidate_metrics["median_excess"] >= baseline_metrics["median_excess"]
        ):
            excess_horizons += 1
        candidate_paths = portfolios[candidate].query("horizon == @horizon")
        baseline_paths = portfolios[baseline].query("horizon == @horizon")
        if (
            candidate_metrics["mae"] >= baseline_metrics["mae"]
            and candidate_paths["portfolio_mdd"].mean() >= baseline_paths["portfolio_mdd"].mean()
        ):
            risk_horizons += 1
        compared = candidate_paths.merge(
            baseline_paths,
            on="signal_date",
            suffixes=("_candidate", "_baseline"),
        )
        delta = compared["portfolio_return_candidate"] - compared["portfolio_return_baseline"]
        if (delta > 0).sum() > (delta < 0).sum():
            date_majorities += 1
    return excess_horizons >= 2 and risk_horizons >= 2 and date_majorities >= 2


def _decision(
    groups: dict[str, pd.DataFrame],
    portfolios: dict[str, pd.DataFrame],
    expected_dates: int,
) -> tuple[str, list[str]]:
    if any(groups[name]["signal_date"].nunique() != expected_dates for name in GROUPS):
        return "INSUFFICIENT", ["At least one A/D/E Top150 series is missing a frozen signal date."]
    a_preferred = (
        _preferred(groups, portfolios, GROUPS[0], GROUPS[1])
        and _preferred(groups, portfolios, GROUPS[0], GROUPS[2])
    )
    d_preferred = _preferred(groups, portfolios, GROUPS[1], GROUPS[0])
    e_preferred = _preferred(groups, portfolios, GROUPS[2], GROUPS[0])
    t10 = {name: base._stock_metrics(groups[name], 10) for name in GROUPS}
    evidence = [
        "T+10 mean excess A/D/E: " + " / ".join(
            base._fmt(t10[name]["mean_excess"], percent=True) for name in GROUPS
        ) + ".",
        "T+10 median excess A/D/E: " + " / ".join(
            base._fmt(t10[name]["median_excess"], percent=True) for name in GROUPS
        ) + ".",
        "Any preferred result, including A, must meet the predeclared two-horizon excess, risk, and date-majority rule against its relevant pure-level rival; no model is preferred from a return-only comparison.",
    ]
    if a_preferred and not d_preferred and not e_preferred:
        return "SW1_ONLY_PREFERRED", evidence
    if d_preferred and not e_preferred:
        return "SW2_ONLY_PREFERRED", evidence
    if e_preferred and not d_preferred:
        return "SW3_ONLY_PREFERRED", evidence
    if d_preferred and e_preferred:
        return "NO_STABLE_DIFFERENCE", evidence
    return "NO_STABLE_DIFFERENCE", evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("../data/research/right_side_random12_frozen_20260913"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../docs/right-side-sw-sector-single-level-ablation-v3.md"),
    )
    args = parser.parse_args()
    data_dir, input_dir, output = args.data_dir.resolve(), args.input_dir.resolve(), args.output.resolve()
    source, signal_dates = base._load_snapshots(input_dir / "snapshots")
    repo = KlineRepository(DataStore(data_dir))
    prices = base._history(repo, data_dir, min(signal_dates))
    scores, distributions, membership_diagnostics = base._score_all(repo, data_dir, source, signal_dates)
    frame = source.merge(scores, on=["signal_date", "symbol"], how="left", validate="one_to_one")
    groups, common = _build_groups(frame)
    portfolios = base._portfolio_all(groups, prices, sorted(prices["date"].unique()))
    decision, evidence = _decision(groups, portfolios, len(signal_dates))
    overlap_daily, overlap_average = _overlap_rows(groups)
    below_top = [
        f"{current}: {int(day['common_eligible'].sum())}"
        for current, day in frame.groupby("signal_date", sort=True)
        if int(day["common_eligible"].sum()) < base.TOP_N
    ]
    rank_changes = (
        _rank_change_rows(common, from_suffix="a", to_suffix="d", label="D vs A")
        + _rank_change_rows(common, from_suffix="a", to_suffix="e", label="E vs A")
    )
    lines = [
        "# Right-side SW Sector Single-Level Ablation V3",
        "",
        f"**Final status: `{decision}`**",
        "",
        "## 1. Frozen contract",
        "",
        "This exploratory frozen random-12 ablation keeps the Wyckoff candidate pools, forward labels, Top150, VP, RiskBucket, and every RS formula/benchmark/weight unchanged. Each group reuses the frozen snapshot Legacy SW1 `RSScore`; no SW2/SW3 RS is calculated or used.",
        "",
        "Only SectorStrength level changes: A = `SW1`; D = `SW2`; E = `SW3`. Each group is `Opportunity = 0.40 × SectorScore + 0.60 × LegacyRSScore`. Sector Strength V1.1 and the `unique_members >= 8` gate are frozen. No fallback, zero-fill, dynamic weighting, or parameter scan is applied.",
        "",
        f"Dates ({len(signal_dates)}): " + ", ".join(item.isoformat() for item in signal_dates) + ".",
        "",
        "## 2. Common-universe coverage",
        "",
        "Main comparison uses only rows with valid, N>=8 SW1/SW2/SW3 SectorStrength and a valid frozen Legacy RS score. Thus A/D/E use exactly the same per-date candidate universe. `INSUFFICIENT_MEMBERS`, missing mapping, and ambiguous mapping remain fail-closed diagnostics, never zero scores.",
        "",
        base._markdown_table(
            ["signal date", "frozen candidates", "SW1 valid", "SW1 <8", "SW1 missing", "SW1 ambiguous", "SW1 coverage", "SW2 valid", "SW2 <8", "SW2 missing", "SW2 ambiguous", "SW2 coverage", "SW3 valid", "SW3 <8", "SW3 missing", "SW3 ambiguous", "SW3 coverage", "common sector", "common rankable", "common coverage"],
            base._coverage_rows(scores),
        ),
        "",
        ("No date has fewer than 150 common eligible stocks." if not below_top else "Dates below 150 common eligible stocks (all were used): " + "; ".join(below_top) + "."),
        "",
        "## 3. SW1/SW2/SW3 sample-size statistics",
        "",
        base._markdown_table(
            ["level", "mean industries/date", "mean members", "median", "p25", "p75", "min", "max", "mean industries <8/date"],
            base._member_rows(distributions),
        ),
        "",
        "Mean ambiguous resolved membership symbols/date (SW1/SW2/SW3) = " + " / ".join(
            base._fmt(np.mean([item[f"ambiguous_sw{level}"] for item in membership_diagnostics.values()]))
            for level in base.LEVELS
        ) + ". Stable SW codes are the calculation keys; ambiguity is fail-closed.",
        "",
        "## 4. A/D/E Top150 performance",
        "",
        base._markdown_table(
            ["group", "horizon", "n", "mean return", "median return", "mean excess", "median excess", "positive rate", "mean MAE", "mean MFE", "equal-weight portfolio return", "portfolio MDD", "beat benchmark dates"],
            base._summary_rows(groups, portfolios),
        ),
        "",
        "## 5. Date-level comparison",
        "",
        "Return wins/ties/losses compare same-date equal-weight terminal portfolio returns. Positive ΔMDD is healthier because it is closer to zero.",
        "",
        base._markdown_table(
            ["comparison", "horizon", "matched dates", "return wins/ties/losses", "mean Δ return", "median Δ return", "healthier MDD dates", "mean Δ MDD"],
            _pairwise_date_rows(portfolios),
        ),
        "",
        "## 6. Top150 overlap",
        "",
        base._markdown_table(["comparison", "mean overlap", "mean replaced", "mean Jaccard"], overlap_average),
        "",
        base._markdown_table(["signal date", "comparison", "overlap", "replaced", "Jaccard"], overlap_daily),
        "",
        "## 7. Industry concentration",
        "",
        "This is diagnostic only; sector concentration never changes selection. Values are random-12 daily means for each Top150.",
        "",
        base._markdown_table(
            ["group", "level", "mean largest industry share", "mean Top3 share", "mean industry count", "mean missing industries"],
            base._concentration_rows(groups),
        ),
        "",
        "## 8. Rank-change examples",
        "",
        "Positive rank change means the pure SW2/SW3 Sector level moved the stock upward against A in the complete common eligible ranking. Examples are largest rank moves only and were not selected by forward return.",
        "",
        base._markdown_table(
            ["comparison", "signal date", "stock", "SW1", "SW2", "SW3", "SW1 strength", "SW2 strength", "SW3 strength", "Legacy RS", "opp A", "opp D", "opp E", "rank A", "rank D", "rank E", "rank change"],
            rank_changes,
        ),
        "",
        "## 9. Point-in-time limitation",
        "",
        "The SW2021 membership store has available effective intervals but lacks complete historical exits. This is therefore an exploratory frozen random-12 result, not a long-horizon point-in-time proof of a preferred industry hierarchy.",
        "",
        "## 10. Final decision",
        "",
        *[f"- {item}" for item in evidence],
        f"- Decision: `{decision}`. The Sector hierarchy study is now closed; this result does not change the formal Legacy strategy or authorize further hierarchy, weight, or N-threshold tuning.",
        "",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
