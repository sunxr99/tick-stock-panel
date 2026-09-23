"""Download point-in-time Eastmoney board and constituent history from Tushare.

The Tushare ``dc_index`` endpoint supplies the board daily facts, while
``dc_member`` supplies a date-stamped member relation.  Member data is saved
one trade date per Parquet shard so an interrupted long download can resume
without discarding completed work or accumulating an unbounded board history
in memory.  The script deliberately does not write to the existing SW
membership store: the taxonomies are different.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import polars as pl

_API_URL = "https://tuaremax.top"
_DC_INDEX_FIELDS = (
    "ts_code,trade_date,name,leading,leading_code,pct_change,leading_pct,"
    "total_mv,turnover_rate,up_num,down_num,idx_type,level"
)
_DC_MEMBER_FIELDS = "trade_date,ts_code,con_code,name"
_PAGE_SIZE = 2_000
_RETRIES = 5


def _request(
    client: httpx.Client, *, token: str, api_name: str, params: dict[str, Any], fields: str
) -> dict[str, Any]:
    """Call one Tushare page, retrying only the mirror's transient limit errors."""
    last_error: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            response = client.post(
                _API_URL,
                json={"api_name": api_name, "token": token, "params": params, "fields": fields},
            )
            response.raise_for_status()
            payload = response.json()
            if int(payload.get("code", -1)) == 0:
                return payload.get("data") or {}
            message = str(payload.get("msg") or payload.get("message") or "unknown Tushare error")
            if "连接超限" not in message and "过多线程" not in message:
                raise RuntimeError(f"{api_name}: {message}")
            last_error = RuntimeError(f"{api_name}: {message}")
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"{api_name} failed after {_RETRIES} attempts: {last_error}")


def _frame(data: dict[str, Any], *, expected_fields: str) -> pl.DataFrame:
    fields = list(data.get("fields") or [])
    expected = expected_fields.split(",")
    if fields != expected:
        raise RuntimeError(f"unexpected fields: expected {expected}, got {fields}")
    rows = list(data.get("items") or [])
    return pl.DataFrame(rows, schema=fields, orient="row") if rows else pl.DataFrame(schema={field: pl.Utf8 for field in fields})


def _atomic_parquet(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    frame.write_parquet(temporary, compression="zstd")
    temporary.replace(path)


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _member_shard_path(root: Path, trade_date: str) -> Path:
    return root / "dc_members" / f"trade_date={trade_date}" / "part.parquet"


def _fetch_member_snapshot(
    client: httpx.Client, *, token: str, trade_date: str
) -> pl.DataFrame:
    pages: list[pl.DataFrame] = []
    offset = 0
    page_signatures: set[tuple[object, object, int]] = set()
    while True:
        data = _request(
            client,
            token=token,
            api_name="dc_member",
            params={"trade_date": trade_date, "limit": _PAGE_SIZE, "offset": offset},
            fields=_DC_MEMBER_FIELDS,
        )
        page = _frame(data, expected_fields=_DC_MEMBER_FIELDS)
        if page.is_empty():
            break
        signature = (page.row(0), page.row(-1), page.height)
        if signature in page_signatures:
            raise RuntimeError(f"dc_member pagination repeated a page for {trade_date} at offset {offset}")
        page_signatures.add(signature)
        pages.append(page)
        if not bool(data.get("has_more")):
            break
        offset += page.height
        time.sleep(0.15)
    if not pages:
        return pl.DataFrame(schema={field: pl.Utf8 for field in _DC_MEMBER_FIELDS.split(",")})
    return pl.concat(pages, how="vertical").filter(
        pl.col("trade_date") == pl.lit(trade_date)
    ).unique().sort(
        ["trade_date", "ts_code", "con_code"]
    )


def pull(*, start: date, end: date, token: str, output_dir: Path, resume: bool = True, max_dates: int | None = None) -> dict[str, Any]:
    if start > end:
        raise ValueError("start must not be after end")
    start_text, end_text = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    output_dir = output_dir.resolve()
    manifest_path = output_dir / "dc_members_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if resume and manifest_path.exists() else {}
    completed = set(manifest.get("completed_dates") or [])
    empty = set(manifest.get("empty_dates") or [])
    failed: dict[str, str] = dict(manifest.get("failed_dates") or {})

    with httpx.Client(timeout=90.0) as client:
        index_data = _request(client, token=token, api_name="dc_index", params={}, fields=_DC_INDEX_FIELDS)
        index = _frame(index_data, expected_fields=_DC_INDEX_FIELDS).filter(
            pl.col("trade_date").is_between(pl.lit(start_text), pl.lit(end_text))
        ).sort(["trade_date", "ts_code"])
        _atomic_parquet(index, output_dir / "dc_index.parquet")
        board_count = index.get_column("ts_code").n_unique()
        trade_dates = index.get_column("trade_date").unique().sort().to_list()
        if max_dates is not None:
            trade_dates = trade_dates[:max_dates]
        print(f"dc_index rows={index.height}; boards={board_count}; dates={len(trade_dates)}", flush=True)

        for position, trade_date in enumerate(trade_dates, start=1):
            if resume and (trade_date in completed or trade_date in empty):
                continue
            try:
                members = _fetch_member_snapshot(client, token=token, trade_date=trade_date)
                if members.is_empty():
                    empty.add(trade_date)
                else:
                    _atomic_parquet(members, _member_shard_path(output_dir, trade_date))
                    completed.add(trade_date)
                failed.pop(trade_date, None)
            except Exception as exc:  # Preserve successful shards and report the exact unresolved board.
                failed[trade_date] = str(exc)
            _atomic_json(
                {
                    "requested_start": start.isoformat(),
                    "requested_end": end.isoformat(),
                    "completed_dates": sorted(completed),
                    "empty_dates": sorted(empty),
                    "failed_dates": failed,
                },
                manifest_path,
            )
            if position % 10 == 0 or position == len(trade_dates):
                print(
                    f"members progress={position}/{len(trade_dates)} completed={len(completed)} "
                    f"empty={len(empty)} failed={len(failed)}",
                    flush=True,
                )
            time.sleep(0.15)

    metadata = {
        "source": "tushare_dc_index_dc_member",
        "api_url": _API_URL,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "dc_index_rows": index.height,
        "dc_index_observed_start": index.get_column("trade_date").min() if not index.is_empty() else None,
        "dc_index_observed_end": index.get_column("trade_date").max() if not index.is_empty() else None,
        "board_count": board_count,
        "trade_date_count": len(trade_dates),
        "completed_trade_date_count": len(completed),
        "empty_trade_date_count": len(empty),
        "failed_trade_date_count": len(failed),
        "member_storage": "dc_members/trade_date=<YYYYMMDD>/part.parquet",
        "point_in_time_key": "trade_date + ts_code + con_code",
        "note": "Member coverage is board-specific. Missing date-board rows must be treated as unavailable, not backfilled.",
    }
    _atomic_json(metadata, output_dir / "metadata.json")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-09-22")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--output-dir", type=Path, default=Path("../data/eastmoney_board_history"))
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--max-dates", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("Set TUSHARE_TOKEN in the environment; it is never persisted by this script.")
    print(json.dumps(
        pull(
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            token=token,
            output_dir=args.output_dir,
            resume=not args.no_resume,
            max_dates=args.max_dates,
        ),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
