from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import polars as pl

from app.services.volume_profile import (
    DataGranularity,
    ExtensionState,
    PositionState,
    ProfileQuality,
)
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
    assert snapshot["diagnostics"]["stage_counts"]["research_trigger_pool"] == {
        "count": 0,
        "affects_formal_selection": False,
    }
    assert snapshot["diagnostics"]["sample_final_traces"][0]["source"] == "L3 strict"
    assert snapshot["diagnostics"]["sample_final_traces"][0]["l4"] == "reject"


def test_funnel_labels_legacy_l4_hits_as_research_only(monkeypatch) -> None:
    symbols = ["000001", "000002", "000003"]
    histories = {symbol: _history(1.2 + index * 0.1) for index, symbol in enumerate(symbols)}
    monkeypatch.setattr(
        "app.wyckoff.funnel.detect_structure_triggers",
        lambda *_args, **_kwargs: SimpleNamespace(
            triggers={"sos": [("000002", 1.0)], "spring": [], "lps": [], "evr": []},
            stage_map={},
            trading_ranges={},
        ),
    )
    result = run_funnel(
        symbols,
        histories,
        benchmark=None,
        sector_map={symbol: "半导体" for symbol in symbols},
        cfg=FunnelConfig(
            ma_short=10,
            ma_long=30,
            enable_rps_filter=False,
            enable_rs_filter=False,
            min_avg_amount_wan=100,
            sector_min_count=2,
        ),
    )

    assert result.layer3_symbols == symbols
    assert result.research_trigger_symbols == ["000002"]
    assert result.final_traces["000002"]["research_trigger"] is True
    assert result.diagnostics["stage_counts"]["research_trigger_pool"] == {
        "count": 1,
        "affects_formal_selection": False,
    }


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

    assert result.layer3_symbols == []
    assert diagnostics["l3_fallback"]["missing_group_metadata"] is False
    assert diagnostics["source_counts"] == {"L3 strict": 0, "L3 fallback": 0}
    assert diagnostics["stage_counts"]["final"]["strategy_total"] == 0


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
        trading_ranges={
            "000001.SZ": {
                "support": 9.0,
                "resistance": 11.0,
                "range_start": "2026-05-01",
                "range_confirmed_at": "2026-07-20",
            },
        },
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
    ranking_calls = []

    def _rank(_repo, *, as_of, candidates):
        ranking_calls.append((as_of, candidates))
        ranked = [
            {
                **candidate,
                "sector_score": 70.0,
                "rs_score": 80.0 - index,
                "strength_score": 76.0 - index,
                "final_rank_score": 80.0 - index,
                "priority_level": "PRIORITY_B",
                "rank": index + 1,
            }
            for index, candidate in enumerate(candidates)
        ]
        return list(reversed(ranked))

    monkeypatch.setattr(
        "app.services.wyckoff_candidate_ranking.rank_wyckoff_candidates", _rank
    )
    def profile(extension):
        return SimpleNamespace(
            quality=ProfileQuality.FULL,
            data_granularity=DataGranularity.MINUTE_1M,
            fallback_used=False,
            extension_context=extension,
            position_context=PositionState.ABOVE_VAH,
            acceptance_context="ACCEPTANCE_D",
        )
    monkeypatch.setattr(
        "app.services.volume_profile.VolumeProfileService.prepare_batch_context",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "app.services.volume_profile.VolumeProfileService.build_batch",
        lambda _self, _context, *, symbols, mode: {
            symbol: {
                "vp20": profile(ExtensionState.EXTREME if symbol == "000001.SZ" else ExtensionState.NORMAL),
                "vp60": profile(ExtensionState.NORMAL),
            }
            for symbol in symbols
        },
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
        repo=object(),
    )
    strategy = type("Strategy", (), {"wyckoff_config": FunnelConfig()})()

    result = StrategyEngine(strategy_dirs=[])._run_wyckoff_funnel(
        "wyckoff_funnel", strategy, context, started_at=0.0
    )

    assert all("wyckoff_snapshot" not in row for row in result.rows)
    evidence_snapshot = result.evidence["wyckoff_snapshot"]
    expected_snapshot = snapshot.to_snapshot()
    expected_snapshot["l3_grouping"] = {
        "kind": "industry",
        "level": 1,
        "source": "current_enriched_industry",
    }
    assert {key: value for key, value in evidence_snapshot.items() if key != "v2"} == expected_snapshot
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
    assert result.rows[0]["wyckoff_range_start"] == "2026-05-01"
    assert result.rows[0]["wyckoff_range_confirmed_at"] == "2026-07-20"
    assert result.rows[1]["czsc_buy_types"] == []
    assert result.rows[1]["czsc_confirmation_time"] is None
    assert result.rows[0]["czsc_event_identity_version"] == 2
    assert result.rows[1]["czsc_event_identity_version"] == 2
    assert result.rows[0]["opportunity_rank"] == 1
    assert result.rows[0]["vp_risk_bucket"] == "EXTREME"
    assert result.rows[0]["timing_status"] is None
    assert result.evidence["all_wyckoff_candidate_count"] == 2
    assert result.evidence["wyckoff_research_trigger_count"] == 0
    assert result.evidence["wyckoff_research_trigger_affects_formal_selection"] is False
    assert result.evidence["risk_distribution"] == {
        "EXTREME": 1,
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 1,
        "UNKNOWN": 0,
    }
    assert result.rows[0]["research_context_score"] == 80.0
    assert result.rows[1]["research_context_score"] == 79.0
    assert [row["symbol"] for row in result.rows] == ["000001.SZ", "000002.SZ"]
    assert result.rows[0]["research_context_rank"] == 1
    assert result.rows[1]["research_context_rank"] == 2
    assert result.rows[0]["research_context_level"] == "NEUTRAL_STATE"
    assert result.rows[0]["candidate_order"] == 1
    assert result.rows[1]["candidate_order"] == 2
    assert "final_rank_score" not in result.rows[0]
    assert ranking_calls[0][0] == history["date"][0]
    assert result.scores == {}
    assert result.evidence["wyckoff_snapshot"]["v2"]["affects_formal_selection"] is False


