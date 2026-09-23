from __future__ import annotations

from datetime import date

import polars as pl

from scripts.run_wyckoff_strength_rolling_validation import (
    _assign_cohorts,
    _select_monthly_dates,
)


def test_monthly_selection_uses_month_end_and_evenly_downsamples() -> None:
    eligible = [date(2025, month, day) for month, day in ((1, 3), (1, 31), (2, 14), (2, 28), (3, 31), (4, 30))]

    assert _select_monthly_dates(eligible, max_dates=0) == [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30)]
    assert _select_monthly_dates(eligible, max_dates=2) == [date(2025, 1, 31), date(2025, 4, 30)]


def test_cohorts_keep_formal_pool_and_make_controls_deterministic() -> None:
    rows = [
        {"signal_date": date(2025, 1, 2), "symbol": f"000{i:03d}.SZ", "research_candidate_rank": i, "research_candidate_score": 100 - i}
        for i in range(1, 7)
    ]
    signals = pl.DataFrame(rows)

    first = _assign_cohorts(signals, cohort_size=2, seed=7)
    second = _assign_cohorts(signals, cohort_size=2, seed=7)

    assert first.filter(pl.col("cohort") == "formal_all").height == 6
    assert first.filter(pl.col("cohort") == "high_score").get_column("symbol").to_list() == ["000001.SZ", "000002.SZ"]
    assert first.filter(pl.col("cohort") == "low_score").get_column("symbol").to_list() == ["000005.SZ", "000006.SZ"]
    assert first.filter(pl.col("cohort") == "random_control").get_column("symbol").to_list() == second.filter(pl.col("cohort") == "random_control").get_column("symbol").to_list()
