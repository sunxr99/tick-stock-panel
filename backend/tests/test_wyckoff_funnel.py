from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl

from app.strategy.engine import StrategyDataContext, StrategyEngine
from app.wyckoff.config import FunnelConfig
from app.wyckoff.funnel import FunnelResult, run_funnel


def _history(multiplier: float) -> pd.DataFrame:
    close = np.linspace(10.0, 10.0 * multiplier, 120)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-01", periods=120),
            "open": close * 0.995,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": np.full(120, 1_000_000.0),
            "amount": close * 1_000_000.0,
            "pct_chg": pd.Series(close).pct_change().fillna(0.0) * 100,
        }
    )


def test_funnel_keeps_each_layer_and_snapshot_evidence() -> None:
    symbols = ["000001", "000002", "000003"]
    histories = {symbol: _history(1.2 + index * 0.1) for index, symbol in enumerate(symbols)}
    config = FunnelConfig(
        ma_short=10,
        ma_long=30,
        enable_rps_filter=False,
        enable_rs_filter=False,
        min_avg_amount_wan=100,
        sector_min_count=2,
    )

    result = run_funnel(
        symbols,
        histories,
        benchmark=None,
        sector_map={symbol: "半导体" for symbol in symbols},
        cfg=config,
    )
    snapshot = result.to_snapshot()

    assert result.layer1_symbols == symbols
    assert result.layer2_symbols == symbols
    assert result.layer3_symbols == symbols
    assert snapshot["layer3_symbols"] == symbols
    assert set(snapshot["triggers"]) == {"sos", "spring", "lps", "evr"}
    assert snapshot["diagnostics"]["stage_counts"]["final"]["strategy_total"] == len(symbols)
    assert snapshot["diagnostics"]["stage_counts"]["candidate_lane"] == {
        "count": 0,
        "implemented": False,
    }
    assert snapshot["diagnostics"]["sample_final_traces"][0]["source"] == "L3 strict"
    assert snapshot["diagnostics"]["sample_final_traces"][0]["l4"] == "reject"


def test_funnel_records_missing_group_metadata_fallback() -> None:
    symbols = ["000001", "000002", "000003"]
    result = run_funnel(
        symbols,
        {symbol: _history(1.2) for symbol in symbols},
        benchmark=None,
        cfg=FunnelConfig(
            ma_short=10,
            ma_long=30,
            enable_rps_filter=False,
            enable_rs_filter=False,
            min_avg_amount_wan=100,
        ),
    )

    diagnostics = result.to_snapshot()["diagnostics"]

    assert diagnostics["l3_fallback"]["missing_group_metadata"] is True
    assert diagnostics["source_counts"] == {"L3 strict": 0, "L3 fallback": len(symbols)}


def test_funnel_l1_excludes_st_before_any_later_layer() -> None:
    histories = {"000001": _history(1.3), "000002": _history(1.2), "000003": _history(1.1)}
    config = FunnelConfig(ma_short=10, ma_long=30, enable_rps_filter=False, enable_rs_filter=False, min_avg_amount_wan=100)

    result = run_funnel(
        list(histories),
        histories,
        benchmark=None,
        name_map={"000002": "*ST 测试"},
        cfg=config,
    )

    assert "000002" not in result.layer1_symbols
    assert "000002" not in result.layer2_symbols


def test_engine_keeps_wyckoff_snapshot_once_at_result_level(monkeypatch) -> None:
    snapshot = FunnelResult(
        layer1_symbols=["000001.SZ", "000002.SZ"],
        layer2_symbols=["000001.SZ", "000002.SZ"],
        layer3_symbols=["000001.SZ", "000002.SZ"],
        top_sectors=["测试行业"],
        channel_map={"000001.SZ": "trend"},
        pre_ignition_symbols=[],
        triggers={"sos": [("000001.SZ", 1.0)]},
        stage_map={"000001.SZ": "Markup"},
        trading_ranges={},
    )
    monkeypatch.setattr("app.wyckoff.funnel.run_funnel", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(
        "app.custom.chanlun.filter_daily_czsc_buy_points",
        lambda _history: pl.DataFrame({
            "symbol": ["000001.SZ"],
            "czsc_buy_types": [["一买"]],
            "czsc_buy_signals": [["日线_TEST_一买_任意_任意_0"]],
            "czsc_confirmation_time": ["2026-07-20"],
        }),
    )
    history = pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ"],
        "date": ["2026-07-20", "2026-07-20"],
        "open": [1.0, 1.0], "high": [1.1, 1.1], "low": [0.9, 0.9],
        "close": [1.0, 1.0], "volume": [1.0, 1.0], "amount": [1.0, 1.0],
    }).with_columns(pl.col("date").str.to_date())
    context = StrategyDataContext(
        asset_type="stock", timeframe="1d", as_of=history["date"][0], history=history,
        current=pl.DataFrame({
            "symbol": ["000001.SZ", "000002.SZ"],
            "close": [10.5, 20.5],
            "change_pct": [0.021, -0.013],
            "amount": [123_000_000.0, 456_000_000.0],
            "vol_ratio_5d": [1.7, 0.8],
            "rsi_14": [63.2, 42.1],
            "momentum_20d": [0.16, -0.04],
        }),
        market={"wyckoff_benchmark": history.drop("symbol")},
    )
    strategy = type("Strategy", (), {"wyckoff_config": FunnelConfig()})()

    result = StrategyEngine(strategy_dirs=[])._run_wyckoff_funnel(
        "wyckoff_funnel", strategy, context, started_at=0.0
    )

    assert all("wyckoff_snapshot" not in row for row in result.rows)
    evidence_snapshot = result.evidence["wyckoff_snapshot"]
    assert {key: value for key, value in evidence_snapshot.items() if key != "v2"} == snapshot.to_snapshot()
    assert result.rows[0]["wyckoff_signals"] == []
    assert result.rows[0]["wyckoff_legacy_signals"] == ["sos"]
    assert result.rows[0]["close"] == 10.5
    assert result.rows[0]["change_pct"] == 0.021
    assert result.rows[0]["amount"] == 123_000_000.0
    assert result.rows[0]["vol_ratio_5d"] == 1.7
    assert result.rows[0]["rsi_14"] == 63.2
    assert result.rows[0]["momentum_20d"] == 0.16
    assert result.rows[0]["czsc_buy_types"] == ["一买"]
    assert result.rows[0]["czsc_confirmation_time"] == "2026-07-20"
    assert result.rows[1]["czsc_buy_types"] == []
    assert result.rows[1]["czsc_confirmation_time"] is None
    assert result.rows[0]["czsc_event_identity_version"] == 2
    assert result.rows[1]["czsc_event_identity_version"] == 2
    assert result.evidence["wyckoff_snapshot"]["v2"]["affects_formal_selection"] is False
