from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from scripts.run_wyckoff_top20_backtest import (
    _append_cohorts,
    _attach_forward_returns,
    _state_distribution,
    _summary,
)


def test_forward_return_uses_next_session_open_and_horizon_close() -> None:
    dates = [date(2026, 1, 2) + timedelta(days=index) for index in range(5)]
    signals = pl.DataFrame({
        "signal_date": [dates[0]],
        "symbol": ["AAA.SH"],
        "research_context_rank": [1],
        "research_context_score": [90.0],
    })
    prices = pl.DataFrame({
        "symbol": ["AAA.SH"] * len(dates),
        "date": dates,
        "open": [10.0, 11.0, 12.0, 13.0, 14.0],
        "high": [11.0, 12.0, 13.0, 14.0, 15.0],
        "low": [9.0, 10.0, 11.0, 12.0, 13.0],
        "close": [10.5, 11.5, 12.5, 13.5, 14.5],
    })

    result = _attach_forward_returns(signals, prices, dates)

    assert result["return_1d"][0] == (11.5 / 11.0) - 1.0
    assert result["return_3d"][0] == (13.5 / 11.0) - 1.0
    assert result["mae_3d"][0] == (10.0 / 11.0) - 1.0
    assert result["mfe_3d"][0] == (14.0 / 11.0) - 1.0


def test_forward_return_includes_same_window_benchmark_and_excess() -> None:
    dates = [date(2026, 1, 2) + timedelta(days=index) for index in range(5)]
    signals = pl.DataFrame({
        "signal_date": [dates[0]],
        "symbol": ["AAA.SH"],
    })
    prices = pl.DataFrame({
        "symbol": ["AAA.SH"] * len(dates),
        "date": dates,
        "open": [10.0, 11.0, 12.0, 13.0, 14.0],
        "high": [11.0, 12.0, 13.0, 14.0, 15.0],
        "low": [9.0, 10.0, 11.0, 12.0, 13.0],
        "close": [10.5, 11.5, 12.5, 13.5, 14.5],
    })
    benchmark = pl.DataFrame({
        "date": dates,
        "open": [100.0, 100.0, 100.0, 100.0, 100.0],
        "close": [100.0, 101.0, 102.0, 103.0, 104.0],
    })

    result = _attach_forward_returns(signals, prices, dates, benchmark)

    expected_stock = (11.5 / 11.0) - 1.0
    expected_benchmark = (101.0 / 100.0) - 1.0
    assert result["return_1d"][0] == expected_stock
    assert result["benchmark_return_1d"][0] == expected_benchmark
    assert result["excess_return_1d"][0] == expected_stock - expected_benchmark


def test_summary_reports_mean_median_positive_rate_and_profit_factor() -> None:
    result = _summary(pl.Series("return_1d", [0.1, -0.05, 0.0]))

    assert result["n"] == 3
    assert result["mean"] == 0.05 / 3
    assert result["median"] == 0.0
    assert result["positive_rate"] == 1 / 3
    assert result["profit_factor"] == 2.0


def test_cohorts_include_all_top_and_bottom_ranked_rows() -> None:
    ranked = [
        {
            "symbol": f"{index:06d}.SZ",
            "rank": index,
            "final_rank_score": float(100 - index),
            "sector_context": {"sector_id": "industry:1:bank", "name": "银行"},
        }
        for index in range(1, 26)
    ]
    rows: list[dict[str, object]] = []

    _append_cohorts(rows=rows, as_of=date(2024, 1, 2), ranked=ranked)

    top = [row for row in rows if row["cohort"] == "TOP20"]
    all_rows = [row for row in rows if row["cohort"] == "ALL_WYCKOFF"]
    bottom = [row for row in rows if row["cohort"] == "BOTTOM20"]
    assert len(top) == 20
    assert len(all_rows) == 25
    assert len(bottom) == 20
    assert top[0]["symbol"] == "000001.SZ"
    assert bottom[0]["symbol"] == "000006.SZ"
    assert top[0]["industry_name"] == "银行"


def test_state_distribution_keeps_unclassified_records_in_denominator() -> None:
    frame = pl.DataFrame({"phase": ["LEADING", None, "UNMATCHED"]})

    result = _state_distribution(frame, "phase", ("LEADING", "FADING"))

    assert result["n"] == 3
    assert result["counts"] == {"LEADING": 1, "FADING": 0, "UNCLASSIFIED": 2}
    assert result["percentages"]["UNCLASSIFIED"] == 2 / 3
