from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.services import rps_rotation
from app.services.sector_membership import canonicalize_member_map


class _Repo:
    def __init__(self, stocks: pl.DataFrame, benchmark: pl.DataFrame) -> None:
        self._enriched_history_cache = stocks
        self._stocks = stocks
        self._benchmark = benchmark

    def get_enriched_range(self, start, end, columns=None):
        frame = self._stocks.filter(pl.col("date").is_between(start, end))
        return frame.select(columns) if columns else frame

    def get_index_daily(self, _symbol, start, end, columns=None):
        frame = self._benchmark.filter(pl.col("date").is_between(start, end))
        return frame.select(columns) if columns else frame


def _frames(days: int = 30) -> tuple[pl.DataFrame, pl.DataFrame, list[date]]:
    dates = [date(2026, 1, 2) + timedelta(days=index) for index in range(days)]
    stocks: list[dict] = []
    for current_date in dates:
        stocks.extend([
            {"symbol": "AAA.SH", "date": current_date, "change_pct": 0.02},
            {"symbol": "AAB.SH", "date": current_date, "change_pct": 0.02},
            {"symbol": "BBB.SH", "date": current_date, "change_pct": 0.01},
            {"symbol": "BBC.SH", "date": current_date, "change_pct": 0.01},
        ])
    benchmark = pl.DataFrame([
        {"date": current_date, "change_pct": 0.005} for current_date in dates
    ])
    return pl.DataFrame(stocks), benchmark, dates


def _mapping() -> pl.DataFrame:
    return pl.DataFrame({
        "_sym_up": ["AAA.SH", "AAB.SH", "BBB.SH", "BBC.SH"],
        "concept": ["Alpha", "Alpha", "Beta", "Beta"],
    })


def test_canonical_member_map_does_not_double_count_bare_and_qualified_keys() -> None:
    member_map = canonicalize_member_map(pl.DataFrame({
        "_sym_up": ["600000", "600000.SH", "000001", "000001.SZ", "920122", "920122.BJ"],
        "industry": ["Bank", "Bank", "Bank", "Bank", "Broker", "Broker"],
    }), "industry")

    assert member_map.to_dicts() == [
        {"_sym_up": "000001.SZ", "industry": "Bank"},
        {"_sym_up": "600000.SH", "industry": "Bank"},
        {"_sym_up": "920122.BJ", "industry": "Broker"},
    ]


def test_industry_sparse_gate_excludes_groups_before_sector_ranking(monkeypatch) -> None:
    stocks, benchmark, dates = _frames()
    mapping = pl.DataFrame({
        "_sym_up": ["AAA.SH", "AAB.SH", "BBB.SH", "BBC.SH"],
        "industry": ["电子-半导体-设备"] * 3 + ["电子-软件-应用"],
        "sw2_code": ["801081.SI"] * 3 + ["801082.SI"],
        "sw2_name": ["半导体"] * 3 + ["软件"],
    })
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args: (mapping, 2))

    results = rps_rotation.build_sector_strength(
        _Repo(stocks, benchmark),
        kind="industry",
        level=2,
        as_of=dates[-1],
        _strict_industry_level=True,
        _min_industry_members=2,
    )

    assert [(result.sector_id, result.name, result.member_count) for result in results] == [
        ("industry:2:801081.SI", "半导体", 3)
    ]


def test_sector_strength_compounds_returns_and_exposes_ranking_components(monkeypatch) -> None:
    stocks, benchmark, dates = _frames()
    repo = _Repo(stocks, benchmark)
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args: (_mapping(), 2))

    results = rps_rotation.build_sector_strength(repo, as_of=dates[-1])
    by_name = {result.name: result for result in results}
    alpha = by_name["Alpha"]
    beta = by_name["Beta"]

    assert alpha.return_3d == pytest.approx((1.02**3) - 1)
    assert alpha.relative_return_3d == pytest.approx((1.02**3) - (1.015**3))
    assert alpha.return_20d == pytest.approx((1.02**20) - 1)
    assert alpha.up_ratio == 1.0
    assert alpha.strong_stock_ratio == 0.0
    assert alpha.rank == 1
    assert alpha.percentile == 100.0
    assert beta.rank == 2
    assert beta.percentile == 0.0
    assert alpha.rank_change_1d == 0
    assert alpha.rank_change_3d == 0
    assert alpha.persistence_days > 0
    assert alpha.persistence_score == pytest.approx(min(alpha.persistence_days, 20) * 5)
    assert alpha.rank_std_5d == 0.0
    assert alpha.coverage_ratio == 1.0
    assert alpha.data_quality["status"] == "complete"
    assert alpha.data_quality["rank_basis"] == "sector_strength_score"
    assert alpha.data_quality["benchmark_id"] == "all_stock_equal_weight"
    assert alpha.score is not None and beta.score is not None and alpha.score > beta.score


def test_sector_strength_requires_exact_historical_trading_date_alignment(monkeypatch) -> None:
    stocks, benchmark, dates = _frames()
    # Alpha traded on the as-of date but missed the second day of the latest
    # 3-day window.  The implementation must not substitute an older return.
    stocks = stocks.filter(~((pl.col("symbol") == "AAA.SH") & (pl.col("date") == dates[-2])))
    stocks = stocks.filter(~((pl.col("symbol") == "AAB.SH") & (pl.col("date") == dates[-2])))
    repo = _Repo(stocks, benchmark)
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args: (_mapping(), 2))

    results = rps_rotation.build_sector_strength(repo, as_of=dates[-1])
    by_name = {result.name: result for result in results}

    assert by_name["Alpha"].return_3d is None
    assert by_name["Alpha"].relative_return_3d is None
    assert "3d" in by_name["Alpha"].data_quality["missing_return_windows"]
    assert by_name["Beta"].return_3d == pytest.approx((1.01**3) - 1)


