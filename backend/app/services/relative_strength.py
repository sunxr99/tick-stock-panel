"""Explainable, daily stock Relative Strength within selected sector contexts.

This module is intentionally a read-only consumer of the frozen Sector Strength
V1.1 contract.  Callers supply the selected stable ``sector_id`` values; no
candidate-pool filtering or strategy integration happens here.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date

import polars as pl

from app.services.rps_rotation import (
    _BENCHMARK_ID,
    _SECTOR_DISPLAY_NAME,
    _history_dates,
    _load_concept_map_df,
    _market_daily_returns,
    _normalized_map,
    _rank_values,
    _window_return,
    membership_note_for_kind,
    membership_source_for_kind,
)
from app.services.strength_state import extension_state, relative_strength_state

_RS_WINDOWS = (3, 5, 10, 20, 60)
_RS_WEIGHTS = {3: 0.15, 5: 0.20, 10: 0.25, 20: 0.30, 60: 0.10}
_MIN_BENCHMARK_STOCKS = 2
_MIN_SECTOR_STOCKS = 2


@dataclass(frozen=True)
class RelativeStrengthResult:
    """One stock in one selected sector context on one trading date.

    ``sector_ids`` retains every selected sector context for the stock.  A
    multi-concept stock therefore deliberately yields multiple results with
    the same market fields and distinct sector fields, rather than silently
    selecting one concept.
    """

    as_of: date
    symbol: str
    benchmark_id: str
    sector_ids: tuple[str, ...]
    membership_as_of: date | None
    sector_id: str
    sector_name: str
    sector_kind: str
    sector_level: int | None
    sw1_code: str | None
    sw1_name: str | None
    sw2_code: str | None
    sw2_name: str | None
    sw3_code: str | None
    sw3_name: str | None
    stock_return_3d: float | None
    stock_return_5d: float | None
    stock_return_10d: float | None
    stock_return_20d: float | None
    stock_return_60d: float | None
    vs_market_3d: float | None
    vs_market_5d: float | None
    vs_market_10d: float | None
    vs_market_20d: float | None
    vs_market_60d: float | None
    market_rs_score: float | None
    market_rank: int | None
    market_percentile: float | None
    vs_sector_3d: float | None
    vs_sector_5d: float | None
    vs_sector_10d: float | None
    vs_sector_20d: float | None
    vs_sector_60d: float | None
    sector_rs_score: float | None
    sector_rank: int | None
    sector_percentile: float | None
    rs_score: float | None
    rs_change_1d: float | None
    rs_change_3d: float | None
    market_rs_change_3d: float | None
    sector_rs_change_3d: float | None
    market_rank_change_3d: int | None
    sector_rank_change_3d: int | None
    stock_return_20d_percentile: float | None
    distance_from_ma20: float | None
    distance_from_ma60: float | None
    consecutive_up_days: int | None
    rs_extension_score: float | None
    rs_extension_state: str | None
    rs_state: str | None
    state_reasons: tuple[str, ...]
    data_quality: dict[str, object]
    unavailable_reason: str | None


def _parse_sector_id(sector_id: str) -> tuple[str, int | None, str]:
    """Parse the stable IDs emitted by ``SectorStrengthResult``."""
    parts = sector_id.split(":", 2)
    if len(parts) != 3 or parts[0] not in {"concept", "industry"}:
        raise ValueError(f"invalid sector_id: {sector_id!r}")
    kind, level_text, name = parts
    if not name:
        raise ValueError(f"invalid sector_id: {sector_id!r}")
    if kind == "concept":
        if level_text != "all":
            raise ValueError(f"concept sector_id must use ':all:': {sector_id!r}")
        return kind, None, name
    if level_text not in {"1", "2", "3", "all"}:
        raise ValueError(f"invalid industry level in sector_id: {sector_id!r}")
    return kind, None if level_text == "all" else int(level_text), name


def _selected_membership(
    repo,
    sector_ids: Iterable[str],
    as_of: date | None = None,
    *,
    strict_industry_level: bool = False,
) -> pl.DataFrame:
    """Load only the selected Sector Strength membership contexts."""
    requested: dict[tuple[str, int | None], set[str]] = defaultdict(set)
    for sector_id in sector_ids:
        kind, level, name = _parse_sector_id(sector_id)
        requested[(kind, level)].add(name)
    rows: list[dict[str, object]] = []
    for (kind, level), names in requested.items():
        loaded = _load_concept_map_df(repo, kind, as_of)
        map_df = loaded[0] if isinstance(loaded, tuple) else loaded
        normalized = _normalized_map(
            map_df, kind, level, strict_industry_level=strict_industry_level
        )
        if normalized.is_empty():
            continue
        selected = normalized.filter(pl.col(kind).is_in(sorted(names)))
        for row in selected.iter_rows(named=True):
            sector_key = str(row[kind])
            display_name = str(row.get(_SECTOR_DISPLAY_NAME) or sector_key)
            rows.append({
                "_sym_up": str(row["_sym_up"]),
                "sector_id": f"{kind}:{level or 'all'}:{sector_key}",
                "sector_name": display_name,
                "sector_kind": kind,
                "sector_level": level,
                **{
                    column: row.get(column)
                    for column in ("sw1_code", "sw1_name", "sw2_code", "sw2_name", "sw3_code", "sw3_name")
                },
            })
    schema = {
        "_sym_up": pl.Utf8,
        "sector_id": pl.Utf8,
        "sector_name": pl.Utf8,
        "sector_kind": pl.Utf8,
        "sector_level": pl.Int64,
        "sw1_code": pl.Utf8,
        "sw1_name": pl.Utf8,
        "sw2_code": pl.Utf8,
        "sw2_name": pl.Utf8,
        "sw3_code": pl.Utf8,
        "sw3_name": pl.Utf8,
    }
    return pl.DataFrame(rows, schema=schema).unique() if rows else pl.DataFrame(schema=schema)


def _stock_daily_returns(frame: pl.DataFrame) -> dict[str, dict[date, float]]:
    """Materialize normalized per-stock daily returns once for all consumers."""
    daily: dict[str, dict[date, float]] = defaultdict(dict)
    for row in frame.iter_rows(named=True):
        daily[str(row["_sym_up"])][row["date"]] = float(row["change_pct"])
    return daily


def _window_returns(
    daily_values: dict[date, float], dates: list[date], index: int
) -> dict[int, float | None]:
    return {
        window: _window_return(daily_values, dates, index, window)
        for window in _RS_WINDOWS
    }


def _weighted_score(percentiles: dict[int, float | None]) -> float | None:
    if any(percentiles.get(window) is None for window in _RS_WINDOWS):
        return None
    return sum(_RS_WEIGHTS[window] * float(percentiles[window]) for window in _RS_WINDOWS)


def _distance_from_ma(
    daily_values: dict[date, float], dates: list[date], index: int, window: int
) -> float | None:
    """Distance of a stock's return-derived index from an exact-session MA."""
    if index < window - 1:
        return None
    window_dates = dates[index - window + 1:index + 1]
    if any(current not in daily_values for current in window_dates):
        return None
    price = 100.0
    prices: list[float] = []
    for current in window_dates:
        price *= 1.0 + daily_values[current]
        prices.append(price)
    average = sum(prices) / len(prices)
    return price / average - 1.0 if average else None


