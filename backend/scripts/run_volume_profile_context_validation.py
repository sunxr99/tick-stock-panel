"""Build read-only VP contexts for the complete Wyckoff research cohort.

The runner deliberately works only from the already materialized
``ALL_WYCKOFF`` cohort.  It never changes a strategy result, and it persists
one Parquet checkpoint per signal day so an interrupted long run can resume
without recalculating completed dates.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from app.services.volume_profile import (
    BatchMinuteDataContext,
    ProfileQuality,
    ProfileType,
    VolumeProfileRequest,
    VolumeProfileResult,
    VolumeProfileService,
)
from app.tickflow.repository import DataStore, KlineRepository

ALL_WYCKOFF = "ALL_WYCKOFF"
DAILY_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return None


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _profile_values(prefix: str, result: VolumeProfileResult | None, *, reason: str | None = None) -> dict[str, object]:
    if result is None:
        return {
            f"{prefix}_quality": ProfileQuality.UNAVAILABLE,
            f"{prefix}_unavailable_reason": reason or "not_computed",
        }
    return {
        f"{prefix}_quality": _text(result.quality),
        f"{prefix}_data_granularity": _text(result.data_granularity),
        f"{prefix}_allocation_mode": _text(result.allocation_mode),
        f"{prefix}_fallback_used": result.fallback_used,
        f"{prefix}_minute_coverage_ratio": result.minute_coverage_ratio,
        f"{prefix}_expected_minute_bars": result.expected_minute_bars,
        f"{prefix}_actual_minute_bars": result.actual_minute_bars,
        f"{prefix}_required_trading_days": result.required_trading_days,
        f"{prefix}_actual_trading_days": result.actual_trading_days,
        f"{prefix}_poc": result.poc,
        f"{prefix}_vah": result.vah,
        f"{prefix}_val": result.val,
        f"{prefix}_current_price": result.current_price,
        f"{prefix}_distance_to_poc_pct": result.distance_to_poc_pct,
        f"{prefix}_distance_to_vah_pct": result.distance_to_vah_pct,
        f"{prefix}_distance_to_poc_atr": result.distance_to_poc_atr,
        f"{prefix}_distance_to_vah_atr": result.distance_to_vah_atr,
        f"{prefix}_position": _text(result.position_context),
        f"{prefix}_proximity": ",".join(str(item) for item in result.proximity_contexts),
        f"{prefix}_acceptance": _text(result.acceptance_context),
        f"{prefix}_extension": _text(result.extension_context),
        f"{prefix}_poc_state": _text(result.poc_state),
        f"{prefix}_value_area_state": _text(result.value_area_state),
        f"{prefix}_poc_change_3d_pct": result.poc_change_3d_pct,
        f"{prefix}_vah_change_3d_pct": result.vah_change_3d_pct,
        f"{prefix}_val_change_3d_pct": result.val_change_3d_pct,
        f"{prefix}_unavailable_reason": result.unavailable_reason,
    }


def _write_progress(
    path: Path,
    *,
    status: str,
    completed_dates: int,
    total_dates: int,
    completed_observations: int,
    total_observations: int,
    signal_date: date | None = None,
    elapsed_seconds: float | None = None,
    current_date_observations: int | None = None,
    current_date_total_observations: int | None = None,
    stage: str | None = None,
    preloaded_minute_dates: int | None = None,
    total_preload_minute_dates: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "completed_signal_dates": completed_dates,
                "total_signal_dates": total_dates,
                "completed_observations": completed_observations,
                "total_observations": total_observations,
                "signal_date": signal_date.isoformat() if signal_date else None,
                "elapsed_seconds": round(elapsed_seconds, 2) if elapsed_seconds is not None else None,
                "current_date_observations": current_date_observations,
                "current_date_total_observations": current_date_total_observations,
                "stage": stage,
                "preloaded_minute_dates": preloaded_minute_dates,
                "total_preload_minute_dates": total_preload_minute_dates,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _range_profile(
    service: VolumeProfileService,
    context: BatchMinuteDataContext,
    *,
    symbol: str,
    as_of: date,
    range_start: date | None,
    range_confirmed_at: date | None,
) -> VolumeProfileResult | None:
    if range_start is None:
        return None
    if range_confirmed_at is None or range_confirmed_at > as_of:
        return None
    return service.build_with_dynamic_context_from_context(
        context,
        symbol,
        VolumeProfileRequest(
            ProfileType.WYCKOFF_RANGE,
            as_of,
            range_start=range_start,
            range_confirmed_at=range_confirmed_at,
        ),
    )


def _one_date(
    service: VolumeProfileService,
    context: BatchMinuteDataContext,
    rows: pl.DataFrame,
    on_progress: Callable[[int, int, date], None] | None = None,
) -> pl.DataFrame:
    output: list[dict[str, object]] = []
    total = rows.height
    for index, row in enumerate(rows.iter_rows(named=True), start=1):
        as_of = _as_date(row["signal_date"])
        if as_of is None:
            raise ValueError("signal_date is required")
        symbol = str(row["symbol"])
        vp20 = service.build_with_dynamic_context_from_context(context, symbol, VolumeProfileRequest(ProfileType.VP20, as_of))
        vp60 = service.build_with_dynamic_context_from_context(context, symbol, VolumeProfileRequest(ProfileType.VP60, as_of))
        range_start = _as_date(row.get("wyckoff_range_start"))
        range_confirmed_at = _as_date(row.get("wyckoff_range_confirmed_at"))
        range_vp = _range_profile(
            service,
            context,
            symbol=symbol,
            as_of=as_of,
            range_start=range_start,
            range_confirmed_at=range_confirmed_at,
        )
        output.append(
            {
                **row,
                **_profile_values("vp20", vp20),
                **_profile_values("vp60", vp60),
                **_profile_values(
                    "range_vp",
                    range_vp,
                    reason=(
                        "wyckoff_range_start_unavailable"
                        if range_start is None
                        else "wyckoff_range_not_as_of_confirmed"
                        if range_confirmed_at is None or range_confirmed_at > as_of
                        else None
                    ),
                ),
            }
        )
        if on_progress is not None and (index % 10 == 0 or index == total):
            on_progress(index, total, as_of)
    return pl.DataFrame(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("../data/research/wyckoff_sector_rs_cohorts_2026-02-02_2026-02-27.parquet"),
    )
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--output-dir", type=Path, default=Path("../data/research/vp_context_2026-02"))
    parser.add_argument("--progress-path", type=Path, default=Path("../data/research/vp_context_validation_progress.json"))
    parser.add_argument(
        "--signal-dates",
        nargs="*",
        type=date.fromisoformat,
        default=None,
        help="optional explicit signal dates for a reproducible research subset",
    )
    parser.add_argument("--restart", action="store_true", help="discard only this runner's existing daily checkpoints")
    args = parser.parse_args()

    source = pl.read_parquet(args.input).filter(pl.col("cohort") == ALL_WYCKOFF)
    if args.signal_dates:
        source = source.filter(pl.col("signal_date").is_in(args.signal_dates))
    if source.is_empty():
        raise ValueError("ALL_WYCKOFF cohort is empty")
    signal_dates = sorted({_as_date(value) for value in source.get_column("signal_date").to_list()})
    dates = [value for value in signal_dates if value is not None]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.restart:
        for path in args.output_dir.glob("signal_date=*.parquet"):
            path.unlink()

    repo = KlineRepository(DataStore(args.data_dir.resolve()))
    service = VolumeProfileService(repo)
    started = time.perf_counter()
    completed_dates = 0
    completed_observations = 0
    total = source.height
    _write_progress(
        args.progress_path,
        status="running",
        completed_dates=0,
        total_dates=len(dates),
        completed_observations=0,
        total_observations=total,
    )
    for as_of in dates:
        path = args.output_dir / f"signal_date={as_of.isoformat()}.parquet"
        daily_rows = source.filter(pl.col("signal_date") == as_of)
        if path.exists():
            restored = pl.read_parquet(path)
            if restored.height == daily_rows.height:
                completed_dates += 1
                completed_observations += restored.height
                _write_progress(
                    args.progress_path,
                    status="running",
                    completed_dates=completed_dates,
                    total_dates=len(dates),
                    completed_observations=completed_observations,
                    total_observations=total,
                    signal_date=as_of,
                    elapsed_seconds=time.perf_counter() - started,
                )
                print(f"[resume {completed_dates}/{len(dates)}] {as_of}: rows={restored.height}", flush=True)
                continue
        def on_date_progress(
            current: int,
            day_total: int,
            current_date: date,
            *,
            completed_dates_at_start: int = completed_dates,
            completed_observations_at_start: int = completed_observations,
        ) -> None:
            _write_progress(
                args.progress_path,
                status="running",
                completed_dates=completed_dates_at_start,
                total_dates=len(dates),
                completed_observations=completed_observations_at_start + current,
                total_observations=total,
                signal_date=current_date,
                elapsed_seconds=time.perf_counter() - started,
                current_date_observations=current,
                current_date_total_observations=day_total,
                stage="building_profiles",
            )

        def on_preload(
            current: int,
            preload_total: int,
            *,
            completed_dates_at_start: int = completed_dates,
            completed_observations_at_start: int = completed_observations,
            signal_date_at_start: date = as_of,
        ) -> None:
            _write_progress(
                args.progress_path,
                status="running",
                completed_dates=completed_dates_at_start,
                total_dates=len(dates),
                completed_observations=completed_observations_at_start,
                total_observations=total,
                signal_date=signal_date_at_start,
                elapsed_seconds=time.perf_counter() - started,
                stage="preloading_minute_partitions",
                preloaded_minute_dates=current,
                total_preload_minute_dates=preload_total,
            )

        range_metadata = {
            str(row["symbol"]): (
                _as_date(row.get("wyckoff_range_start")),
                _as_date(row.get("wyckoff_range_confirmed_at")),
            )
            for row in daily_rows.select(["symbol", "wyckoff_range_start", "wyckoff_range_confirmed_at"]).iter_rows(named=True)
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
            symbols=daily_rows.get_column("symbol").to_list(),
            as_of=as_of,
            range_starts=range_starts,
            range_confirmed_at=range_confirmed_at,
            on_minute_partition=on_preload,
        )
        result = _one_date(service, context, daily_rows, on_progress=on_date_progress)
        result.write_parquet(path)
        completed_dates += 1
        completed_observations += result.height
        _write_progress(
            args.progress_path,
            status="running",
            completed_dates=completed_dates,
            total_dates=len(dates),
            completed_observations=completed_observations,
            total_observations=total,
            signal_date=as_of,
            elapsed_seconds=time.perf_counter() - started,
        )
        print(f"[{completed_dates}/{len(dates)}] {as_of}: rows={result.height}", flush=True)
    _write_progress(
        args.progress_path,
        status="complete",
        completed_dates=completed_dates,
        total_dates=len(dates),
        completed_observations=completed_observations,
        total_observations=total,
        signal_date=dates[-1],
        elapsed_seconds=time.perf_counter() - started,
    )


if __name__ == "__main__":
    main()
