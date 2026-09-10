"""Run a memory-bounded, executable-price Wyckoff V2 research backtest.

Example (from ``backend``)::

    uv run --frozen python scripts/run_wyckoff_v2_research.py \
      --start 2025-09-05 --end 2026-09-04 --batch-size 100

This script is intentionally research-only. It reads the front-adjusted daily
parquet and writes a report under ``data/research``; it never changes funnel
configuration, cached screener results, or strategy parameters.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from datetime import date
from itertools import islice
from pathlib import Path

import pandas as pd
import polars as pl

from app.parquet import scan_enriched_parquet
from app.wyckoff.v2 import run_event_backtest_frames

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "kline_daily_enriched"


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _batches(values: list[str], size: int) -> Iterator[list[str]]:
    iterator = iter(values)
    while batch := list(islice(iterator, size)):
        yield batch


def _load_frames(
    source: pl.LazyFrame,
    symbols: list[str],
    *,
    batch_size: int,
) -> Iterator[tuple[str, pd.DataFrame]]:
    total_batches = (len(symbols) + batch_size - 1) // batch_size
    for batch_number, batch in enumerate(_batches(symbols, batch_size), start=1):
        partition = (
            source.filter(pl.col("symbol").is_in(batch))
            .sort(["symbol", "date"])
            .collect()
        )
        print(f"已加载 {batch_number}/{total_batches} 批 ({len(batch)} 只股票)", flush=True)
        for key, frame in partition.partition_by("symbol", as_dict=True, maintain_order=True).items():
            symbol = str(key[0] if isinstance(key, tuple) else key)
            yield symbol, frame.drop("symbol").to_pandas()


def main() -> None:
    parser = argparse.ArgumentParser(description="Wyckoff V2 事件级研究回测 (前复权日线, 次日开盘入场)")
    parser.add_argument("--start", type=_parse_date, required=True, help="含首日, 格式 YYYY-MM-DD")
    parser.add_argument("--end", type=_parse_date, required=True, help="含末日, 格式 YYYY-MM-DD")
    parser.add_argument("--batch-size", type=int, default=100, help="每批股票数, 默认 100")
    parser.add_argument("--symbol-limit", type=int, default=0, help="仅用于试跑; 0 代表全市场")
    parser.add_argument("--output", type=Path, default=None, help="报告 JSON 路径")
    args = parser.parse_args()
    if args.start > args.end:
        raise ValueError("--start 不能晚于 --end")
    if args.batch_size <= 0:
        raise ValueError("--batch-size 必须为正数")

    source = (
        scan_enriched_parquet(str(DEFAULT_DATA_DIR / "**" / "*.parquet"))
        .filter(pl.col("date").is_between(args.start, args.end))
        .select(["symbol", "date", "open", "high", "low", "close", "volume"])
    )
    symbols = source.select(pl.col("symbol").unique().sort()).collect().get_column("symbol").to_list()
    if args.symbol_limit > 0:
        symbols = symbols[: args.symbol_limit]
    if not symbols:
        raise ValueError("所选日期范围没有可回测的日线数据")

    print(
        f"开始回测: {args.start.isoformat()} 至 {args.end.isoformat()}, {len(symbols)} 只股票, "
        f"每批 {args.batch_size} 只.",
        flush=True,
    )
    report = run_event_backtest_frames(_load_frames(source, symbols, batch_size=args.batch_size))
    report["dataset"] = {
        "source": "kline_daily_enriched",
        "price_basis": "front_adjusted",
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "symbols_loaded": len(symbols),
        "batch_size": args.batch_size,
    }
    output = args.output or PROJECT_ROOT / "data" / "research" / (
        f"wyckoff_v2_event_backtest_{args.start.isoformat()}_{args.end.isoformat()}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"回测完成, 报告已写入: {output}", flush=True)


if __name__ == "__main__":
    main()
