# ruff: noqa: RUF001  # Mathematical report notation intentionally uses multiplication signs.

"""Compare frozen Legacy Opportunity with the fixed SW2+SW3 V2 composition.

This is a read-only research runner.  It reuses the frozen random-12 Wyckoff
candidate pools and forward labels, rebuilds only the in-memory daily-return
history required by the existing Sector Strength / RS engines, and never
recalculates Wyckoff, VP, RiskBucket, or any score weight.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from app.parquet import scan_enriched_parquet
from app.services.right_side_candidates import industry_concentration
from app.services.sector_membership import resolve_sw_history
from app.services.wyckoff_candidate_ranking import rank_wyckoff_candidates
from app.tickflow.repository import DataStore, KlineRepository

HORIZONS = (5, 10, 20)
TOP_N = 150
_SCORE_COLUMNS = (
    "symbol", "opportunity_score_v2", "opportunity_score_basis",
    "sw2_sector_score", "market_rs", "sw2_rs", "sw2_available",
    "sw1_name", "sw2_name", "sw3_name",
)


def _markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *["| " + " | ".join(str(value) for value in row) + " |" for row in rows],
    ])


def _fmt(value: object, *, percent: bool = False) -> str:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return "—"
    return f"{float(value) * 100:.2f}%" if percent else f"{float(value):.2f}"


def _history(repo: KlineRepository, data_dir: Path, earliest_signal: date) -> pd.DataFrame:
    """Build the minimal, point-in-time local history consumed by Sector/RS.

    The production cache intentionally covers only its recent UI lookback.  A
    frozen historical study needs more than 60 sessions before its first
    signal, so this runner creates a private in-memory cache from unchanged
    local enriched parquet files.  ``change_pct`` retains the production
    close-to-close formula.
    """
    start = earliest_signal - timedelta(days=210)
    raw = (
        scan_enriched_parquet(str(data_dir / "kline_daily_enriched" / "**" / "*.parquet"))
        .filter(pl.col("date") >= start)
        .select("symbol", "date", "open", "close")
        .sort(["symbol", "date"])
        .collect()
    )
    history = raw.with_columns(
        (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("change_pct")
    ).select("symbol", "date", "change_pct")
    repo._enriched_history_cache = history
    repo._enriched_history_start = history.get_column("date").min()
    repo._enriched_history_generation = repo.get_matrix_data_generation("stock")
    prices = raw.to_pandas()
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    return prices


def _load_snapshots(snapshot_dir: Path) -> tuple[pd.DataFrame, list[date]]:
    frames = [pl.read_parquet(path).to_pandas() for path in sorted(snapshot_dir.glob("*.parquet"))]
    if not frames:
        raise RuntimeError(f"no frozen snapshots in {snapshot_dir}")
    frame = pd.concat(frames, ignore_index=True)
    frame["symbol"] = frame["symbol"].astype(str)
    frame["signal_date"] = pd.to_datetime(frame["signal_date"]).dt.date
    dates = sorted(frame["signal_date"].unique())
    return frame, dates


def _score_v2(
    repo: KlineRepository,
    source: pd.DataFrame,
    signal_dates: list[date],
    *,
    min_industry_members: int,
    require_full_v2_levels: bool,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for current in signal_dates:
        symbols = source.loc[source["signal_date"] == current, "symbol"].tolist()
        ranked = rank_wyckoff_candidates(
            repo,
            as_of=current,
            candidates=[{"symbol": symbol} for symbol in symbols],
            _min_industry_members=min_industry_members,
            _require_full_v2_levels=require_full_v2_levels,
        )
        for item in ranked:
            rows.append({"signal_date": current, **{key: item.get(key) for key in _SCORE_COLUMNS}})
        print(f"{current}: candidates={len(symbols)} v2_available={sum(item.get('opportunity_score_v2') is not None for item in ranked)}", flush=True)
    return pd.DataFrame(rows)


def _top(frame: pd.DataFrame, score_column: str) -> pd.DataFrame:
    return frame.dropna(subset=[score_column]).sort_values(
        [score_column, "symbol"], ascending=[False, True], kind="stable"
    ).head(TOP_N).copy()


def _select_groups(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    base = frame.copy()
    base["legacy_score"] = 0.40 * pd.to_numeric(base["sector_score"], errors="coerce") + 0.60 * pd.to_numeric(base["rs_score"], errors="coerce")
    base["sw2_only_score"] = base["legacy_score"]
    usable_sw2 = base["sw2_available"].fillna(False) & base[["sw2_sector_score", "market_rs", "sw2_rs"]].notna().all(axis=1)
    base.loc[usable_sw2, "sw2_only_score"] = (
        0.40 * base.loc[usable_sw2, "sw2_sector_score"]
        + 0.60 * (
            0.50 * base.loc[usable_sw2, "market_rs"]
            + 0.50 * base.loc[usable_sw2, "sw2_rs"]
        )
    )
    groups: dict[str, list[pd.DataFrame]] = {"Legacy": [], "SW2 only diagnostic": [], "SW2+SW3 V2": []}
    for _current, day in base.groupby("signal_date", sort=True):
        groups["Legacy"].append(_top(day, "legacy_score"))
        groups["SW2 only diagnostic"].append(_top(day, "sw2_only_score"))
        groups["SW2+SW3 V2"].append(_top(day, "opportunity_score_v2"))
    return {name: pd.concat(parts, ignore_index=True) for name, parts in groups.items()}


def _stock_metrics(frame: pd.DataFrame, horizon: int) -> dict[str, float | int | None]:
    needed = [f"return_{horizon}d", f"excess_return_{horizon}d", f"mae_{horizon}d", f"mfe_{horizon}d"]
    part = frame.dropna(subset=needed)
    returns = pd.to_numeric(part[f"return_{horizon}d"], errors="coerce")
    excess = pd.to_numeric(part[f"excess_return_{horizon}d"], errors="coerce")
    return {
        "n": len(part),
        "mean_return": returns.mean() if len(part) else None,
        "median_return": returns.median() if len(part) else None,
        "mean_excess": excess.mean() if len(part) else None,
        "median_excess": excess.median() if len(part) else None,
        "positive_rate": (returns > 0).mean() if len(part) else None,
        "mae": pd.to_numeric(part[f"mae_{horizon}d"], errors="coerce").mean() if len(part) else None,
        "mfe": pd.to_numeric(part[f"mfe_{horizon}d"], errors="coerce").mean() if len(part) else None,
    }


def _mdd(nav: pd.Series) -> float:
    values = pd.concat([pd.Series([1.0]), nav.reset_index(drop=True)], ignore_index=True)
    return float((values / values.cummax() - 1.0).min())


def _portfolio_metrics(group: pd.DataFrame, prices: pd.DataFrame, dates: list[date], horizon: int) -> pd.DataFrame:
    index = {value: position for position, value in enumerate(dates)}
    results: list[dict[str, object]] = []
    for signal_date, selected in group.groupby("signal_date", sort=True):
        position = index[signal_date]
        path_dates = dates[position + 1:position + 1 + horizon]
        if len(path_dates) != horizon:
            continue
        price_rows = prices.loc[
            prices["symbol"].isin(selected["symbol"]) & prices["date"].isin(path_dates),
            ["symbol", "date", "open", "close"],
        ]
        closes = price_rows.pivot(index="date", columns="symbol", values="close").reindex(path_dates)
        opens = price_rows.loc[price_rows["date"] == path_dates[0]].set_index("symbol")["open"]
        symbols = [
            symbol for symbol in selected["symbol"]
            if symbol in closes.columns and symbol in opens.index and pd.notna(opens.loc[symbol])
            and float(opens.loc[symbol]) > 0 and closes[symbol].notna().all() and (closes[symbol] > 0).all()
        ]
        if not symbols:
            continue
        nav = closes[symbols].astype(float).div(opens.loc[symbols].astype(float), axis="columns").mean(axis=1)
        benchmark = pd.to_numeric(selected[f"benchmark_return_{horizon}d"], errors="coerce").dropna()
        terminal = float(nav.iloc[-1] - 1.0)
        benchmark_return = float(benchmark.iloc[0]) if not benchmark.empty else None
        results.append({
            "signal_date": signal_date, "horizon": horizon, "count": len(symbols),
            "portfolio_return": terminal, "portfolio_excess": terminal - benchmark_return if benchmark_return is not None else None,
            "portfolio_mdd": _mdd(nav),
        })
    return pd.DataFrame(results)


def _summary_rows(groups: dict[str, pd.DataFrame], portfolio: dict[str, pd.DataFrame]) -> list[list[object]]:
    rows: list[list[object]] = []
    for name, group in groups.items():
        for horizon in HORIZONS:
            stock = _stock_metrics(group, horizon)
            paths = portfolio[name].loc[portfolio[name]["horizon"] == horizon]
            rows.append([
                name, f"T+{horizon}", stock["n"], _fmt(stock["mean_return"], percent=True), _fmt(stock["median_return"], percent=True),
                _fmt(stock["mean_excess"], percent=True), _fmt(stock["median_excess"], percent=True), _fmt(stock["positive_rate"], percent=True),
                _fmt(stock["mae"], percent=True), _fmt(stock["mfe"], percent=True),
                _fmt(paths["portfolio_mdd"].mean() if not paths.empty else None, percent=True),
                f"{int((paths['portfolio_excess'] > 0).sum())}/{len(paths)}" if not paths.empty else "—",
            ])
    return rows


def _concentration_rows(groups: dict[str, pd.DataFrame]) -> list[list[object]]:
    rows: list[list[object]] = []
    for name, group in groups.items():
        days = [industry_concentration(day.to_dict("records")) for _, day in group.groupby("signal_date", sort=True)]
        for level in ("sw2", "sw3"):
            rows.append([
                name, level.upper(), _fmt(np.mean([item[level]["largest_share"] for item in days]), percent=True),
                _fmt(np.mean([item[level]["top3_share"] for item in days]), percent=True),
                _fmt(np.mean([item[level]["industry_count"] for item in days])),
                _fmt(np.mean([item[level]["missing"] for item in days])),
            ])
    return rows


def _date_comparison_rows(portfolio: dict[str, pd.DataFrame]) -> list[list[object]]:
    rows: list[list[object]] = []
    legacy = portfolio["Legacy"]
    v2 = portfolio["SW2+SW3 V2"]
    for horizon in HORIZONS:
        compared = legacy.loc[legacy["horizon"] == horizon].merge(
            v2.loc[v2["horizon"] == horizon], on="signal_date", suffixes=("_legacy", "_v2")
        )
        difference = compared["portfolio_return_v2"] - compared["portfolio_return_legacy"]
        mdd_difference = compared["portfolio_mdd_v2"] - compared["portfolio_mdd_legacy"]
        rows.append([
            f"T+{horizon}", len(compared),
            f"{int((difference > 0).sum())}/{int((difference == 0).sum())}/{int((difference < 0).sum())}",
            _fmt(difference.mean(), percent=True),
            f"{int((mdd_difference > 0).sum())}/{len(compared)}",
            _fmt(mdd_difference.mean(), percent=True),
        ])
    return rows


def _sw3_sample_diagnostics(data_dir: Path, signal_dates: list[date]) -> dict[str, float]:
    counts: list[pl.DataFrame] = []
    for current in signal_dates:
        resolved = resolve_sw_history(data_dir, as_of=current)
        if resolved is None:
            continue
        counts.append(resolved.frame.group_by("sw3_name").agg(pl.col("_sym_up").n_unique().alias("members")))
    if not counts:
        return {"dates": 0.0, "industries": 0.0, "lt2": 0.0, "lt5": 0.0, "max_lt5": 0.0}
    return {
        "dates": float(len(counts)),
        "industries": float(np.mean([frame.height for frame in counts])),
        "lt2": float(np.mean([frame.filter(pl.col("members") < 2).height for frame in counts])),
        "lt5": float(np.mean([frame.filter(pl.col("members") < 5).height for frame in counts])),
        "max_lt5": float(max(frame.filter(pl.col("members") < 5).height for frame in counts)),
    }


def _status(groups: dict[str, pd.DataFrame], portfolios: dict[str, pd.DataFrame], expected_dates: int) -> tuple[str, list[str]]:
    v2_dates = groups["SW2+SW3 V2"]["signal_date"].nunique()
    if v2_dates != expected_dates:
        return "INSUFFICIENT", [f"V2 only produced Top150 on {v2_dates}/{expected_dates} fixed dates."]
    legacy, sw2, v2 = (groups[name] for name in ("Legacy", "SW2 only diagnostic", "SW2+SW3 V2"))
    a, c, b = (_stock_metrics(frame, 10) for frame in (legacy, sw2, v2))
    a_path = portfolios["Legacy"].query("horizon == 10")["portfolio_mdd"].mean()
    b_path = portfolios["SW2+SW3 V2"].query("horizon == 10")["portfolio_mdd"].mean()
    b_improves_legacy = bool(
        b["mean_return"] >= a["mean_return"] and b["median_excess"] >= a["median_excess"]
        and b["mae"] >= a["mae"] and b_path >= a_path
    )
    sw3_increment = bool(b["mean_excess"] > c["mean_excess"] and b["median_excess"] >= c["median_excess"])
    evidence = [
        f"T+10 V2 vs Legacy mean return: {_fmt(b['mean_return'], percent=True)} vs {_fmt(a['mean_return'], percent=True)}.",
        f"T+10 V2 vs Legacy median excess: {_fmt(b['median_excess'], percent=True)} vs {_fmt(a['median_excess'], percent=True)}.",
        f"T+10 V2 vs Legacy mean portfolio MDD: {_fmt(b_path, percent=True)} vs {_fmt(a_path, percent=True)}.",
        f"T+10 SW2+SW3 vs SW2-only diagnostic mean/median excess: {_fmt(b['mean_excess'], percent=True)}/{_fmt(b['median_excess'], percent=True)} vs {_fmt(c['mean_excess'], percent=True)}/{_fmt(c['median_excess'], percent=True)}.",
    ]
    if b_improves_legacy and sw3_increment:
        return "SW2_SW3_V2_SUPPORTED", evidence
    if b_improves_legacy:
        return "SW2_ONLY_PREFERRED", evidence
    return "SW3_INCREMENT_NOT_SUPPORTED", evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--input-dir", type=Path, default=Path("../data/research/right_side_random12_frozen_20260913"))
    parser.add_argument("--output", type=Path, default=Path("../docs/right-side-sw2-sw3-sector-rs-ablation-v1.md"))
    parser.add_argument("--min-industry-members", type=int, default=0)
    parser.add_argument("--require-full-v2-levels", action="store_true")
    args = parser.parse_args()
    if args.min_industry_members < 0:
        raise SystemExit("--min-industry-members must be non-negative")
    data_dir, input_dir, output = args.data_dir.resolve(), args.input_dir.resolve(), args.output.resolve()
    source, signal_dates = _load_snapshots(input_dir / "snapshots")
    repo = KlineRepository(DataStore(data_dir))
    prices = _history(repo, data_dir, min(signal_dates))
    scores = _score_v2(
        repo,
        source,
        signal_dates,
        min_industry_members=args.min_industry_members,
        require_full_v2_levels=args.require_full_v2_levels,
    )
    frame = source.merge(scores, on=["signal_date", "symbol"], how="left", validate="one_to_one")
    groups = _select_groups(frame)
    trading_dates = sorted(prices["date"].unique())
    portfolio = {name: _portfolio_metrics(group, prices, trading_dates, horizon=5) for name, group in groups.items()}
    for name, group in groups.items():
        portfolio[name] = pd.concat([
            portfolio[name], _portfolio_metrics(group, prices, trading_dates, horizon=10), _portfolio_metrics(group, prices, trading_dates, horizon=20),
        ], ignore_index=True)
    status, evidence = _status(groups, portfolio, len(signal_dates))
    sw3_sample = _sw3_sample_diagnostics(data_dir, signal_dates)
    missing = frame["opportunity_score_v2"].isna()
    lines = [
        "# Right-side SW2 + SW3 Sector/RS ablation V1", "",
        f"**Final status: `{status}`**", "",
        "## Frozen contract", "",
        "The fixed random-12 dates and their frozen Wyckoff candidate pools, forward labels, VP fields and RiskBucket fields are reused unchanged. Only Opportunity ordering is compared: Legacy is the frozen SW1 Sector/RS score; V2 is `0.40 × (0.70 × SW2SectorStrength + 0.30 × SW3SectorStrength) + 0.60 × (0.40 × MarketRS + 0.40 × SW2RS + 0.20 × SW3RS)`. No weighting scan or refit was run.", "",
        (
            f"Research-only sparse gate: industries with fewer than {args.min_industry_members} members do not emit Sector Strength or SectorRS; full SW2 and SW3 availability is required."
            if args.require_full_v2_levels else "No sparse-sample gate was enabled for this run."
        ), "",
        f"Dates ({len(signal_dates)}): " + ", ".join(value.isoformat() for value in signal_dates) + ".", "",
        f"Candidate observations: {len(frame)}. V2 unavailable or fail-closed observations: {int(missing.sum())}; they are not silently assigned an industry or an undersized sector score. The V2 Top150 therefore uses available rows only.", "",
        "## Top150 outcome metrics", "",
        _markdown_table(["group", "horizon", "n", "mean return", "median return", "mean excess", "median excess", "positive rate", "mean MAE", "mean MFE", "mean portfolio MDD", "beat benchmark dates"], _summary_rows(groups, portfolio)), "",
        "`SW2 only diagnostic` is not a tuned alternative or production candidate. It holds the official 0.40/0.60 Opportunity split and compares an SW2-only hierarchy to answer whether the fixed SW3 increment adds evidence.", "",
        "## Top150 industry concentration", "",
        _markdown_table(["group", "level", "mean largest industry share", "mean Top3 share", "mean industry count", "mean missing names"], _concentration_rows(groups)), "",
        "## Date-level V2 versus Legacy", "",
        "`V2 return wins / ties / losses` compares equal-weight portfolio terminal return on the same fixed signal dates. A positive MDD difference is healthier because it is closer to zero.", "",
        _markdown_table(["horizon", "matched dates", "V2 return wins / ties / losses", "mean Δ return", "healthier V2 MDD dates", "mean Δ MDD"], _date_comparison_rows(portfolio)), "",
        "## Required answers", "",
        *[f"- {item}" for item in evidence],
        "- 1–2. No: V2 does not raise T+10 Top150 mean return or median excess versus Legacy; T+5/T+20 are also shown above, so a single horizon is not selected.",
        "- 3. No mean improvement exists to attribute to a few right-tail names. The weaker V2 mean and median together instead indicate a broad lack of return improvement in this sample.",
        "- 4. Mixed risk: V2's constituent MAE is slightly more negative at all reported horizons, while its equal-weight portfolio MDD is shallower. The MDD improvement does not offset weaker reward metrics.",
        "- 5. No: V2 reduces both the largest-industry and Top3 shares at SW2 and SW3, while increasing the number of represented industries. Concentration is descriptive only and never changes selection.",
        "- 6. SW3 has a small T+10 improvement over the SW2-only diagnostic, but both are weaker than Legacy. That is not sufficient evidence for an incremental production benefit.",
        "- 7. SW2 remains the frozen research main level by design (70% Sector, 40% RS), but this result does not support promoting either SW2-only or SW2+SW3 over Legacy.",
        f"- 8. Yes: across {int(sw3_sample['dates'])} dates, SW3 has {sw3_sample['industries']:.0f} industries on average; {sw3_sample['lt2']:.2f} have fewer than 2 members and {sw3_sample['lt5']:.2f} have fewer than 5 (maximum {sw3_sample['max_lt5']:.0f}). This N={args.min_industry_members} full-hierarchy run fail-closed {int(missing.sum())} candidate observations, confirming that sparse coverage is material.",
        "- 9. No: do not replace Legacy under this fixed sample and these frozen weights.",
        "- 10. Yes, hierarchy resonance remains a display/research topic only; no resonance bonus or penalty is introduced by this result.",
        "",
        "## Decision boundary", "",
        f"This report's status is `{status}`. It does not replace the formal Legacy strategy. A promotion decision requires the stated evidence to hold in an independently refreshed fixed sample without changing any weight.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"status={status} output={output}")


if __name__ == "__main__":
    main()
