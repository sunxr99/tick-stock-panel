"""Reproducible read-only VP V1 smoke, comparison, and timing runner.

It neither writes Parquet nor touches strategy results.  The default two
months are intentionally within the local one-year minute history.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

import polars as pl

from app.services.volume_profile import (
    AllocationMode,
    ProfileType,
    VolumeProfileRequest,
    VolumeProfileService,
)
from app.tickflow.repository import DataStore, KlineRepository


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _summary(result) -> dict:
    return {
        "quality": result.quality,
        "granularity": result.data_granularity,
        "fallback_used": result.fallback_used,
        "minute_coverage_ratio": result.minute_coverage_ratio,
        "required_trading_days": result.required_trading_days,
        "actual_trading_days": result.actual_trading_days,
        "expected_minute_bars": result.expected_minute_bars,
        "actual_minute_bars": result.actual_minute_bars,
        "poc": result.poc,
        "vah": result.vah,
        "val": result.val,
        "position": result.position_context,
        "acceptance": result.acceptance_context,
        "extension": result.extension_context,
        "poc_state": result.poc_state,
        "value_area_state": result.value_area_state,
        "unavailable_reason": result.unavailable_reason,
    }


def _run_one(service: VolumeProfileService, symbol: str, as_of: date) -> dict:
    minute = service.build_with_dynamic_context(
        symbol, VolumeProfileRequest(ProfileType.VP20, as_of)
    )
    daily = service.build(
        symbol,
        VolumeProfileRequest(
            ProfileType.VP20,
            as_of,
            allocation_mode=AllocationMode.DAILY_RANGE_OVERLAP,
        ),
    )
    close = service.build(
        symbol,
        VolumeProfileRequest(
            ProfileType.VP20,
            as_of,
            allocation_mode=AllocationMode.CLOSE_ONLY,
        ),
    )
    vp60 = service.build_with_dynamic_context(
        symbol, VolumeProfileRequest(ProfileType.VP60, as_of)
    )
    return {
        "symbol": symbol,
        "as_of": as_of.isoformat(),
        "vp20_minute_range_overlap": _summary(minute),
        "vp20_daily_range_overlap": _summary(daily),
        "vp20_close_only": _summary(close),
        "vp60_minute_range_overlap": _summary(vp60),
    }


def _benchmark(service: VolumeProfileService, repo: KlineRepository, as_of: date, count: int) -> dict:
    instruments = repo.get_instruments()
    symbols = (
        instruments.filter(
            pl.col("symbol").str.ends_with(".SH")
            | pl.col("symbol").str.ends_with(".SZ")
            | pl.col("symbol").str.ends_with(".BJ")
        )
        .get_column("symbol")
        .head(count)
        .to_list()
    )
    started = time.perf_counter()
    results = [service.build_vp20(str(symbol), as_of) for symbol in symbols]
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "count": len(symbols),
        "elapsed_ms": round(elapsed_ms, 2),
        "per_symbol_ms": round(elapsed_ms / len(symbols), 2) if symbols else None,
        "full": sum(item.quality == "FULL" for item in results),
        "partial": sum(item.quality == "PARTIAL" for item in results),
        "fallback": sum(item.quality == "FALLBACK" for item in results),
        "unavailable": sum(item.quality == "UNAVAILABLE" for item in results),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--months", nargs="*", default=["2025-10-31", "2026-02-27"])
    parser.add_argument("--symbols", nargs="*", default=["000001.SZ", "600519.SH", "300750.SZ"])
    parser.add_argument("--benchmark-counts", nargs="*", type=int, default=[])
    args = parser.parse_args()
    repo = KlineRepository(DataStore(args.data_dir.resolve()))
    service = VolumeProfileService(repo)
    output = {"samples": [_run_one(service, symbol, _parse_date(month)) for month in args.months for symbol in args.symbols]}
    if args.benchmark_counts:
        as_of = _parse_date(args.months[-1])
        output["performance"] = [_benchmark(service, repo, as_of, count) for count in args.benchmark_counts]
    print(json.dumps(output, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
