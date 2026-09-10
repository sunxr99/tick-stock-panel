"""多日分时 API 契约。"""

import asyncio
from datetime import date, datetime
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import polars as pl
import pytest
from fastapi import HTTPException

from app.api import indices as indices_api
from app.api import kline as kline_api
from app.services import kline_sync


def _request(repo=None, capset=None):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                repo=repo or MagicMock(),
                capabilities=capset or MagicMock(),
            )
        )
    )


def test_minute_range_returns_latest_sessions_with_previous_closes():
    repo = MagicMock()
    repo.resolve_asset_type.return_value = "stock"
    # _get_stock_info 走 instruments 内存缓存 (不再走 execute_one DuckDB 查询)
    repo.get_instruments.return_value = pl.DataFrame({
        "symbol": ["600000.SH"],
        "name": ["浦发银行"],
        "total_shares": [1.0],
        "float_shares": [1.0],
    })
    repo.get_minute_range.return_value = pl.DataFrame({
        "symbol": ["600000.SH"] * 3,
        "datetime": [
            datetime(2026, 8, 5, 1, 30),
            datetime(2026, 8, 6, 1, 30),
            datetime(2026, 8, 7, 1, 30),
        ],
        "open": [10.0, 11.0, 12.0],
        "high": [10.2, 11.2, 12.2],
        "low": [9.8, 10.8, 11.8],
        "close": [10.1, 11.1, 12.1],
        "volume": [100.0, 110.0, 120.0],
        "amount": [101_000.0, 122_100.0, 145_200.0],
    })
    repo.get_daily_asset.return_value = pl.DataFrame({
        "date": [
            date(2026, 8, 4),
            date(2026, 8, 5),
            date(2026, 8, 6),
            date(2026, 8, 7),
        ],
        "close": [9.9, 10.1, 11.1, 12.1],
    })

    result = kline_api.get_minute_range(_request(repo), "600000.SH", 2)

    assert result["name"] == "浦发银行"
    assert result["requested_days"] == 2
    assert result["source"] == "local"
    assert [session["date"] for session in result["sessions"]] == [
        "2026-08-06",
        "2026-08-07",
    ]
    assert [session["prev_close"] for session in result["sessions"]] == [
        10.1,
        11.1,
    ]
    assert result["sessions"][0]["rows"][0]["close"] == 11.1


def test_minute_range_reads_index_store():
    repo = MagicMock()
    repo.resolve_asset_type.return_value = "index"
    repo.get_instruments_asset.return_value = pl.DataFrame()
    repo.get_minute_range.return_value = pl.DataFrame({
        "symbol": ["000001.SH"],
        "datetime": [datetime(2026, 8, 7, 9, 31)],
        "open": [3000.0], "high": [3010.0], "low": [2990.0], "close": [3005.0],
        "volume": [100.0], "amount": [300500.0],
    })
    repo.get_daily_asset.return_value = pl.DataFrame({
        "date": [date(2026, 8, 6), date(2026, 8, 7)], "close": [2990.0, 3005.0],
    })

    result = kline_api.get_minute_range(_request(repo), "000001.SH", 10)

    assert result["asset_type"] == "index"
    assert result["source"] == "local"
    assert result["sessions"][0]["rows"][0]["close"] == 3005.0
    call = repo.get_minute_range.call_args
    assert call.args[0] == ["000001.SH"]
    assert call.kwargs["asset_type"] == "index"


def test_sync_minute_single_uses_requested_days(monkeypatch):
    repo = MagicMock()
    repo.resolve_asset_type.return_value = "stock"
    capset = MagicMock()
    sync = MagicMock(return_value=2400)
    refresh = MagicMock()
    monkeypatch.setattr(kline_api, "_minute_allowed", lambda _: True)
    monkeypatch.setattr(kline_api.kline_sync, "sync_and_persist_minute", sync)
    monkeypatch.setattr("app.jobs.daily_pipeline._refresh_single_view", refresh)

    result = asyncio.run(kline_api.sync_minute_single(
        _request(repo, capset),
        {"symbol": "600000.SH", "days": 10},
    ))

    assert result["rows"] == 2400
    sync.assert_called_once_with(
        ["600000.SH"], repo, capset, days=10, force_full_days=True, asset_type="stock",
    )
    refresh.assert_called_once_with(repo, "kline_minute")


