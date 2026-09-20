"""Research-only backtest for Sector/RS-ranked Wyckoff candidates.

The Wyckoff funnel still decides the candidate set. This runner only annotates
the existing candidate set with the frozen Sector/RS research context, then
compares Top20, every complete Wyckoff candidate, and Bottom20. It does not
change any strategy configuration.

Entry is the next trading session's open.  T+N is the close of the Nth
session after the signal date.  Returns are gross, front-adjusted prices;
fees, slippage, limit-up/down execution and suspension handling are reported
as limitations rather than silently simulated.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import polars as pl

from app.parquet import scan_enriched_parquet
from app.services.screener import ScreenerService, _load_wyckoff_concept_context
from app.services.wyckoff_candidate_ranking import rank_wyckoff_candidates
from app.strategy.engine import StrategyEngine
from app.tickflow.repository import DataStore, KlineRepository
from app.wyckoff.funnel import run_funnel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
HORIZONS = (1, 3, 5, 10, 20)
TOP_N = 20
COHORT_TOP = "TOP20"
COHORT_ALL = "ALL_WYCKOFF"
COHORT_BOTTOM = "BOTTOM20"
_PHASES = ("EMERGING", "ACCELERATING", "LEADING", "EXHAUSTED", "FADING")
_RS_STATES = ("LOW", "RISING", "HIGH_AND_RISING", "HIGH_AND_FLAT", "HIGH_AND_FALLING", "EXTENDED")
_EXTENSION_STATES = ("NORMAL", "ELEVATED", "EXTENDED", "EXTREME")


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _strategy_dirs(data_dir: Path) -> list[Path]:
    return [
        PROJECT_ROOT / "backend" / "app" / "strategy" / "builtin",
        data_dir / "strategies" / "custom",
        data_dir / "strategies" / "ai",
        data_dir / "strategies" / "composite",
    ]


def _load_trading_dates(data_dir: Path) -> list[date]:
    source = scan_enriched_parquet(str(data_dir / "kline_daily_enriched" / "**" / "*.parquet"))
    return (
        source.select(pl.col("date").unique().sort())
        .collect()
        .get_column("date")
        .to_list()
    )


def _load_prices(data_dir: Path, start: date, end: date) -> pl.DataFrame:
    source = scan_enriched_parquet(str(data_dir / "kline_daily_enriched" / "**" / "*.parquet"))
    return (
        source.filter(pl.col("date").is_between(start, end))
        .select(["symbol", "date", "open", "high", "low", "close"])
        .collect()
    )


def _engine(data_dir: Path) -> StrategyEngine:
    return StrategyEngine(strategy_dirs=_strategy_dirs(data_dir))


def _ranked_row(*, as_of: date, row: dict[str, object], cohort: str) -> dict[str, object]:
    sector_context = row.get("sector_context")
    sector_context = sector_context if isinstance(sector_context, dict) else {}
    return {
        "signal_date": as_of,
        "cohort": cohort,
        "symbol": str(row["symbol"]),
        "research_context_rank": int(row["rank"]),
        "research_context_score": float(row["final_rank_score"]),
        "sector_score": row.get("sector_score"),
        "rs_score": row.get("rs_score"),
        "sector_phase": row.get("sector_phase"),
        "rs_state": row.get("rs_state"),
        "sector_extension_state": row.get("sector_extension_state"),
        "rs_extension_state": row.get("rs_extension_state"),
        # Range metadata is emitted by the Wyckoff structure detector from
        # the same point-in-time history as this candidate.  Persist it in
        # the research cohort so Range VP can enforce confirmed_at <= as_of.
        "wyckoff_range_start": row.get("wyckoff_range_start"),
        "wyckoff_range_confirmed_at": row.get("wyckoff_range_confirmed_at"),
        "industry_id": sector_context.get("sector_id"),
        "industry_name": sector_context.get("name"),
    }


def _append_cohorts(*, rows: list[dict[str, object]], as_of: date, ranked: list[dict[str, object]]) -> None:
    cohorts = {
        COHORT_TOP: ranked[:TOP_N],
        COHORT_ALL: ranked,
        COHORT_BOTTOM: ranked[-TOP_N:],
    }
    for cohort, cohort_rows in cohorts.items():
        rows.extend(_ranked_row(as_of=as_of, row=row, cohort=cohort) for row in cohort_rows)


def _write_progress(
    path: Path | None,
    *,
    status: str,
    completed: int,
    total: int,
    as_of: date | None = None,
    candidates: int | None = None,
    ranked: int | None = None,
) -> None:
    """Persist human-readable progress for a long, read-only replay."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "completed_signal_days": completed,
        "total_signal_days": total,
        "as_of": as_of.isoformat() if as_of else None,
        "candidates": candidates,
        "ranked": ranked,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _signal_rows(
    *,
    repo: KlineRepository,
    engine: StrategyEngine,
    dates: Iterable[date],
    chunk_size: int,
    progress_path: Path | None = None,
) -> list[dict[str, object]]:
    screener = ScreenerService(repo)
    rows: list[dict[str, object]] = []
    date_list = list(dates)
    _write_progress(progress_path, status="running", completed=0, total=len(date_list))
    config = engine.get("wyckoff_funnel").wyckoff_config
    for chunk_start in range(0, len(date_list), chunk_size):
        chunk_dates = date_list[chunk_start:chunk_start + chunk_size]
        context = screener.build_strategy_context(
            engine,
            chunk_dates[-1],
            ["wyckoff_funnel"],
        )
        if context.history is None or context.history.is_empty():
            raise RuntimeError(f"无法加载 Wyckoff 历史窗口: {chunk_dates[-1]}")
        # Let the ranking services consume precisely this point-in-time window.
        repo._enriched_history_cache = context.history
        repo._enriched_history_generation = repo.get_matrix_data_generation("stock")
        benchmark = (context.market or {}).get("wyckoff_benchmark")
        if benchmark is None or benchmark.is_empty():
            raise RuntimeError(f"缺少 Wyckoff benchmark: {chunk_dates[-1]}")
        sector_map = (context.market or {}).get("wyckoff_sector_map") or {}

        for offset, as_of in enumerate(chunk_dates, start=1):
            # Concept membership remains the configured current snapshot, but
            # the mainline list is point-in-time and must not reuse a later
            # date from this history chunk.
            concept_map, hot_concepts = _load_wyckoff_concept_context(
                repo, as_of, int(config.top_n_sectors)
            )
            history = context.history.filter(pl.col("date") <= as_of)
            partitions = history.partition_by("symbol", as_dict=True, maintain_order=True)
            df_map = {
                str(key[0] if isinstance(key, tuple) else key): frame.drop("symbol").to_pandas()
                for key, frame in partitions.items()
            }
            symbols = sorted(df_map)
            current = history.filter(pl.col("date") == as_of)
            name_map = {
                str(row["symbol"]): str(row.get("name") or "")
                for row in current.iter_rows(named=True)
            }
            cap_map: dict[str, float] = {}
            if {"close", "total_shares"}.issubset(current.columns):
                cap_map = {
                    str(row["symbol"]): float(row["close"] or 0.0) * float(row["total_shares"] or 0.0) / 1e8
                    for row in current.select(["symbol", "close", "total_shares"]).iter_rows(named=True)
                    if row["close"] is not None and row["total_shares"] is not None
                }
            benchmark_frame = benchmark.filter(pl.col("date") <= as_of).to_pandas()
            funnel = run_funnel(
                symbols,
                df_map,
                benchmark=benchmark_frame,
                name_map=name_map,
                market_cap_map=cap_map,
                sector_map=sector_map,
                concept_map=concept_map,
                hot_concepts=hot_concepts,
                cfg=config,
            )
            candidates = [
                {
                    "symbol": symbol,
                    "wyckoff_channel": funnel.channel_map.get(symbol, ""),
                    "wyckoff_stage": funnel.stage_map.get(symbol, ""),
                    "wyckoff_source": funnel.final_traces.get(symbol, {}).get("source", "L3 strict"),
                    "wyckoff_l3_path": funnel.final_traces.get(symbol, {}).get("l3_path", "unknown"),
                    "wyckoff_range_start": funnel.trading_ranges.get(symbol, {}).get("range_start"),
                    "wyckoff_range_confirmed_at": funnel.trading_ranges.get(symbol, {}).get("range_confirmed_at"),
                }
                for symbol in funnel.layer3_symbols
            ]
            ranked = rank_wyckoff_candidates(repo, as_of=as_of, candidates=candidates)
            ranked = [
                row for row in ranked
                if row.get("ranking_status") == "complete"
                and row.get("final_rank_score") is not None
                and row.get("rank") is not None
            ]
            ranked.sort(
                key=lambda row: (
                    int(row["rank"]),
                    -float(row["final_rank_score"]),
                    str(row.get("symbol") or ""),
                )
            )
            _append_cohorts(rows=rows, as_of=as_of, ranked=ranked)
            absolute = chunk_start + offset
            print(
                f"[{absolute}/{len(date_list)}] {as_of}: candidates={len(candidates)} "
                f"ranked={len(ranked)} selected={min(len(ranked), TOP_N)}",
                flush=True,
            )
            _write_progress(
                progress_path,
                status="running",
                completed=absolute,
                total=len(date_list),
                as_of=as_of,
                candidates=len(candidates),
                ranked=len(ranked),
            )
    return rows


