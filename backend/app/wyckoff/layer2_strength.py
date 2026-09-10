"""Layer 2 cross-sectional strength screening for the Wyckoff funnel.

This is a source migration from local ``reference/WyckoffTradingAgent``.  It
keeps the benchmark and universe-level RPS inputs explicit: callers must not
silently substitute a per-symbol indicator for either one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.wyckoff.config import FunnelConfig
from app.wyckoff.trend_drawdown_risk import max_drawdown_pct


@dataclass(frozen=True)
class BenchmarkContext:
    sorted_df: pd.DataFrame | None
    latest_date: object | None
    dropping: bool
    pct_by_date: dict[object, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RpsContext:
    fast: dict[str, float]
    slow: dict[str, float]
    active: bool


@dataclass(frozen=True)
class Layer2SymbolResult:
    passed: bool
    channel: str
    pre_ignition: bool
    channels: dict[str, bool]


def close_return_pct(close: pd.Series, lookback: int) -> float | None:
    clean = pd.to_numeric(close, errors="coerce").dropna()
    if len(clean) <= max(int(lookback), 1):
        return None
    start, end = float(clean.iloc[-lookback - 1]), float(clean.iloc[-1])
    return None if start == 0 else (end - start) / start * 100.0


def build_benchmark_context(bench_df: pd.DataFrame | None, cfg: FunnelConfig) -> BenchmarkContext:
    if bench_df is None or bench_df.empty:
        return BenchmarkContext(None, None, False)
    frame = _sorted(bench_df)
    pct = _numeric_column(frame, "pct_chg")
    if pct.empty or pct.isna().all():
        pct = _numeric_column(frame, "close").pct_change() * 100.0
    dropping = len(pct.dropna()) >= cfg.bench_drop_days and float(((pct.tail(cfg.bench_drop_days) / 100 + 1).prod() - 1) * 100) <= cfg.bench_drop_threshold
    dates = _column(frame, "date")
    latest = dates.iloc[-1] if not dates.empty else None
    by_date = dict(zip(dates, pct, strict=True)) if not dates.empty and not dates.duplicated().any() else {}
    return BenchmarkContext(frame, latest, dropping, by_date)


def build_rps_context(symbols: list[str], df_map: dict[str, pd.DataFrame], cfg: FunnelConfig, *, rps_universe: list[str] | None = None) -> RpsContext:
    if not cfg.enable_rps_filter:
        return RpsContext({}, {}, False)
    rows: list[tuple[str, float, float]] = []
    for symbol in rps_universe or symbols:
        frame = df_map.get(symbol)
        if frame is None or frame.empty:
            continue
        close = pd.to_numeric(_sorted(frame).get("close"), errors="coerce")
        fast, slow = close_return_pct(close, cfg.rps_window_fast), close_return_pct(close, cfg.rps_window_slow)
        if fast is not None and slow is not None:
            rows.append((symbol, fast, slow))
    if not rows:
        return RpsContext({}, {}, False)
    ranked = pd.DataFrame(rows, columns=["symbol", "fast", "slow"])
    return RpsContext(
        (ranked.set_index("symbol")["fast"].rank(pct=True) * 100).to_dict(),
        (ranked.set_index("symbol")["slow"].rank(pct=True) * 100).to_dict(),
        True,
    )


def evaluate_layer2_symbol(
    symbol: str,
    frame: pd.DataFrame,
    cfg: FunnelConfig,
    *,
    benchmark: BenchmarkContext,
    rps: RpsContext,
    detect_sos: Callable[[pd.DataFrame, FunnelConfig], float | None],
) -> Layer2SymbolResult:
    """Evaluate all eight upstream Layer-2 entry channels for one symbol."""
    df = _sorted(frame)
    close = pd.to_numeric(df["close"], errors="coerce")
    ma_short, ma_long = close.rolling(cfg.ma_short).mean().iloc[-1], close.rolling(cfg.ma_long).mean().iloc[-1]
    last = float(close.iloc[-1])
    bullish = bool(pd.notna(ma_short) and pd.notna(ma_long) and ma_short > ma_long)
    hold_ma20 = benchmark.dropping and last >= close.rolling(cfg.ma_hold).mean().iloc[-1]
    fast, slow = rps.fast.get(symbol), rps.slow.get(symbol)
    slope_ok, slope = _rps_slope(close, cfg, rps.active)
    momentum_rps, ambush_rps = _rps_flags(fast, slow, slope_ok, slope, cfg, rps.active)
    momentum_rs, ambush_rs = _rs_flags(df, close, ma_short, ma_long, last, slow, cfg, benchmark)
    channels = {
        "momentum": (bullish or hold_ma20) and momentum_rs and momentum_rps and _bias_ok(last, ma_long, cfg.momentum_bias_200_max),
        "ambush": cfg.enable_ambush_channel and _bias_abs_ok(last, ma_long, cfg.ambush_bias_200_abs_max) and (close_return_pct(close, 20) or float("inf")) <= cfg.ambush_ret20_max and ambush_rs and ambush_rps,
        "accum": _accum_ok(df, close, last, ma_short, ma_long, cfg),
        "dry_vol": _dry_volume_ok(df, close, last, cfg),
        "rs_div": _rs_divergence_ok(df, close, last, benchmark.sorted_df, cfg),
        "trend_cont": cfg.enable_trend_cont_channel and bullish and rps.active and slow is not None and slow >= cfg.trend_cont_rps_slow_min and _trend_volume_ok(df, cfg.trend_cont_vol_ratio_min),
        "breakout_accel": _breakout_accel_ok(df, close, last, ma_short, bullish, fast, rps.active, cfg),
        "sos": ((not rps.active) or (slow is not None and slow >= cfg.sos_bypass_rps_slow_min)) and detect_sos(df, cfg) is not None,
    }
    channels = {key: bool(value) for key, value in channels.items()}
    labels = _channel_labels(channels)
    pre_ignition = not labels and _pre_ignition_ok(df, close, last, ma_long, bullish, hold_ma20, slow, cfg)
    return Layer2SymbolResult(bool(labels), "+".join(labels), pre_ignition, channels)


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values("date", kind="stable") if "date" in frame.columns else frame


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return one numeric column even when an upstream frame has duplicate names."""
    value = _column(frame, column)
    return pd.to_numeric(value, errors="coerce")


