"""Replay the current formal Wyckoff strategy on a random 12-day sample.

Unlike the older Sector/RS and VP research runners, this script calls the
strategy engine with the saved ``wyckoff_funnel`` override.  It therefore
uses the same L1--L3 funnel, post-L3 basic filter and Top-150 presentation
limit as a manual strategy run.  Legacy L4 and V2 remain research evidence;
neither changes membership here.

Signals are known after the signal-day close.  Gross returns enter at the next
trading day's open and exit at the T+N close.  This is a research report, not
a fill simulator: fees, slippage, suspensions and price-limit fills are not
modelled.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from run_wyckoff_top20_backtest import (
    HORIZONS,
    _attach_forward_returns,
    _load_prices,
    _load_trading_dates,
    _strategy_dirs,
)

from app.services.screener import ScreenerService
from app.strategy import config as strategy_config
from app.strategy.engine import StrategyEngine
from app.tickflow.repository import DataStore, KlineRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_SEED = 20260919
DEFAULT_SAMPLE_SIZE = 12
# The local SW2021 membership interval archive begins on this date.  Starting
# here keeps L3 point-in-time and fail-closed rather than silently falling back
# to a later industry membership list.
DEFAULT_START = date(2023, 9, 12)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _eligible_dates(
    *,
    trading_dates: list[date],
    start: date,
    benchmark_dates: set[date] | None = None,
) -> list[date]:
    """Keep only dates with full T+20 and benchmark coverage available."""
    last_signal_index = len(trading_dates) - max(HORIZONS) - 1
    return [
        value
        for index, value in enumerate(trading_dates)
        if value >= start and index <= last_signal_index
        and (
            benchmark_dates is None
            or (
                trading_dates[index + 1] in benchmark_dates
                and trading_dates[index + max(HORIZONS)] in benchmark_dates
            )
        )
    ]


def _select_dates(*, eligible: list[date], seed: int, sample_size: int) -> tuple[list[date], dict[str, Any]]:
    """Draw across months first so a short market regime cannot dominate."""
    if len(eligible) < sample_size:
        raise ValueError(f"only {len(eligible)} eligible dates, need {sample_size}")
    by_month: dict[str, list[date]] = defaultdict(list)
    for value in eligible:
        by_month[value.strftime("%Y-%m")].append(value)
    months = sorted(by_month)
    rng = random.Random(seed)
    if len(months) >= sample_size:
        chosen_months = sorted(rng.sample(months, sample_size))
        selected = [rng.choice(by_month[month]) for month in chosen_months]
        method = "one_fixed_seed_draw_per_selected_month"
        extra_months: list[str] = []
    else:
        selected = [rng.choice(by_month[month]) for month in months]
        extra_count = sample_size - len(selected)
        selectable_months = [month for month in months if len(by_month[month]) >= 2]
        if len(selectable_months) < extra_count:
            raise ValueError("not enough distinct dates to complete stratified sample")
        extra_months = sorted(rng.sample(selectable_months, extra_count))
        for month in extra_months:
            selected.append(rng.choice([value for value in by_month[month] if value not in selected]))
        method = "one_fixed_seed_draw_per_available_month_then_fixed_seed_extra_month_draws"
    return sorted(selected), {
        "seed": seed,
        "sample_size": sample_size,
        "eligible_date_count": len(eligible),
        "eligible_months": months,
        "selection_method": method,
        "extra_months": extra_months,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _metric(values: pl.Series) -> dict[str, float | int | None]:
    valid = [float(value) for value in values.drop_nulls().to_list()]
    if not valid:
        return {"n": 0, "mean": None, "median": None, "positive_rate": None}
    return {
        "n": len(valid),
        "mean": statistics.fmean(valid),
        "median": statistics.median(valid),
        "positive_rate": sum(value > 0 for value in valid) / len(valid),
    }


def _date_equal_metric(signals: pl.DataFrame, column: str) -> dict[str, float | int | None]:
    """Summarise equal-weighted daily cohorts, not just all stock observations."""
    if signals.is_empty():
        return _metric(pl.Series(column, [], dtype=pl.Float64))
    daily = signals.group_by("signal_date").agg(pl.col(column).mean())
    return _metric(daily.get_column(column))


def _signal_row(*, as_of: date, row: dict[str, Any]) -> dict[str, Any]:
    """Keep only scalar strategy-output fields needed for a replay artifact.

    UI rows also carry nested V2 evidence.  Empty nested dictionaries are
    valid presentation values but cannot be represented as a Parquet struct,
    and are not an input to the forward-return calculation.
    """
    return {
        "signal_date": as_of,
        "symbol": str(row["symbol"]),
        "candidate_order": row.get("candidate_order"),
        "opportunity_score": row.get("opportunity_score"),
        "wyckoff_channel": row.get("wyckoff_channel"),
        "wyckoff_stage": row.get("wyckoff_stage"),
        "wyckoff_source": row.get("wyckoff_source"),
        "wyckoff_l3_path": row.get("wyckoff_l3_path"),
        "vp_risk_bucket": row.get("vp_risk_bucket"),
    }


def _load_stored_signals(path: Path, *, completed_days: int) -> pl.DataFrame:
    """Read resumable results without trusting an interrupted first write."""
    if not path.exists():
        return pl.DataFrame()
    try:
        return pl.read_parquet(path)
    except pl.exceptions.ComputeError:
        if completed_days:
            raise
        # ``write_parquet`` can leave an empty target when its first write is
        # interrupted.  No completed date means no valid result can be lost;
        # the next successful write atomically replaces this target.
        return pl.DataFrame()


def _report(*, signals: pl.DataFrame, state: dict[str, Any], rows_path: Path) -> dict[str, Any]:
    return {
        "status": "complete",
        "experiment": "current_wyckoff_funnel_month_stratified_random12",
        "research_only": True,
        "selection": state["selection"],
        "signal_dates": state["selected_signal_dates"],
        "formal_strategy_contract": {
            "strategy_id": "wyckoff_funnel",
            "saved_override_applied": True,
            "l3": "SW2021 industry level 1, fail-closed",
            "legacy_l4": "research trigger only; does not alter membership",
            "wyckoff_v2": "parallel diagnostics only; does not alter membership",
            "post_l3_basic_filter": True,
            "presentation_limit": 150,
        },
        "execution": {
            "signal_time": "signal-day close",
            "entry": "next trading-day open",
            "exit": "T+N close",
            "prices": "front-adjusted enriched daily OHLCV",
            "costs_slippage_price_limits_suspensions_modelled": False,
        },
        "candidate_counts_by_day": state["date_runs"],
        "rows": signals.height,
        "unique_symbols": signals.get_column("symbol").n_unique() if not signals.is_empty() else 0,
        "horizons": {
            f"T+{horizon}": {
                "return": _metric(signals.get_column(f"return_{horizon}d")),
                "benchmark_return": _metric(signals.get_column(f"benchmark_return_{horizon}d")),
                "excess_return": _metric(signals.get_column(f"excess_return_{horizon}d")),
                "equal_weight_by_signal_day": {
                    "return": _date_equal_metric(signals, f"return_{horizon}d"),
                    "benchmark_return": _date_equal_metric(signals, f"benchmark_return_{horizon}d"),
                    "excess_return": _date_equal_metric(signals, f"excess_return_{horizon}d"),
                },
            }
            for horizon in HORIZONS
        },
        "artifacts": {"signals_parquet": str(rows_path.resolve())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="当前正式 Wyckoff 漏斗随机12日研究回测")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR / "research" / "wyckoff_current_random12_20260919")
    parser.add_argument("--start", type=_parse_date, default=DEFAULT_START)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    output_dir = args.output_dir.resolve()
    state_path = output_dir / "progress.json"
    rows_path = output_dir / "signals.parquet"
    report_path = output_dir / "report.json"
    trading_dates = _load_trading_dates(data_dir)
    repo = KlineRepository(DataStore(data_dir))
    benchmark_coverage = repo.get_index_daily(
        "000001.SH", args.start, trading_dates[-1], columns=["date"]
    )
    benchmark_dates = set(benchmark_coverage.get_column("date").to_list())
    eligible = _eligible_dates(
        trading_dates=trading_dates,
        start=args.start,
        benchmark_dates=benchmark_dates,
    )
    state = _read_json(state_path)
    if state.get("selected_signal_dates"):
        selected_dates = [date.fromisoformat(value) for value in state["selected_signal_dates"]]
    else:
        selected_dates, selection = _select_dates(
            eligible=eligible, seed=args.seed, sample_size=args.sample_size
        )
        state = {
            "status": "running",
            "selected_signal_dates": [value.isoformat() for value in selected_dates],
            "selection": selection,
            "date_runs": {},
        }
        _write_json(state_path, state)

    final_index = trading_dates.index(selected_dates[-1])
    prices = _load_prices(
        data_dir,
        selected_dates[0],
        trading_dates[final_index + max(HORIZONS)],
    )
    benchmark_prices = repo.get_index_daily(
        "000001.SH",
        selected_dates[0],
        trading_dates[final_index + max(HORIZONS)],
        columns=["date", "open", "close"],
    )
    engine = StrategyEngine(strategy_dirs=_strategy_dirs(data_dir))
    overrides = strategy_config.load_override(data_dir, "wyckoff_funnel")
    screener = ScreenerService(repo)
    stored = _load_stored_signals(
        rows_path,
        completed_days=len(state.get("date_runs") or {}),
    )
    records = stored.to_dicts() if not stored.is_empty() else []
    completed = set(stored.get_column("signal_date").to_list()) if not stored.is_empty() else set()
    started = time.perf_counter()

    for ordinal, as_of in enumerate(selected_dates, start=1):
        if as_of in completed:
            print(f"[resume {ordinal}/{len(selected_dates)}] {as_of}", flush=True)
            continue
        context = screener.build_strategy_context(
            engine,
            as_of,
            ["wyckoff_funnel"],
            overrides_map={"wyckoff_funnel": overrides},
        )
        result = engine.run("wyckoff_funnel", context, overrides=overrides)
        evidence = result.evidence
        state["date_runs"][as_of.isoformat()] = {
            "all_l3_candidates": evidence.get("all_wyckoff_candidate_count"),
            "after_basic_filter": evidence.get("basic_filter_candidate_count"),
            "displayed_candidates": result.total,
            "research_triggers": evidence.get("wyckoff_research_trigger_count"),
        }
        records.extend(_signal_row(as_of=as_of, row=row) for row in result.rows)
        raw = pl.DataFrame(records)
        signals = _attach_forward_returns(raw, prices, trading_dates, benchmark_prices)
        signals.write_parquet(rows_path)
        state["completed_signal_dates"] = len(state["date_runs"])
        state["current_signal_date"] = as_of.isoformat()
        state["elapsed_seconds"] = round(time.perf_counter() - started, 2)
        _write_json(state_path, state)
        print(f"[{ordinal}/{len(selected_dates)}] {as_of}: {state['date_runs'][as_of.isoformat()]}", flush=True)

    signals = pl.read_parquet(rows_path) if rows_path.exists() else pl.DataFrame()
    state["status"] = "complete"
    state["completed_signal_dates"] = len(selected_dates)
    state["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    _write_json(state_path, state)
    report = _report(signals=signals, state=state, rows_path=rows_path)
    _write_json(report_path, report)
    print(json.dumps({"report": str(report_path), "horizons": report["horizons"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":  # pragma: no cover - command line entrypoint
    main()