def _attach_forward_returns(
    signals: pl.DataFrame,
    prices: pl.DataFrame,
    dates: list[date],
    benchmark_prices: pl.DataFrame | None = None,
) -> pl.DataFrame:
    if signals.is_empty():
        return signals
    index_by_date = {value: index for index, value in enumerate(dates)}
    enriched = signals.with_columns(
        pl.col("signal_date").map_elements(
            lambda value: index_by_date.get(value), return_dtype=pl.Int64
        ).alias("_signal_index")
    )
    for horizon in HORIZONS:
        enriched = enriched.with_columns(
            pl.col("_signal_index").map_elements(
                lambda value, lag=horizon: dates[value + lag] if value is not None and value + lag < len(dates) else None,
                return_dtype=pl.Date,
            ).alias(f"_exit_date_{horizon}d"),
            pl.col("_signal_index").map_elements(
                lambda value: dates[value + 1] if value is not None and value + 1 < len(dates) else None,
                return_dtype=pl.Date,
            ).alias(f"_entry_date_{horizon}d"),
        )
        entry = prices.select(
            pl.col("symbol"),
            pl.col("date").alias(f"_entry_date_{horizon}d"),
            pl.col("open").alias(f"_entry_open_{horizon}d"),
        )
        exit_ = prices.select(
            pl.col("symbol"),
            pl.col("date").alias(f"_exit_date_{horizon}d"),
            pl.col("close").alias(f"_exit_close_{horizon}d"),
        )
        enriched = enriched.join(entry, on=["symbol", f"_entry_date_{horizon}d"], how="left")
        enriched = enriched.join(exit_, on=["symbol", f"_exit_date_{horizon}d"], how="left")
        enriched = enriched.with_columns(
            pl.when(
                pl.col(f"_entry_open_{horizon}d").is_not_null()
                & pl.col(f"_exit_close_{horizon}d").is_not_null()
                & (pl.col(f"_entry_open_{horizon}d") != 0)
            )
            .then(pl.col(f"_exit_close_{horizon}d") / pl.col(f"_entry_open_{horizon}d") - 1.0)
            .otherwise(None)
            .alias(f"return_{horizon}d")
        )
        if benchmark_prices is not None and not benchmark_prices.is_empty():
            benchmark_entry = benchmark_prices.select(
                pl.col("date").alias(f"_entry_date_{horizon}d"),
                pl.col("open").alias(f"_benchmark_entry_open_{horizon}d"),
            )
            benchmark_exit = benchmark_prices.select(
                pl.col("date").alias(f"_exit_date_{horizon}d"),
                pl.col("close").alias(f"_benchmark_exit_close_{horizon}d"),
            )
            enriched = enriched.join(
                benchmark_entry,
                on=f"_entry_date_{horizon}d",
                how="left",
            ).join(
                benchmark_exit,
                on=f"_exit_date_{horizon}d",
                how="left",
            )
            enriched = enriched.with_columns(
                pl.when(
                    pl.col(f"_benchmark_entry_open_{horizon}d").is_not_null()
                    & pl.col(f"_benchmark_exit_close_{horizon}d").is_not_null()
                    & (pl.col(f"_benchmark_entry_open_{horizon}d") != 0)
                )
                .then(
                    pl.col(f"_benchmark_exit_close_{horizon}d")
                    / pl.col(f"_benchmark_entry_open_{horizon}d")
                    - 1.0
                )
                .otherwise(None)
                .alias(f"benchmark_return_{horizon}d")
            )
            enriched = enriched.with_columns(
                pl.when(
                    pl.col(f"return_{horizon}d").is_not_null()
                    & pl.col(f"benchmark_return_{horizon}d").is_not_null()
                )
                .then(
                    pl.col(f"return_{horizon}d")
                    - pl.col(f"benchmark_return_{horizon}d")
                )
                .otherwise(None)
                .alias(f"excess_return_{horizon}d")
            )
        mae, mfe = _path_excursions(
            enriched,
            prices=prices,
            dates=dates,
            horizon=horizon,
        )
        enriched = enriched.with_columns(
            pl.Series(f"mae_{horizon}d", mae, dtype=pl.Float64),
            pl.Series(f"mfe_{horizon}d", mfe, dtype=pl.Float64),
        )
    return enriched.drop("_signal_index")