def _stock_daily_return_points(frame: pd.DataFrame) -> pd.Series:
    """Return stock daily returns in percentage points for the RS comparison.

    Index history supplies ``pct_chg`` in percentage points, while the enriched
    stock-history contract supplies ``change_pct`` as a decimal.  Keep the
    conversion at this boundary so both legs of the relative-strength formula
    use the same unit.
    """
    pct_chg = _numeric_column(frame, "pct_chg")
    if not pct_chg.empty and not pct_chg.isna().all():
        return pct_chg
    return _numeric_column(frame, "change_pct") * 100.0


def _column(frame: pd.DataFrame, column: str) -> pd.Series:
    value = frame.loc[:, column] if column in frame.columns else pd.Series(dtype=float)
    if isinstance(value, pd.DataFrame):
        value = value.iloc[:, 0]
    return value


def _cum_return(pct: pd.Series) -> float | None:
    clean = pd.to_numeric(pct, errors="coerce").dropna()
    return float(((clean / 100 + 1).prod() - 1) * 100) if not clean.empty else None


def _rs_flags(df: pd.DataFrame, close: pd.Series, ma_short: float, ma_long: float, last: float, slow: float | None, cfg: FunnelConfig, benchmark: BenchmarkContext) -> tuple[bool, bool]:
    if not cfg.enable_rs_filter or benchmark.sorted_df is None:
        return True, True
    stock_pct = _stock_daily_return_points(df)
    if "date" not in df.columns or stock_pct.empty or stock_pct.isna().all() or not benchmark.pct_by_date:
        return False, False
    pairs = [(value, benchmark.pct_by_date[date]) for date, value in zip(df["date"], stock_pct, strict=True) if date in benchmark.pct_by_date]
    if len(pairs) < max(cfg.rs_window_long, cfg.rs_window_short):
        return False, False
    stock_pct, bench_pct = (pd.Series(values) for values in zip(*pairs, strict=True))
    rs_long, rs_short = _cum_return(stock_pct.tail(cfg.rs_window_long)), _cum_return(stock_pct.tail(cfg.rs_window_short))
    bench_long, bench_short = _cum_return(bench_pct.tail(cfg.rs_window_long)), _cum_return(bench_pct.tail(cfg.rs_window_short))
    if None in (rs_long, rs_short, bench_long, bench_short):
        return False, False
    long_min, short_min = cfg.rs_min_long, cfg.rs_min_short
    if cfg.rs_dynamic_relax_enabled and (bench_long >= cfg.rs_bench_surge_long_pct or bench_short >= cfg.rs_bench_surge_short_pct):
        long_min, short_min = long_min * cfg.rs_surge_relax_factor, short_min * cfg.rs_surge_relax_factor
    momentum = rs_long - bench_long >= long_min and rs_short - bench_short >= short_min
    if not momentum and cfg.rs_structural_bypass_enabled and slow is not None and slow >= cfg.rs_structural_bypass_rps_slow_min:
        momentum = bool(pd.notna(ma_short) and pd.notna(ma_long) and ma_short > ma_long > 0 and (close_return_pct(close, 20) or -float("inf")) >= cfg.rs_structural_bypass_ret20_floor and abs(last / ma_short - 1) <= 0.12 and (max_drawdown_pct(close, cfg.trend_cont_drawdown_window) or 0) <= 18 and _structural_volume_ok(df))
    return momentum, rs_long - bench_long >= cfg.ambush_rs_long_min and rs_short - bench_short >= cfg.ambush_rs_short_min


