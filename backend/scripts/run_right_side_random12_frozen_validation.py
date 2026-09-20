"""Run the frozen, month-stratified random-12 right-side VP validation.

This is deliberately a research-only orchestration script.  It replays the
existing Wyckoff/Sector/RS pipeline as of each selected signal date, writes an
ALL_WYCKOFF checkpoint immediately, then builds the frozen VP20/VP60 context
from minute data no later than that date.  No ranking or signal definition is
changed here.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from derive_vp_extension_random5 import _as_position, _optional_float
from run_volume_profile_context_validation import _as_date, _one_date
from run_wyckoff_top20_backtest import (
    COHORT_ALL,
    HORIZONS,
    _attach_forward_returns,
    _engine,
    _load_prices,
    _load_trading_dates,
    _signal_rows,
)

from app.services.volume_profile import VolumeProfileEngine, VolumeProfileService
from app.tickflow.repository import DataStore, KlineRepository

SEED = 20260913
SAMPLE_SIZE = 12


def _minute_partition_dates(data_dir: Path) -> set[date]:
    result: set[date] = set()
    for path in (data_dir / "kline_minute").glob("date=*"):
        try:
            result.add(date.fromisoformat(path.name.split("=", 1)[1]))
        except ValueError:
            continue
    return result


def _eligible_dates(data_dir: Path) -> tuple[list[date], list[date]]:
    """Require all market-wide VP60 date partitions and complete T+20 exits."""
    trading_dates = _load_trading_dates(data_dir)
    minute_dates = _minute_partition_dates(data_dir)
    eligible = [
        as_of
        for index, as_of in enumerate(trading_dates)
        if index >= 59
        and index + max(HORIZONS) < len(trading_dates)
        and all(value in minute_dates for value in trading_dates[index - 59 : index + 1])
    ]
    return trading_dates, eligible


def _select_dates(*, eligible: list[date], seed: int, sample_size: int) -> tuple[list[date], dict[str, Any]]:
    if len(eligible) < sample_size:
        raise ValueError(f"only {len(eligible)} eligible dates, need {sample_size}")
    by_month: dict[str, list[date]] = defaultdict(list)
    for value in eligible:
        by_month[value.strftime("%Y-%m")].append(value)
    months = sorted(by_month)
    rng = random.Random(seed)
    if len(months) >= sample_size:
        selected_months = sorted(rng.sample(months, sample_size))
        selected = [rng.choice(by_month[month]) for month in selected_months]
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
    selected = sorted(selected)
    return selected, {
        "seed": seed,
        "sample_size": sample_size,
        "eligible_date_count": len(eligible),
        "eligible_months": months,
        "selection_method": method,
        "extra_months": extra_months,
    }


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _fixed_extensions(frame: pl.DataFrame) -> pl.DataFrame:
    columns: list[pl.Series] = []
    for profile in ("vp20", "vp60"):
        values = [
            VolumeProfileEngine.extension_state_for(
                position_context=_as_position(row[f"{profile}_position"]),
                distance_to_vah_atr=_optional_float(row[f"{profile}_distance_to_vah_atr"]),
                distance_to_vah_pct=_optional_float(row[f"{profile}_distance_to_vah_pct"]),
            ).value
            for row in frame.select(
                [
                    f"{profile}_position",
                    f"{profile}_distance_to_vah_atr",
                    f"{profile}_distance_to_vah_pct",
                ]
            ).iter_rows(named=True)
        ]
        columns.append(pl.Series(f"{profile}_extension_fixed", values, dtype=pl.String))
    return frame.with_columns(columns)


def _profile_counts(frame: pl.DataFrame) -> dict[str, int]:
    return {
        "candidates": frame.height,
        "vp20_full": frame.filter(pl.col("vp20_quality") == "FULL").height,
        "vp60_full": frame.filter(pl.col("vp60_quality") == "FULL").height,
        "vp20_not_full": frame.filter(pl.col("vp20_quality") != "FULL").height,
        "vp60_not_full": frame.filter(pl.col("vp60_quality") != "FULL").height,
    }


def _build_vp_snapshot(*, source: pl.DataFrame, service: VolumeProfileService) -> pl.DataFrame:
    as_of = _as_date(source.item(0, "signal_date"))
    if as_of is None:
        raise ValueError("signal_date is required")
    range_metadata = {
        str(row["symbol"]): (
            _as_date(row.get("wyckoff_range_start")),
            _as_date(row.get("wyckoff_range_confirmed_at")),
        )
        for row in source.select(["symbol", "wyckoff_range_start", "wyckoff_range_confirmed_at"]).iter_rows(named=True)
    }
    range_starts = {
        symbol: start
        for symbol, (start, confirmed) in range_metadata.items()
        if start is not None and confirmed is not None and confirmed <= as_of
    }
    range_confirmed_at = {
        symbol: confirmed
        for symbol, (_, confirmed) in range_metadata.items()
        if symbol in range_starts and confirmed is not None
    }
    context = service.prepare_batch_context(
        symbols=source.get_column("symbol").to_list(),
        as_of=as_of,
        range_starts=range_starts,
        range_confirmed_at=range_confirmed_at,
    )
    return _fixed_extensions(_one_date(service, context, source))


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen month-stratified random-12 VP validation")
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--output-dir", type=Path, default=Path("../data/research/right_side_random12_frozen_20260913"))
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--sample-size", type=int, default=SAMPLE_SIZE)
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    output_dir = args.output_dir.resolve()
    cohort_dir = output_dir / "cohort"
    snapshot_dir = output_dir / "snapshots"
    state_path = output_dir / "progress.json"
    cohort_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    state = _read_state(state_path)
    trading_dates, eligible = _eligible_dates(data_dir)
    if state.get("selected_signal_dates"):
        selected_dates = [date.fromisoformat(value) for value in state["selected_signal_dates"]]
        selection = state["selection"]
    else:
        selected_dates, selection = _select_dates(eligible=eligible, seed=args.seed, sample_size=args.sample_size)
        state = {
            "status": "running",
            "selected_signal_dates": [value.isoformat() for value in selected_dates],
            "selection": selection,
            "date_runs": {},
            "failure_count": 0,
        }
        _write_state(state_path, state)

    final_index = max(trading_dates.index(value) for value in selected_dates)
    prices = _load_prices(data_dir, min(selected_dates), trading_dates[final_index + max(HORIZONS)])
    repo = KlineRepository(DataStore(data_dir))
    benchmark_prices = repo.get_index_daily(
        "000001.SH",
        min(selected_dates),
        trading_dates[final_index + max(HORIZONS)],
        columns=["date", "open", "close"],
    )
    engine = _engine(data_dir)
    vp_service = VolumeProfileService(repo)
    run_started = time.perf_counter()

    for ordinal, as_of in enumerate(selected_dates, start=1):
        day_key = as_of.isoformat()
        cohort_path = cohort_dir / f"signal_date={day_key}.parquet"
        snapshot_path = snapshot_dir / f"signal_date={day_key}.parquet"
        record = state.setdefault("date_runs", {}).get(day_key, {})
        if snapshot_path.exists() and record.get("status") == "complete":
            print(f"[resume {ordinal}/{len(selected_dates)}] {day_key}", flush=True)
            continue
        date_started = time.perf_counter()
        try:
            if cohort_path.exists():
                cohort = pl.read_parquet(cohort_path)
                wyckoff_seconds = float(record.get("wyckoff_seconds", 0.0))
            else:
                wyckoff_started = time.perf_counter()
                replay_rows = _signal_rows(
                    repo=repo,
                    engine=engine,
                    dates=[as_of],
                    chunk_size=1,
                    progress_path=None,
                )
                replay = pl.DataFrame(replay_rows).filter(pl.col("cohort") == COHORT_ALL)
                cohort = _attach_forward_returns(replay, prices, trading_dates, benchmark_prices)
                cohort.write_parquet(cohort_path)
                wyckoff_seconds = time.perf_counter() - wyckoff_started
            if cohort.is_empty():
                raise RuntimeError(f"ALL_WYCKOFF is empty for {day_key}")
            vp_started = time.perf_counter()
            snapshot = _build_vp_snapshot(source=cohort, service=vp_service)
            snapshot.write_parquet(snapshot_path)
            vp_seconds = time.perf_counter() - vp_started
            counts = _profile_counts(snapshot)
            state["date_runs"][day_key] = {
                "status": "complete",
                "elapsed_seconds": round(time.perf_counter() - date_started, 2),
                "wyckoff_seconds": round(wyckoff_seconds, 2),
                "vp_seconds": round(vp_seconds, 2),
                "failure_count": 0,
                **counts,
            }
            state["completed_signal_dates"] = sum(
                item.get("status") == "complete" for item in state["date_runs"].values()
            )
            state["current_signal_date"] = day_key
            state["elapsed_seconds"] = round(time.perf_counter() - run_started, 2)
            _write_state(state_path, state)
            print(f"[{ordinal}/{len(selected_dates)}] {day_key}: {state['date_runs'][day_key]}", flush=True)
        except Exception as exc:
            state["date_runs"][day_key] = {
                "status": "failed",
                "elapsed_seconds": round(time.perf_counter() - date_started, 2),
                "failure_count": 1,
                "error": f"{type(exc).__name__}: {exc}",
            }
            state["failure_count"] = sum(
                item.get("status") == "failed" for item in state["date_runs"].values()
            )
            state["current_signal_date"] = day_key
            _write_state(state_path, state)
            raise

    state["status"] = "complete"
    state["completed_signal_dates"] = len(selected_dates)
    state["elapsed_seconds"] = round(time.perf_counter() - run_started, 2)
    _write_state(state_path, state)
    print(f"complete: {state_path}", flush=True)


if __name__ == "__main__":  # pragma: no cover - command-line entrypoint
    main()
