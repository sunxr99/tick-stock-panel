from __future__ import annotations

import pandas as pd

from app.wyckoff.trend_drawdown_risk import (
    annotate_trend_drawdown_risk,
    classify_trend_drawdown_pct,
    max_drawdown_pct,
)


def test_drawdown_is_positive_and_uses_peak_to_trough() -> None:
    drawdown = max_drawdown_pct(pd.Series([10.0, 12.0, 9.0, 11.0]))

    assert drawdown == 25.0


def test_deep_drawdown_is_a_soft_penalty() -> None:
    risk = classify_trend_drawdown_pct(35.0)

    assert risk.label.startswith("60日深回撤")
    assert 0.04 < risk.rank_penalty < 0.08


def test_only_trend_continuation_entries_receive_risk_annotation() -> None:
    entries = [{"code": "000001"}, {"code": "000002"}]
    frames = {
        "000001": pd.DataFrame({"close": [10.0, 12.0, 8.0]}),
        "000002": pd.DataFrame({"close": [10.0, 12.0, 8.0]}),
    }

    annotate_trend_drawdown_risk(entries, frames, {"000001": "趋势延续", "000002": "吸筹"})

    assert entries[0]["metrics"]["trend_drawdown60_pct"] == 33.3333
    assert "risk" not in entries[1]
