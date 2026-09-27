"""Download the latest ten TDX 88-board sessions and member snapshots.

Credentials use ``TUSHARE_TOKEN`` or the application's local secure store.  The script writes a
separate point-in-time dataset and never changes the existing 东方财富、同花顺或申万
membership stores.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import polars as pl

_API_URL = "https://tuaremax.top"
_INDEX_FIELDS = "ts_code,trade_date,name,idx_type,idx_count,total_share,float_share,total_mv,float_mv"
_DAILY_FIELDS = "ts_code,trade_date,close,open,high,low,pre_close,change,pct_change,vol,amount,rise,vol_ratio,turnover_rate,swing,up_num,down_num,limit_up_num,limit_down_num,lu_days,3day,5day,10day,20day,60day,mtd,ytd,1year,pe,pb,float_mv,ab_total_mv,float_share,total_share,bm_buy_net,bm_buy_ratio,bm_net,bm_ratio"
_MEMBER_FIELDS = "ts_code,trade_date,con_code,con_name"
_PAGE_SIZE = 10_000
_RETRIES = 5


def _request(client: httpx.Client, *, token: str, api_name: str, params: dict[str, Any], fields: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            progress = ", ".join(f"{key}={value}" for key, value in params.items()) or "latest"
            print(f"TDX request {api_name} ({progress}), attempt {attempt + 1}/{_RETRIES}", flush=True)
            response = client.post(_API_URL, json={"api_name": api_name, "token": token, "params": params, "fields": fields})
            response.raise_for_status()
            payload = response.json()
            if int(payload.get("code", -1)) == 0:
                return payload.get("data") or {}
            raise RuntimeError(f"{api_name}: {payload.get('msg') or payload.get('message') or 'unknown Tushare error'}")
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last_error = exc
            print(f"TDX request {api_name} failed: {exc}; retrying", flush=True)
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"{api_name} failed after {_RETRIES} attempts: {last_error}")


def _frame(data: dict[str, Any], fields: str) -> pl.DataFrame:
    columns = fields.split(",")
    got = list(data.get("fields") or [])
    if got != columns:
        raise RuntimeError(f"unexpected fields: expected {columns}, got {got}")
    items = list(data.get("items") or [])
    return pl.DataFrame(items, schema=columns, orient="row") if items else pl.DataFrame(schema={column: pl.Utf8 for column in columns})


def _write(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    frame.write_parquet(temporary, compression="zstd")
    temporary.replace(path)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _upsert_day(path: Path, frame: pl.DataFrame, *, trade_date: str) -> pl.DataFrame:
    """Replace one date in a fact file while preserving the existing window."""
    if path.exists():
        existing = pl.read_parquet(path).filter(pl.col("trade_date").cast(pl.Utf8) != trade_date)
        frame = pl.concat([existing, frame], how="diagonal_relaxed")
    return frame.unique().sort(["trade_date", "ts_code"])


def _member_snapshot(client: httpx.Client, *, token: str, trade_date: str) -> pl.DataFrame:
    pages: list[pl.DataFrame] = []
    offset = 0
    while True:
        data = _request(client, token=token, api_name="tdx_member", params={"trade_date": trade_date, "limit": _PAGE_SIZE, "offset": offset}, fields=_MEMBER_FIELDS)
        page = _frame(data, _MEMBER_FIELDS)
        if page.is_empty():
            break
        pages.append(page)
        print(f"TDX {trade_date}: member page offset={offset}, rows={page.height}", flush=True)
        if not data.get("has_more", page.height == _PAGE_SIZE):
            break
        offset += page.height
        time.sleep(0.1)
    if not pages:
        return pl.DataFrame(schema={column: pl.Utf8 for column in _MEMBER_FIELDS.split(",")})
    return pl.concat(pages, how="vertical").filter(pl.col("trade_date") == trade_date).unique().sort(["ts_code", "con_code"])


def pull(*, token: str, output_dir: Path, sessions: int = 10) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    with httpx.Client(timeout=90.0) as client:
        all_index = _frame(_request(client, token=token, api_name="tdx_index", params={}, fields=_INDEX_FIELDS), _INDEX_FIELDS)
        candidate_dates = all_index.get_column("trade_date").cast(pl.Utf8).unique().sort(descending=True).to_list()
        daily_frames = []
        completed: list[str] = []
        member_rows: dict[str, int] = {}
        skipped_without_members: list[str] = []
        for trade_date in candidate_dates:
            daily = _frame(_request(client, token=token, api_name="tdx_daily", params={"trade_date": trade_date}, fields=_DAILY_FIELDS), _DAILY_FIELDS)
            members = _member_snapshot(client, token=token, trade_date=trade_date)
            if members.is_empty():
                skipped_without_members.append(trade_date)
                print(f"TDX {trade_date}: skipped because its member snapshot is not published", flush=True)
                continue
            daily_frames.append(daily)
            _write(members, output_dir / "tdx_members" / f"trade_date={trade_date}" / "part.parquet")
            completed.append(trade_date)
            member_rows[trade_date] = members.height
            print(f"TDX {trade_date}: boards={daily.height}, members={members.height}", flush=True)
            if len(completed) >= sessions:
                break
            time.sleep(0.1)
    completed.sort()
    index = all_index.filter(pl.col("trade_date").is_in(completed)).sort(["trade_date", "ts_code"])
    _write(index, output_dir / "tdx_index.parquet")
    daily = pl.concat(daily_frames, how="vertical").unique().sort(["trade_date", "ts_code"])
    _write(daily, output_dir / "tdx_daily.parquet")
    metadata = {
        "source": "tushare_tdx_index_tdx_daily_tdx_member",
        "requested_sessions": sessions,
        "trade_dates": completed,
        "index_rows": index.height,
        "daily_rows": daily.height,
        "member_rows_by_date": member_rows,
        "skipped_without_members": skipped_without_members,
        "member_storage": "tdx_members/trade_date=<YYYYMMDD>/part.parquet",
        "point_in_time_key": "trade_date + ts_code + con_code",
        "note": "TDX categories are flat: concept, industry, style, and region; no level hierarchy is inferred.",
    }
    _write_json(metadata, output_dir / "metadata.json")
    return metadata


def refresh_trade_date(*, token: str, output_dir: Path, trade_date: str, sessions: int = 10) -> dict[str, Any]:
    """Fetch a newly published session without redownloading prior snapshots."""
    output_dir = output_dir.resolve()
    with httpx.Client(timeout=90.0) as client:
        index = _frame(_request(client, token=token, api_name="tdx_index", params={"trade_date": trade_date}, fields=_INDEX_FIELDS), _INDEX_FIELDS)
        daily = _frame(_request(client, token=token, api_name="tdx_daily", params={"trade_date": trade_date}, fields=_DAILY_FIELDS), _DAILY_FIELDS)
        members = _member_snapshot(client, token=token, trade_date=trade_date)
    if index.is_empty() or daily.is_empty() or members.is_empty():
        raise RuntimeError(f"TDX {trade_date} is not complete: index={index.height}, daily={daily.height}, members={members.height}")
    index = _upsert_day(output_dir / "tdx_index.parquet", index, trade_date=trade_date)
    daily = _upsert_day(output_dir / "tdx_daily.parquet", daily, trade_date=trade_date)
    dates = index.get_column("trade_date").cast(pl.Utf8).unique().sort().tail(sessions).to_list()
    index = index.filter(pl.col("trade_date").is_in(dates))
    daily = daily.filter(pl.col("trade_date").is_in(dates))
    _write(index, output_dir / "tdx_index.parquet")
    _write(daily, output_dir / "tdx_daily.parquet")
    _write(members, output_dir / "tdx_members" / f"trade_date={trade_date}" / "part.parquet")
    metadata_path = output_dir / "metadata.json"
    previous = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    counts = {key: value for key, value in dict(previous.get("member_rows_by_date") or {}).items() if key in dates}
    counts[trade_date] = members.height
    metadata = {
        **previous,
        "requested_sessions": sessions,
        "trade_dates": dates,
        "index_rows": index.height,
        "daily_rows": daily.height,
        "member_rows_by_date": counts,
        "skipped_without_members": [item for item in previous.get("skipped_without_members", []) if item != trade_date],
        "refreshed_trade_date": trade_date,
    }
    _write_json(metadata, metadata_path)
    return metadata


def backfill_trade_dates(*, token: str, output_dir: Path, trade_dates: list[str]) -> dict[str, Any]:
    """Append exact historical sessions without truncating the current window.

    This is intended for point-in-time research.  It never substitutes a
    newer member snapshot for an older date, and preserves all existing rows.
    """
    selected = sorted(set(trade_dates))
    if not selected or any(len(value) != 8 or not value.isdigit() for value in selected):
        raise ValueError("trade_dates must contain one or more YYYYMMDD values")
    output_dir = output_dir.resolve()
    with httpx.Client(timeout=90.0) as client:
        index_frames: list[pl.DataFrame] = []
        daily_frames: list[pl.DataFrame] = []
        member_rows: dict[str, int] = {}
        for trade_date in selected:
            print(f"TDX {trade_date}: downloading index, daily, and member snapshot", flush=True)
            index = _frame(_request(client, token=token, api_name="tdx_index", params={"trade_date": trade_date}, fields=_INDEX_FIELDS), _INDEX_FIELDS)
            daily = _frame(_request(client, token=token, api_name="tdx_daily", params={"trade_date": trade_date}, fields=_DAILY_FIELDS), _DAILY_FIELDS)
            members = _member_snapshot(client, token=token, trade_date=trade_date)
            if index.is_empty() or daily.is_empty() or members.is_empty():
                raise RuntimeError(
                    f"TDX {trade_date} is not complete: index={index.height}, daily={daily.height}, members={members.height}"
                )
            index_frames.append(index)
            daily_frames.append(daily)
            _write(members, output_dir / "tdx_members" / f"trade_date={trade_date}" / "part.parquet")
            member_rows[trade_date] = members.height
            print(f"TDX {trade_date}: boards={daily.height}, members={members.height}", flush=True)
            time.sleep(0.1)
    existing_index = pl.read_parquet(output_dir / "tdx_index.parquet") if (output_dir / "tdx_index.parquet").exists() else pl.DataFrame()
    existing_daily = pl.read_parquet(output_dir / "tdx_daily.parquet") if (output_dir / "tdx_daily.parquet").exists() else pl.DataFrame()
    index = pl.concat([existing_index, *index_frames], how="diagonal_relaxed").unique().sort(["trade_date", "ts_code"])
    daily = pl.concat([existing_daily, *daily_frames], how="diagonal_relaxed").unique().sort(["trade_date", "ts_code"])
    _write(index, output_dir / "tdx_index.parquet")
    _write(daily, output_dir / "tdx_daily.parquet")
    metadata_path = output_dir / "metadata.json"
    previous = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    old_counts = dict(previous.get("member_rows_by_date") or {})
    old_counts.update(member_rows)
    metadata = {
        **previous,
        "index_rows": index.height,
        "daily_rows": daily.height,
        "member_rows_by_date": old_counts,
        "backfilled_trade_dates": selected,
        "backfill_note": "exact-date snapshots appended for research; existing sessions retained",
    }
    _write_json(metadata, metadata_path)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=10)
    parser.add_argument("--trade-date", help="Fetch one newly published YYYYMMDD snapshot and advance the local window")
    parser.add_argument("--backfill-trade-date", action="append", default=[], help="Append one exact historical YYYYMMDD snapshot; may be repeated")
    parser.add_argument("--output-dir", type=Path, default=Path("../data/tdx_board_history_recent"))
    args = parser.parse_args()
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        from app import secrets_store

        token = secrets_store.get_tushare_token()
    if not token:
        raise SystemExit("Configure TUSHARE_TOKEN or the application's local Tushare credential.")
    if args.trade_date and args.backfill_trade_date:
        raise SystemExit("--trade-date and --backfill-trade-date cannot be combined")
    operation = backfill_trade_dates if args.backfill_trade_date else refresh_trade_date if args.trade_date else pull
    kwargs = {"token": token, "output_dir": args.output_dir}
    if args.backfill_trade_date:
        kwargs["trade_dates"] = args.backfill_trade_date
    else:
        kwargs["sessions"] = max(1, args.sessions)
    if args.trade_date:
        kwargs["trade_date"] = args.trade_date
    print(json.dumps(operation(**kwargs), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