def _path_excursions(
    frame: pl.DataFrame,
    *,
    prices: pl.DataFrame,
    dates: list[date],
    horizon: int,
) -> tuple[list[float | None], list[float | None]]:
    """Return MAE/MFE from next-session entry open through the T+N exit date.

    A missing intrawindow high/low produces ``None`` rather than an optimistic
    excursion based on only the available dates.
    """
    if not {"high", "low"}.issubset(prices.columns):
        return [None] * frame.height, [None] * frame.height
    by_symbol: dict[str, dict[date, tuple[float | None, float | None]]] = {}
    for row in prices.select(["symbol", "date", "low", "high"]).iter_rows(named=True):
        by_symbol.setdefault(str(row["symbol"]), {})[row["date"]] = (
            row["low"],
            row["high"],
        )
    index_by_date = {value: index for index, value in enumerate(dates)}
    mae: list[float | None] = []
    mfe: list[float | None] = []
    required = ["symbol", f"_entry_date_{horizon}d", f"_exit_date_{horizon}d", f"_entry_open_{horizon}d"]
    for row in frame.select(required).iter_rows(named=True):
        entry_date = row[f"_entry_date_{horizon}d"]
        exit_date = row[f"_exit_date_{horizon}d"]
        entry_open = row[f"_entry_open_{horizon}d"]
        start_index = index_by_date.get(entry_date)
        end_index = index_by_date.get(exit_date)
        if (
            entry_open is None
            or not math.isfinite(float(entry_open))
            or float(entry_open) == 0
            or start_index is None
            or end_index is None
        ):
            mae.append(None)
            mfe.append(None)
            continue
        path = by_symbol.get(str(row["symbol"]), {})
        highs: list[float] = []
        lows: list[float] = []
        for current_date in dates[start_index:end_index + 1]:
            low, high = path.get(current_date, (None, None))
            if low is None or high is None or not math.isfinite(float(low)) or not math.isfinite(float(high)):
                highs = []
                lows = []
                break
            lows.append(float(low))
            highs.append(float(high))
        if not lows or not highs:
            mae.append(None)
            mfe.append(None)
            continue
        mae.append(min(lows) / float(entry_open) - 1.0)
        mfe.append(max(highs) / float(entry_open) - 1.0)
    return mae, mfe


