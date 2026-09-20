"""Read-only performance benchmark for VP single and batch execution paths."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from time import perf_counter

import polars as pl
import psutil

from app.services.volume_profile import (
    ProfileType,
    VolumeProfileMode,
    VolumeProfileRequest,
    VolumeProfileService,
)
from app.tickflow.repository import DataStore, KlineRepository


def _as_date(value: object) -> date | None:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10]) if value else None


def _rows(path: Path, as_of: date, count: int) -> pl.DataFrame:
    return (
        pl.read_parquet(path)
        .filter((pl.col("cohort") == "ALL_WYCKOFF") & (pl.col("signal_date") == as_of))
        .head(count)
    )


def _range_metadata(rows: pl.DataFrame, as_of: date) -> tuple[dict[str, date], dict[str, date]]:
    pairs = {
        str(row["symbol"]): (start, confirmed)
        for row in rows.iter_rows(named=True)
        if (start := _as_date(row.get("wyckoff_range_start"))) is not None
        and (confirmed := _as_date(row.get("wyckoff_range_confirmed_at"))) is not None
        and confirmed <= as_of
    }
    return (
        {symbol: start for symbol, (start, _) in pairs.items()},
        {symbol: confirmed for symbol, (_, confirmed) in pairs.items()},
    )


def _one(service: VolumeProfileService, rows: pl.DataFrame, as_of: date, *, full: bool) -> dict[str, object]:
    symbols = [str(value) for value in rows.get_column("symbol").to_list()]
    ranges, range_confirmed_at = _range_metadata(rows, as_of)
    process = psutil.Process()
    rss_base = process.memory_info().rss
    old_started = perf_counter()
    for symbol in symbols:
        service.build(symbol, VolumeProfileRequest(ProfileType.VP20, as_of))
    old_vp20_ms = (perf_counter() - old_started) * 1000.0

    prepare_started = perf_counter()
    context = service.prepare_batch_context(
        symbols=symbols,
        as_of=as_of,
        range_starts=ranges,
        range_confirmed_at=range_confirmed_at,
    )
    prepare_ms = (perf_counter() - prepare_started) * 1000.0
    rss_after_prepare = process.memory_info().rss
    lite_started = perf_counter()
    service.build_batch(context, symbols=symbols, mode=VolumeProfileMode.LITE)
    lite_ms = (perf_counter() - lite_started) * 1000.0
    result: dict[str, object] = {
        "candidates": len(symbols),
        "old_single_vp20_total_ms": round(old_vp20_ms, 2),
        "batch_prepare_ms": round(prepare_ms, 2),
        "batch_lite_compute_ms": round(lite_ms, 2),
        "batch_lite_total_ms": round(prepare_ms + lite_ms, 2),
        "lite_speedup_vs_single_vp20": round(old_vp20_ms / (prepare_ms + lite_ms), 3) if prepare_ms + lite_ms else None,
        "minute_partition_reads": context.minute_partition_reads,
        "minute_rows_loaded": context.minute_rows_loaded,
        "minute_estimated_bytes": context.minute_estimated_bytes,
        "rss_base_bytes": rss_base,
        "rss_after_prepare_bytes": rss_after_prepare,
        "rss_after_lite_bytes": process.memory_info().rss,
        "context_timings_ms": {key: round(value, 2) for key, value in context.timings_ms.items()},
    }
    if full:
        full_started = perf_counter()
        service.build_batch(
            context,
            symbols=symbols,
            mode=VolumeProfileMode.FULL,
            range_starts=ranges,
            range_confirmed_at=range_confirmed_at,
        )
        result["batch_full_compute_ms"] = round((perf_counter() - full_started) * 1000.0, 2)
        result["batch_full_total_ms"] = round(prepare_ms + float(result["batch_full_compute_ms"]), 2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("../data/research/wyckoff_sector_rs_cohorts_2026-02-02_2026-02-27.parquet"))
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 2, 27))
    parser.add_argument("--counts", nargs="*", type=int, default=[20, 100, 500])
    parser.add_argument("--full-max", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("../data/research/volume_profile_batch_benchmark.json"))
    args = parser.parse_args()
    service = VolumeProfileService(KlineRepository(DataStore(args.data_dir.resolve())))
    results = []
    for count in args.counts:
        rows = _rows(args.input, args.as_of, count)
        if rows.height < count:
            raise ValueError(f"only {rows.height} candidates available for {args.as_of}")
        results.append(_one(service, rows, args.as_of, full=count <= args.full_max))
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    payload = {"as_of": args.as_of.isoformat(), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