def _rps_slope(close: pd.Series, cfg: FunnelConfig, active: bool) -> tuple[bool, float]:
    if not cfg.enable_rps_filter or not active or len(close) < cfg.rps_slope_window:
        return True, 0.0
    values = close.tail(max(cfg.rps_slope_window, 2)).dropna()
    if len(values) < 2 or values.iloc[0] <= 0:
        return True, 0.0
    returns = (values / values.iloc[0] - 1) * 100
    slope = float(np.polyfit(np.arange(len(returns)), returns, 1)[0])
    return slope >= cfg.rps_slope_min, slope


def _rps_flags(fast: float | None, slow: float | None, slope_ok: bool, slope: float, cfg: FunnelConfig, active: bool) -> tuple[bool, bool]:
    if not cfg.enable_rps_filter or not active:
        return True, True
    if fast is None or slow is None:
        return False, False
    accel = slope >= cfg.rps_slope_accel_bypass and fast >= cfg.rps_accel_fast_min and slow >= cfg.rps_accel_slow_min
    momentum = (fast >= cfg.rps_fast_min and slow >= cfg.rps_slow_min and slope_ok) or (slow >= cfg.rps_slow_strong_bypass and fast >= cfg.rps_fast_bypass_min) or accel
    return momentum, fast <= cfg.ambush_rps_fast_max and slow >= cfg.ambush_rps_slow_min


def _bias_ok(last: float, ma: float, maximum: float) -> bool:
    return not pd.notna(ma) or ma <= 0 or (last - ma) / ma <= maximum


def _bias_abs_ok(last: float, ma: float, maximum: float) -> bool:
    return pd.notna(ma) and ma > 0 and abs((last - ma) / ma) <= maximum


def _accum_ok(df: pd.DataFrame, close: pd.Series, last: float, ma_short: float, ma_long: float, cfg: FunnelConfig) -> bool:
    if not cfg.enable_accumulation_channel or len(df) < max(cfg.accum_lookback_days, cfg.accum_vol_dry_ref_window):
        return False
    low_position = last <= float(close.tail(cfg.accum_lookback_days).min()) * (1 + cfg.accum_price_from_low_max)
    zone, volume = df.tail(cfg.accum_range_window), pd.to_numeric(df.get("volume"), errors="coerce")
    low, high = pd.to_numeric(zone.get("low"), errors="coerce").min(), pd.to_numeric(zone.get("high"), errors="coerce").max()
    range_ok = pd.notna(low) and low > 0 and (high - low) / low * 100 <= cfg.accum_range_max_pct
    recent, reference = volume.tail(cfg.accum_vol_dry_window).mean(), volume.tail(cfg.accum_vol_dry_ref_window).iloc[:-cfg.accum_vol_dry_window].mean()
    dry = pd.notna(reference) and reference > 0 and recent / reference < cfg.accum_vol_dry_ratio
    ma_gap = pd.notna(ma_short) and pd.notna(ma_long) and ma_long > 0 and abs((ma_short - ma_long) / ma_long) <= cfg.accum_ma_gap_max
    return bool(low_position and range_ok and dry and ma_gap)


def _dry_volume_ok(df: pd.DataFrame, close: pd.Series, last: float, cfg: FunnelConfig) -> bool:
    if not cfg.enable_dry_vol_channel or len(df) < cfg.dry_vol_ref_window or last > float(close.tail(cfg.dry_vol_ref_window).min()) * (1 + cfg.dry_vol_price_from_low_max):
        return False
    volume = pd.to_numeric(df.get("volume"), errors="coerce").tail(cfg.dry_vol_ref_window).dropna()
    return len(volume) >= 50 and float(volume.tail(cfg.dry_vol_lookback).min()) <= float(volume.quantile(cfg.dry_vol_quantile))


