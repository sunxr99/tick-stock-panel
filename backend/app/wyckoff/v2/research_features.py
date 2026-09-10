"""Point-in-time descriptive features used by V2 research experiments.

Nothing in this module changes candidate admission.  Every value is computed
from bars available on the event date and is frozen on the event/entry record.
"""

from __future__ import annotations

import math

import pandas as pd

from app.wyckoff.v2.features import clv, median_volume_before, numeric, volume_percentile
from app.wyckoff.v2.models import TradingRangeSnapshot


def background_context(frame: pd.DataFrame, index: int) -> dict[str, float | str | None]:
    """Return a deliberately simple, point-in-time trend label and raw inputs."""
    close = numeric(frame, "close")
    current = float(close.iloc[index])

    def ret(days: int) -> float | None:
        if index < days or float(close.iloc[index - days]) <= 0:
            return None
        return (current / float(close.iloc[index - days]) - 1.0) * 100.0

    def slope(window: int) -> float | None:
        if index + 1 < window:
            return None
        values = close.iloc[index - window + 1 : index + 1]
        mean = float(values.mean())
        if mean <= 0:
            return None
        return (float(values.iloc[-1]) / float(values.iloc[0]) - 1.0) * 100.0 / window

    def distance_ma(window: int) -> float | None:
        if index + 1 < window:
            return None
        average = float(close.iloc[index - window + 1 : index + 1].mean())
        return (current / average - 1.0) * 100.0 if average > 0 else None

    lookback = close.iloc[max(0, index - 119) : index + 1]
    position = None
    if not lookback.empty and float(lookback.max()) > float(lookback.min()):
        position = (current - float(lookback.min())) / (float(lookback.max()) - float(lookback.min()))
    return_60, ma50_slope = ret(60), slope(50)
    if (return_60 is not None and return_60 <= -12.0) or (ma50_slope is not None and ma50_slope < -0.12):
        label = "BACKGROUND_DOWN"
    elif (return_60 is not None and return_60 >= 12.0) or (ma50_slope is not None and ma50_slope > 0.12):
        label = "BACKGROUND_UP"
    else:
        label = "BACKGROUND_SIDEWAYS"
    return {
        "background": label,
        "return_20": ret(20), "return_60": return_60, "return_120": ret(120),
        "ma20_slope": slope(20), "ma50_slope": ma50_slope, "ma200_slope": slope(200),
        "distance_to_ma50": distance_ma(50), "distance_to_ma200": distance_ma(200),
        "position_in_120d_range": position,
    }


def spring_snapshot(frame: pd.DataFrame, index: int, trading_range: TradingRangeSnapshot, atr: float) -> dict[str, float | str | None]:
    """Freeze all descriptive Spring fields at detection, without new gates."""
    open_, high, low, close, volume = (float(frame[column].iloc[index]) for column in ("open", "high", "low", "close", "volume"))
    spread = max(high - low, 1e-9)
    body = abs(close - open_)
    lower_wick = min(open_, close) - low
    upper_wick = high - max(open_, close)
    normal_volume = median_volume_before(frame, index, 20)
    values: dict[str, float | str | None] = {
        "range_age_bars": trading_range.age_bars,
        "range_width_pct": trading_range.width_pct,
        "range_width_atr": trading_range.width_atr,
        "support_test_count": trading_range.support_tests,
        "resistance_test_count": trading_range.resistance_tests,
        "range_drift_pct": trading_range.drift_pct,
        "range_quality_score": trading_range.quality,
        "support_stability": trading_range.support_stability,
        "resistance_stability": trading_range.resistance_stability,
        "spring_penetration_atr": (trading_range.support - low) / atr,
        "spring_penetration_pct": (trading_range.support - low) / trading_range.support * 100.0,
        "spring_reclaim_atr": (close - trading_range.support) / atr,
        "spring_reclaim_pct": (close - trading_range.support) / trading_range.support * 100.0,
        "spring_clv": clv(open_, high, low, close),
        "spring_spread_atr": spread / atr,
        "spring_body_atr": body / atr,
        "spring_lower_wick_atr": lower_wick / atr,
        "spring_upper_wick_atr": upper_wick / atr,
        "spring_lower_wick_ratio": lower_wick / spread,
        "spring_close_location_in_range": (close - trading_range.support) / max(trading_range.resistance - trading_range.support, 1e-9),
        "spring_volume_ratio_vs_median20": volume / normal_volume if normal_volume else None,
        "spring_volume_percentile_120": volume_percentile(frame, index, 120),
    }
    values.update(background_context(frame, index))
    return values


def test_snapshot(
    frame: pd.DataFrame, index: int, *, spring_index: int, spring_low: float, trading_range: TradingRangeSnapshot, atr: float,
) -> dict[str, float | str | None]:
    open_, high, low, close, volume = (float(frame[column].iloc[index]) for column in ("open", "high", "low", "close", "volume"))
    normal = median_volume_before(frame, index, 20)
    spring_volume = float(frame["volume"].iloc[spring_index])
    return {
        "test_delay_bars": index - spring_index,
        "test_distance_to_support_atr": abs(low - trading_range.support) / atr,
        "test_distance_to_spring_low_atr": (low - spring_low) / atr,
        "test_volume_ratio_vs_normal": volume / normal if normal else None,
        "test_volume_ratio_vs_spring": volume / spring_volume if spring_volume else None,
        "test_spread_atr": (high - low) / atr,
        "test_clv": clv(open_, high, low, close),
        "test_low_vs_spring_low_atr": (low - spring_low) / atr,
        "test_close_vs_support_atr": (close - trading_range.support) / atr,
        "test_timing": "FAST_TEST" if index - spring_index <= 3 else "MID_TEST" if index - spring_index <= 6 else "LATE_TEST",
    }


def finite_research(values: dict[str, object]) -> dict[str, object]:
    """Make event persistence JSON-safe while retaining labels and missingness."""
    return {key: (value if not isinstance(value, float) or math.isfinite(value) else None) for key, value in values.items()}