def _consecutive_up_days(daily_values: dict[date, float], dates: list[date], index: int) -> int | None:
    count = 0
    for position in range(index, -1, -1):
        value = daily_values.get(dates[position])
        if value is None:
            return count if count else None
        if value <= 0:
            break
        count += 1
    return count


def _sector_daily_returns(
    stock_frame: pl.DataFrame, membership: pl.DataFrame
) -> dict[str, dict[date, float]]:
    joined = stock_frame.join(membership.select(["_sym_up", "sector_id"]), on="_sym_up", how="inner")
    if joined.is_empty():
        return {}
    daily = joined.group_by(["date", "sector_id"]).agg(
        pl.col("change_pct").mean().alias("sector_return")
    )
    values: dict[str, dict[date, float]] = defaultdict(dict)
    for row in daily.iter_rows(named=True):
        values[str(row["sector_id"])][row["date"]] = float(row["sector_return"])
    return values


def build_relative_strength(
    repo,
    *,
    sector_ids: Iterable[str],
    as_of: date | None = None,
    _include_state: bool = True,
    _strict_industry_level: bool = False,
) -> list[RelativeStrengthResult]:
    """Build Stock RS V1 for explicit Sector Strength selection contexts.

    All return windows use exact enriched trading dates through ``as_of`` and
    compound decimal ``change_pct`` values.  A missing stock/sector/benchmark
    session invalidates its relevant window instead of borrowing an earlier
    observation.  The market benchmark is the Sector Strength V1.1 all-stock
    equal-weight series, with a minimum two valid stocks on every date.
    """
    sector_ids = tuple(sector_ids)
    trading_dates, target = _history_dates(repo, as_of)
    if target is None:
        return []
    membership = _selected_membership(
        repo, sector_ids, target, strict_industry_level=_strict_industry_level
    )
    if membership.is_empty():
        return []
    dates = trading_dates[-max(_RS_WINDOWS):]
    if not dates:
        return []
    df = repo.get_enriched_range(
        dates[0], target, columns=["symbol", "date", "change_pct"]
    )
    if df is None or df.is_empty() or not {"symbol", "date", "change_pct"}.issubset(df.columns):
        return []
    stock_frame = (
        df.filter(pl.col("change_pct").is_not_null() & pl.col("change_pct").is_finite())
        .with_columns(pl.col("symbol").str.to_uppercase().alias("_sym_up"))
        .group_by(["date", "_sym_up"])
        .agg(pl.col("change_pct").mean().alias("change_pct"))
    )
    if stock_frame.is_empty():
        return []

    target_index = dates.index(target)
    stock_daily = _stock_daily_returns(stock_frame)
    stock_returns = {
        symbol: _window_returns(values, dates, target_index)
        for symbol, values in stock_daily.items()
    }
    benchmark_daily, benchmark_counts = _market_daily_returns(stock_frame)
    benchmark_returns = _window_returns(benchmark_daily, dates, target_index)
    for window in _RS_WINDOWS:
        window_dates = dates[target_index - window + 1:target_index + 1]
        if len(window_dates) != window or any(
            benchmark_counts.get(current_date, 0) < _MIN_BENCHMARK_STOCKS
            for current_date in window_dates
        ):
            benchmark_returns[window] = None

    vs_market: dict[int, dict[str, float]] = {}
    market_percentiles: dict[int, dict[str, float]] = {}
    for window in _RS_WINDOWS:
        benchmark_return = benchmark_returns[window]
        values = {
            symbol: float(returns[window]) - float(benchmark_return)
            for symbol, returns in stock_returns.items()
            if returns[window] is not None and benchmark_return is not None
        }
        vs_market[window] = values
        market_percentiles[window] = _rank_values(values)[1] if values else {}
    market_scores = {
        symbol: score
        for symbol in stock_returns
        if (score := _weighted_score({
            window: market_percentiles[window].get(symbol) for window in _RS_WINDOWS
        })) is not None
    }
    market_ranks, market_score_percentiles = _rank_values(market_scores) if market_scores else ({}, {})

    # Extension is an independent description of price stretch.  It is not a
    # component of the frozen MarketRS, SectorRS, or RSScore formulas.
    stock_return_20d_values = {
        symbol: float(returns[20])
        for symbol, returns in stock_returns.items()
        if returns.get(20) is not None
    }
    _, stock_return_20d_percentiles = (
        _rank_values(stock_return_20d_values) if stock_return_20d_values else ({}, {})
    )
    distance_ma20_values: dict[str, float] = {}
    distance_ma60_values: dict[str, float] = {}
    consecutive_up_values: dict[str, float] = {}
    extension_raw: dict[str, dict[str, float | int | None]] = {}
    for symbol, daily_values in stock_daily.items():
        distance_ma20 = _distance_from_ma(daily_values, dates, target_index, 20)
        distance_ma60 = _distance_from_ma(daily_values, dates, target_index, 60)
        consecutive_up = _consecutive_up_days(daily_values, dates, target_index)
        extension_raw[symbol] = {
            "distance_from_ma20": distance_ma20,
            "distance_from_ma60": distance_ma60,
            "consecutive_up_days": consecutive_up,
        }
        if distance_ma20 is not None:
            distance_ma20_values[symbol] = distance_ma20
        if distance_ma60 is not None:
            distance_ma60_values[symbol] = distance_ma60
        if consecutive_up is not None:
            consecutive_up_values[symbol] = float(consecutive_up)
    _, distance_ma20_percentiles = (
        _rank_values(distance_ma20_values) if distance_ma20_values else ({}, {})
    )
    _, distance_ma60_percentiles = (
        _rank_values(distance_ma60_values) if distance_ma60_values else ({}, {})
    )
    _, consecutive_up_percentiles = (
        _rank_values(consecutive_up_values) if consecutive_up_values else ({}, {})
    )
    extension_scores: dict[str, float] = {}
    for symbol in stock_daily:
        components = (
            stock_return_20d_percentiles.get(symbol),
            distance_ma20_percentiles.get(symbol),
            distance_ma60_percentiles.get(symbol),
            consecutive_up_percentiles.get(symbol),
        )
        if all(value is not None for value in components):
            extension_scores[symbol] = sum(float(value) for value in components) / len(components)

    sector_daily = _sector_daily_returns(stock_frame, membership)
    sector_returns = {
        sector_id: _window_returns(values, dates, target_index)
        for sector_id, values in sector_daily.items()
    }
    members_by_sector: dict[str, set[str]] = defaultdict(set)
    contexts_by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in membership.iter_rows(named=True):
        symbol = str(row["_sym_up"])
        sector_id = str(row["sector_id"])
        members_by_sector[sector_id].add(symbol)
        contexts_by_symbol[symbol].append(row)

    sector_vs: dict[str, dict[int, dict[str, float]]] = {}
    sector_percentiles: dict[str, dict[int, dict[str, float]]] = {}
    sector_scores: dict[str, dict[str, float]] = {}
    sector_ranks: dict[str, dict[str, int]] = {}
    sector_score_percentiles: dict[str, dict[str, float]] = {}
    for sector_id, members in members_by_sector.items():
        by_window: dict[int, dict[str, float]] = {}
        by_percentile: dict[int, dict[str, float]] = {}
        for window in _RS_WINDOWS:
            sector_return = sector_returns.get(sector_id, {}).get(window)
            values = {
                symbol: float(stock_returns[symbol][window]) - float(sector_return)
                for symbol in members
                if symbol in stock_returns
                and stock_returns[symbol][window] is not None
                and sector_return is not None
            }
            by_window[window] = values
            by_percentile[window] = _rank_values(values)[1] if values else {}
        scores = {
            symbol: score
            for symbol in members
            if (score := _weighted_score({
                window: by_percentile[window].get(symbol) for window in _RS_WINDOWS
            })) is not None
        }
        sector_vs[sector_id] = by_window
        sector_percentiles[sector_id] = by_percentile
        sector_scores[sector_id] = scores
        if len(scores) >= _MIN_SECTOR_STOCKS:
            sector_ranks[sector_id], sector_score_percentiles[sector_id] = _rank_values(scores)
        else:
            sector_ranks[sector_id], sector_score_percentiles[sector_id] = {}, {}

    all_sector_ids = {
        symbol: tuple(sorted(str(context["sector_id"]) for context in contexts))
        for symbol, contexts in contexts_by_symbol.items()
    }
    results: list[RelativeStrengthResult] = []
    for symbol in sorted(contexts_by_symbol):
        stock = stock_returns.get(symbol, {})
        for context in sorted(contexts_by_symbol[symbol], key=lambda item: str(item["sector_id"])):
            sector_id = str(context["sector_id"])
            sector_kind = str(context["sector_kind"])
            membership_source = membership_source_for_kind(sector_kind)
            sector = sector_returns.get(sector_id, {})
            sector_score = sector_scores.get(sector_id, {}).get(symbol)
            market_score = market_scores.get(symbol)
            rs_score = (
                0.40 * market_score + 0.60 * sector_score
                if market_score is not None and sector_score is not None
                and symbol in sector_ranks.get(sector_id, {}) else None
            )
            missing_stock_windows = [
                f"{window}d" for window in _RS_WINDOWS if stock.get(window) is None
            ]
            missing_benchmark_windows = [
                f"{window}d" for window in _RS_WINDOWS if benchmark_returns[window] is None
            ]
            missing_sector_windows = [
                f"{window}d" for window in _RS_WINDOWS if sector.get(window) is None
            ]
            reasons: list[str] = []
            if missing_stock_windows:
                reasons.append("stock_history_incomplete_or_missing_trading_dates")
            if missing_benchmark_windows:
                reasons.append("benchmark_unavailable_or_insufficient_sample")
            if missing_sector_windows:
                reasons.append("sector_history_incomplete")
            if len(sector_scores.get(sector_id, {})) < _MIN_SECTOR_STOCKS:
                reasons.append("sector_member_count_below_minimum")
            results.append(RelativeStrengthResult(
                as_of=target,
                symbol=symbol,
                benchmark_id=_BENCHMARK_ID,
                sector_ids=all_sector_ids[symbol],
                membership_as_of=target if membership_source == "tushare_sw_index_member_all" else None,
                sector_id=sector_id,
                sector_name=str(context["sector_name"]),
                sector_kind=sector_kind,
                sector_level=context["sector_level"],
                sw1_code=context.get("sw1_code"),
                sw1_name=context.get("sw1_name"),
                sw2_code=context.get("sw2_code"),
                sw2_name=context.get("sw2_name"),
                sw3_code=context.get("sw3_code"),
                sw3_name=context.get("sw3_name"),
                stock_return_3d=stock.get(3),
                stock_return_5d=stock.get(5),
                stock_return_10d=stock.get(10),
                stock_return_20d=stock.get(20),
                stock_return_60d=stock.get(60),
                vs_market_3d=vs_market[3].get(symbol),
                vs_market_5d=vs_market[5].get(symbol),
                vs_market_10d=vs_market[10].get(symbol),
                vs_market_20d=vs_market[20].get(symbol),
                vs_market_60d=vs_market[60].get(symbol),
                market_rs_score=market_score,
                market_rank=market_ranks.get(symbol),
                market_percentile=market_score_percentiles.get(symbol),
                vs_sector_3d=sector_vs.get(sector_id, {}).get(3, {}).get(symbol),
                vs_sector_5d=sector_vs.get(sector_id, {}).get(5, {}).get(symbol),
                vs_sector_10d=sector_vs.get(sector_id, {}).get(10, {}).get(symbol),
                vs_sector_20d=sector_vs.get(sector_id, {}).get(20, {}).get(symbol),
                vs_sector_60d=sector_vs.get(sector_id, {}).get(60, {}).get(symbol),
                sector_rs_score=sector_score,
                sector_rank=sector_ranks.get(sector_id, {}).get(symbol),
                sector_percentile=sector_score_percentiles.get(sector_id, {}).get(symbol),
                rs_score=rs_score,
                rs_change_1d=None,
                rs_change_3d=None,
                market_rs_change_3d=None,
                sector_rs_change_3d=None,
                market_rank_change_3d=None,
                sector_rank_change_3d=None,
                stock_return_20d_percentile=stock_return_20d_percentiles.get(symbol),
                distance_from_ma20=extension_raw.get(symbol, {}).get("distance_from_ma20"),
                distance_from_ma60=extension_raw.get(symbol, {}).get("distance_from_ma60"),
                consecutive_up_days=extension_raw.get(symbol, {}).get("consecutive_up_days"),
                rs_extension_score=extension_scores.get(symbol),
                rs_extension_state=extension_state(extension_scores.get(symbol)),
                rs_state=None,
                state_reasons=("state_history_not_requested",),
                data_quality={
                    "status": "complete" if rs_score is not None else "partial",
                    "missing_stock_return_windows": missing_stock_windows,
                    "missing_benchmark_return_windows": missing_benchmark_windows,
                    "missing_sector_return_windows": missing_sector_windows,
                    "benchmark_valid_stock_count": benchmark_counts.get(target, 0),
                    "minimum_benchmark_stock_count": _MIN_BENCHMARK_STOCKS,
                    "eligible_sector_stock_count": len(sector_scores.get(sector_id, {})),
                    "minimum_sector_stock_count": _MIN_SECTOR_STOCKS,
                    "membership_source": membership_source,
                    "membership_note": membership_note_for_kind(sector_kind),
                    "state_status": "not_requested",
                    "state_missing_components": ["score_history"],
                },
                unavailable_reason=";".join(reasons) if reasons else None,
            ))
    results = sorted(results, key=lambda result: (result.symbol, result.sector_id))
    if not _include_state:
        return results

    # State deltas compare exact prior trading sessions.  Historical calls use
    # the same frozen computation with state recursion disabled; consequently
    # no result can observe a date later than its own ``as_of``.
    prior_by_lag: dict[int, dict[tuple[str, str], RelativeStrengthResult]] = {}
    for lag in (1, 3):
        if len(trading_dates) <= lag:
            continue
        prior_date = trading_dates[-1 - lag]
        previous = build_relative_strength(
            repo,
            sector_ids=sector_ids,
            as_of=prior_date,
            _include_state=False,
            _strict_industry_level=_strict_industry_level,
        )
        prior_by_lag[lag] = {
            (item.symbol, item.sector_id): item for item in previous
        }

    def change(
        current: float | None, previous: RelativeStrengthResult | None, field: str
    ) -> float | None:
        prior = getattr(previous, field) if previous is not None else None
        return current - prior if current is not None and prior is not None else None

    updated: list[RelativeStrengthResult] = []
    for result in results:
        key = (result.symbol, result.sector_id)
        previous_1d = prior_by_lag.get(1, {}).get(key)
        previous_3d = prior_by_lag.get(3, {}).get(key)
        rs_change_1d = change(result.rs_score, previous_1d, "rs_score")
        rs_change_3d = change(result.rs_score, previous_3d, "rs_score")
        market_rs_change_3d = change(
            result.market_rs_score, previous_3d, "market_rs_score"
        )
        sector_rs_change_3d = change(
            result.sector_rs_score, previous_3d, "sector_rs_score"
        )
        market_rank_change_3d = (
            previous_3d.market_rank - result.market_rank
            if previous_3d is not None
            and previous_3d.market_rank is not None
            and result.market_rank is not None else None
        )
        sector_rank_change_3d = (
            previous_3d.sector_rank - result.sector_rank
            if previous_3d is not None
            and previous_3d.sector_rank is not None
            and result.sector_rank is not None else None
        )
        state, state_reasons = relative_strength_state(
            rs_score=result.rs_score,
            rs_change_3d=rs_change_3d,
            extension=result.rs_extension_state,
        )
        missing_state_components = [
            name for name, value in {
                "rs_score": result.rs_score,
                "rs_change_3d": rs_change_3d,
                "rs_extension_score": result.rs_extension_score,
            }.items() if value is None
        ]
        data_quality = {
            **result.data_quality,
            "state_status": "complete" if state is not None else "partial",
            "state_missing_components": missing_state_components,
        }
        updated.append(replace(
            result,
            rs_change_1d=rs_change_1d,
            rs_change_3d=rs_change_3d,
            market_rs_change_3d=market_rs_change_3d,
            sector_rs_change_3d=sector_rs_change_3d,
            market_rank_change_3d=market_rank_change_3d,
            sector_rank_change_3d=sector_rank_change_3d,
            rs_state=state,
            state_reasons=state_reasons,
            data_quality=data_quality,
        ))
    return updated
