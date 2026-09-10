from __future__ import annotations

import numpy as np
import pandas as pd

from app.wyckoff.config import FunnelConfig
from app.wyckoff.layer2_strength import (
    RpsContext,
    build_benchmark_context,
    build_rps_context,
    evaluate_layer2_symbol,
)


def _frame(multiplier: float, n: int = 140) -> pd.DataFrame:
    close = np.linspace(10.0, 10.0 * multiplier, n)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-01", periods=n),
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
            "pct_chg": pd.Series(close).pct_change().fillna(0.0) * 100,
        }
    )


def test_layer2_uses_universe_rps_not_a_per_stock_score() -> None:
    universe = {"000001": _frame(1.8), "000002": _frame(1.4), "000003": _frame(1.1)}
    config = FunnelConfig(
        ma_short=10,
        ma_long=30,
        rps_window_fast=20,
        rps_window_slow=60,
        rps_slope_window=5,
        enable_rs_filter=False,
        rps_fast_min=60,
        rps_slow_min=60,
        momentum_bias_200_max=1.0,
    )

    rps = build_rps_context(list(universe), universe, config)
    result = evaluate_layer2_symbol(
        "000001",
        universe["000001"],
        config,
        benchmark=build_benchmark_context(None, config),
        rps=rps,
        detect_sos=lambda _frame, _config: None,
    )

    assert rps.active is True
    assert rps.slow["000001"] > rps.slow["000003"]
    assert result.passed is True
    assert result.channels["momentum"] is True
    assert "主升通道" in result.channel


def test_layer2_does_not_pass_when_required_universe_rps_is_unavailable() -> None:
    frame = _frame(1.1)
    config = FunnelConfig(
        ma_short=10,
        ma_long=30,
        enable_rs_filter=False,
        enable_accumulation_channel=False,
        enable_dry_vol_channel=False,
        enable_rs_divergence_channel=False,
        enable_trend_cont_channel=False,
        enable_breakout_accel_channel=False,
    )

    result = evaluate_layer2_symbol(
        "000001",
        frame,
        config,
        benchmark=build_benchmark_context(None, config),
        rps=RpsContext({}, {}, True),
        detect_sos=lambda _frame, _config: None,
    )

    assert result.passed is False
    assert result.pre_ignition is False


def test_layer2_rs_uses_enriched_decimal_change_pct() -> None:
    stock = _frame(2.0, n=80).drop(columns=["pct_chg"])
    stock["change_pct"] = stock["close"].pct_change().fillna(0.0)
    benchmark = pd.DataFrame(
        {
            "date": stock["date"],
            "close": np.full(len(stock), 100.0),
            "pct_chg": np.zeros(len(stock)),
        }
    )
    config = FunnelConfig(
        ma_short=10,
        ma_long=30,
        enable_rps_filter=False,
        momentum_bias_200_max=1.0,
        enable_accumulation_channel=False,
        enable_dry_vol_channel=False,
        enable_rs_divergence_channel=False,
        enable_trend_cont_channel=False,
        enable_breakout_accel_channel=False,
    )

    result = evaluate_layer2_symbol(
        "000001",
        stock,
        config,
        benchmark=build_benchmark_context(benchmark, config),
        rps=RpsContext({}, {}, False),
        detect_sos=lambda _frame, _config: None,
    )

    assert result.channels["momentum"] is True
    assert result.passed is True
