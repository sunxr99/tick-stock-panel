from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.services import relative_strength


class _Repo:
    def __init__(self, stocks: pl.DataFrame) -> None:
        self._enriched_history_cache = stocks
        self._stocks = stocks

    def get_enriched_range(self, start, end, columns=None):
        frame = self._stocks.filter(pl.col("date").is_between(start, end))
        return frame.select(columns) if columns else frame


def _frames(days: int = 65) -> tuple[pl.DataFrame, list[date]]:
    dates = [date(2026, 1, 2) + timedelta(days=index) for index in range(days)]
    daily_returns = {
        "AAA.SH": 0.03,
        "AAB.SH": 0.02,
        "BBB.SH": 0.015,
        "BBC.SH": -0.01,
    }
    rows = [
        {"symbol": symbol, "date": current_date, "change_pct": change_pct}
        for current_date in dates
        for symbol, change_pct in daily_returns.items()
    ]
    return pl.DataFrame(rows), dates


def _mapping() -> pl.DataFrame:
    return pl.DataFrame({
        "_sym_up": ["AAA.SH", "AAB.SH", "BBB.SH", "BBC.SH"],
        "concept": ["Alpha", "Alpha", "Beta", "Beta"],
    })


def _build(monkeypatch, stocks: pl.DataFrame, sector_ids=("concept:all:Alpha", "concept:all:Beta")):
    monkeypatch.setattr(relative_strength, "_load_concept_map_df", lambda *_args: (_mapping(), 2))
    return relative_strength.build_relative_strength(
        _Repo(stocks), sector_ids=sector_ids, as_of=stocks["date"].max()
    )


def _by_context(results):
    return {(result.symbol, result.sector_id): result for result in results}


def test_stock_vs_market_sector_and_rank_are_explainable(monkeypatch) -> None:
    stocks, dates = _frames()
    by_context = _by_context(_build(monkeypatch, stocks))
    aaa = by_context[("AAA.SH", "concept:all:Alpha")]
    bbb = by_context[("BBB.SH", "concept:all:Beta")]

    market_daily = (0.03 + 0.02 + 0.015 - 0.01) / 4
    assert aaa.stock_return_3d == pytest.approx((1.03**3) - 1)
    assert aaa.vs_market_3d == pytest.approx((1.03**3) - (1 + market_daily) ** 3)
    assert aaa.vs_sector_3d == pytest.approx((1.03**3) - (1.025**3))
    assert aaa.market_rank == 1
    assert aaa.market_percentile == 100.0
    assert aaa.sector_rank == 1
    assert aaa.sector_percentile == 100.0
    assert aaa.market_rs_score is not None
    assert aaa.sector_rs_score is not None
    assert aaa.rs_score is not None
    assert bbb.market_percentile < aaa.market_percentile
    assert bbb.sector_percentile == 100.0
    assert aaa.rs_score > bbb.rs_score
    assert aaa.as_of == dates[-1]
    assert aaa.benchmark_id == "all_stock_equal_weight"


def test_rank_percentile_ties_are_preserved(monkeypatch) -> None:
    stocks, _ = _frames()
    stocks = stocks.with_columns(
        pl.when(pl.col("symbol").is_in(["BBB.SH", "BBC.SH"]))
        .then(pl.lit(0.005))
        .otherwise(pl.col("change_pct"))
        .alias("change_pct")
    )
    by_context = _by_context(_build(monkeypatch, stocks))
    bbb = by_context[("BBB.SH", "concept:all:Beta")]
    bbc = by_context[("BBC.SH", "concept:all:Beta")]

    assert bbb.sector_rs_score == bbc.sector_rs_score
    assert bbb.sector_percentile == bbc.sector_percentile == 50.0
    assert {bbb.sector_rank, bbc.sector_rank} == {1, 2}


def test_multi_concept_membership_emits_each_context(monkeypatch) -> None:
    stocks, _ = _frames()
    mapping = _mapping().vstack(pl.DataFrame({
        "_sym_up": ["AAA.SH", "AAB.SH"],
        "concept": ["Gamma", "Gamma"],
    }))
    monkeypatch.setattr(relative_strength, "_load_concept_map_df", lambda *_args: (mapping, 3))

    results = relative_strength.build_relative_strength(
        _Repo(stocks),
        sector_ids=("concept:all:Alpha", "concept:all:Gamma"),
        as_of=stocks["date"].max(),
    )
    aaa = [result for result in results if result.symbol == "AAA.SH"]

    assert [result.sector_id for result in aaa] == ["concept:all:Alpha", "concept:all:Gamma"]
    assert all(result.sector_ids == ("concept:all:Alpha", "concept:all:Gamma") for result in aaa)
    assert all(result.membership_as_of is None for result in aaa)
    assert all(result.data_quality["membership_source"] == "current_ext_snapshot" for result in aaa)


def test_industry_uses_requested_stable_level(monkeypatch) -> None:
    stocks, _ = _frames()
    mapping = _mapping().rename({"concept": "industry"}).with_columns(
        pl.lit("Tech-Software-Apps").alias("industry")
    )
    monkeypatch.setattr(relative_strength, "_load_concept_map_df", lambda *_args: (mapping, 1))

    results = relative_strength.build_relative_strength(
        _Repo(stocks), sector_ids=("industry:1:Tech",), as_of=stocks["date"].max()
    )

    assert results
    assert {result.sector_id for result in results} == {"industry:1:Tech"}
    assert {result.sector_level for result in results} == {1}


