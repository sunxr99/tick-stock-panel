"""Download the latest ten TDX 88-board sessions and member snapshots.

Credentials are read only from ``TUSHARE_TOKEN``.  The script writes a
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
            response = client.post(_API_URL, json={"api_name": api_name, "token": token, "params": params, "fields": fields})
            response.raise_for_status()
            payload = response.json()
            if int(payload.get("code", -1)) == 0:
                return payload.get("data") or {}
            raise RuntimeError(f"{api_name}: {payload.get('msg') or payload.get('message') or 'unknown Tushare error'}")
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last_error = exc
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


def _member_snapshot(client: httpx.Client, *, token: str, trade_date: str) -> pl.DataFrame:
    pages: list[pl.DataFrame] = []
    offset = 0
    while True:
        data = _request(client, token=token, api_name="tdx_member", params={"trade_date": trade_date, "limit": _PAGE_SIZE, "offset": offset}, fields=_MEMBER_FIELDS)
        page = _frame(data, _MEMBER_FIELDS)
        if page.is_empty():
            break
        pages.append(page)
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
        index = _frame(_request(client, token=token, api_name="tdx_index", params={}, fields=_INDEX_FIELDS), _INDEX_FIELDS)
        dates = index.get_column("trade_date").cast(pl.Utf8).unique().sort().tail(sessions).to_list()
        index = index.filter(pl.col("trade_date").is_in(dates)).sort(["trade_date", "ts_code"])
        _write(index, output_dir / "tdx_index.parquet")
        daily_frames = []
        completed: list[str] = []
        member_rows: dict[str, int] = {}
        for trade_date in dates:
            daily = _frame(_request(client, token=token, api_name="tdx_daily", params={"trade_date": trade_date}, fields=_DAILY_FIELDS), _DAILY_FIELDS)
            daily_frames.append(daily)
            members = _member_snapshot(client, token=token, trade_date=trade_date)
            _write(members, output_dir / "tdx_members" / f"trade_date={trade_date}" / "part.parquet")
            completed.append(trade_date)
            member_rows[trade_date] = members.height
            print(f"TDX {trade_date}: boards={daily.height}, members={members.height}", flush=True)
            time.sleep(0.1)
    daily = pl.concat(daily_frames, how="vertical").unique().sort(["trade_date", "ts_code"])
    _write(daily, output_dir / "tdx_daily.parquet")
    metadata = {
        "source": "tushare_tdx_index_tdx_daily_tdx_member",
        "requested_sessions": sessions,
        "trade_dates": completed,
        "index_rows": index.height,
        "daily_rows": daily.height,
        "member_rows_by_date": member_rows,
        "member_storage": "tdx_members/trade_date=<YYYYMMDD>/part.parquet",
        "point_in_time_key": "trade_date + ts_code + con_code",
        "note": "TDX categories are flat: concept, industry, style, and region; no level hierarchy is inferred.",
    }
    _write_json(metadata, output_dir / "metadata.json")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("../data/tdx_board_history_recent"))
    args = parser.parse_args()
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("Set TUSHARE_TOKEN in the environment; it is never persisted by this script.")
    print(json.dumps(pull(token=token, output_dir=args.output_dir, sessions=max(1, args.sessions)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