def test_sector_strength_rank_change_uses_the_exact_prior_trading_date(monkeypatch) -> None:
    stocks, benchmark, dates = _frames()
    # Beta leads through t-3, then weakens enough to be overtaken.  This makes
    # the three-day rank movement observable without changing the date grid.
    stocks = stocks.with_columns(
        pl.when((pl.col("symbol").is_in(["BBB.SH", "BBC.SH"])) & (pl.col("date") < dates[-3]))
        .then(pl.lit(0.04))
        .when(pl.col("symbol").is_in(["BBB.SH", "BBC.SH"]))
        .then(pl.lit(-0.20))
        .otherwise(pl.col("change_pct"))
        .alias("change_pct")
    )
    repo = _Repo(stocks, benchmark)
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args: (_mapping(), 2))

    by_name = {
        result.name: result
        for result in rps_rotation.build_sector_strength(repo, as_of=dates[-1])
    }

    assert by_name["Alpha"].rank == 1
    assert by_name["Beta"].rank == 2
    assert by_name["Alpha"].rank_change_3d == 1
    assert by_name["Beta"].rank_change_3d == -1


def test_sector_strength_score_favors_recent_broad_strength(monkeypatch) -> None:
    stocks, benchmark, dates = _frames()
    stocks = stocks.with_columns(
        pl.when(pl.col("symbol").is_in(["AAA.SH", "AAB.SH"]))
        .then(pl.when(pl.col("date") < dates[-5]).then(pl.lit(0.04)).otherwise(pl.lit(-0.01)))
        .otherwise(
            pl.when(pl.col("date") < dates[-5]).then(pl.lit(0.005)).otherwise(pl.lit(0.05))
        )
        .alias("change_pct")
    )
    repo = _Repo(stocks, benchmark)
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args: (_mapping(), 2))

    by_name = {
        result.name: result
        for result in rps_rotation.build_sector_strength(repo, as_of=dates[-1])
    }

    assert by_name["Alpha"].relative_return_20d > by_name["Beta"].relative_return_20d
    assert by_name["Beta"].relative_momentum_score > by_name["Alpha"].relative_momentum_score
    assert by_name["Beta"].breadth_score > by_name["Alpha"].breadth_score
    assert by_name["Beta"].score > by_name["Alpha"].score
    assert by_name["Beta"].rank == 1


def test_breadth_breaks_equal_momentum_tie(monkeypatch) -> None:
    stocks, benchmark, dates = _frames()
    stocks = stocks.with_columns(pl.lit(0.01).alias("change_pct")).with_columns(
        pl.when((pl.col("symbol") == "AAA.SH") & (pl.col("date") == dates[-1]))
        .then(pl.lit(0.04))
        .when((pl.col("symbol") == "AAB.SH") & (pl.col("date") == dates[-1]))
        .then(pl.lit(-0.02))
        .otherwise(pl.col("change_pct"))
        .alias("change_pct")
    )
    repo = _Repo(stocks, benchmark)
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args: (_mapping(), 2))

    by_name = {
        result.name: result
        for result in rps_rotation.build_sector_strength(repo, as_of=dates[-1])
    }

    assert by_name["Alpha"].relative_momentum_score == by_name["Beta"].relative_momentum_score
    assert by_name["Beta"].up_ratio > by_name["Alpha"].up_ratio
    assert by_name["Beta"].breadth_score > by_name["Alpha"].breadth_score
    assert by_name["Beta"].score > by_name["Alpha"].score


def test_all_stock_benchmark_omits_missing_dates_without_forward_fill() -> None:
    first = date(2026, 1, 2)
    missing = date(2026, 1, 3)
    daily, counts = rps_rotation._market_daily_returns(pl.DataFrame({
        "date": [first, missing],
        "change_pct": [0.01, None],
    }))

    assert daily == {first: 0.01}
    assert counts == {first: 1}
    assert rps_rotation._window_return(daily, [first, missing], 1, 2) is None


def test_sector_strength_marks_missing_all_stock_benchmark(monkeypatch) -> None:
    stocks, benchmark, dates = _frames()
    stocks = stocks.with_columns(
        pl.when(pl.col("date") == dates[-2])
        .then(pl.lit(None))
        .otherwise(pl.col("change_pct"))
        .alias("change_pct")
    )
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args: (_mapping(), 2))

    results = rps_rotation.build_sector_strength(_Repo(stocks, benchmark), as_of=dates[-1])

    assert results
    assert all(result.relative_return_3d is None for result in results)
    assert all(result.data_quality["benchmark_available"] is False for result in results)
    assert all("3d" in result.data_quality["missing_return_windows"] for result in results)


def test_sector_strength_does_not_use_future_returns(monkeypatch) -> None:
    stocks, benchmark, dates = _frames()
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args: (_mapping(), 2))
    baseline = {
        result.name: result
        for result in rps_rotation.build_sector_strength(_Repo(stocks, benchmark), as_of=dates[-2])
    }
    future_changed = stocks.with_columns(
        pl.when((pl.col("symbol") == "BBB.SH") & (pl.col("date") == dates[-1]))
        .then(pl.lit(0.99))
        .otherwise(pl.col("change_pct"))
        .alias("change_pct")
    )
    replay = {
        result.name: result
        for result in rps_rotation.build_sector_strength(_Repo(future_changed, benchmark), as_of=dates[-2])
    }

    assert replay["Alpha"].score == baseline["Alpha"].score
    assert replay["Beta"].rank == baseline["Beta"].rank
    assert replay["Alpha"].score_change_3d == baseline["Alpha"].score_change_3d
    assert replay["Beta"].up_ratio_change_3d == baseline["Beta"].up_ratio_change_3d