def _summary(frame: pl.Series) -> dict[str, object]:
    values = [float(value) for value in frame.drop_nulls().to_list()]
    if not values:
        return {"n": 0, "mean": None, "median": None, "positive_rate": None, "profit_factor": None}
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "positive_rate": sum(value > 0 for value in values) / len(values),
        "profit_factor": gains / losses if losses else None,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(frame: pl.Series) -> dict[str, object]:
    values = [float(value) for value in frame.drop_nulls().to_list()]
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p25": _percentile(values, 0.25),
        "p75": _percentile(values, 0.75),
    }


def _cohort_horizon_metrics(frame: pl.DataFrame, horizon: int) -> dict[str, object]:
    returns = _summary(frame.get_column(f"return_{horizon}d"))
    benchmark = _summary(frame.get_column(f"benchmark_return_{horizon}d"))
    excess = _summary(frame.get_column(f"excess_return_{horizon}d"))
    mae = _distribution(frame.get_column(f"mae_{horizon}d"))
    mfe = _distribution(frame.get_column(f"mfe_{horizon}d"))
    return {
        "n": returns["n"],
        "mean_return": returns["mean"],
        "median_return": returns["median"],
        "return_profit_factor": returns["profit_factor"],
        "benchmark_mean_return": benchmark["mean"],
        "benchmark_median_return": benchmark["median"],
        "mean_excess_return": excess["mean"],
        "median_excess_return": excess["median"],
        "positive_excess_rate": excess["positive_rate"],
        "excess_profit_factor": excess["profit_factor"],
        "mae": mae,
        "mfe": mfe,
    }


