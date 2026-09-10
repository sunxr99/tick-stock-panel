from __future__ import annotations

import numpy as np
import pandas as pd

from app.wyckoff.config import FunnelConfig
from app.wyckoff.wyckoff_structure import (
    _range_quality,
    build_structure_shadow,
    detect_structure_triggers,
    identify_trading_range,
)


def _range_df(n: int = 120) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    x = np.linspace(0, 10 * np.pi, n)
    close = 11.0 + 0.9 * np.sin(x)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.998,
            "high": close + 0.22,
            "low": close - 0.22,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
            "pct_chg": pd.Series(close).pct_change().fillna(0.0) * 100.0,
        }
    )


def test_identify_trading_range_from_repeated_swings() -> None:
    trading_range = identify_trading_range(_range_df(), FunnelConfig(), exclude_last=0)

    assert trading_range is not None
    assert 9.5 <= trading_range.support <= 10.5
    assert 11.5 <= trading_range.resistance <= 12.5
    assert trading_range.support_tests >= 2
    assert trading_range.resistance_tests >= 2


def test_range_quality_scores_width_relative_to_atr() -> None:
    matched = _range_quality(12.0, 0.0, 12.0, 3, 3, 3.0)
    too_wide_for_volatility = _range_quality(12.0, 0.0, 12.0, 3, 3, 1.5)

    assert matched > too_wide_for_volatility


def test_structure_spring_uses_prior_trading_range() -> None:
    frame = _range_df()
    frame.loc[frame.index[-1], ["open", "high", "low", "close", "volume", "pct_chg"]] = [
        10.0,
        10.7,
        9.55,
        10.45,
        1_700_000.0,
        4.0,
    ]
    config = FunnelConfig(spring_vol_ratio=1.0)

    result = detect_structure_triggers(["000001"], {"000001": frame}, config)

    assert result.trading_ranges["000001"].support < 10.5
    assert result.triggers["spring"]
    assert result.stage_map["000001"] == "Accum_C"


def test_structure_sos_uses_dynamic_resistance() -> None:
    frame = _range_df()
    frame.loc[frame.index[-1], ["open", "high", "low", "close", "volume", "pct_chg"]] = [
        11.6,
        12.9,
        11.5,
        12.65,
        3_000_000.0,
        7.0,
    ]
    config = FunnelConfig(sos_pct_min=5.0, sos_vol_ratio=2.0)

    result = detect_structure_triggers(["000001"], {"000001": frame}, config)

    assert result.triggers["sos"]
    assert result.stage_map["000001"] == "Markup"


def test_structure_shadow_keeps_structure_only_signal_observational() -> None:
    frame = _range_df()
    frame.loc[frame.index[-1], ["open", "high", "low", "close", "volume", "pct_chg"]] = [
        10.0,
        10.7,
        9.55,
        10.45,
        1_700_000.0,
        4.0,
    ]
    structure = detect_structure_triggers(["000001"], {"000001": frame}, FunnelConfig(spring_vol_ratio=1.0))

    shadow = build_structure_shadow({}, structure, universe_count=1)

    assert shadow["mode"] == "observation_only"
    assert shadow["affects_formal_selection"] is False
    assert shadow["by_trigger"]["spring"]["structure_only"] == ["000001"]
    assert shadow["by_trigger"]["spring"]["structure_only_count"] == 1
    assert shadow["by_trigger"]["spring"]["structure_scores"]["000001"] > 0
    assert shadow["range_coverage"] == 1.0
    assert shadow["trading_ranges"]["000001"]["quality_score"] > 0
    assert shadow["diagnostic_stage_map"] == {"000001": "Accum_C"}
