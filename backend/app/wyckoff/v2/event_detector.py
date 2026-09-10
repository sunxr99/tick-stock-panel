"""Stateless event candidates for Wyckoff v2; no legacy observer inputs."""

from __future__ import annotations

import pandas as pd

from app.wyckoff.v2.config import WyckoffV2Config
from app.wyckoff.v2.features import clv, numeric, volume_percentile, volume_ratio
from app.wyckoff.v2.models import TradingRangeSnapshot


def _bar(frame: pd.DataFrame, index: int) -> tuple[float, float, float, float, float]:
    row = frame.iloc[index]
    return tuple(float(row[column]) for column in ("open", "high", "low", "close", "volume"))


def spring_candidate(
    frame: pd.DataFrame, index: int, trading_range: TradingRangeSnapshot, atr: float, cfg: WyckoffV2Config
) -> tuple[str, dict[str, float]] | None:
    open_, high, low, close, _volume = _bar(frame, index)
    penetration_atr = (trading_range.support - low) / atr
    close_location = clv(open_, high, low, close)
    if not (0.0 < penetration_atr <= cfg.spring_penetration_atr_max and close > trading_range.support and close_location >= cfg.spring_min_clv):
        return None
    effort = volume_ratio(frame, index, cfg.evr_volume_lookback, median=True)
    if effort is None:
        return None
    if effort >= cfg.spring_high_effort_ratio:
        event_type = "SPRING_HIGH_EFFORT"
    elif effort <= cfg.spring_low_supply_ratio:
        event_type = "SPRING_LOW_SUPPLY"
    else:
        event_type = "SPRING_NEUTRAL"
    return event_type, {"penetration_atr": penetration_atr, "clv": close_location, "volume_ratio": effort}


def sos_candidate(
    frame: pd.DataFrame, index: int, trading_range: TradingRangeSnapshot, atr: float, cfg: WyckoffV2Config
) -> dict[str, float] | None:
    if index < 1:
        return None
    _open, high, low, close, _volume = _bar(frame, index)
    prev_close = float(numeric(frame, "close").iloc[index - 1])
    breakout_atr = (close - trading_range.creek) / atr
    spread_atr = (high - low) / atr
    close_location = clv(_open, high, low, close)
    volume_pct = volume_percentile(frame, index, cfg.sos_volume_lookback)
    if volume_pct is None or not (
        prev_close <= trading_range.creek + trading_range.tolerance
        and breakout_atr >= cfg.sos_breakout_atr_min
        and spread_atr >= cfg.sos_spread_atr_min
        and close_location >= cfg.sos_min_clv
        and volume_pct >= cfg.sos_volume_percentile_min
    ):
        return None
    return {
        "breakout_atr": breakout_atr,
        "spread_atr": spread_atr,
        "clv": close_location,
        "volume_percentile": volume_pct,
    }


def evr_candidate(
    frame: pd.DataFrame, index: int, trading_range: TradingRangeSnapshot, atr: float, cfg: WyckoffV2Config
) -> tuple[str, dict[str, float]] | None:
    if index < 1:
        return None
    open_, high, low, close, _volume = _bar(frame, index)
    effort = volume_ratio(frame, index, cfg.evr_volume_lookback, median=True)
    if effort is None:
        return None
    result = abs(close - float(numeric(frame, "close").iloc[index - 1])) / atr
    if effort < cfg.evr_effort_min or result > cfg.evr_result_atr_max:
        return None
    close_location = clv(open_, high, low, close)
    metrics = {"effort": effort, "result_atr": result, "evr_ratio": effort / max(result, 1e-9), "clv": close_location}
    if low <= trading_range.support + cfg.evr_near_boundary_atr * atr and close_location >= cfg.evr_bullish_min_clv:
        return "EVR_BULLISH_ABSORPTION", metrics
    if high >= trading_range.resistance - cfg.evr_near_boundary_atr * atr and close_location <= cfg.evr_bearish_max_clv:
        return "EVR_BEARISH_DISTRIBUTION", metrics
    return None
