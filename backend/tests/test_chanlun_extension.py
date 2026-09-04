"""chanlun 扩展的契约测试 — 锁定 czsc 输入列标准化 (不依赖 czsc / 真实行情数据)。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import polars as pl

from app.custom.chanlun import (
    _BUY_SELL_TYPES,
    _fetch_bars,
    _find_buy_sell_points,
    _serialize,
)


class _FakeRepo:
    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    def resolve_asset_type(self, symbol: str) -> str:
        del symbol
        return "stock"

    def get_daily_asset(self, asset_type, symbol, start, end, columns=None):
        del asset_type, symbol, start, end, columns
        return self._df


def _daily_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 3,
            "date": [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)],
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.5, 10.5, 11.5],
            "close": [10.8, 11.8, 12.8],
            "volume": [1000.0, 2000.0, 3000.0],
            "amount": [1e6, 2e6, 3e6],
        }
    )


def test_fetch_bars_renames_volume_and_builds_dt_column() -> None:
    out, asset_type = _fetch_bars(_FakeRepo(_daily_df()), "000001.SZ", days=30)

    assert asset_type == "stock"
    assert list(out.columns) == ["dt", "symbol", "open", "close", "high", "low", "vol", "amount"]
    assert out["vol"].tolist() == [1000.0, 2000.0, 3000.0]
    assert out["dt"].tolist() == [
        pd.Timestamp(2026, 1, 5),
        pd.Timestamp(2026, 1, 6),
        pd.Timestamp(2026, 1, 7),
    ]


def test_fetch_bars_fills_missing_amount_with_zero() -> None:
    out, _ = _fetch_bars(_FakeRepo(_daily_df().drop("amount")), "000001.SZ", days=30)
    assert out["amount"].tolist() == [0.0, 0.0, 0.0]


def test_fetch_bars_returns_empty_frame_on_no_data() -> None:
    out, asset_type = _fetch_bars(_FakeRepo(pl.DataFrame()), "000001.SZ", days=30)
    assert out.empty
    assert asset_type == "stock"


def _czsc_and_bars():
    """构造 czsc 模块与 mock 日K (本地生成, 不依赖网络 / API Key)。"""
    import czsc
    from czsc.mock import generate_symbol_kines

    df = generate_symbol_kines("000001", "日线", "20240101", "20241201", seed=42)
    return czsc, czsc.format_standard_kline(df, freq=czsc.Freq.D)


def test_serialize_produces_structured_fields() -> None:
    czsc, bars = _czsc_and_bars()
    data = _serialize(czsc, bars)

    assert set(data) == {"bars", "bi", "zs", "buy_sell"}
    assert len(data["bars"]) == len(bars)
    first = data["bars"][0]
    assert first["open"] > 0 and first["high"] >= first["low"]

    for bi in data["bi"]:
        assert bi["direction"] in ("向上", "向下")
        assert bi["start_price"] > 0 and bi["end_price"] > 0

    for zs in data["zs"]:
        assert zs["zg"] >= zs["zd"]


def test_buy_sell_points_use_valid_types_and_no_consecutive_duplicates() -> None:
    czsc, bars = _czsc_and_bars()
    points = _find_buy_sell_points(czsc, bars)

    for p in points:
        assert p["type"] in _BUY_SELL_TYPES
        assert p["price"] > 0

    # 边沿检测: 同类型按时间不应连续重复 (信号是持续状态, 只在首次出现时记录)
    last_dt: dict[str, str] = {}
    for p in points:
        if p["type"] in last_dt:
            assert p["dt"] != last_dt[p["type"]], f"{p['type']} 连续重复出现"
        last_dt[p["type"]] = p["dt"]