def _rs_divergence_ok(df: pd.DataFrame, close: pd.Series, last: float, bench: pd.DataFrame | None, cfg: FunnelConfig) -> bool:
    if not cfg.enable_rs_divergence_channel or bench is None or len(df) < cfg.rs_div_bench_ref_window:
        return False
    bench_close = pd.to_numeric(bench.get("close"), errors="coerce").dropna()
    stock_low = pd.to_numeric(df.get("low"), errors="coerce").dropna()
    if len(bench_close) < cfg.rs_div_bench_ref_window or len(stock_low) < cfg.rs_div_bench_ref_window:
        return False
    b_recent, b_ref = bench_close.tail(cfg.rs_div_bench_window), bench_close.tail(cfg.rs_div_bench_ref_window).iloc[:-cfg.rs_div_bench_window]
    s_recent, s_ref = stock_low.tail(cfg.rs_div_stock_window), stock_low.tail(cfg.rs_div_bench_ref_window).iloc[:-cfg.rs_div_stock_window]
    low_ok = last <= float(close.tail(max(cfg.dry_vol_ref_window, 250)).min()) * (1 + cfg.rs_div_price_from_low_max)
    return bool(low_ok and b_recent.min() < b_ref.min() and s_recent.min() >= s_ref.min())


def _trend_volume_ok(df: pd.DataFrame, minimum: float) -> bool:
    volume = pd.to_numeric(df.get("volume"), errors="coerce").dropna()
    return len(volume) < 20 or volume.tail(20).mean() <= 0 or volume.tail(5).mean() / volume.tail(20).mean() >= minimum


def _structural_volume_ok(df: pd.DataFrame) -> bool:
    volume = pd.to_numeric(df.get("volume"), errors="coerce").dropna()
    return len(volume) < 20 or volume.tail(20).mean() <= 0 or volume.tail(5).mean() / volume.tail(20).mean() <= 1.8


def _breakout_accel_ok(df: pd.DataFrame, close: pd.Series, last: float, ma_short: float, bullish: bool, fast: float | None, active: bool, cfg: FunnelConfig) -> bool:
    if not cfg.enable_breakout_accel_channel or not active or bullish or fast is None or fast < cfg.breakout_accel_rps_fast_min or not (pd.notna(ma_short) and last > ma_short):
        return False
    ret = close_return_pct(close, cfg.breakout_accel_ret_window)
    volume = pd.to_numeric(df.get("volume"), errors="coerce")
    reference = volume.tail(cfg.breakout_accel_vol_ref_window).iloc[:-cfg.breakout_accel_ret_window].mean()
    return ret is not None and ret >= cfg.breakout_accel_ret_min and reference > 0 and volume.tail(cfg.breakout_accel_ret_window).mean() / reference >= cfg.breakout_accel_vol_ratio


def _pre_ignition_ok(df: pd.DataFrame, close: pd.Series, last: float, ma_long: float, bullish: bool, holding: bool, slow: float | None, cfg: FunnelConfig) -> bool:
    if not pd.notna(ma_long) or ma_long <= 0 or slow is None:
        return False
    volume = pd.to_numeric(df.get("volume"), errors="coerce")
    baseline = volume.tail(cfg.sos_vol_window).iloc[:-1].mean()
    return bool((bullish or holding) and (last - ma_long) / ma_long <= cfg.pre_ignition_bias_max and slow >= cfg.pre_ignition_rps_slow_min and baseline > 0 and volume.iloc[-2] / baseline >= cfg.pre_ignition_vol_ratio_min)


def _channel_labels(channels: dict[str, bool]) -> list[str]:
    return [label for key, label in (("momentum", "主升通道"), ("ambush", "潜伏通道"), ("accum", "吸筹通道"), ("dry_vol", "地量蓄势"), ("rs_div", "暗中护盘"), ("trend_cont", "趋势延续"), ("breakout_accel", "加速突破"), ("sos", "点火破局")) if channels[key]]


__all__ = ["BenchmarkContext", "Layer2SymbolResult", "RpsContext", "build_benchmark_context", "build_rps_context", "evaluate_layer2_symbol"]
