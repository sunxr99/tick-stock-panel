"""Pull a point-in-time three-year SW industry membership interval store.

The Tushare ``index_member_all`` endpoint exposes ``in_date``/``out_date``
events, so unlike the THS member endpoint it does not need one request per
trading day.  Current (``is_new=Y``) and historical (``is_new=N``) rows are
fetched, filtered locally to the requested interval, and written to a
dedicated parquet file.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from app import secrets_store
from app.config import settings
from app.services.sector_membership import replace_sw_membership_history

_API_NAME = "index_member_all"
_FIELDS = "l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new"
_PAGE_SIZE = 2000
_SOURCE = "tushare_sw_index_member_all"
_TAXONOMY_VERSION = "SW2021"


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    return date.fromisoformat(text)


def _fetch_rows(client: httpx.Client, *, token: str, api_url: str, is_new: str) -> list[list[Any]]:
    rows: list[list[Any]] = []
    offset = 0
    while True:
        payload: dict[str, Any] | None = None
        for attempt in range(5):
            response = client.post(
                api_url.rstrip("/"),
                json={
                    "api_name": _API_NAME,
                    "token": token,
                    "params": {"is_new": is_new, "limit": _PAGE_SIZE, "offset": offset},
                    "fields": _FIELDS,
                },
            )
            response.raise_for_status()
            candidate = response.json()
            if int(candidate.get("code", -1)) == 0:
                payload = candidate
                break
            message = str(candidate.get("msg") or "")
            if "连接超限" not in message and "过多线程" not in message:
                raise RuntimeError(message or f"Tushare {_API_NAME} request failed")
            time.sleep(2.0 * (attempt + 1))
        if payload is None:
            raise RuntimeError("Tushare gateway connection limit persisted after retries")
        if int(payload.get("code", -1)) != 0:
            raise RuntimeError(payload.get("msg") or f"Tushare {_API_NAME} request failed")
        data = payload.get("data") or {}
        fields = list(data.get("fields") or [])
        items = list(data.get("items") or [])
        if fields != _FIELDS.split(","):
            raise RuntimeError(f"Tushare {_API_NAME} returned unexpected fields: {fields}")
        rows.extend(items)
        if len(items) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
        time.sleep(0.25)
    return rows


def _to_intervals(rows: list[list[Any]], *, start: date, end: date) -> list[dict[str, object]]:
    fields = _FIELDS.split(",")
    index = {name: fields.index(name) for name in fields}
    intervals: set[tuple[object, ...]] = set()
    for raw in rows:
        if len(raw) != len(fields):
            continue
        in_date = _parse_date(raw[index["in_date"]])
        out_date = _parse_date(raw[index["out_date"]])
        symbol = str(raw[index["ts_code"]] or "").strip().upper()
        # Keep the complete SW hierarchy in one stable path.  The resolver
        # can then expose level 1/2/3 consistently via the existing
        # ``level`` parameter without pretending that SW industry data is a
        # concept taxonomy.
        hierarchy = {
            key.replace("l", "sw", 1): str(raw[index[key]] or "").strip() or None
            for key in ("l1_code", "l1_name", "l2_code", "l2_name", "l3_code", "l3_name")
        }
        sector = "-".join(
            hierarchy[field]
            for field in ("sw1_name", "sw2_name", "sw3_name")
            if hierarchy[field]
        )
        if not symbol or not sector or in_date is None or in_date > end:
            continue
        if out_date is not None and out_date < start:
            continue
        intervals.add(
            (
                symbol,
                sector,
                in_date,
                out_date,
                hierarchy["sw1_code"],
                hierarchy["sw1_name"],
                hierarchy["sw2_code"],
                hierarchy["sw2_name"],
                hierarchy["sw3_code"],
                hierarchy["sw3_name"],
            )
        )
    return [
        {
            "symbol": row[0],
            "kind": "industry",
            "sector": row[1],
            "effective_from": row[2],
            "effective_to": row[3],
            # The interval itself is the point-in-time evidence.  Use the
            # requested coverage start as the dataset knowledge boundary so
            # resolver logic does not discard older active intervals.
            "membership_as_of": start,
            "source": _SOURCE,
            "taxonomy_version": _TAXONOMY_VERSION,
            "sw1_code": row[4],
            "sw1_name": row[5],
            "sw2_code": row[6],
            "sw2_name": row[7],
            "sw3_code": row[8],
            "sw3_name": row[9],
        }
        for row in sorted(intervals, key=lambda item: (item[2], item[0], item[1]))
    ]


def pull(*, start: date, end: date, token: str, api_url: str, data_dir: Path) -> dict[str, object]:
    if start > end:
        raise ValueError("start must not be after end")
    with httpx.Client(timeout=90.0) as client:
        current_rows = _fetch_rows(client, token=token, api_url=api_url, is_new="Y")
        historical_rows = _fetch_rows(client, token=token, api_url=api_url, is_new="N")
    intervals = _to_intervals(current_rows + historical_rows, start=start, end=end)
    from polars import DataFrame

    written = replace_sw_membership_history(data_dir, DataFrame(intervals)) if intervals else 0
    metadata = {
        "source": _SOURCE,
        "taxonomy_version": _TAXONOMY_VERSION,
        "api_name": _API_NAME,
        "api_url": api_url.rstrip("/"),
        "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(),
        "fetched_rows": {"is_new_Y": len(current_rows), "is_new_N": len(historical_rows)},
        "selected_interval_rows": len(intervals),
        "written_rows": written,
        "uses_future_data": False,
        "note": "Intervals use in_date/out_date; no concept or THS snapshots.",
    }
    metadata_path = data_dir / "sector_membership_history" / "sw_memberships_metadata.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = metadata_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(metadata_path)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-09-12", help="inclusive coverage start (YYYY-MM-DD)")
    parser.add_argument("--end", default=date.today().isoformat(), help="inclusive coverage end (YYYY-MM-DD)")
    parser.add_argument("--api-url", default=settings.tushare_api_url)
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    parser.add_argument("--token", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    token = args.token or secrets_store.get_tushare_token()
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured")
    result = pull(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        token=token,
        api_url=args.api_url,
        data_dir=args.data_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
