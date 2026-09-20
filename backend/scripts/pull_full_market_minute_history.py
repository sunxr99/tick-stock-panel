"""Backfill current A-share universe 1-minute OHLCV in resumable small ranges.

This is an operational data-ingestion script.  It deliberately reuses the
existing TickFlow batch fetcher and date-partition writer instead of creating a
parallel storage format.  A checkpoint is advanced only after one calendar
segment returns and its rows have been written; rerunning a completed segment
is safe because the writer de-duplicates (symbol, datetime).
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import polars as pl

from app.config import settings
from app.services.kline_sync import _write_minute_partition, sync_minute_batch
from app.tickflow.capabilities import Cap
from app.tickflow.policy import detect_capabilities
from app.tickflow.repository import DataStore, KlineRepository


def _current_a_share_symbols(repo: KlineRepository) -> list[str]:
    instruments = repo.get_instruments()
    if instruments.is_empty() or "symbol" not in instruments.columns:
        raise RuntimeError("current stock instruments are unavailable")
    return sorted(
        symbol
        for symbol in instruments.get_column("symbol").drop_nulls().cast(pl.String).to_list()
        if symbol.endswith((".SH", ".SZ", ".BJ"))
    )


def _checkpoint_path(data_dir: Path, start: date, end: date) -> Path:
    return data_dir / "kline_minute" / f"_full_market_1m_{start}_{end}.json"


def _load_resume_start(path: Path, start: date, end: date) -> date:
    if not path.exists():
        return start
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        completed = date.fromisoformat(str(saved["completed_through"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return start
    next_day = completed + timedelta(days=1)
    return min(next_day, end + timedelta(days=1))


def _save_checkpoint(
    path: Path,
    *,
    start: date,
    end: date,
    completed_through: date,
    symbol_count: int,
    rows_written: int,
) -> None:
    payload = {
        "kind": "current_a_share_1m_backfill",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "completed_through": completed_through.isoformat(),
        "symbol_count": symbol_count,
        "rows_written_from_touched_partitions": rows_written,
        "note": "Current instrument snapshot is used; this is not a historical constituent universe.",
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def pull(*, start: date, end: date, segment_calendar_days: int, dry_run: bool = False) -> None:
    if start > end:
        raise ValueError("start must not be after end")
    if segment_calendar_days < 1:
        raise ValueError("segment_calendar_days must be positive")

    store = DataStore(settings.data_dir)
    repo = KlineRepository(store)
    symbols = _current_a_share_symbols(repo)
    capset = detect_capabilities()
    if not capset.has(Cap.KLINE_MINUTE_BATCH):
        raise RuntimeError("current provider does not grant kline.minute.batch")
    checkpoint = _checkpoint_path(store.data_dir, start, end)
    cursor = _load_resume_start(checkpoint, start, end)
    total_segments = max(0, ((end - cursor).days // segment_calendar_days) + 1)
    print(json.dumps({
        "start": start.isoformat(),
        "end": end.isoformat(),
        "resume_from": cursor.isoformat() if cursor <= end else None,
        "symbols": len(symbols),
        "segment_calendar_days": segment_calendar_days,
        "estimated_segments": total_segments,
        "checkpoint": str(checkpoint),
        "dry_run": dry_run,
    }, ensure_ascii=False))
    if dry_run or cursor > end:
        return

    segment_number = 0
    while cursor <= end:
        segment_number += 1
        segment_end = min(end, cursor + timedelta(days=segment_calendar_days - 1))
        touched_rows = [0]

        def persist(frame: pl.DataFrame, *, state: list[int] = touched_rows) -> None:
            with repo._write_lock:
                state[0] += _write_minute_partition(frame, store.data_dir / "kline_minute")

        def progress(
            current: int,
            total: int,
            label: str,
            *,
            current_segment: int = segment_number,
            segments: int = total_segments,
            segment_start: date = cursor,
            current_segment_end: date = segment_end,
        ) -> None:
            if current == 1 or current == total or current % 10 == 0:
                print(
                    f"segment={current_segment}/{segments} range={segment_start}~{current_segment_end} "
                    f"request={current}/{total} provider_range={label}",
                    flush=True,
                )

        print(f"starting segment={segment_number}/{total_segments} range={cursor}~{segment_end}", flush=True)
        sync_minute_batch(
            symbols,
            start_time=datetime.combine(cursor, time.min),
            end_time=datetime.combine(segment_end, time(hour=16)),
            batch_size=100,
            rpm=30,
            on_chunk_done=progress,
            # Five trading days keeps a full-market segment bounded rather
            # than accumulating a whole month of minute rows in memory.
            segment_trading_days=5,
            on_segment=persist,
        )
        _save_checkpoint(
            checkpoint,
            start=start,
            end=end,
            completed_through=segment_end,
            symbol_count=len(symbols),
            rows_written=touched_rows[0],
        )
        print(
            f"completed segment={segment_number}/{total_segments} range={cursor}~{segment_end} "
            f"rows_from_touched_partitions={touched_rows[0]}",
            flush=True,
        )
        cursor = segment_end + timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2025-09-12", help="inclusive YYYY-MM-DD")
    parser.add_argument("--end", default="2026-09-11", help="inclusive YYYY-MM-DD")
    parser.add_argument("--segment-calendar-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    pull(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        segment_calendar_days=args.segment_calendar_days,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
