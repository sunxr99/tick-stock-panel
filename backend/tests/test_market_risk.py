"""大盘风险 V1: 口径、可用性与按日期覆盖持久化。"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import market_risk as market_risk_api
from app.services import market_risk


def _write_market_data(root, days: int = 260) -> list[date]:
    dates = [date(2025, 1, 1) + timedelta(days=index) for index in range(days)]
    for index, current in enumerate(dates):
        # A 连续上涨、B 连续下跌; 最后一日应各有一个 250 日新高/新低。
        stocks = pl.DataFrame({
            "symbol": ["A.SH", "B.SZ"],
            "date": [current, current],
            "open": [100.0 + index, 500.0 - index],
            "high": [101.0 + index, 501.0 - index],
            "low": [99.0 + index, 499.0 - index],
            "close": [100.0 + index, 500.0 - index],
            "volume": [10.0, 10.0],
            "amount": [100.0, 300.0],
        })
        stock_path = root / "kline_daily" / f"date={current.isoformat()}" / "part.parquet"
        stock_path.parent.mkdir(parents=True, exist_ok=True)
        stocks.write_parquet(stock_path)
        indices = pl.DataFrame({
            "symbol": ["000985.SH", "000300.SH"],
            "date": [current, current],
            "open": [3000.0 + index, 4000.0 + index],
            "high": [3001.0 + index, 4001.0 + index],
            "low": [2999.0 + index, 3999.0 + index],
            "close": [3000.0 + index, 4000.0 + index],
            "volume": [1.0, 1.0],
            "amount": [1.0, 1.0],
        })
        index_path = root / "kline_index_daily" / f"date={current.isoformat()}" / "part.parquet"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        indices.write_parquet(index_path)
    return dates


def test_build_market_risk_uses_active_stock_denominators_and_windows(tmp_path):
    dates = _write_market_data(tmp_path)
    row = market_risk.build_market_risk_rows(tmp_path, dates[-3], dates[-1]).row(-1, named=True)

    assert row["price_basis"] == "raw_unadjusted"
    assert row["active_stock_count"] == 2
    assert row["ma20_valid_count"] == 2
    assert row["ma50_valid_count"] == 2
    assert row["ma20_above_count"] == 1
    assert row["ma50_above_count"] == 1
    assert row["up_count"] == 1
    assert row["down_count"] == 1
    assert row["flat_count"] == 0
    assert row["down_amount_share"] == 0.75
    assert row["new_high_250_count"] == 1
    assert row["new_low_250_count"] == 1
    assert row["csi_all_available"] is True
    assert row["csi300_available"] is True
    assert row["csi_all_above_ma20"] is True
    assert row["csi300_atr14_close_ratio"] is not None
    assert row["availability"] == "available"
    assert row["risk_level"] == "watch"
    assert row["risk_signal_categories"] == ["卖压"]
    assert row["market_phase"] == "uptrend_healthy"
    assert row["top_warning_level"] == "low"
    assert row["market_strength_trend_score"] == 100.0
    assert row["market_strength_breadth_score"] == 50.0
    assert row["market_strength_participation_score"] == 37.5
    assert row["market_strength_new_high_low_score"] == 50.0
    assert row["market_amount"] == 400.0
    assert row["market_amount_ma5"] == 400.0
    assert row["market_amount_ma20"] == 400.0
    assert row["market_amount_ratio_20"] == 1.0
    assert row["market_amount_ma5_ratio_20"] == 1.0
    assert row["market_strength_volume_score"] == 50.0
    assert row["market_strength_score"] == 62.5


def test_short_history_is_marked_partial_not_neutral(tmp_path):
    dates = _write_market_data(tmp_path, days=30)
    row = market_risk.build_market_risk_rows(tmp_path, dates[-1], dates[-1]).row(0, named=True)

    assert row["new_high_low_250_valid_count"] == 0
    assert row["csi_all_available"] is False
    assert row["availability"] == "partial"
    assert row["risk_state"] == "insufficient_data"
    assert row["data_warnings"]
    assert row["risk_level"] == "unavailable"
    assert row["market_phase"] == "insufficient_data"
    assert row["top_warning_level"] == "unavailable"
    assert row["market_strength_score"] is None


def test_ma60_break_without_active_capitulation_is_not_automatically_high_risk(tmp_path):
    dates = _write_market_data(tmp_path)
    base = market_risk.build_market_risk_rows(tmp_path, dates[-1], dates[-1]).row(0, named=True)
    row = dict(base)
    row["csi_all_above_ma60"] = False
    row["csi300_above_ma60"] = False
    row = market_risk._annotate_risk_rows([row], pl.DataFrame())[0]

    assert row["risk_level"] == "elevated"
    assert "指数趋势" in row["risk_signal_categories"]
    assert row["market_phase"] == "weakening_confirmed"


def test_market_strength_volume_uses_recent_turnover_level_and_trend(tmp_path):
    dates = _write_market_data(tmp_path)
    base = market_risk.build_market_risk_rows(tmp_path, dates[-1], dates[-1]).row(0, named=True)
    low = market_risk._market_strength_components({
        **base,
        "market_amount_ratio_20": 0.70,
        "market_amount_ma5_ratio_20": 0.85,
    })
    high = market_risk._market_strength_components({
        **base,
        "market_amount_ratio_20": 1.30,
        "market_amount_ma5_ratio_20": 1.15,
    })

    assert low["volume"] == 0.0
    assert high["volume"] == 100.0
    assert high["score"] == low["score"] + 10.0


def test_active_capitulation_requires_short_term_breakdown_low_strength_and_internal_pressure(tmp_path):
    dates = _write_market_data(tmp_path)
    base = market_risk.build_market_risk_rows(tmp_path, dates[-1], dates[-1]).row(0, named=True)
    row = dict(base)
    row["csi_all_above_ma60"] = False
    row["csi300_above_ma60"] = False
    row["csi_all_above_ma20"] = False
    row["csi300_above_ma20"] = False
    row["csi_all_ma20_direction"] = "down"
    row["csi300_ma20_direction"] = "down"

    annotated = market_risk._annotate_risk_rows([row], pl.DataFrame())

    assert annotated[0]["market_strength_score"] < 35.0
    assert annotated[0]["risk_level"] == "high"


def test_top_warning_requires_persistent_internal_selling_while_index_is_strong(tmp_path):
    dates = _write_market_data(tmp_path)
    base = market_risk.build_market_risk_rows(tmp_path, dates[-1], dates[-1]).row(0, named=True)
    rows = []
    for index in range(3):
        row = dict(base)
        row["date"] = dates[-3 + index]
        row["up_count"] = 1
        row["down_count"] = 3
        row["down_amount_share"] = 0.6
        rows.append(row)

    annotated = market_risk._annotate_risk_rows(rows, pl.DataFrame())

    assert annotated[-1]["market_phase"] == "top_warning"
    assert annotated[-1]["top_warning_level"] == "watch"
    assert annotated[-1]["top_warning_categories"] == ["卖压连续占优"]


def test_recovery_candidate_requires_multiple_independent_improvements(tmp_path):
    dates = _write_market_data(tmp_path)
    base = market_risk.build_market_risk_rows(tmp_path, dates[-1], dates[-1]).row(0, named=True)
    rows = []
    for index, breadth in enumerate((0.2, 0.3, 0.4)):
        row = dict(base)
        row["date"] = dates[-3 + index]
        row["ma50_above_pct"] = breadth
        row["up_count"] = 3
        row["down_count"] = 1
        row["down_amount_share"] = 0.4
        row["csi_all_above_ma60"] = False
        row["csi300_above_ma60"] = False
        row["csi_all_above_ma20"] = True
        row["csi_all_ma20_direction"] = "up"
        row["csi300_above_ma20"] = True
        row["csi300_ma20_direction"] = "up"
        rows.append(row)

    annotated = market_risk._annotate_risk_rows(rows, pl.DataFrame())

    assert annotated[-1]["market_phase"] == "weakening_confirmed"
    assert annotated[-1]["recovery_candidate"] == "candidate"
    assert annotated[-1]["recovery_categories"] == ["广度连续修复", "买盘重新占优", "中证全指短期趋势修复"]


def test_low_level_consolidation_deescalates_high_risk_only_after_multiple_improvements(tmp_path):
    dates = _write_market_data(tmp_path)
    base = market_risk.build_market_risk_rows(tmp_path, dates[-1], dates[-1]).row(0, named=True)
    rows = []
    for index in range(6):
        row = dict(base)
        row["date"] = dates[-6 + index]
        row["csi_all_above_ma60"] = False
        row["csi300_above_ma60"] = False
        row["csi_all_above_ma20"] = True
        row["csi300_above_ma20"] = True
        row["csi_all_ma20_direction"] = "flat"
        row["csi300_ma20_direction"] = "flat"
        row["csi_all_position_60"] = 0.2
        row["csi300_position_60"] = 0.3
        row["ma20_above_pct"] = 0.2 + index * 0.05
        row["ma50_above_pct"] = 0.2 + index * 0.05
        row["up_count"] = 3
        row["down_count"] = 1
        row["down_amount_share"] = 0.4
        row["new_high_250_count"] = 2
        row["new_low_250_count"] = 8 - index
        row["csi_all_atr14_close_ratio"] = 0.03 - index * 0.001
        rows.append(row)

    annotated = market_risk._annotate_risk_rows(rows, pl.DataFrame())
    latest = annotated[-1]

    assert latest["market_phase"] == "low_level_consolidation"
    assert latest["risk_level"] == "elevated"
    assert {"指数短期止跌", "市场强度 5 日回升", "市场广度修复", "卖压缓解"}.issubset(latest["low_level_consolidation_categories"])


def test_upsert_replaces_same_trade_date(tmp_path):
    first = pl.DataFrame({"date": [date(2026, 1, 2)], "risk_state": ["neutral"], "risk_reasons": [[]]})
    second = pl.DataFrame({"date": [date(2026, 1, 2)], "risk_state": ["attention"], "risk_reasons": [["测试原因"]]})
    market_risk.upsert_market_risk_history(tmp_path, first)
    market_risk.upsert_market_risk_history(tmp_path, second)

    saved = market_risk.load_market_risk_history(tmp_path)
    assert saved.height == 1
    assert saved.row(0, named=True)["risk_state"] == "attention"
    assert saved.row(0, named=True)["risk_reasons"] == ["测试原因"]


def test_incremental_rebuilds_existing_history_when_methodology_changes(tmp_path):
    dates = _write_market_data(tmp_path)
    market_risk.upsert_market_risk_history(tmp_path, pl.DataFrame({
        "date": [dates[-2], dates[-1]],
        "risk_level": ["high", "high"],
        "market_phase": ["weakening_confirmed", "weakening_confirmed"],
        "market_strength_score": [10.0, 10.0],
        "low_level_consolidation_categories": [[], []],
        "methodology_version": ["market_risk_v1.4", "market_risk_v1.4"],
    }))

    rebuilt = market_risk.compute_market_risk_incremental(None, tmp_path, today=dates[-1])

    assert rebuilt.height == 2
    assert set(rebuilt.get_column("methodology_version")) == {market_risk.METHODOLOGY_VERSION}


def test_api_reads_persisted_snapshot_without_recomputation(tmp_path):
    market_risk.upsert_market_risk_history(tmp_path, pl.DataFrame({
        "date": [date(2026, 1, 2)],
        "risk_state": ["attention"],
        "availability": ["available"],
        "risk_reasons": [["下跌家数多于上涨家数"]],
    }))
    app = FastAPI()
    app.state.repo = type("Repo", (), {"store": type("Store", (), {"data_dir": tmp_path})()})()
    app.include_router(market_risk_api.router)
    client = TestClient(app)

    assert client.get("/api/market-risk/latest").json()["row"] == {
        "date": "2026-01-02",
        "risk_state": "attention",
        "availability": "available",
        "risk_reasons": ["下跌家数多于上涨家数"],
    }
    assert client.get("/api/market-risk/date/2026-01-03").json() == {"row": None}