def test_engine_applies_saved_board_filter_after_full_market_wyckoff_funnel(monkeypatch) -> None:
    snapshot = FunnelResult(
        layer1_symbols=["600000.SH", "300001.SZ"],
        layer2_symbols=["600000.SH", "300001.SZ"],
        layer3_symbols=["600000.SH", "300001.SZ"],
        top_sectors=[],
        channel_map={},
        pre_ignition_symbols=[],
        triggers={},
        stage_map={},
        trading_ranges={},
    )
    funnel_symbols: list[str] = []

    def _run_funnel(symbols, *_args, **_kwargs):
        funnel_symbols.extend(symbols)
        return snapshot

    monkeypatch.setattr("app.wyckoff.funnel.run_funnel", _run_funnel)
    monkeypatch.setattr(
        "app.services.wyckoff_candidate_ranking.rank_wyckoff_candidates",
        lambda _repo, *, as_of, candidates: [
            {**candidate, "strength_score": 80.0, "final_rank_score": 80.0, "rank": 1}
            for candidate in candidates
        ],
    )
    monkeypatch.setattr(
        "app.services.volume_profile.VolumeProfileService.prepare_batch_context",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "app.services.volume_profile.VolumeProfileService.build_batch",
        lambda *_args, **_kwargs: {},
    )
    history = pl.DataFrame({
        "symbol": ["600000.SH", "300001.SZ"],
        "date": ["2026-07-20", "2026-07-20"],
        "open": [10.0, 10.0], "high": [11.0, 11.0], "low": [9.0, 9.0],
        "close": [10.0, 10.0], "volume": [1.0, 1.0], "amount": [1.0, 1.0],
    }).with_columns(pl.col("date").str.to_date())
    context = StrategyDataContext(
        asset_type="stock",
        timeframe="1d",
        as_of=history["date"][0],
        history=history,
        current=pl.DataFrame({
            "symbol": ["600000.SH", "300001.SZ"],
            "close": [10.0, 10.0],
            "amount": [1.0, 1.0],
        }),
        market={"wyckoff_benchmark": history.drop("symbol")},
        repo=object(),
    )
    strategy = type(
        "Strategy",
        (),
        {"wyckoff_config": FunnelConfig(), "basic_filter": {}},
    )()

    result = StrategyEngine(strategy_dirs=[])._run_wyckoff_funnel(
        "wyckoff_funnel",
        strategy,
        context,
        overrides={"basic_filter": {"enabled": True, "boards": ["沪主板"]}},
        started_at=0.0,
    )

    # The full universe still reaches Wyckoff, so cross-sectional strength is
    # unchanged; the saved board selection only gates visible L3 candidates.
    assert funnel_symbols == ["600000.SH", "300001.SZ"]
    assert [row["symbol"] for row in result.rows] == ["600000.SH"]
    assert result.evidence["all_wyckoff_candidate_count"] == 2
    assert result.evidence["basic_filter_candidate_count"] == 1
    assert result.evidence["basic_filter_applied"] is True
