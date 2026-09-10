from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.wyckoff.v2 import (
    WyckoffV2Config,
    run_event_backtest,
    run_event_backtest_frames,
    run_parameter_grid,
)
from app.wyckoff.v2.backtest import _outcome


def _range_frame() -> pd.DataFrame:
    periods = 120
    close = 11.0 + 0.8 * np.sin(np.linspace(0, 10 * np.pi, periods))
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-01", periods=periods),
            "open": close - 0.05,
            "high": close + 0.25,
            "low": close - 0.25,
            "close": close,
            "volume": np.full(periods, 1_000.0),
        }
    )


def _append(frame: pd.DataFrame, *, open_: float, high: float, low: float, close: float, volume: float) -> pd.DataFrame:
    date = pd.Timestamp(frame["date"].iloc[-1]) + pd.offsets.BusinessDay()
    return pd.concat(
        [
            frame,
            pd.DataFrame({"date": [date], "open": [open_], "high": [high], "low": [low], "close": [close], "volume": [volume]}),
        ],
        ignore_index=True,
    )


def _frame_with_mature_spring_entry() -> pd.DataFrame:
    frame = _range_frame()
    frame = _append(frame, open_=10.25, high=10.70, low=9.65, close=10.50, volume=1_000.0)
    frame = _append(frame, open_=10.20, high=10.70, low=9.98, close=10.48, volume=500.0)
    frame = _append(frame, open_=10.55, high=10.95, low=10.45, close=10.85, volume=900.0)
    frame = _append(frame, open_=10.88, high=11.20, low=10.80, close=11.10, volume=950.0)
    frame = _append(frame, open_=11.12, high=11.50, low=11.00, close=11.40, volume=1_000.0)
    return frame


def _config() -> WyckoffV2Config:
    return WyckoffV2Config(range_width_atr_min=3.0, range_width_atr_max=14.0, sos_volume_lookback=20)


def test_event_backtest_reports_forward_return_mfe_and_mae_without_touching_selection() -> None:
    report = run_event_backtest({"000001.SZ": _frame_with_mature_spring_entry()}, _config(), horizons=(1, 3))

    entry = report["entries"]["spring_aggressive"]
    assert report["mode"] == "research_only"
    assert report["affects_formal_selection"] is False
    assert entry["events"] >= 1
    assert entry["horizons"]["1"]["count"] >= 1
    assert entry["horizons"]["1"]["mean_mfe_pct"] is not None
    assert entry["horizons"]["1"]["mean_mae_pct"] is not None
    assert report["execution"] == {
        "entry_timing": "next_trading_day_open",
        "exit_timing": "signal_date_plus_n_close",
        "costs_and_slippage_included": False,
    }


def test_event_backtest_enters_at_the_next_trading_day_open_not_the_signal_close() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-01", periods=3),
            "open": [10.0, 20.0, 21.0],
            "high": [10.5, 23.0, 22.0],
            "low": [9.5, 19.0, 20.0],
            "close": [10.0, 22.0, 21.5],
            "volume": [1_000.0, 1_000.0, 1_000.0],
        }
    )

    outcome = _outcome(frame, signal_index=0, horizon=1)

    assert outcome == {
        "return_pct": pytest.approx(10.0),
        "mfe_pct": pytest.approx(15.0),
        "mae_pct": pytest.approx(-5.0),
        "invalidation_hit": None,
    }


def test_streaming_backtest_matches_the_mapping_api_and_reports_invalidation_hits() -> None:
    frame = _frame_with_mature_spring_entry()
    report = run_event_backtest({"000001.SZ": frame}, _config(), horizons=(1,))
    streamed = run_event_backtest_frames(iter([("000001.SZ", frame)]), _config(), horizons=(1,))

    assert streamed == report
    assert "invalidation_hit_rate" in streamed["entries"]["spring_aggressive"]["horizons"]["1"]


def test_backtest_emits_range_identity_event_details_and_excess_return() -> None:
    records: list[dict[str, object]] = []
    report = run_event_backtest_frames(
        [("000001.SZ", _frame_with_mature_spring_entry())],
        _config(),
        horizons=(1,),
        entries=("spring_aggressive",),
        benchmark_return=lambda _date, _days: 1.0,
        event_sink=records.append,
    )

    metric = report["entries"]["spring_aggressive"]["horizons"]["1"]
    assert metric["mean_excess_return_pct"] is not None
    assert report["event_statistics"]["unique_ranges"] >= 1
    assert records and records[0]["range_id"]
    assert "outcomes" in records[0]


def test_parameter_grid_only_accepts_explicit_v2_research_parameters() -> None:
    reports = run_parameter_grid(
        {"000001.SZ": _frame_with_mature_spring_entry()},
        {"spring_test_normal_volume_ratio": (0.7, 0.8)},
        _config(),
        horizons=(1,),
    )

    assert [item["parameters"]["spring_test_normal_volume_ratio"] for item in reports] == [0.7, 0.8]
    assert all(item["report"]["mode"] == "research_only" for item in reports)


def test_experiment_matrix_returns_funnel_and_failure_profiles() -> None:
    report = run_event_backtest_frames(
        [("000001.SZ", _frame_with_mature_spring_entry())],
        _config(),
        horizons=(1,),
        experiment_variants=("SPRING_BASE", "SPRING_CONFIRM_CLV"),
    )

    assert report["experiment_variants"] == ["SPRING_BASE", "SPRING_CONFIRM_CLV"]
    assert "TRADING_RANGE" in report["lps_funnel"]
    assert report["spring_failure_profiles"]
    assert "spring_aggressive" in report["entries"]
    assert "spring_confirm_clv" in report["entries"]


def test_market_regime_is_reported_as_a_research_stratification() -> None:
    report = run_event_backtest_frames(
        [("000001.SZ", _frame_with_mature_spring_entry())],
        _config(),
        horizons=(1,),
        entries=("spring_aggressive",),
        market_regime=lambda _day: "BULL",
    )

    assert "BULL" in report["market_regime"]["spring_aggressive"]
