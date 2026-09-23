from __future__ import annotations

from datetime import date

import polars as pl

from app.services import tdx_board_rotation


def _index(day: str, code: str, name: str, idx_type: str) -> dict[str, str]:
    return {"trade_date": day, "ts_code": code, "name": name, "idx_type": idx_type}


def _daily(day: str, code: str, pct_change: float) -> dict[str, object]:
    return {
        "trade_date": day, "ts_code": code, "close": 100.0, "pct_change": pct_change,
        "amount": 1_000_000.0, "turnover_rate": 2.0, "up_num": 8, "down_num": 2,
    }


def _write(tmp_path, index_rows, daily_rows) -> None:
    index_path = tdx_board_rotation.index_path(tmp_path)
    index_path.parent.mkdir(parents=True)
    pl.DataFrame(index_rows).write_parquet(index_path)
    pl.DataFrame(daily_rows).write_parquet(tdx_board_rotation.daily_path(tmp_path))


def test_rotation_separates_flat_tdx_categories_and_calculates_returns(tmp_path) -> None:
    index_rows = []
    daily_rows = []
    for number, day in enumerate(("20260914", "20260915", "20260916", "20260917", "20260918"), start=1):
        index_rows.extend([
            _index(day, "880001.TDX", "AI概念", "概念板块"),
            _index(day, "880002.TDX", "半导体", "行业板块"),
            _index(day, "880003.TDX", "高股息", "风格板块"),
            _index(day, "880004.TDX", "上海板块", "地区板块"),
        ])
        daily_rows.extend([
            _daily(day, "880001.TDX", float(number)), _daily(day, "880002.TDX", 2.0),
            _daily(day, "880003.TDX", 3.0), _daily(day, "880004.TDX", 4.0),
        ])
    _write(tmp_path, index_rows, daily_rows)

    concept = tdx_board_rotation.latest_hot_rotation(tmp_path)
    industry = tdx_board_rotation.latest_hot_rotation(tmp_path, category="industry")
    style = tdx_board_rotation.latest_hot_rotation(tmp_path, category="style")
    all_rows = tdx_board_rotation.latest_hot_rotation(tmp_path, category="all")

    assert concept.get_column("name").to_list() == ["AI概念"]
    assert industry.get_column("name").to_list() == ["半导体"]
    assert style.get_column("name").to_list() == ["高股息"]
    assert set(all_rows.get_column("category").to_list()) == {"region", "concept", "style", "industry"}
    assert concept.row(0, named=True)["return_5d"] > 0


def test_member_lookup_requires_exact_trade_date_and_board(tmp_path) -> None:
    path = tdx_board_rotation.member_path(tmp_path, trade_date=date(2026, 9, 22))
    path.parent.mkdir(parents=True)
    pl.DataFrame({
        "trade_date": ["20260922", "20260922", "20260921"],
        "ts_code": ["880001.TDX", "880002.TDX", "880001.TDX"],
        "con_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
        "con_name": ["平安银行", "万科A", "旧成员"],
    }).write_parquet(path)

    frame = tdx_board_rotation.load_hot_rotation_members(
        tmp_path, trade_date=date(2026, 9, 22), ts_code="880001.tdx"
    )

    assert frame.to_dicts() == [{
        "trade_date": "20260922", "ts_code": "880001.TDX", "con_code": "000001.SZ", "con_name": "平安银行",
    }]
