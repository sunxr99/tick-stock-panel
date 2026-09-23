from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.wyckoff.config import FunnelConfig
from app.wyckoff.wyckoff_structure import (
    _ensure_pct_chg,
    _range_quality,
    build_structure_shadow,
    detect_sos,
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
    assert trading_range.range_start is not None
    assert trading_range.range_confirmed_at is not None
    assert trading_range.range_start <= trading_range.range_confirmed_at


def test_range_metadata_is_as_of_safe_and_prefix_reproducible() -> None:
    frame = _range_df()
    prefix = frame.iloc[:90].copy()
    first = identify_trading_range(prefix, FunnelConfig(), exclude_last=1)
    second = identify_trading_range(prefix, FunnelConfig(), exclude_last=1)

    assert first is not None and second is not None
    assert first == second
    assert first.range_confirmed_at == prefix["date"].iloc[-1].date()
    assert first.range_start <= first.range_confirmed_at


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


def test_layer2_sos_detector_reuses_the_same_prior_range_rule() -> None:
    frame = _range_df()
    frame.loc[frame.index[-1], ["open", "high", "low", "close", "volume", "pct_chg"]] = [
        11.6,
        12.9,
        11.5,
        12.65,
        3_000_000.0,
        7.0,
    ]

    assert detect_sos(frame, FunnelConfig(sos_pct_min=5.0, sos_vol_ratio=2.0)) is not None


def test_structure_converts_decimal_change_pct_for_sos() -> None:
    frame = _range_df().drop(columns="pct_chg")
    frame["change_pct"] = frame["close"].pct_change().fillna(0.0)
    frame.loc[frame.index[-1], ["open", "high", "low", "close", "volume", "change_pct"]] = [
        11.6,
        12.9,
        11.5,
        12.65,
        3_000_000.0,
        0.07,
    ]

    result = detect_structure_triggers(
        ["000001"], {"000001": frame}, FunnelConfig(sos_pct_min=5.0, sos_vol_ratio=2.0)
    )

    assert result.triggers["sos"]


def test_structure_rejects_conflicting_return_units() -> None:
    frame = _range_df()
    frame["change_pct"] = frame["pct_chg"] / 100.0
    frame.loc[frame.index[-1], "change_pct"] = 0.01

    with pytest.raises(ValueError, match="disagree"):
        _ensure_pct_chg(frame)


def test_legacy_lps_requires_support_retest_and_recovery_confirmation() -> None:
    frame = _range_df()
    frame.loc[frame.index[-2], ["open", "high", "low", "close", "volume", "pct_chg"]] = [
        10.2, 10.5, 10.0, 10.4, 100_000.0, 0.0,
    ]
    frame.loc[frame.index[-1], ["open", "high", "low", "close", "volume", "pct_chg"]] = [
        10.2, 10.85, 10.0, 10.7, 100_000.0, 2.9,
    ]

    confirmed = detect_structure_triggers(["000001"], {"000001": frame}, FunnelConfig())
    assert confirmed.triggers["lps"]

    frame.loc[frame.index[-1], ["open", "high", "low", "close", "pct_chg"]] = [
        10.1, 10.35, 10.0, 10.2, 0.0,
    ]
    rejected = detect_structure_triggers(["000001"], {"000001": frame}, FunnelConfig())
    assert rejected.triggers["lps"] == []


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