def test_sync_minute_single_stores_index_separately(monkeypatch):
    repo = MagicMock()
    repo.resolve_asset_type.return_value = "index"
    capset = MagicMock()
    sync = MagicMock(return_value=240)
    refresh = MagicMock()
    monkeypatch.setattr(kline_api, "_minute_allowed", lambda _: True)
    monkeypatch.setattr(kline_api.kline_sync, "sync_and_persist_minute", sync)
    monkeypatch.setattr("app.jobs.daily_pipeline._refresh_single_view", refresh)

    result = asyncio.run(kline_api.sync_minute_single(
        _request(repo, capset), {"symbol": "000001.SH", "days": 1},
    ))

    assert result["rows"] == 240
    sync.assert_called_once_with(
        ["000001.SH"], repo, capset, days=1, force_full_days=True, asset_type="index",
    )
    refresh.assert_called_once_with(repo, "kline_index_minute")


def test_index_minute_api_prefers_local_index_partition(monkeypatch):
    repo = MagicMock()
    repo.get_index_instruments.return_value = pl.DataFrame()
    repo.get_minute.return_value = pl.DataFrame({
        "symbol": ["000001.SH"],
        "datetime": [datetime(2026, 8, 7, 9, 31)],
        "close": [3005.0],
    })
    fetch = MagicMock()
    monkeypatch.setattr(indices_api.kline_sync, "fetch_minute_single", fetch)

    result = indices_api.get_index_minute(_request(repo), "000001.SH", date(2026, 8, 7))

    assert result["source"] == "local"
    assert result["rows"][0]["close"] == 3005.0
    repo.get_minute.assert_called_once_with("000001.SH", date(2026, 8, 7), asset_type="index")
    fetch.assert_not_called()


def test_sync_minute_single_rejects_invalid_days():
    with pytest.raises(HTTPException, match="days 必须在 1 到 30 之间"):
        asyncio.run(kline_api.sync_minute_single(
            _request(),
            {"symbol": "600000.SH", "days": 0},
        ))


def test_czsc_minute_sync_window_uses_actual_daily_analysis_start() -> None:
    repo = MagicMock()
    repo.resolve_asset_type.return_value = "stock"
    repo.get_daily_asset.return_value = pl.DataFrame({
        "date": [date(2026, 1, 6), date(2026, 1, 2), date(2026, 1, 5)],
    })

    asset_type, start, end = kline_api._czsc_daily_analysis_window(repo, "600000.SH", 250)

    assert asset_type == "stock"
    assert start == datetime(2026, 1, 2)
    assert end == datetime(2026, 1, 6, 23, 59, 59, 999999)
    requested_start = repo.get_daily_asset.call_args.args[2]
    assert requested_start < start.date()


def test_czsc_native_minutes_are_stored_per_frequency(tmp_path, monkeypatch) -> None:
    calls = []
    repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        _write_lock=threading.Lock(),
    )
    capset = MagicMock()
    monkeypatch.setattr(kline_sync, "_resolve_minute_provider", lambda _: (None, False, None))
    monkeypatch.setattr(kline_sync, "resolve_limit", lambda *args, **kwargs: SimpleNamespace(batch=10, rpm=1))
    monkeypatch.setattr(kline_sync.preferences, "get_minute_sync_segment_days", lambda: 20)

    def fake_sync(symbols, *, freq, on_segment, **kwargs):
        calls.append((symbols, freq))
        on_segment(pl.DataFrame({
            "symbol": [symbols[0]],
            "datetime": [datetime(2026, 1, 5, 9, 45)],
            "open": [10.0], "high": [10.1], "low": [9.9], "close": [10.0],
            "volume": [1.0], "amount": [10.0],
        }))
        return pl.DataFrame()

    monkeypatch.setattr(kline_sync, "sync_minute_batch", fake_sync)
    result = kline_sync.sync_and_persist_czsc_native_minutes(
        "600000.SH",
        repo,
        capset,
        start_time=datetime(2026, 1, 2),
        end_time=datetime(2026, 1, 6),
    )

    assert [freq for _, freq in calls] == ["15m", "30m", "60m"]
    assert result == {"15m": 1, "30m": 1, "60m": 1}
    assert not (tmp_path / "kline_minute").exists()
    assert all(
        (tmp_path / "kline_czsc_minute" / f"freq={freq}" / "date=2026-01-05" / "part.parquet").exists()
        for freq in result
    )
