"""市场总览辅助计算的日终量能口径。"""
from datetime import date, timedelta

import polars as pl

from app.services.market_overview_builder import _market_amount_context_from_frame


def test_market_amount_context_uses_trading_day_ma_windows():
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(20)]
    amounts = [100.0] * 19 + [200.0]
    frame = pl.DataFrame({
        "date": dates,
        "amount": amounts,
        "volume": [10.0] * 20,
        "close": [10.0] * 20,
    })

    context = _market_amount_context_from_frame(frame, dates[-1])

    assert context["market_amount"] == 200.0
    assert context["market_amount_ma5"] == 120.0
    assert context["market_amount_ma20"] == 105.0
    assert context["market_amount_ratio_20"] == 200.0 / 105.0
    assert context["market_amount_ma5_ratio_20"] == 120.0 / 105.0
