"""Configuration shared by the migrated Wyckoff domain modules.

The fields below are the upstream defaults required by the dynamic structure
diagnostics.  The full funnel configuration will grow here as later layers are
migrated, so every module has one stable configuration boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FunnelConfig:
    """Wyckoff funnel settings currently used by the structure layer."""

    trading_days: int = 320

    # Layer 1: investable A-share universe.
    require_cn_main_or_chinext: bool = True
    include_bse_board: bool = True
    min_market_cap_yi: float = 25.0
    min_avg_amount_wan: float = 4000.0
    l1_min_close_price: float = 2.0
    l1_delist_risk_cap_floor_yi: float = 10.0
    l1_cap_bypass_amount_wan: float = 8000.0
    amount_avg_window: int = 20
    amount_skew_check_enabled: bool = True
    amount_skew_max: float = 3.0
    amount_median_min_ratio: float = 0.45
    amount_pass_days_min_ratio: float = 0.35

    spring_support_window: int = 60
    spring_vol_ratio: float = 1.3
    spring_tr_max_range_pct: float = 30.0
    spring_tr_max_drift_pct: float = 12.0
    spring_tr_atr_window: int = 20

    # Layer 2: cross-sectional strength and eight candidate channels.
    ma_short: int = 50
    ma_long: int = 200
    ma_hold: int = 20
    bench_drop_days: int = 3
    bench_drop_threshold: float = -2.0
    rs_window_long: int = 10
    rs_window_short: int = 3
    rs_min_long: float = 2.0
    rs_min_short: float = 1.0
    rs_dynamic_relax_enabled: bool = True
    rs_bench_surge_long_pct: float = 4.0
    rs_bench_surge_short_pct: float = 2.0
    rs_surge_relax_factor: float = 0.35
    rs_structural_bypass_enabled: bool = True
    rs_structural_bypass_rps_slow_min: float = 65.0
    rs_structural_bypass_ret20_floor: float = -4.0
    enable_rs_filter: bool = True
    enable_rps_filter: bool = True
    rps_window_fast: int = 50
    rps_window_slow: int = 120
    rps_fast_min: float = 65.0
    rps_slow_min: float = 70.0
    rps_slow_strong_bypass: float = 80.0
    rps_fast_bypass_min: float = 50.0
    rps_slope_window: int = 10
    rps_slope_min: float = 0.5
    rps_slope_accel_bypass: float = 1.5
    rps_accel_fast_min: float = 50.0
    rps_accel_slow_min: float = 55.0
    momentum_bias_200_max: float = 0.25
    enable_pre_ignition_watch: bool = True
    pre_ignition_bias_max: float = 0.20
    pre_ignition_rps_slow_min: float = 60.0
    pre_ignition_vol_ratio_min: float = 0.6
    enable_ambush_channel: bool = True
    ambush_rps_fast_max: float = 45.0
    ambush_rps_slow_min: float = 70.0
    ambush_rs_long_min: float = -2.0
    ambush_rs_short_min: float = -8.0
    ambush_bias_200_abs_max: float = 0.08
    ambush_ret20_max: float = -3.0
    enable_accumulation_channel: bool = True
    accum_lookback_days: int = 250
    accum_price_from_low_max: float = 0.45
    accum_range_window: int = 60
    accum_range_max_pct: float = 40.0
    accum_vol_dry_window: int = 20
    accum_vol_dry_ref_window: int = 120
    accum_vol_dry_ratio: float = 0.75
    accum_ma_gap_max: float = 0.08
    enable_dry_vol_channel: bool = True
    dry_vol_lookback: int = 10
    dry_vol_ref_window: int = 250
    dry_vol_quantile: float = 0.20
    dry_vol_price_from_low_max: float = 0.35
    enable_rs_divergence_channel: bool = True
    rs_div_bench_window: int = 20
    rs_div_stock_window: int = 20
    rs_div_bench_ref_window: int = 60
    rs_div_price_from_low_max: float = 0.50
    rs_div_bench_vol_expand_ratio: float = 1.2
    rs_div_stock_vol_shrink_ratio: float = 0.8
    enable_trend_cont_channel: bool = True
    trend_cont_rps_slow_min: float = 75.0
    trend_cont_vol_ratio_min: float = 0.70
    trend_cont_drawdown_window: int = 60
    enable_breakout_accel_channel: bool = True
    breakout_accel_rps_fast_min: float = 70.0
    breakout_accel_ret_window: int = 20
    breakout_accel_ret_min: float = 15.0
    breakout_accel_vol_ratio: float = 1.3
    breakout_accel_vol_ref_window: int = 60
    sos_bypass_rps_slow_min: float = 30.0

    # Layer 3: industry/concept resonance.
    top_n_sectors: int = 5
    sector_min_count: int = 3
    sector_count_quantile: float = 0.70
    sector_super_strength_quantile: float = 0.90
    sector_heat_bypass_min_count: int = 0
    # Formal L3 resonance is industry based.  Concepts may still be opted in
    # for an explicitly configured research run, but must not silently change
    # the production candidate universe.
    use_concept_map: bool = False
    l3_keep_strength_min: float = 0.60
    l3_leader_strength_min: float = 0.80
    l3_hot_leader_strength_min: float = 0.55

    # Legacy-L4 LPS is only a research trigger.  Keep its rules explicit and
    # independent from Wyckoff V2's event/state machine.
    lps_lookback: int = 2
    lps_vol_dry_ratio: float = 0.65
    lps_vol_ref_window: int = 60
    lps_support_zone_max: float = 0.15
    lps_recovery_atr_min: float = 0.25
    lps_close_position_min: float = 0.55

    enable_evr_trigger: bool = True
    evr_vol_ratio: float = 1.8
    evr_vol_window: int = 20
    evr_max_drop: float = 2.0
    evr_max_rise: float = 2.0

    sos_pct_min: float = 6.0
    sos_vol_ratio: float = 3.0
    sos_vol_window: int = 20
    sos_breakout_tolerance: float = 0.01