def _state_distribution(frame: pl.DataFrame, column: str, states: tuple[str, ...]) -> dict[str, object]:
    values = [str(value) if value is not None else "UNCLASSIFIED" for value in frame.get_column(column).to_list()]
    total = frame.height
    counts = {state: sum(value == state for value in values) for state in states}
    counts["UNCLASSIFIED"] = sum(value not in states for value in values)
    return {
        "n": total,
        "counts": counts,
        "percentages": {state: count / total if total else None for state, count in counts.items()},
    }


def _industry_concentration(frame: pl.DataFrame) -> dict[str, object]:
    daily: list[dict[str, object]] = []
    for (signal_date,), day_frame in frame.group_by("signal_date", maintain_order=True):
        counts = (
            day_frame.with_columns(pl.col("industry_name").fill_null("未映射").alias("_industry"))
            .group_by("_industry")
            .len()
            .sort("len", descending=True)
            .get_column("len")
            .to_list()
        )
        total = sum(int(value) for value in counts)
        daily.append({
            "signal_date": signal_date,
            "industry_count": len(counts),
            "largest_industry_ratio": int(counts[0]) / total if counts else None,
            "top3_industry_ratio": sum(int(value) for value in counts[:3]) / total if counts else None,
        })
    def values(field: str) -> list[float]:
        return [float(row[field]) for row in daily if row[field] is not None]
    return {
        "daily": daily,
        "aggregate": {
            "signal_days": len(daily),
            "mean_industry_count": statistics.fmean(values("industry_count")) if daily else None,
            "median_industry_count": statistics.median(values("industry_count")) if daily else None,
            "mean_largest_industry_ratio": statistics.fmean(values("largest_industry_ratio")) if values("largest_industry_ratio") else None,
            "mean_top3_industry_ratio": statistics.fmean(values("top3_industry_ratio")) if values("top3_industry_ratio") else None,
        },
    }


def _top20_context(frame: pl.DataFrame) -> dict[str, object]:
    return {
        "score_distribution": {
            "final_rank_score": _distribution(frame.get_column("research_context_score")),
            "sector_score": _distribution(frame.get_column("sector_score")),
            "rs_score": _distribution(frame.get_column("rs_score")),
        },
        "sector_phase_distribution": _state_distribution(frame, "sector_phase", _PHASES),
        "rs_state_distribution": _state_distribution(frame, "rs_state", _RS_STATES),
        "sector_extension_distribution": _state_distribution(
            frame, "sector_extension_state", _EXTENSION_STATES
        ),
        "rs_extension_distribution": _state_distribution(
            frame, "rs_extension_state", _EXTENSION_STATES
        ),
        "industry_concentration": _industry_concentration(frame),
    }


