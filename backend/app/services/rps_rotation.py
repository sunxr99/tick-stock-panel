"""概念涨幅轮动矩阵 service。

输出「每列(日期)各自把所有概念按当天涨幅从高到低排序」的矩阵,供前端
「概念分析 → 涨幅RPS轮动」对话框渲染。

数据来源全部复用现有资产, 不引入新数据源:
  - 个股历史涨跌幅: repo.get_enriched_range(..., columns=["symbol","date","change_pct"])
    命中启动时构建的 _enriched_history_cache (0ms, 含 change_pct 小数列)
  - 概念成分股映射: 复用 market_overview_builder 的 _dimension_field / _read_ext_rows /
    _symbol_keys / _dimension_values, 与看板/复盘的概念聚合口径完全一致

性能: 387 概念 x 30 天的 group_by + sort 是 polars 内存操作, 实测 <50ms;
另加进程级结果缓存 (_CACHE_TTL=120s), 重复请求 <1ms。
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from math import prod
from statistics import pstdev

import polars as pl

from app.services.ext_data import ExtConfigStore
from app.services.market_overview_builder import (
    _dimension_field,
    _dimension_values,
    _read_ext_rows,
    _symbol_keys,
)
from app.services.sector_membership import canonicalize_member_map, resolve_sw_history
from app.services.strength_state import breadth_state, extension_state, sector_phase

logger = logging.getLogger(__name__)

# 进程级结果缓存 (照搬 overview.py:18 的模式, TTL 拉长到 120s —— 轮动矩阵
# 不像看板那样需要近实时, 盘后数据稳定, 缓存久一点无妨)
_CACHE_TTL = 120.0
_cache: dict[str, dict] = {}
_cache_ts: dict[str, float] = {}


def invalidate_cache() -> None:
    """清空轮动矩阵结果缓存(数据管道完成后调用, 避免返回旧数据)。"""
    _cache.clear()
    _cache_ts.clear()


def _latest_enriched_date(repo) -> date | None:
    """取 enriched 缓存里的最新交易日(矩阵的右端=最新日期)。"""
    cache = getattr(repo, "_enriched_history_cache", None)  # 缓存字段无公开 getter
    if cache is None or cache.is_empty() or "date" not in cache.columns:
        return None
    return cache["date"].max()


def _load_concept_map_df(
    repo, kind: str = "concept", as_of: date | None = None
) -> tuple[pl.DataFrame, int]:
    """构建并缓存 {symbol_upper → 维度成员} 的已展开 polars 映射表。

    kind: "concept"(概念) 或 "industry"(行业)。复用 market_overview_builder 的
    _dimension_field(config, kind) 识别维度 —— 该函数两种维度都支持。

    返回 (map_df, member_count):
      - map_df: 两列 (_sym_up: 大写 symbol, <kind>: 维度成员名), 已 explode。
        无数据时返回空 DataFrame。
      - member_count: 去重维度成员总数。

    缓存: 维度成分股是 snapshot, 进程内不变, 缓存 600s。按 kind 分别缓存。
    """
    # Industry calculations use the dedicated SW interval store for both
    # historical and current requests.  A missing SW file still falls back to
    # the existing extension snapshot so deployments can start before the
    # local import is completed.  Concept calculations deliberately retain
    # the THS snapshot because SW has no concept-membership taxonomy.
    if kind == "industry":
        target = as_of or _latest_enriched_date(repo) or date.today()
        resolved = resolve_sw_history(repo.store.data_dir, as_of=target)
        if resolved is not None and not resolved.frame.is_empty():
            _map_source[kind] = "tushare_sw_index_member_all"
            return resolved.frame, resolved.frame.get_column("industry").n_unique()

    now = time.time()
    cached = _map_cache.get(kind)
    if cached is not None and (now - _map_ts.get(kind, 0)) < 600:
        # Keep the return contract identical to the cold path.  Returning the
        # DataFrame by itself makes callers unpack its columns as Series,
        # which breaks the daily concept-membership snapshot on cache hits.
        member_count = cached.get_column(kind).n_unique() if kind in cached.columns else 0
        return cached, member_count

    data_dir = repo.store.data_dir
    store = ExtConfigStore(data_dir)
    pairs: list[tuple[str, str]] = []
    members_seen: set[str] = set()

    for config in store.load_all():
        field = _dimension_field(config, kind)
        if not field:
            continue
        for ext_row in _read_ext_rows(data_dir, config, field):
            members = _dimension_values(ext_row.get(field))
            if not members:
                continue
            keys = _symbol_keys(ext_row, config)
            for key in keys:
                for m in members:
                    pairs.append((key, m))
                    members_seen.add(m)

    if pairs:
        raw_map_df = pl.DataFrame(
            {"_sym_up": [p[0] for p in pairs], kind: [p[1] for p in pairs]},
            schema={"_sym_up": pl.Utf8, kind: pl.Utf8},
        )
        # _symbol_keys intentionally exposes both `600000.SH` and `600000`
        # for overview lookup compatibility.  Sector membership is a countable
        # universe, so collapse those aliases before member_count/coverage and
        # before joining enriched's exchange-qualified symbols.
        map_df = canonicalize_member_map(raw_map_df, kind)
    else:
        map_df = pl.DataFrame(schema={"_sym_up": pl.Utf8, kind: pl.Utf8})
    _map_cache[kind] = map_df
    _map_ts[kind] = now
    _map_source[kind] = "current_ext_snapshot"
    return map_df, len(members_seen)


def load_current_member_map(repo, kind: str) -> pl.DataFrame:
    """Return the canonical current membership map for prospective research.

    This deliberately reuses the same mapping that Sector Strength consumes.
    Industry callers receive the current-date SW interval resolution; concept
    callers receive the current THS snapshot.  Callers that persist it must
    label it with the capture date.
    """
    map_df, _ = _load_concept_map_df(repo, kind)
    return map_df


# 维度映射缓存: {kind: (map_df, count)}。按 kind 隔离(概念/行业分别缓存)。
_map_cache: dict[str, pl.DataFrame] = {}
_map_ts: dict[str, float] = {}
_map_source: dict[str, str] = {}


# Sector Strength V1 is deliberately an extension of this module's existing
# member-map + daily equal-weight aggregation.  It is not a second rotation
# engine and has no strategy-selection side effects.
_STRENGTH_WINDOWS = (3, 5, 10, 20)
_RANK_WINDOW = 20
_RANK_HISTORY_DAYS = 3
_PERSISTENCE_LOOKBACK = 60
_BENCHMARK_ID = "all_stock_equal_weight"
_STRONG_STOCK_THRESHOLD = 0.03
_MEMBERSHIP_NOTE = "成员关系使用当前同花顺扩展数据快照, 概念历史回溯可能存在归属漂移"
_SW_MEMBERSHIP_NOTE = "行业成员关系来自申万 index_member_all 的 in_date/out_date 区间"
_SECTOR_DISPLAY_NAME = "_sector_display_name"


def membership_source_for_kind(kind: str) -> str:
    """Return the configured membership provenance for a sector dimension."""
    return _map_source.get(
        kind,
        "tushare_sw_index_member_all" if kind == "industry" else "current_ext_snapshot",
    )


def membership_note_for_kind(kind: str) -> str:
    """Return a user-facing note describing the membership time semantics."""
    return _SW_MEMBERSHIP_NOTE if kind == "industry" else _MEMBERSHIP_NOTE
_RELATIVE_MOMENTUM_WEIGHTS = {3: 0.20, 5: 0.25, 10: 0.25, 20: 0.30}
_BREADTH_WEIGHTS = {"up_ratio": 0.70, "strong_stock_ratio": 0.30}
_SCORE_WEIGHTS = {"relative_momentum": 0.55, "breadth": 0.30, "persistence": 0.15}
_PERSISTENCE_SCORE_CAP = 20


@dataclass(frozen=True)
class SectorStrengthResult:
    """一个板块在单个交易日的可解释日频强度结果。

    ``score`` is a fixed blend of normalized relative momentum, breadth, and
    persistence.  Its inputs and component scores remain alongside the raw
    return and breadth fields so the ranking is always reproducible.
    """

    as_of: date
    kind: str
    sector_id: str
    name: str
    level: int | None
    member_count: int
    valid_member_count: int
    return_3d: float | None
    return_5d: float | None
    return_10d: float | None
    return_20d: float | None
    relative_return_3d: float | None
    relative_return_5d: float | None
    relative_return_10d: float | None
    relative_return_20d: float | None
    relative_return_percentile_3d: float | None
    relative_return_percentile_5d: float | None
    relative_return_percentile_10d: float | None
    relative_return_percentile_20d: float | None
    up_ratio: float | None
    strong_stock_ratio: float | None
    up_ratio_percentile: float | None
    strong_stock_ratio_percentile: float | None
    relative_momentum_score: float | None
    breadth_score: float | None
    persistence_score: float | None
    score: float | None
    rank: int | None
    percentile: float | None
    rank_change_1d: int | None
    rank_change_3d: int | None
    rank_std_5d: float | None
    persistence_days: int
    coverage_ratio: float
    score_change_1d: float | None
    score_change_3d: float | None
    percentile_change_1d: float | None
    percentile_change_3d: float | None
    score_slope_3d: float | None
    score_slope_5d: float | None
    rank_slope_3d: float | None
    up_ratio_change_1d: float | None
    up_ratio_change_3d: float | None
    strong_stock_ratio_change_1d: float | None
    strong_stock_ratio_change_3d: float | None
    breadth_state: str | None
    return_20d_percentile: float | None
    distance_from_ma20: float | None
    distance_from_ma60: float | None
    consecutive_up_days: int | None
    extension_score: float | None
    extension_state: str | None
    phase: str | None
    phase_reasons: tuple[str, ...]
    data_quality: dict[str, object]


def _normalized_map(
    map_df: pl.DataFrame,
    kind: str,
    level: int | None,
    *,
    strict_industry_level: bool = False,
) -> pl.DataFrame:
    """Apply the same industry-level rule as rotation and overview."""
    if kind != "industry" or level is None:
        return map_df
    code_column = f"sw{level}_code"
    name_column = f"sw{level}_name"
    # SW names are presentation fields and can change.  When the interval
    # store carries the vendor codes, calculations and stable IDs must group
    # on those codes; the matching name remains alongside the map for API/UI
    # output.  Old name-only stores deliberately retain the legacy path below.
    has_codes = (
        code_column in map_df.columns
        and map_df.get_column(code_column).drop_nulls().cast(pl.Utf8).str.strip_chars().ne("").any()
    )
    if has_codes:
        return (
            map_df.with_columns(
                pl.col(code_column).cast(pl.Utf8).str.strip_chars().alias(kind),
                pl.coalesce([
                    pl.col(name_column).cast(pl.Utf8).str.strip_chars(),
                    pl.col(code_column).cast(pl.Utf8).str.strip_chars(),
                ]).alias(_SECTOR_DISPLAY_NAME),
            )
            .filter(pl.col(kind).is_not_null() & pl.col(kind).ne(""))
            .unique()
        )
    parts = pl.col(kind).str.split("-")
    if strict_industry_level:
        # V2 must never reinterpret an SW1-only record as SW2/SW3.  Older
        # persisted files may have one path segment; they remain readable but
        # are explicitly unavailable at the requested deeper level.
        return (
            map_df.with_columns(
                pl.when(parts.list.len() > level - 1)
                .then(parts.list.get(level - 1, null_on_oob=True))
                .otherwise(pl.lit(None, dtype=pl.Utf8))
                .alias(kind),
                pl.when(parts.list.len() > level - 1)
                .then(parts.list.get(level - 1, null_on_oob=True))
                .otherwise(pl.lit(None, dtype=pl.Utf8))
                .alias(_SECTOR_DISPLAY_NAME),
            )
            .filter(pl.col(kind).is_not_null() & pl.col(kind).ne(""))
            .unique()
        )
    idx = pl.min_horizontal(pl.lit(level - 1), pl.col(kind).str.count_matches("-"))
    return map_df.with_columns(
        parts.list.get(idx).alias(kind),
        parts.list.get(idx).alias(_SECTOR_DISPLAY_NAME),
    ).unique()


def _history_dates(repo, as_of: date | None) -> tuple[list[date], date | None]:
    """Read trading dates from the same enriched cache used by rotation.

    A requested historical date must itself be an enriched trading date.  This
    avoids silently aligning a historical result to the nearest calendar day.
    """
    cache = getattr(repo, "_enriched_history_cache", None)
    if cache is None or cache.is_empty() or "date" not in cache.columns:
        return [], None
    dates = sorted(cache.get_column("date").unique().to_list())
    if not dates:
        return [], None
    target = as_of or dates[-1]
    if target not in set(dates):
        return [], None
    return [d for d in dates if d <= target], target


def _compound_return(values: list[float]) -> float:
    return prod(1.0 + value for value in values) - 1.0


def _window_return(
    daily_values: dict[date, float], dates: list[date], index: int, window: int
) -> float | None:
    start = index - window + 1
    if start < 0:
        return None
    window_dates = dates[start:index + 1]
    if any(d not in daily_values for d in window_dates):
        return None
    return _compound_return([daily_values[d] for d in window_dates])


def _rank_values(values: dict[str, float]) -> tuple[dict[str, int], dict[str, float]]:
    """Descending ranks plus tie-aware 0--100 cross-sectional percentiles."""
    ordered = sorted(values, key=lambda sector: (-values[sector], sector))
    total = len(ordered)
    ranks = {sector: index + 1 for index, sector in enumerate(ordered)}
    if total == 1:
        return ranks, {ordered[0]: 100.0}
    percentiles: dict[str, float] = {}
    position = 0
    while position < total:
        value = values[ordered[position]]
        end = position + 1
        while end < total and values[ordered[end]] == value:
            end += 1
        average_rank = ((position + 1) + end) / 2
        percentile = 100.0 * (total - average_rank) / (total - 1)
        for sector in ordered[position:end]:
            percentiles[sector] = percentile
        position = end
    return ranks, percentiles


def _market_daily_returns(df: pl.DataFrame) -> tuple[dict[date, float], dict[date, int]]:
    """Build the all-A equal-weight benchmark from the normalized stock panel.

    The result deliberately uses the full enriched stock universe before the
    sector-member join.  A date with no valid stock returns is absent rather
    than forward-filled, which makes every relative-return window date-exact.
    """
    if df.is_empty():
        return {}, {}
    valid = df.filter(
        pl.col("change_pct").is_not_null() & pl.col("change_pct").is_finite()
    )
    daily = valid.group_by("date").agg(
        pl.col("change_pct").mean().alias("market_return"),
        pl.len().alias("valid_stock_count"),
    )
    return (
        {row["date"]: float(row["market_return"]) for row in daily.iter_rows(named=True)},
        {row["date"]: int(row["valid_stock_count"]) for row in daily.iter_rows(named=True)},
    )


def _rank_std_5d(
    rank_history: dict[date, dict[str, int]],
    dates: list[date],
    index: int,
    sector: str,
) -> float | None:
    """Return population rank standard deviation over five exact sessions."""
    if index < 4:
        return None
    window_dates = dates[index - 4:index + 1]
    values = [rank_history[d].get(sector) for d in window_dates]
    if any(value is None for value in values):
        return None
    return pstdev(float(value) for value in values if value is not None)


def _history_change(
    history: dict[date, dict[str, float]], dates: list[date], index: int, key: str, lag: int
) -> float | None:
    if index < lag:
        return None
    current = history.get(dates[index], {}).get(key)
    previous = history.get(dates[index - lag], {}).get(key)
    return current - previous if current is not None and previous is not None else None


def _distance_from_ma(
    daily_values: dict[date, float], dates: list[date], index: int, window: int
) -> float | None:
    """Distance of a return-derived equal-weight index from its exact-session MA."""
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


def build_sector_strength(
    repo,
    *,
    kind: str = "concept",
    level: int | None = None,
    as_of: date | None = None,
    _strict_industry_level: bool = False,
    _min_industry_members: int = 0,
) -> list[SectorStrengthResult]:
    """Build daily Sector Strength V1 results for concept or industry groups.

    Returns are compounded from the existing daily equal-weight member return.
    A sector is eligible for a window only when it and the benchmark both have
    every required *trading* date; absent data is exposed as ``None`` rather
    than being backfilled from an earlier date.
    """
    if kind not in {"concept", "industry"}:
        raise ValueError("kind must be 'concept' or 'industry'")
    if _min_industry_members < 0:
        raise ValueError("_min_industry_members must be non-negative")
    if kind != "industry":
        level = None
    elif level is not None and level not in {1, 2, 3}:
        raise ValueError("industry level must be 1, 2, or 3")

    trading_dates, target = _history_dates(repo, as_of)
    if target is None:
        return []
    # A rank at t-3 needs 20 daily returns ending at t-3.  The additional
    # lookback supports a bounded, deterministic persistence count.
    required_dates = _RANK_WINDOW + _RANK_HISTORY_DAYS + _PERSISTENCE_LOOKBACK
    dates = trading_dates[-required_dates:]
    if not dates:
        return []

    loaded = _load_concept_map_df(repo, kind, target)
    map_df = loaded[0] if isinstance(loaded, tuple) else loaded
    if map_df.is_empty():
        return []
    map_df = _normalized_map(
        map_df, kind, level, strict_industry_level=_strict_industry_level
    )
    if map_df.is_empty():
        return []

    display_names = {
        str(row[kind]): str(row.get(_SECTOR_DISPLAY_NAME) or row[kind])
        for row in map_df.select(kind, *([_SECTOR_DISPLAY_NAME] if _SECTOR_DISPLAY_NAME in map_df.columns else [])).unique().iter_rows(named=True)
    }

    member_counts = {
        row[kind]: int(row["member_count"])
        for row in map_df.group_by(kind).agg(
            pl.col("_sym_up").n_unique().alias("member_count")
        ).iter_rows(named=True)
    }
    if kind == "industry" and _min_industry_members:
        eligible = {
            sector for sector, count in member_counts.items()
            if count >= _min_industry_members
        }
        map_df = map_df.filter(pl.col(kind).is_in(sorted(eligible)))
        member_counts = {
            sector: count for sector, count in member_counts.items()
            if sector in eligible
        }
        if map_df.is_empty():
            return []
    df = repo.get_enriched_range(
        dates[0], target, columns=["symbol", "date", "change_pct"]
    )
    if df is None or df.is_empty() or not {"symbol", "date", "change_pct"}.issubset(df.columns):
        return []

    valid_df = df.filter(
        pl.col("change_pct").is_not_null() & pl.col("change_pct").is_finite()
    )
    joined = (
        valid_df
        .with_columns(pl.col("symbol").str.to_uppercase().alias("_sym_up"))
        .join(map_df, on="_sym_up", how="inner")
    )
    if joined.is_empty():
        return []
    daily = joined.group_by(["date", kind]).agg(
        pl.col("change_pct").mean().alias("daily_return"),
        pl.len().alias("valid_member_count"),
        pl.col("change_pct").gt(0).sum().alias("up_count"),
        pl.col("change_pct").ge(_STRONG_STOCK_THRESHOLD).sum().alias("strong_stock_count"),
    )
    if daily.is_empty():
        return []

    sector_daily: dict[str, dict[date, dict[str, float | int]]] = defaultdict(dict)
    for row in daily.iter_rows(named=True):
        sector_daily[str(row[kind])][row["date"]] = row

    benchmark_daily, benchmark_counts = _market_daily_returns(valid_df)
    benchmark_returns: dict[date, dict[int, float | None]] = {}
    sector_returns: dict[date, dict[str, dict[int, float | None]]] = {}

    for index, current_date in enumerate(dates):
        benchmark_returns[current_date] = {
            window: _window_return(benchmark_daily, dates, index, window)
            for window in _STRENGTH_WINDOWS
        }
        current_sector_returns: dict[str, dict[int, float | None]] = {}
        for sector, by_date in sector_daily.items():
            returns = {
                window: _window_return(
                    {d: float(row["daily_return"]) for d, row in by_date.items()},
                    dates,
                    index,
                    window,
                )
                for window in _STRENGTH_WINDOWS
            }
            current_sector_returns[sector] = returns
        sector_returns[current_date] = current_sector_returns

    # First normalize raw factors independently for every date.  This creates
    # comparable 0--100 inputs without using future dates or an optimized
    # weight search.
    factor_history: dict[date, dict[str, dict[str, float | None]]] = {}
    momentum_history: dict[date, dict[str, float]] = {}
    breadth_history: dict[date, dict[str, float]] = {}
    up_ratio_history: dict[date, dict[str, float]] = {}
    strong_stock_ratio_history: dict[date, dict[str, float]] = {}
    for current_date in dates:
        relatives_by_window: dict[int, dict[str, float]] = {}
        for window in _STRENGTH_WINDOWS:
            benchmark_return = benchmark_returns[current_date][window]
            relatives_by_window[window] = {
                sector: float(returns[window]) - float(benchmark_return)
                for sector, returns in sector_returns[current_date].items()
                if returns.get(window) is not None and benchmark_return is not None
            }
        relative_percentiles = {
            window: _rank_values(values)[1] if values else {}
            for window, values in relatives_by_window.items()
        }
        up_ratios: dict[str, float] = {}
        strong_ratios: dict[str, float] = {}
        for sector, by_date in sector_daily.items():
            row = by_date.get(current_date)
            if row is None or not int(row["valid_member_count"]):
                continue
            valid_count = int(row["valid_member_count"])
            up_ratios[sector] = float(row["up_count"]) / valid_count
            strong_ratios[sector] = float(row["strong_stock_count"]) / valid_count
        up_percentiles = _rank_values(up_ratios)[1] if up_ratios else {}
        strong_percentiles = _rank_values(strong_ratios)[1] if strong_ratios else {}
        up_ratio_history[current_date] = up_ratios
        strong_stock_ratio_history[current_date] = strong_ratios

        factor_history[current_date] = {}
        for sector in sector_daily:
            relative_scores = [relative_percentiles[window].get(sector) for window in _STRENGTH_WINDOWS]
            relative_momentum = (
                sum(
                    _RELATIVE_MOMENTUM_WEIGHTS[window] * relative_percentiles[window][sector]
                    for window in _STRENGTH_WINDOWS
                )
                if all(score is not None for score in relative_scores) else None
            )
            up_percentile = up_percentiles.get(sector)
            strong_percentile = strong_percentiles.get(sector)
            breadth_score = (
                _BREADTH_WEIGHTS["up_ratio"] * up_percentile
                + _BREADTH_WEIGHTS["strong_stock_ratio"] * strong_percentile
                if up_percentile is not None and strong_percentile is not None else None
            )
            factor_history[current_date][sector] = {
                **{
                    f"relative_return_percentile_{window}d": relative_percentiles[window].get(sector)
                    for window in _STRENGTH_WINDOWS
                },
                "up_ratio_percentile": up_percentile,
                "strong_stock_ratio_percentile": strong_percentile,
                "relative_momentum_score": relative_momentum,
                "breadth_score": breadth_score,
            }
            if relative_momentum is not None:
                momentum_history.setdefault(current_date, {})[sector] = relative_momentum
            if breadth_score is not None:
                breadth_history.setdefault(current_date, {})[sector] = breadth_score

    # Persistence deliberately comes from the prior, independent momentum
    # factor.  Using final score rank here would make the score circular.
    persistence_history: dict[date, dict[str, int]] = {}
    persistence_score_history: dict[date, dict[str, float]] = {}
    running_persistence: dict[str, int] = defaultdict(int)
    for current_date in dates:
        _, momentum_percentiles = _rank_values(momentum_history.get(current_date, {}))
        current_persistence: dict[str, int] = {}
        current_scores: dict[str, float] = {}
        for sector in sector_daily:
            if momentum_percentiles.get(sector, -1.0) >= 75.0:
                running_persistence[sector] += 1
            else:
                running_persistence[sector] = 0
            current_persistence[sector] = running_persistence[sector]
            if sector in momentum_percentiles:
                current_scores[sector] = min(
                    running_persistence[sector], _PERSISTENCE_SCORE_CAP
                ) * 100.0 / _PERSISTENCE_SCORE_CAP
        persistence_history[current_date] = current_persistence
        persistence_score_history[current_date] = current_scores

    score_history: dict[date, dict[str, float]] = {}
    rank_history: dict[date, dict[str, int]] = {}
    percentile_history: dict[date, dict[str, float]] = {}
    for current_date in dates:
        scores: dict[str, float] = {}
        for sector, factors in factor_history[current_date].items():
            relative_momentum = factors["relative_momentum_score"]
            breadth_score = factors["breadth_score"]
            persistence_score = persistence_score_history[current_date].get(sector)
            if (
                relative_momentum is not None
                and breadth_score is not None
                and persistence_score is not None
            ):
                scores[sector] = (
                    _SCORE_WEIGHTS["relative_momentum"] * float(relative_momentum)
                    + _SCORE_WEIGHTS["breadth"] * float(breadth_score)
                    + _SCORE_WEIGHTS["persistence"] * persistence_score
                )
        score_history[current_date] = scores
        rank_history[current_date], percentile_history[current_date] = _rank_values(scores) if scores else ({}, {})

    target_index = dates.index(target)
    current_ranks = rank_history[target]
    current_percentiles = percentile_history[target]

    previous_1d = dates[target_index - 1] if target_index >= 1 else None
    previous_3d = dates[target_index - 3] if target_index >= 3 else None

    # Extension is deliberately separate from the frozen strength score.  All
    # four inputs are normalized cross-sectionally on the same as-of session;
    # the raw values remain in the result for inspection.
    return_20d_values = {
        sector: float(returns[20])
        for sector, returns in sector_returns[target].items()
        if returns.get(20) is not None
    }
    _, return_20d_percentiles = _rank_values(return_20d_values) if return_20d_values else ({}, {})
    distance_ma20_values: dict[str, float] = {}
    distance_ma60_values: dict[str, float] = {}
    consecutive_up_values: dict[str, float] = {}
    extension_raw: dict[str, dict[str, float | int | None]] = {}
    for sector, by_date in sector_daily.items():
        daily_values = {current_date: float(row["daily_return"]) for current_date, row in by_date.items()}
        distance_ma20 = _distance_from_ma(daily_values, dates, target_index, 20)
        distance_ma60 = _distance_from_ma(daily_values, dates, target_index, 60)
        consecutive_up = _consecutive_up_days(daily_values, dates, target_index)
        extension_raw[sector] = {
            "distance_from_ma20": distance_ma20,
            "distance_from_ma60": distance_ma60,
            "consecutive_up_days": consecutive_up,
        }
        if distance_ma20 is not None:
            distance_ma20_values[sector] = distance_ma20
        if distance_ma60 is not None:
            distance_ma60_values[sector] = distance_ma60
        if consecutive_up is not None:
            consecutive_up_values[sector] = float(consecutive_up)
    _, distance_ma20_percentiles = _rank_values(distance_ma20_values) if distance_ma20_values else ({}, {})
    _, distance_ma60_percentiles = _rank_values(distance_ma60_values) if distance_ma60_values else ({}, {})
    _, consecutive_up_percentiles = _rank_values(consecutive_up_values) if consecutive_up_values else ({}, {})
    extension_scores: dict[str, float] = {}
    for sector in sector_daily:
        components = (
            return_20d_percentiles.get(sector),
            distance_ma20_percentiles.get(sector),
            distance_ma60_percentiles.get(sector),
            consecutive_up_percentiles.get(sector),
        )
        if all(value is not None for value in components):
            extension_scores[sector] = sum(float(value) for value in components) / len(components)

    results: list[SectorStrengthResult] = []
    for sector in sorted(sector_daily):
        latest = sector_daily[sector].get(target)
        if latest is None:
            continue
        returns = sector_returns[target].get(sector, {})
        relatives = {
            window: (
                None
                if returns.get(window) is None or benchmark_returns[target][window] is None
                else float(returns[window]) - float(benchmark_returns[target][window])
            )
            for window in _STRENGTH_WINDOWS
        }
        member_count = member_counts.get(sector, 0)
        valid_member_count = int(latest["valid_member_count"])
        coverage_ratio = valid_member_count / member_count if member_count else 0.0
        missing_windows = [
            f"{window}d" for window in _STRENGTH_WINDOWS
            if returns.get(window) is None or benchmark_returns[target][window] is None
        ]
        current_rank = current_ranks.get(sector)
        rank_change_1d = (
            rank_history[previous_1d].get(sector) - current_rank
            if current_rank is not None and previous_1d is not None
            and rank_history[previous_1d].get(sector) is not None else None
        )
        rank_change_3d = (
            rank_history[previous_3d].get(sector) - current_rank
            if current_rank is not None and previous_3d is not None
            and rank_history[previous_3d].get(sector) is not None else None
        )
        score_change_1d = _history_change(score_history, dates, target_index, sector, 1)
        score_change_3d = _history_change(score_history, dates, target_index, sector, 3)
        score_change_5d = _history_change(score_history, dates, target_index, sector, 5)
        percentile_change_1d = _history_change(percentile_history, dates, target_index, sector, 1)
        percentile_change_3d = _history_change(percentile_history, dates, target_index, sector, 3)
        up_ratio_change_1d = _history_change(up_ratio_history, dates, target_index, sector, 1)
        up_ratio_change_3d = _history_change(up_ratio_history, dates, target_index, sector, 3)
        strong_stock_ratio_change_1d = _history_change(
            strong_stock_ratio_history, dates, target_index, sector, 1
        )
        strong_stock_ratio_change_3d = _history_change(
            strong_stock_ratio_history, dates, target_index, sector, 3
        )
        current_extension_score = extension_scores.get(sector)
        current_extension_state = extension_state(current_extension_score)
        current_breadth_state = breadth_state(
            up_ratio_change_3d, strong_stock_ratio_change_3d
        )
        current_phase, phase_reasons = sector_phase(
            percentile=current_percentiles.get(sector),
            score_change_3d=score_change_3d,
            rank_change_3d=rank_change_3d,
            breadth=current_breadth_state,
            extension=current_extension_state,
        )
        factors = factor_history[target].get(sector, {})
        score = score_history[target].get(sector)
        missing_score_components = [
            component for component, value in {
                "relative_momentum": factors.get("relative_momentum_score"),
                "breadth": factors.get("breadth_score"),
                "persistence": persistence_score_history[target].get(sector),
            }.items() if value is None
        ]
        state_missing_components = [
            name for name, value in {
                "score_change_3d": score_change_3d,
                "rank_change_3d": rank_change_3d,
                "breadth_state": current_breadth_state,
                "extension_score": current_extension_score,
            }.items() if value is None
        ]
        data_quality: dict[str, object] = {
            "status": (
                "complete"
                if not missing_windows and not missing_score_components and coverage_ratio == 1.0
                else "partial"
            ),
            "rank_basis": "sector_strength_score",
            "missing_return_windows": missing_windows,
            "missing_score_components": missing_score_components,
            "benchmark_id": _BENCHMARK_ID,
            "benchmark_available": bool(benchmark_returns[target][_RANK_WINDOW] is not None),
            "benchmark_valid_stock_count": benchmark_counts.get(target, 0),
            "persistence_basis": "relative_momentum_score percentile >= 75",
            "membership_source": membership_source_for_kind(kind),
            "membership_note": membership_note_for_kind(kind),
            "state_status": "complete" if not state_missing_components else "partial",
            "state_missing_components": state_missing_components,
        }
        results.append(SectorStrengthResult(
            as_of=target,
            kind=kind,
            sector_id=f"{kind}:{level or 'all'}:{sector}",
            name=display_names.get(sector, sector),
            level=level,
            member_count=member_count,
            valid_member_count=valid_member_count,
            return_3d=returns.get(3),
            return_5d=returns.get(5),
            return_10d=returns.get(10),
            return_20d=returns.get(20),
            relative_return_3d=relatives[3],
            relative_return_5d=relatives[5],
            relative_return_10d=relatives[10],
            relative_return_20d=relatives[20],
            relative_return_percentile_3d=factors.get("relative_return_percentile_3d"),
            relative_return_percentile_5d=factors.get("relative_return_percentile_5d"),
            relative_return_percentile_10d=factors.get("relative_return_percentile_10d"),
            relative_return_percentile_20d=factors.get("relative_return_percentile_20d"),
            up_ratio=float(latest["up_count"]) / valid_member_count if valid_member_count else None,
            strong_stock_ratio=(
                float(latest["strong_stock_count"]) / valid_member_count
                if valid_member_count else None
            ),
            up_ratio_percentile=factors.get("up_ratio_percentile"),
            strong_stock_ratio_percentile=factors.get("strong_stock_ratio_percentile"),
            relative_momentum_score=factors.get("relative_momentum_score"),
            breadth_score=factors.get("breadth_score"),
            persistence_score=persistence_score_history[target].get(sector),
            score=score,
            rank=current_rank,
            percentile=current_percentiles.get(sector),
            rank_change_1d=rank_change_1d,
            rank_change_3d=rank_change_3d,
            rank_std_5d=_rank_std_5d(rank_history, dates, target_index, sector),
            persistence_days=persistence_history[target].get(sector, 0),
            coverage_ratio=coverage_ratio,
            score_change_1d=score_change_1d,
            score_change_3d=score_change_3d,
            percentile_change_1d=percentile_change_1d,
            percentile_change_3d=percentile_change_3d,
            score_slope_3d=score_change_3d / 3.0 if score_change_3d is not None else None,
            score_slope_5d=score_change_5d / 5.0 if score_change_5d is not None else None,
            rank_slope_3d=rank_change_3d / 3.0 if rank_change_3d is not None else None,
            up_ratio_change_1d=up_ratio_change_1d,
            up_ratio_change_3d=up_ratio_change_3d,
            strong_stock_ratio_change_1d=strong_stock_ratio_change_1d,
            strong_stock_ratio_change_3d=strong_stock_ratio_change_3d,
            breadth_state=current_breadth_state,
            return_20d_percentile=return_20d_percentiles.get(sector),
            distance_from_ma20=extension_raw.get(sector, {}).get("distance_from_ma20"),
            distance_from_ma60=extension_raw.get(sector, {}).get("distance_from_ma60"),
            consecutive_up_days=extension_raw.get(sector, {}).get("consecutive_up_days"),
            extension_score=current_extension_score,
            extension_state=current_extension_state,
            phase=current_phase,
            phase_reasons=phase_reasons,
            data_quality=data_quality,
        ))
    return sorted(results, key=lambda result: (result.rank is None, result.rank or 0, result.sector_id))


def build_rps_rotation(repo, days: int = 12, kind: str = "concept", level: int | None = None) -> dict:
    """构建维度涨幅轮动矩阵(概念或行业)。

    Args:
        repo: KlineRepository(含 _enriched_history_cache 内存历史)。
        days: 取最近 N 个交易日, 范围 [7, 30], 默认 12。
        kind: "concept"(概念) 或 "industry"(行业), 决定维度映射来源。
        level: 行业层级(仅 kind=industry 有效, 1/2/3 级)。None 表示用原始全路径名。
            行业名形如 "银行-银行-股份制银行", level=2 取第二段"银行", 同级下多个
            三级会合并聚合(与 _dimension_rank 的 level 口径一致)。

    Returns:
        {
          "dates": ["2026-06-30", ...],          # 最新在最前, 长度 ≤ days
          "columns": {"2026-06-30": [[成员, 涨幅], ...], ...},  # 每列各自排序(高→低)
          "concept_count": 387,                   # 去重维度成员总数(0 表示无数据)
        }
        涨幅是小数(0.0522 = +5.22%)。无数据时返回空 columns。
        字段名 concept_count 保留兼容(前端按 kind 显示"X 个概念/行业")。
    """
    days = max(7, min(30, days))

    # 结果缓存: 同 (kind, level, latest) 的请求在 TTL 内直接返回。
    latest = _latest_enriched_date(repo)
    if latest is None:
        return {"dates": [], "columns": {}, "concept_count": 0}

    cache_key = f"{kind}|{level}|{latest.isoformat()}"
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and (now - _cache_ts.get(cache_key, 0)) < _CACHE_TTL:
        return _slice_cached(cached, days)

    # 1. 维度映射(symbol → 维度成员), 已按 kind 缓存为 polars DataFrame。
    #    兼容返回裸 DataFrame 的实现: 元组解包会把两列拆成 Series(见
    #    market_mainline.compute_mainline_range 同类处理)。
    loaded = _load_concept_map_df(repo, kind)
    if isinstance(loaded, tuple):
        map_df, member_count = loaded
    else:
        map_df = loaded
        member_count = loaded[kind].n_unique() if kind in loaded.columns else 0
    if map_df.is_empty():
        logger.info("rps_rotation: no %s data (ext dimension not fetched yet)", kind)
        return {"dates": [], "columns": {}, "concept_count": 0}

    # 2. 取最近 N 交易日的个股 change_pct(命中内存缓存)
    start = latest - timedelta(days=days * 2 + 10)  # 日历天 ≈ 2/3 交易日, 多取余量
    df = repo.get_enriched_range(
        start, latest, columns=["symbol", "date", "change_pct"]
    )
    if df is None or df.is_empty():
        return {"dates": [], "columns": {}, "concept_count": 0}

    # 3. 把个股 symbol 映射到维度成员, 一只股票拆成多行(每个成员一行)
    #    symbol 大写匹配(map_df 的 _sym_up 已大写)
    df = df.with_columns(pl.col("symbol").str.to_uppercase().alias("_sym_up"))
    joined = df.join(map_df, on="_sym_up", how="inner").drop("_sym_up")

    if joined.is_empty():
        return {"dates": [], "columns": {}, "concept_count": 0}

    # 行业层级聚合: kind=industry 且指定 level 时, 把 "一级行业-二级行业-三级行业"
    # 拆分取对应层级(level=2 → "二级行业"), 同级下多个三级会合并。
    # 与 market_overview_builder._dimension_rank 的 level 口径完全一致。
    if kind == "industry" and level is not None:
        # polars: 按 "-" 拆分取第 level 段; 段数不足时取最后一段(兜底)
        parts = pl.col(kind).str.split("-")
        idx = pl.min_horizontal(pl.lit(level - 1), pl.col(kind).str.count_matches("-"))
        joined = joined.with_columns(parts.list.get(idx).alias(kind))

    # 4. 按 (date, <kind>) 聚合 avg change_pct —— 与 _dimension_rank 的简单平均口径一致
    agg = joined.group_by(["date", kind]).agg(
        pl.col("change_pct").mean().alias("avg_pct")
    )
    # 去掉 NaN/Null(停牌等无行情的成员日)
    agg = agg.filter(pl.col("avg_pct").is_not_null() & pl.col("avg_pct").is_not_nan())

    # 5. 每个日期内按 avg_pct 降序排, 再 group_by 把每组的 (成员, avg_pct)
    #    收集成并行 list —— 一次 polars 操作拿到全部列, 避免 partition_by 的 tuple key 歧义
    agg = agg.sort(["date", "avg_pct"], descending=[False, True])
    grouped = agg.group_by("date", maintain_order=True).agg(
        pl.col(kind), pl.col("avg_pct")
    )
    # 最新日期排最前
    grouped = grouped.sort("date", descending=True)

    columns: dict[str, list[list]] = {}
    all_dates_sorted: list[str] = []
    for row in grouped.iter_rows(named=True):
        d_str = str(row["date"])
        all_dates_sorted.append(d_str)
        columns[d_str] = list(zip(row[kind], row["avg_pct"], strict=True))

    full = {
        "dates": [str(d) for d in all_dates_sorted],
        "columns": columns,
        "concept_count": member_count,
    }

    # 写缓存(存全量, 按需 slice)
    _cache[cache_key] = full
    _cache_ts[cache_key] = now

    return _slice_cached(full, days)


def _slice_cached(full: dict, days: int) -> dict:
    """从全量缓存截取最近 N 天(days)。"""
    dates_all = full["dates"]
    if len(dates_all) <= days:
        return full
    keep_dates = dates_all[:days]
    return {
        "dates": keep_dates,
        "columns": {d: full["columns"][d] for d in keep_dates},
        "concept_count": full["concept_count"],
    }
