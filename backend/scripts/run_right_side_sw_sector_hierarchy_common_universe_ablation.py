# ruff: noqa: RUF001  # Mathematical report notation intentionally uses multiplication signs.

"""A/B/C Sector-hierarchy ablation on the frozen Right-side random-12 cohort.

This read-only research runner keeps the frozen Wyckoff pool, forward labels,
and *Legacy SW1 Relative Strength* unchanged.  Its only experimental input is
the Sector Strength composition on the same common eligible universe:

* A = SW1
* B = 0.70 SW1 + 0.30 SW2
* C = 0.60 SW1 + 0.30 SW2 + 0.10 SW3

No production strategy data or score is written.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from app.parquet import scan_enriched_parquet
from app.services.rps_rotation import SectorStrengthResult, build_sector_strength
from app.services.sector_membership import resolve_sw_history
from app.tickflow.repository import DataStore, KlineRepository

HORIZONS = (5, 10, 20)
LEVELS = (1, 2, 3)
TOP_N = 150
MIN_MEMBERS = 8
GROUPS = ("A · SW1", "B · SW1+SW2", "C · SW1+SW2+SW3")


def _markdown_table(headers: list[str], rows: Iterable[list[object]]) -> str:
    body = ["| " + " | ".join(str(value) for value in row) + " |" for row in rows]
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *body,
    ])


def _fmt(value: object, *, percent: bool = False) -> str:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return "—"
    return f"{float(value) * 100:.2f}%" if percent else f"{float(value):.2f}"


def _history(repo: KlineRepository, data_dir: Path, earliest_signal: date) -> pd.DataFrame:
    """Build the private enriched cache required by the frozen engines."""
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
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"]).dt.date
    return frame, sorted(frame["signal_date"].unique())


def _finite(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _sector_id(level: int, code: object) -> str | None:
    value = str(code or "").strip()
    return f"industry:{level}:{value}" if value else None


def _membership_context(
    data_dir: Path, current: date
) -> tuple[dict[str, dict[str, object]], dict[int, list[int]], dict[str, int]]:
    """Return stable-code membership rows and per-level member distributions."""
    resolved = resolve_sw_history(data_dir, as_of=current)
    if resolved is None or resolved.frame.is_empty():
        return {}, {level: [] for level in LEVELS}, {f"ambiguous_sw{level}": 0 for level in LEVELS}
    columns = ["_sym_up"] + [item for level in LEVELS for item in (f"sw{level}_code", f"sw{level}_name")]
    frame = resolved.frame.select([item for item in columns if item in resolved.frame.columns])
    contexts: dict[str, dict[str, object]] = {}
    ambiguity = {f"ambiguous_sw{level}": 0 for level in LEVELS}
    # A security may occur in more than one source membership row. Never use
    # an arbitrary first row: a level is usable only when it has one stable
    # code and, where supplied, one display name.
    for part in frame.partition_by("_sym_up", as_dict=False, maintain_order=True):
        symbol = str(part.get_column("_sym_up")[0]).upper()
        context: dict[str, object] = {}
        for level in LEVELS:
            code_key, name_key = f"sw{level}_code", f"sw{level}_name"
            pairs = {
                (str(row[code_key]).strip(), str(row[name_key]).strip() if row.get(name_key) is not None else None)
                for row in part.select([key for key in (code_key, name_key) if key in part.columns]).iter_rows(named=True)
                if row.get(code_key) is not None and str(row[code_key]).strip()
            }
            codes = {code for code, _ in pairs}
            names = {name for _, name in pairs if name}
            conflict = len(codes) > 1 or (len(codes) == 1 and len(names) > 1)
            if conflict:
                ambiguity[f"ambiguous_sw{level}"] += 1
            context[code_key] = next(iter(codes)) if len(codes) == 1 else None
            context[name_key] = next(iter(names)) if len(names) == 1 else None
            context[f"sw{level}_ambiguous"] = conflict
        contexts[symbol] = context
    distributions: dict[int, list[int]] = {}
    for level in LEVELS:
        code = f"sw{level}_code"
        if code not in frame.columns:
            distributions[level] = []
            continue
        counts = (
            frame.filter(pl.col(code).is_not_null() & pl.col(code).cast(pl.Utf8).str.strip_chars().ne(""))
            .group_by(code).agg(pl.col("_sym_up").n_unique().alias("members"))
        )
        distributions[level] = [int(value) for value in counts.get_column("members").to_list()]
    return contexts, distributions, ambiguity


def _sector_result_map(results: list[SectorStrengthResult]) -> dict[str, SectorStrengthResult]:
    return {result.sector_id: result for result in results if _finite(result.score) is not None}


def _level_state(
    context: dict[str, object] | None,
    level: int,
    results: dict[str, SectorStrengthResult],
    member_counts: dict[str, int],
) -> dict[str, object]:
    code = context.get(f"sw{level}_code") if context else None
    name = context.get(f"sw{level}_name") if context else None
    sector_id = _sector_id(level, code)
    count = member_counts.get(str(code)) if code is not None else None
    result = results.get(sector_id or "")
    if context and context.get(f"sw{level}_ambiguous"):
        status = "AMBIGUOUS_MEMBERSHIP"
    elif sector_id is None:
        status = "MISSING_MEMBERSHIP"
    elif count is not None and count < MIN_MEMBERS:
        status = "INSUFFICIENT_MEMBERS"
    elif result is not None:
        status = "VALID"
    else:
        status = "SECTOR_STRENGTH_UNAVAILABLE"
    return {
        f"sw{level}_code": code,
        f"sw{level}_name": name,
        f"sw{level}_member_count": count,
        f"sw{level}_status": status,
        f"sw{level}_available": status == "VALID",
        f"sw{level}_sector_score": _finite(result.score) if result is not None else None,
    }


def _score_day(
    repo: KlineRepository,
    data_dir: Path,
    current: date,
    symbols: list[str],
    legacy_rs_by_symbol: dict[str, float],
) -> tuple[pd.DataFrame, dict[int, list[int]], dict[str, int]]:
    """Calculate three gated Sector contexts and attach frozen Legacy RS."""
    sector_results = {
        level: build_sector_strength(
            repo,
            kind="industry",
            level=level,
            as_of=current,
            _strict_industry_level=True,
            _min_industry_members=MIN_MEMBERS,
        )
        for level in LEVELS
    }
    result_maps = {level: _sector_result_map(results) for level, results in sector_results.items()}
    contexts, distributions, membership_diagnostics = _membership_context(data_dir, current)
    member_counts: dict[int, dict[str, int]] = {
        level: {
            str(result.sector_id.split(":", 2)[2]): int(result.member_count)
            for result in sector_results[level]
        }
        for level in LEVELS
    }
    # Add below-N groups, which have been deliberately removed from results by
    # the N=8 gate, so their status and real member count remain observable.
    resolved = resolve_sw_history(data_dir, as_of=current)
    if resolved is not None and not resolved.frame.is_empty():
        for level in LEVELS:
            code = f"sw{level}_code"
            if code not in resolved.frame.columns:
                continue
            counts = (
                resolved.frame.filter(pl.col(code).is_not_null() & pl.col(code).cast(pl.Utf8).str.strip_chars().ne(""))
                .group_by(code).agg(pl.col("_sym_up").n_unique().alias("members"))
            )
            member_counts[level].update({str(row[code]): int(row["members"]) for row in counts.iter_rows(named=True)})

    # Deliberately do not invoke RelativeStrengthEngine here.  The exact
    # Legacy SW1 RSScore is frozen in the original snapshot and is reused as
    # supplied for every A/B/C row.
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        context = contexts.get(str(symbol).upper())
        row: dict[str, object] = {"symbol": str(symbol).upper()}
        for level in LEVELS:
            row.update(_level_state(context, level, result_maps[level], member_counts[level]))
        row["legacy_rs_score"] = legacy_rs_by_symbol.get(str(symbol).upper())
        row["legacy_rs_available"] = row["legacy_rs_score"] is not None
        row["common_sector_eligible"] = all(bool(row[f"sw{level}_available"]) for level in LEVELS)
        row["common_eligible"] = bool(row["common_sector_eligible"] and row["legacy_rs_available"])
        rows.append(row)
    return pd.DataFrame(rows), distributions, membership_diagnostics


def _score_all(repo: KlineRepository, data_dir: Path, source: pd.DataFrame, dates: list[date]) -> tuple[pd.DataFrame, dict[date, dict[int, list[int]]], dict[date, dict[str, int]]]:
    frames: list[pd.DataFrame] = []
    distributions: dict[date, dict[int, list[int]]] = {}
    diagnostics: dict[date, dict[str, int]] = {}
    for current in dates:
        frozen = source.loc[source["signal_date"] == current, ["symbol", "rs_score"]]
        symbols = frozen["symbol"].tolist()
        legacy_rs_by_symbol = {
            str(row.symbol).upper(): value
            for row in frozen.itertuples(index=False)
            if (value := _finite(row.rs_score)) is not None
        }
        frame, day_distribution, day_diagnostics = _score_day(
            repo, data_dir, current, symbols, legacy_rs_by_symbol
        )
        frame.insert(0, "signal_date", current)
        frames.append(frame)
        distributions[current] = day_distribution
        diagnostics[current] = day_diagnostics
        print(
            f"{current}: candidates={len(symbols)} common_eligible={int(frame['common_eligible'].sum())}",
            flush=True,
        )
    return pd.concat(frames, ignore_index=True), distributions, diagnostics


def _build_groups(frame: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    common = frame.loc[frame["common_eligible"]].copy()
    common["sector_score_a"] = pd.to_numeric(common["sw1_sector_score"], errors="coerce")
    common["sector_score_b"] = 0.70 * common["sw1_sector_score"] + 0.30 * common["sw2_sector_score"]
    common["sector_score_c"] = (
        0.60 * common["sw1_sector_score"] + 0.30 * common["sw2_sector_score"] + 0.10 * common["sw3_sector_score"]
    )
    for suffix in ("a", "b", "c"):
        common[f"opportunity_{suffix}"] = 0.40 * common[f"sector_score_{suffix}"] + 0.60 * common["legacy_rs_score"]
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
    for name, suffix in zip(GROUPS, ("a", "b", "c"), strict=True):
        parts = []
        for _, day in common.groupby("signal_date", sort=True):
            parts.append(day.sort_values([f"opportunity_{suffix}", "symbol"], ascending=[False, True], kind="stable").head(TOP_N).copy())
        groups[name] = pd.concat(parts, ignore_index=True)
    return groups, common


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
        path_dates = dates[index[signal_date] + 1:index[signal_date] + 1 + horizon]
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
            "signal_date": signal_date,
            "horizon": horizon,
            "count": len(symbols),
            "portfolio_return": terminal,
            "portfolio_excess": terminal - benchmark_return if benchmark_return is not None else None,
            "portfolio_mdd": _mdd(nav),
        })
    return pd.DataFrame(results)


def _portfolio_all(groups: dict[str, pd.DataFrame], prices: pd.DataFrame, trading_dates: list[date]) -> dict[str, pd.DataFrame]:
    return {
        name: pd.concat(
            [_portfolio_metrics(group, prices, trading_dates, horizon) for horizon in HORIZONS],
            ignore_index=True,
        )
        for name, group in groups.items()
    }


def _summary_rows(groups: dict[str, pd.DataFrame], portfolios: dict[str, pd.DataFrame]) -> list[list[object]]:
    rows: list[list[object]] = []
    for name, group in groups.items():
        for horizon in HORIZONS:
            stock = _stock_metrics(group, horizon)
            paths = portfolios[name].loc[portfolios[name]["horizon"] == horizon]
            rows.append([
                name, f"T+{horizon}", stock["n"], _fmt(stock["mean_return"], percent=True),
                _fmt(stock["median_return"], percent=True), _fmt(stock["mean_excess"], percent=True),
                _fmt(stock["median_excess"], percent=True), _fmt(stock["positive_rate"], percent=True),
                _fmt(stock["mae"], percent=True), _fmt(stock["mfe"], percent=True),
                _fmt(paths["portfolio_return"].mean() if not paths.empty else None, percent=True),
                _fmt(paths["portfolio_mdd"].mean() if not paths.empty else None, percent=True),
                f"{int((paths['portfolio_excess'] > 0).sum())}/{len(paths)}" if not paths.empty else "—",
            ])
    return rows


def _coverage_rows(scores: pd.DataFrame) -> list[list[object]]:
    rows: list[list[object]] = []
    for current, day in scores.groupby("signal_date", sort=True):
        total = len(day)
        values: list[object] = [current, total]
        for level in LEVELS:
            available = int(day[f"sw{level}_available"].sum())
            insufficient = int((day[f"sw{level}_status"] == "INSUFFICIENT_MEMBERS").sum())
            missing = int((day[f"sw{level}_status"] == "MISSING_MEMBERSHIP").sum())
            ambiguous = int((day[f"sw{level}_status"] == "AMBIGUOUS_MEMBERSHIP").sum())
            values.extend([available, insufficient, missing, ambiguous, _fmt(available / total if total else None, percent=True)])
        values.extend([int(day["common_sector_eligible"].sum()), int(day["common_eligible"].sum()), _fmt(day["common_eligible"].mean(), percent=True)])
        rows.append(values)
    return rows


def _member_rows(distributions: dict[date, dict[int, list[int]]]) -> list[list[object]]:
    rows: list[list[object]] = []
    for level in LEVELS:
        values = [count for per_date in distributions.values() for count in per_date[level]]
        rows.append([
            f"SW{level}", len(values) / len(distributions) if distributions else 0,
            _fmt(np.mean(values) if values else None), _fmt(np.median(values) if values else None),
            _fmt(np.percentile(values, 25) if values else None), _fmt(np.percentile(values, 75) if values else None),
            min(values) if values else "—", max(values) if values else "—",
            _fmt(np.mean([sum(count < MIN_MEMBERS for count in per_date[level]) for per_date in distributions.values()]) if distributions else None),
        ])
    return rows


def _concentration(day: pd.DataFrame, level: int) -> dict[str, float | int]:
    code, name = f"sw{level}_code", f"sw{level}_name"
    total = len(day)
    values = [str(row.get(code) or row.get(name) or "").strip() for row in day[[code, name]].to_dict("records")]
    counts = Counter(value for value in values if value)
    ranked = counts.most_common(3)
    return {
        "largest_share": ranked[0][1] / total if ranked and total else 0.0,
        "top3_share": sum(value for _, value in ranked) / total if total else 0.0,
        "industry_count": len(counts),
        "missing": total - sum(counts.values()),
    }


def _concentration_rows(groups: dict[str, pd.DataFrame]) -> list[list[object]]:
    rows: list[list[object]] = []
    for group, frame in groups.items():
        for level in LEVELS:
            per_day = [_concentration(day, level) for _, day in frame.groupby("signal_date", sort=True)]
            rows.append([
                group, f"SW{level}", _fmt(np.mean([item["largest_share"] for item in per_day]), percent=True),
                _fmt(np.mean([item["top3_share"] for item in per_day]), percent=True),
                _fmt(np.mean([item["industry_count"] for item in per_day])),
                _fmt(np.mean([item["missing"] for item in per_day])),
            ])
    return rows


def _pairwise_date_rows(portfolios: dict[str, pd.DataFrame]) -> list[list[object]]:
    rows: list[list[object]] = []
    for left, right, label in ((GROUPS[1], GROUPS[0], "B vs A"), (GROUPS[2], GROUPS[0], "C vs A"), (GROUPS[2], GROUPS[1], "C vs B")):
        for horizon in HORIZONS:
            compared = portfolios[left].query("horizon == @horizon").merge(
                portfolios[right].query("horizon == @horizon"), on="signal_date", suffixes=("_left", "_right")
            )
            delta = compared["portfolio_return_left"] - compared["portfolio_return_right"]
            delta_mdd = compared["portfolio_mdd_left"] - compared["portfolio_mdd_right"]
            rows.append([
                label, f"T+{horizon}", len(compared),
                f"{int((delta > 0).sum())}/{int((delta == 0).sum())}/{int((delta < 0).sum())}",
                _fmt(delta.mean(), percent=True), _fmt(delta.median(), percent=True),
                f"{int((delta_mdd > 0).sum())}/{len(compared)}", _fmt(delta_mdd.mean(), percent=True),
            ])
    return rows


def _overlap_rows(groups: dict[str, pd.DataFrame]) -> tuple[list[list[object]], list[list[object]]]:
    daily: list[list[object]] = []
    averages: list[list[object]] = []
    for left, right, label in ((GROUPS[0], GROUPS[1], "A vs B"), (GROUPS[0], GROUPS[2], "A vs C"), (GROUPS[1], GROUPS[2], "B vs C")):
        values: list[tuple[int, int, float]] = []
        for current in sorted(set(groups[left]["signal_date"]) & set(groups[right]["signal_date"])):
            left_symbols = set(groups[left].loc[groups[left]["signal_date"] == current, "symbol"])
            right_symbols = set(groups[right].loc[groups[right]["signal_date"] == current, "symbol"])
            overlap = len(left_symbols & right_symbols)
            replaced = len(left_symbols - right_symbols)
            union = len(left_symbols | right_symbols)
            jaccard = overlap / union if union else 0.0
            daily.append([current, label, overlap, replaced, _fmt(jaccard, percent=True)])
            values.append((overlap, replaced, jaccard))
        averages.append([
            label, _fmt(np.mean([item[0] for item in values])), _fmt(np.mean([item[1] for item in values])),
            _fmt(np.mean([item[2] for item in values]), percent=True),
        ])
    return daily, averages


def _rank_change_rows(common: pd.DataFrame, *, from_suffix: str, to_suffix: str, label: str) -> list[list[object]]:
    frame = common.copy()
    frame["rank_change"] = frame[f"rank_{from_suffix}"] - frame[f"rank_{to_suffix}"]
    chosen = pd.concat([
        frame.sort_values(["rank_change", "symbol"], ascending=[False, True], kind="stable").head(3),
        frame.sort_values(["rank_change", "symbol"], ascending=[True, True], kind="stable").head(3),
    ])
    rows: list[list[object]] = []
    for _, row in chosen.iterrows():
        rows.append([
            label, row["signal_date"], row["symbol"], row.get("sw1_name") or "—", row.get("sw2_name") or "—", row.get("sw3_name") or "—",
            _fmt(row["sw1_sector_score"]), _fmt(row["sw2_sector_score"]), _fmt(row["sw3_sector_score"]),
            _fmt(row["sector_score_a"]), _fmt(row["sector_score_b"]), _fmt(row["sector_score_c"]),
            _fmt(row["legacy_rs_score"]), _fmt(row["opportunity_a"]), _fmt(row["opportunity_b"]), _fmt(row["opportunity_c"]),
            row["rank_a"], row["rank_b"], row["rank_c"], int(row["rank_change"]),
        ])
    return rows


def _supports(groups: dict[str, pd.DataFrame], portfolios: dict[str, pd.DataFrame], candidate: str, baseline: str) -> bool:
    """Predeclared conservative stability rule; this is not a weight search."""
    improved_horizons = 0
    risk_ok_horizons = 0
    date_majorities = 0
    for horizon in HORIZONS:
        candidate_stock = _stock_metrics(groups[candidate], horizon)
        baseline_stock = _stock_metrics(groups[baseline], horizon)
        if (
            _finite(candidate_stock["mean_excess"]) is not None
            and _finite(baseline_stock["mean_excess"]) is not None
            and float(candidate_stock["mean_excess"]) >= float(baseline_stock["mean_excess"])
            and float(candidate_stock["median_excess"]) >= float(baseline_stock["median_excess"])
        ):
            improved_horizons += 1
        candidate_paths = portfolios[candidate].query("horizon == @horizon")
        baseline_paths = portfolios[baseline].query("horizon == @horizon")
        if not candidate_paths.empty and not baseline_paths.empty:
            if candidate_stock["mae"] >= baseline_stock["mae"] and candidate_paths["portfolio_mdd"].mean() >= baseline_paths["portfolio_mdd"].mean():
                risk_ok_horizons += 1
            delta = candidate_paths.merge(baseline_paths, on="signal_date", suffixes=("_candidate", "_baseline"))
            if (delta["portfolio_return_candidate"] > delta["portfolio_return_baseline"]).sum() > (delta["portfolio_return_candidate"] < delta["portfolio_return_baseline"]).sum():
                date_majorities += 1
    return improved_horizons >= 2 and risk_ok_horizons >= 2 and date_majorities >= 2


def _decision(groups: dict[str, pd.DataFrame], portfolios: dict[str, pd.DataFrame], expected_dates: int) -> tuple[str, list[str]]:
    if any(groups[name]["signal_date"].nunique() != expected_dates for name in GROUPS):
        return "INSUFFICIENT", ["At least one A/B/C Top150 series is missing a frozen signal date."]
    b_supported = _supports(groups, portfolios, GROUPS[1], GROUPS[0])
    c_supported = b_supported and _supports(groups, portfolios, GROUPS[2], GROUPS[1])
    t10 = {name: _stock_metrics(groups[name], 10) for name in GROUPS}
    evidence = [
        f"T+10 mean excess A/B/C: {_fmt(t10[GROUPS[0]]['mean_excess'], percent=True)} / {_fmt(t10[GROUPS[1]]['mean_excess'], percent=True)} / {_fmt(t10[GROUPS[2]]['mean_excess'], percent=True)}.",
        f"T+10 median excess A/B/C: {_fmt(t10[GROUPS[0]]['median_excess'], percent=True)} / {_fmt(t10[GROUPS[1]]['median_excess'], percent=True)} / {_fmt(t10[GROUPS[2]]['median_excess'], percent=True)}.",
        "Support requires (without optimizing any parameter): at least two horizons with non-worse mean and median excess, at least two with non-worse MAE and portfolio MDD, and a positive date-level return majority on at least two horizons.",
    ]
    if c_supported:
        return "SW1_SW2_SW3_SUPPORTED", evidence
    if b_supported:
        return "SW1_SW2_SUPPORTED", evidence
    a = t10[GROUPS[0]]
    b, c = t10[GROUPS[1]], t10[GROUPS[2]]
    if all(float(a[key]) >= float(other[key]) for other in (b, c) for key in ("mean_excess", "median_excess")):
        return "SW1_ONLY_PREFERRED", evidence
    return "NO_STABLE_INCREMENT", evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--input-dir", type=Path, default=Path("../data/research/right_side_random12_frozen_20260913"))
    parser.add_argument("--output", type=Path, default=Path("../docs/right-side-sw-sector-hierarchy-common-universe-ablation-v2.md"))
    args = parser.parse_args()
    data_dir, input_dir, output = args.data_dir.resolve(), args.input_dir.resolve(), args.output.resolve()
    source, signal_dates = _load_snapshots(input_dir / "snapshots")
    repo = KlineRepository(DataStore(data_dir))
    prices = _history(repo, data_dir, min(signal_dates))
    scores, distributions, membership_diagnostics = _score_all(repo, data_dir, source, signal_dates)
    frame = source.merge(scores, on=["signal_date", "symbol"], how="left", validate="one_to_one")
    groups, common = _build_groups(frame)
    portfolios = _portfolio_all(groups, prices, sorted(prices["date"].unique()))
    decision, evidence = _decision(groups, portfolios, len(signal_dates))
    overlap_daily, overlap_average = _overlap_rows(groups)
    insufficient_top = [
        f"{current}: {int(day['common_eligible'].sum())}"
        for current, day in frame.groupby("signal_date", sort=True)
        if int(day["common_eligible"].sum()) < TOP_N
    ]
    rank_changes = _rank_change_rows(common, from_suffix="a", to_suffix="b", label="B vs A") + _rank_change_rows(common, from_suffix="b", to_suffix="c", label="C vs B")
    lines = [
        "# Right-side SW Sector Hierarchy Common-Universe Ablation V2", "",
        f"**Final status: `{decision}`**", "",
        "## 1. Experiment contract", "",
        "This is an exploratory frozen random-12 ablation. Wyckoff candidate pools, forward labels, Top150 size, VP, RiskBucket and every RS input/formula/benchmark/weight remain unchanged. Each group uses the same frozen Legacy SW1 `RSScore`; no SW2/SW3 RS is calculated or used.", "",
        "The only tested variable is Sector composition, with no parameter scan: A = `SW1`; B = `0.70 × SW1 + 0.30 × SW2`; C = `0.60 × SW1 + 0.30 × SW2 + 0.10 × SW3`. For all groups `Opportunity = 0.40 × SectorScore + 0.60 × LegacyRSScore`.", "",
        f"All three Sector Strength calls retain their frozen V1.1 formula and a fixed `unique_members >= {MIN_MEMBERS}` gate. An undersized group is `INSUFFICIENT_MEMBERS`, never a zero score. Dates ({len(signal_dates)}): " + ", ".join(item.isoformat() for item in signal_dates) + ".", "",
        "## 2. Common eligible universe coverage", "",
        "`common sector eligible` means valid gated SW1/SW2/SW3 Sector Strength. `common eligible` additionally requires an already-required, unchanged Legacy RS score, so an RS data gap removes the row identically from A/B/C rather than changing any group’s candidate pool.", "",
        _markdown_table(
            ["signal date", "frozen candidates", "SW1 valid", "SW1 <8", "SW1 missing", "SW1 ambiguous", "SW1 coverage", "SW2 valid", "SW2 <8", "SW2 missing", "SW2 ambiguous", "SW2 coverage", "SW3 valid", "SW3 <8", "SW3 missing", "SW3 ambiguous", "SW3 coverage", "common sector", "common rankable", "common coverage"],
            _coverage_rows(scores),
        ), "",
        ("No date has fewer than 150 common rankable candidates." if not insufficient_top else "Dates below 150 common rankable candidates (all eligible names were used; no fallback): " + "; ".join(insufficient_top) + "."), "",
        "## 3. SW1/SW2/SW3 member-count statistics", "",
        _markdown_table(["level", "mean industries/date", "mean members", "median", "p25", "p75", "min", "max", "mean industries <8/date"], _member_rows(distributions)), "",
        "Membership ambiguity is fail-closed rather than first-row resolved: mean ambiguous resolved membership symbols/date (SW1/SW2/SW3) = " + " / ".join(
            _fmt(np.mean([item[f'ambiguous_sw{level}'] for item in membership_diagnostics.values()])) for level in LEVELS
        ) + ". Stable SW codes are the calculation keys; names are display-only.", "",
        "## 4. A/B/C Top150 performance", "",
        _markdown_table(["group", "horizon", "n", "mean return", "median return", "mean excess", "median excess", "positive rate", "mean MAE", "mean MFE", "equal-weight portfolio return", "portfolio MDD", "beat benchmark dates"], _summary_rows(groups, portfolios)), "",
        "## 5. Date-level comparison", "",
        "Return wins/ties/losses compare same-date equal-weight portfolio terminal returns. Positive ΔMDD is healthier because it is closer to zero.", "",
        _markdown_table(["comparison", "horizon", "matched dates", "return wins/ties/losses", "mean Δ return", "median Δ return", "healthier MDD dates", "mean Δ MDD"], _pairwise_date_rows(portfolios)), "",
        "## 6. Top150 overlap", "",
        _markdown_table(["comparison", "mean overlap", "mean replaced", "mean Jaccard"], overlap_average), "",
        _markdown_table(["signal date", "comparison", "overlap", "replaced", "Jaccard"], overlap_daily), "",
        "## 7. Industry concentration", "",
        "Diagnostic only; concentration never changes membership or ordering. Values are random-12 daily means for each Top150.", "",
        _markdown_table(["group", "level", "mean largest industry share", "mean Top3 share", "mean industry count", "mean missing industries"], _concentration_rows(groups)), "",
        "## 8. Rank-change examples", "",
        "Positive rank change means the refined Sector composition moved the stock upward in the complete common eligible ranking. The three largest upward and downward moves are shown for each comparison; they are explanatory examples, not selected by forward return.", "",
        _markdown_table(["comparison", "signal date", "stock", "SW1", "SW2", "SW3", "SW1 strength", "SW2 strength", "SW3 strength", "sector A", "sector B", "sector C", "Legacy RS", "opp A", "opp B", "opp C", "rank A", "rank B", "rank C", "rank change"], rank_changes), "",
        "## 9. Point-in-time limitation", "",
        "The current SW2021 membership store is used through its available effective intervals, but it lacks a complete historical exit record. This report therefore answers only whether finer hierarchy adds information on the current frozen random-12 data and available memberships. It does not establish a long-horizon or point-in-time proof for any hierarchy.", "",
        "## 10. Final decision", "",
        *[f"- {item}" for item in evidence],
        f"- Decision: `{decision}`. This is a research conclusion only; it does not replace the current Legacy production strategy and does not authorize further weight or N-threshold tuning.", "",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
