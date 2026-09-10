from datetime import date

import polars as pl
import pytest

from app.wyckoff.adapter import to_wyckoff_ohlcv
from app.wyckoff.cn_boards import cn_board, is_supported_cn_board


def _frame() -> pl.DataFrame:
    return pl.DataFrame({
        "date": [date(2026, 1, 6), date(2026, 1, 5)],
        "open": [11.0, 10.0],
        "high": [12.0, 11.0],
        "low": [10.5, 9.5],
        "close": [11.5, 10.5],
        "volume": [2000.0, 1000.0],
        "amount": [22000.0, 10500.0],
    })


def test_to_wyckoff_ohlcv_standardizes_repository_frame() -> None:
    result = to_wyckoff_ohlcv(_frame(), symbol="605179.SH")

    assert result.columns.tolist() == ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
    assert result["symbol"].tolist() == ["605179.SH", "605179.SH"]
    assert result["date"].tolist() == [date(2026, 1, 5), date(2026, 1, 6)]


def test_to_wyckoff_ohlcv_rejects_invalid_price_envelope() -> None:
    frame = _frame().with_columns(pl.lit(9.0).alias("high"))

    with pytest.raises(ValueError, match="包络"):
        to_wyckoff_ohlcv(frame, symbol="605179.SH")


def test_to_wyckoff_ohlcv_rejects_missing_required_field() -> None:
    with pytest.raises(ValueError, match="amount"):
        to_wyckoff_ohlcv(_frame().drop("amount"), symbol="605179.SH")


def test_cn_board_preserves_a_share_board_classification() -> None:
    assert cn_board("605179.SH") == "main"
    assert cn_board("300750.SZ") == "chinext"
    assert cn_board("688001.SH") == "star"
    assert not is_supported_cn_board("830001.BJ", include_bse=False)