def test_industry_code_is_the_rs_key_while_name_is_display_only(monkeypatch) -> None:
    stocks, _ = _frames()
    mapping = _mapping().rename({"concept": "industry"}).with_columns(
        pl.lit("电子-半导体-半导体设备").alias("industry"),
        pl.lit("801081.SI").alias("sw2_code"),
        pl.lit("半导体").alias("sw2_name"),
    )
    monkeypatch.setattr(relative_strength, "_load_concept_map_df", lambda *_args: (mapping, 1))

    results = relative_strength.build_relative_strength(
        _Repo(stocks),
        sector_ids=("industry:2:801081.SI",),
        as_of=stocks["date"].max(),
        _strict_industry_level=True,
    )

    assert results
    assert {result.sector_id for result in results} == {"industry:2:801081.SI"}
    assert {result.sector_name for result in results} == {"半导体"}


def test_new_stock_and_suspension_do_not_backfill_missing_sessions(monkeypatch) -> None:
    stocks, dates = _frames()
    new_stock = stocks.filter(~((pl.col("symbol") == "AAA.SH") & (pl.col("date") < dates[-10])))
    by_context = _by_context(_build(monkeypatch, new_stock))
    aaa = by_context[("AAA.SH", "concept:all:Alpha")]
    assert aaa.stock_return_60d is None
    assert aaa.rs_score is None
    assert "stock_history_incomplete_or_missing_trading_dates" in aaa.unavailable_reason
    assert aaa.rs_state is None
    assert aaa.data_quality["state_status"] == "partial"
    assert "rs_score" in aaa.data_quality["state_missing_components"]

    suspended = stocks.filter(~((pl.col("symbol") == "AAA.SH") & (pl.col("date") == dates[-2])))
    by_context = _by_context(_build(monkeypatch, suspended))
    halted = by_context[("AAA.SH", "concept:all:Alpha")]
    assert halted.stock_return_3d is None
    assert halted.vs_market_3d is None
    assert "3d" in halted.data_quality["missing_stock_return_windows"]

    nan_return = stocks.with_columns(
        pl.when((pl.col("symbol") == "AAA.SH") & (pl.col("date") == dates[-2]))
        .then(pl.lit(float("nan")))
        .otherwise(pl.col("change_pct"))
        .alias("change_pct")
    )
    by_context = _by_context(_build(monkeypatch, nan_return))
    assert by_context[("AAA.SH", "concept:all:Alpha")].stock_return_3d is None


def test_insufficient_benchmark_and_small_sector_are_explicit(monkeypatch) -> None:
    stocks, dates = _frames()
    insufficient = stocks.with_columns(
        pl.when((pl.col("date") == dates[-2]) & (pl.col("symbol") != "AAA.SH"))
        .then(pl.lit(None))
        .otherwise(pl.col("change_pct"))
        .alias("change_pct")
    )
    by_context = _by_context(_build(monkeypatch, insufficient))
    aaa = by_context[("AAA.SH", "concept:all:Alpha")]
    assert aaa.vs_market_3d is None
    assert aaa.market_rs_score is None
    assert "benchmark_unavailable_or_insufficient_sample" in aaa.unavailable_reason

    mapping = _mapping().filter(pl.col("_sym_up") == "AAA.SH")
    monkeypatch.setattr(relative_strength, "_load_concept_map_df", lambda *_args: (mapping, 1))
    result = relative_strength.build_relative_strength(
        _Repo(stocks), sector_ids=("concept:all:Alpha",), as_of=dates[-1]
    )[0]
    assert result.sector_rank is None
    assert result.rs_score is None
    assert "sector_member_count_below_minimum" in result.unavailable_reason


def test_no_future_data_and_strict_sector_strength_date_alignment(monkeypatch) -> None:
    stocks, dates = _frames()
    monkeypatch.setattr(relative_strength, "_load_concept_map_df", lambda *_args: (_mapping(), 2))
    baseline = _by_context(
        relative_strength.build_relative_strength(
            _Repo(stocks),
            sector_ids=("concept:all:Alpha", "concept:all:Beta"),
            as_of=dates[-2],
        )
    )
    future_changed = stocks.with_columns(
        pl.when((pl.col("symbol") == "BBB.SH") & (pl.col("date") == dates[-1]))
        .then(pl.lit(0.99))
        .otherwise(pl.col("change_pct"))
        .alias("change_pct")
    )
    replay = _by_context(
        relative_strength.build_relative_strength(
            _Repo(future_changed),
            sector_ids=("concept:all:Alpha", "concept:all:Beta"),
            as_of=dates[-2],
        )
    )

    assert replay[("AAA.SH", "concept:all:Alpha")].rs_score == baseline[("AAA.SH", "concept:all:Alpha")].rs_score
    assert replay[("BBB.SH", "concept:all:Beta")].market_rank == baseline[("BBB.SH", "concept:all:Beta")].market_rank
    assert replay[("AAA.SH", "concept:all:Alpha")].rs_change_3d == baseline[("AAA.SH", "concept:all:Alpha")].rs_change_3d
    assert replay[("BBB.SH", "concept:all:Beta")].rs_extension_score == baseline[("BBB.SH", "concept:all:Beta")].rs_extension_score
    assert relative_strength.build_relative_strength(
        _Repo(stocks),
        sector_ids=("concept:all:Alpha",),
        as_of=dates[-1] + timedelta(days=1),
    ) == []


def test_missing_selected_membership_fails_closed(monkeypatch) -> None:
    stocks, _ = _frames()
    monkeypatch.setattr(
        relative_strength,
        "_load_concept_map_df",
        lambda *_args: (pl.DataFrame(schema={"_sym_up": pl.Utf8, "concept": pl.Utf8}), 0),
    )

    assert relative_strength.build_relative_strength(
        _Repo(stocks), sector_ids=("concept:all:Missing",), as_of=stocks["date"].max()
    ) == []
