"""Research defaults for the independent Wyckoff v2 engine.

These values are deliberately separate from ``FunnelConfig``: v2 is a
diagnostic/event engine and must not silently change the legacy funnel's
selection thresholds.  They are starting research parameters, not classic
Wyckoff constants and should be calibrated with the replay report.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WyckoffV2Config:
    range_lookback: int = 90
    range_min_bars: int = 40
    atr_window: int = 20
    swing_window: int = 3
    range_width_atr_min: float = 4.0
    range_width_atr_max: float = 12.0
    range_width_pct_ceiling: float = 45.0
    range_max_drift_pct: float = 18.0
    range_min_tests: int = 2
    tolerance_atr_factor: float = 0.5
    tolerance_pct_floor: float = 0.015

    spring_penetration_atr_max: float = 1.5
    spring_min_clv: float = 0.60
    spring_high_effort_ratio: float = 1.30
    spring_low_supply_ratio: float = 0.80
    spring_test_max_bars: int = 10
    spring_test_normal_volume_window: int = 20
    spring_test_normal_volume_ratio: float = 0.80
    spring_test_max_distance_atr: float = 1.0
    spring_test_spread_ratio_max: float = 0.80
    spring_test_min_clv: float = 0.55

    sos_breakout_atr_min: float = 0.30
    sos_spread_atr_min: float = 1.20
    sos_min_clv: float = 0.70
    sos_volume_lookback: int = 120
    sos_volume_percentile_min: float = 0.80
    sos_follow_through_max_bars: int = 5

    lps_max_bars_after_sos: int = 20
    lps_pullback_distance_atr: float = 1.0
    lps_close_below_creek_atr: float = 0.5
    lps_pullback_depth_atr_max: float = 2.0
    lps_volume_to_sos_max: float = 0.65
    lps_normal_volume_window: int = 20
    lps_volume_to_normal_max: float = 0.90
    lps_turning_lookback: int = 3

    # P1 research variants.  These are intentionally not selection rules: the
    # replay emits each eligible variant independently for A/B comparison.
    demand_confirm_atr_buffer: float = 0.20
    demand_confirm_min_clv: float = 0.65
    demand_confirm_volume_window: int = 20
    demand_confirm_swing_window: int = 3

    sos_held_retention_thresholds: tuple[float, ...] = (0.20, 0.30, 0.40, 0.50)
    lps_shallow_retracement_min: float = 0.20
    lps_shallow_retracement_max: float = 0.50
    lps_shallow_min_impulse_atr: float = 1.0
    lps_shallow_volume_to_sos_max: float = 0.65
    lps_shallow_volume_to_normal_max: float = 0.90

    # Point-in-time market-context labels for research stratification only.
    market_regime_return_window: int = 60
    market_regime_bull_return_pct: float = 10.0
    market_regime_bear_return_pct: float = -10.0

    evr_volume_lookback: int = 20
    evr_effort_min: float = 1.8
    evr_result_atr_max: float = 0.5
    evr_near_boundary_atr: float = 1.0
    evr_bullish_min_clv: float = 0.60
    evr_bearish_max_clv: float = 0.40
