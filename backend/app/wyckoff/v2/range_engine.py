"""ATR-adaptive trading-range discovery for the independent engine.

Range inputs are converted to NumPy once per symbol. The replay loop can then
evaluate many candidate dates without creating a DataFrame and rolling ATR
series for every bar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.wyckoff.v2.config import WyckoffV2Config
from app.wyckoff.v2.models import TradingRangeSnapshot


@dataclass(frozen=True)
class RangeInputs:
    dates: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    atr: np.ndarray
    swing_low_positions: np.ndarray
    swing_high_positions: np.ndarray


def _swing_positions(values: np.ndarray, *, kind: str, window: int) -> np.ndarray:
    width = max(int(window), 1)
    positions: list[int] = []
    for position in range(width, len(values) - width):
        value = values[position]
        around = values[position - width : position + width + 1]
        if np.isnan(value) or np.isnan(around).all():
            continue
        boundary = np.nanmin(around) if kind == "low" else np.nanmax(around)
        if value == boundary:
            positions.append(position)
    return np.asarray(positions, dtype=int)


def prepare_range_inputs(frame: pd.DataFrame, cfg: WyckoffV2Config) -> RangeInputs:
    high = frame["high"].to_numpy(dtype=float, copy=False)
    low = frame["low"].to_numpy(dtype=float, copy=False)
    close = frame["close"].to_numpy(dtype=float, copy=False)
    previous_close = np.concatenate(([np.nan], close[:-1]))
    true_range = np.maximum.reduce((high - low, np.abs(high - previous_close), np.abs(low - previous_close)))
    atr = pd.Series(true_range).rolling(max(int(cfg.atr_window), 1), min_periods=1).mean().to_numpy(dtype=float)
    return RangeInputs(
        dates=frame["date"].to_numpy(copy=False),
        high=high,
        low=low,
        close=close,
        atr=atr,
        swing_low_positions=_swing_positions(low, kind="low", window=cfg.swing_window),
        swing_high_positions=_swing_positions(high, kind="high", window=cfg.swing_window),
    )


def identify_range_before(inputs: RangeInputs, index: int, cfg: WyckoffV2Config) -> TradingRangeSnapshot | None:
    """Build a range from bars strictly before *index*; the event bar is excluded."""
    start = max(0, index - cfg.range_lookback)
    if index - start < cfg.range_min_bars:
        return None
    high = inputs.high[start:index]
    low = inputs.low[start:index]
    close = inputs.close[start:index]
    width = max(int(cfg.swing_window), 1)
    low_positions = inputs.swing_low_positions[
        (inputs.swing_low_positions >= start + width) & (inputs.swing_low_positions < index - width)
    ]
    high_positions = inputs.swing_high_positions[
        (inputs.swing_high_positions >= start + width) & (inputs.swing_high_positions < index - width)
    ]
    lows = inputs.low[low_positions]
    highs = inputs.high[high_positions]
    support = float(np.median(lows[-5:])) if len(lows) >= 2 else float(np.nanquantile(low, 0.10))
    resistance = float(np.median(highs[-5:])) if len(highs) >= 2 else float(np.nanquantile(high, 0.90))
    if support <= 0 or resistance <= support:
        return None
    atr = float(inputs.atr[index - 1])
    if not np.isfinite(atr) or atr <= 0:
        return None
    range_width = resistance - support
    width_atr = range_width / atr
    width_pct = range_width / support * 100.0
    drift = abs(float(close[-1]) / float(close[0]) - 1.0) * 100.0 if float(close[0]) > 0 else float("inf")
    tolerance = max(cfg.tolerance_atr_factor * atr, float(close[-1]) * cfg.tolerance_pct_floor)
    support_tests = int(np.sum(np.abs(low - support) <= tolerance))
    resistance_tests = int(np.sum(np.abs(high - resistance) <= tolerance))
    if not (
        cfg.range_width_atr_min <= width_atr <= cfg.range_width_atr_max
        and width_pct <= cfg.range_width_pct_ceiling
        and drift <= cfg.range_max_drift_pct
        and support_tests >= cfg.range_min_tests
        and resistance_tests >= cfg.range_min_tests
    ):
        return None
    test_quality = min((support_tests + resistance_tests) / 6.0, 1.0)
    width_quality = 1.0 - abs(width_atr - 8.0) / 8.0
    drift_quality = 1.0 - drift / cfg.range_max_drift_pct
    return TradingRangeSnapshot(
        range_id="",
        support=support,
        resistance=resistance,
        creek=resistance,
        window_start=str(pd.Timestamp(inputs.dates[start]).date()),
        window_end=str(pd.Timestamp(inputs.dates[index - 1]).date()),
        established_at=str(pd.Timestamp(inputs.dates[index - 1]).date()),
        atr=atr,
        width_atr=width_atr,
        width_pct=width_pct,
        tolerance=tolerance,
        support_tests=support_tests,
        resistance_tests=resistance_tests,
        quality=max(0.0, min(1.0, 0.45 * test_quality + 0.35 * width_quality + 0.20 * drift_quality)),
        age_bars=len(close),
        drift_pct=drift,
        # A stable boundary has more tests and a smaller dispersion around it.
        # This is a descriptive feature only, never a range admission gate.
        support_stability=max(0.0, min(1.0, support_tests / 6.0)),
        resistance_stability=max(0.0, min(1.0, resistance_tests / 6.0)),
    )