def _report(
    signals: pl.DataFrame,
    *,
    start: date,
    end: date,
    rows_path: Path,
) -> dict[str, object]:
    cohorts: dict[str, object] = {}
    for cohort in (COHORT_TOP, COHORT_ALL, COHORT_BOTTOM):
        subset = signals.filter(pl.col("cohort") == cohort)
        cohorts[cohort] = {
            "signal_days": subset.get_column("signal_date").n_unique(),
            "rows": subset.height,
            "horizons": {
                f"T+{horizon}": _cohort_horizon_metrics(subset, horizon)
                for horizon in HORIZONS
            },
        }
    top20 = signals.filter(pl.col("cohort") == COHORT_TOP)
    all_wyckoff = signals.filter(pl.col("cohort") == COHORT_ALL)
    return {
        "status": "complete",
        "experiment": "wyckoff_candidates_sector_rs_cohort_comparison",
        "research_only": True,
        "selection": {
            "source": "wyckoff_funnel_layer3_candidates",
            "ranking": "research_context_score_descending",
            "top_n": TOP_N,
            "cohorts": [COHORT_TOP, COHORT_ALL, COHORT_BOTTOM],
            "sector_membership": "SW2021_industry_level_1",
            "concept_membership_used_for_ranking": False,
            "wyckoff_funnel_concept_context": "current_ext_snapshot",
        },
        "execution": {
            "signal_date": "after_close",
            "entry": "next_trading_session_open",
            "exit": "T+N_trading_session_close",
            "price_basis": "front_adjusted_enriched_ohlc",
            "costs_included": False,
            "slippage_included": False,
            "limit_and_suspension_execution_modeled": False,
        },
        "benchmark": {
            "symbol": "000001.SH",
            "name": "上证综合指数",
            "comparison": "同一下一交易日开盘至T+N收盘窗口;组合收益减指数收益",
        },
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "cohorts": cohorts,
        "top20_context": _top20_context(top20),
        "extension_comparison": {
            COHORT_TOP: {
                "sector": _state_distribution(top20, "sector_extension_state", _EXTENSION_STATES),
                "rs": _state_distribution(top20, "rs_extension_state", _EXTENSION_STATES),
            },
            COHORT_ALL: {
                "sector": _state_distribution(all_wyckoff, "sector_extension_state", _EXTENSION_STATES),
                "rs": _state_distribution(all_wyckoff, "rs_extension_state", _EXTENSION_STATES),
            },
        },
        "artifacts": {
            "cohort_rows_parquet": str(rows_path.resolve()),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Wyckoff 候选内部 Sector/RS 分层研究回测")
    parser.add_argument("--start", type=_parse_date, default=date(2023, 9, 12))
    parser.add_argument("--end", type=_parse_date, default=None)
    parser.add_argument(
        "--signal-end",
        type=_parse_date,
        default=None,
        help="明确的最后一个信号日;前向退出价格仍从完整本地历史读取",
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--chunk-size", type=int, default=60, help="每次构建的历史窗口日期数")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--progress-path",
        type=Path,
        default=None,
        help="可选: 每个信号日完成后刷新 JSON 进度文件",
    )
    args = parser.parse_args()

    all_dates = _load_trading_dates(args.data_dir)
    if args.chunk_size <= 0:
        raise ValueError("--chunk-size 必须为正数")
    if args.signal_end is not None:
        signal_dates = [
            value for value in all_dates
            if args.start <= value <= args.signal_end
        ]
    else:
        eligible = [value for value in all_dates if value >= args.start]
        if args.end is not None:
            eligible = [value for value in eligible if value <= args.end]
        if len(eligible) <= max(HORIZONS):
            raise ValueError("历史交易日不足以完成 Top20 前向回测")
        signal_dates = eligible[:-max(HORIZONS)]
    if not signal_dates:
        raise ValueError("给定区间没有有效信号交易日")
    final_signal_index = all_dates.index(signal_dates[-1])
    if final_signal_index + max(HORIZONS) >= len(all_dates):
        raise ValueError("最后一个信号日之后的交易日不足以完成 T+20 回测")
    start = signal_dates[0]
    end = signal_dates[-1]
    forward_end = all_dates[final_signal_index + max(HORIZONS)]
    prices = _load_prices(args.data_dir, start, forward_end)

    store = DataStore(args.data_dir)
    repo = KlineRepository(store)
    benchmark_prices = repo.get_index_daily(
        "000001.SH",
        start,
        forward_end,
        columns=["date", "open", "close"],
    )
    engine = _engine(args.data_dir)
    started = time.perf_counter()
    rows = _signal_rows(
        repo=repo,
        engine=engine,
        dates=signal_dates,
        chunk_size=args.chunk_size,
        progress_path=args.progress_path,
    )
    signals = pl.DataFrame(rows) if rows else pl.DataFrame()
    signals = _attach_forward_returns(signals, prices, all_dates, benchmark_prices)

    output_dir = args.data_dir / "research"
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / f"wyckoff_sector_rs_cohorts_{start}_{end}.parquet"
    signals.write_parquet(rows_path)
    report = _report(signals, start=start, end=end, rows_path=rows_path)
    report["elapsed_seconds"] = time.perf_counter() - started
    report_path = args.output or output_dir / f"wyckoff_sector_rs_cohorts_{start}_{end}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _write_progress(
        args.progress_path,
        status="complete",
        completed=len(signal_dates),
        total=len(signal_dates),
        as_of=end,
    )
    print(json.dumps({
        "report": str(report_path),
        "top20": report["cohorts"][COHORT_TOP]["horizons"],
        "all_wyckoff": report["cohorts"][COHORT_ALL]["horizons"],
        "bottom20": report["cohorts"][COHORT_BOTTOM]["horizons"],
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
