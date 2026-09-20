from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest


def _module():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "wyckoff_current_random12",
            scripts_dir / "run_wyckoff_current_random12_backtest.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts_dir))


def test_select_dates_is_seeded_and_month_stratified() -> None:
    module = _module()
    eligible = [
        date(2025, 1, 2), date(2025, 1, 3),
        date(2025, 2, 5), date(2025, 2, 6),
        date(2025, 3, 3), date(2025, 3, 4),
    ]

    selected, metadata = module._select_dates(eligible=eligible, seed=7, sample_size=3)

    assert len(selected) == 3
    assert len({value.strftime("%Y-%m") for value in selected}) == 3
    assert metadata["selection_method"] == "one_fixed_seed_draw_per_selected_month"


def test_eligible_dates_requires_complete_forward_horizon() -> None:
    module = _module()
    dates = [date(2025, 1, day) for day in range(1, 23)]

    result = module._eligible_dates(trading_dates=dates, start=date(2025, 1, 1))

    # Jan 2 still has the complete Jan 3 through Jan 22 T+20 window.
    assert result[-1] == date(2025, 1, 2)


def test_eligible_dates_rejects_missing_benchmark_exit() -> None:
    module = _module()
    dates = [date(2025, 1, day) for day in range(1, 23)]

    result = module._eligible_dates(
        trading_dates=dates,
        start=date(2025, 1, 1),
        benchmark_dates={date(2025, 1, day) for day in range(2, 21)},
    )

    assert result == []


def test_report_separates_return_benchmark_and_excess() -> None:
    module = _module()
    signals = pl.DataFrame({
        "symbol": ["A", "B"],
        "signal_date": [date(2025, 1, 2), date(2025, 2, 3)],
        "return_1d": [0.02, -0.01],
        "benchmark_return_1d": [0.01, 0.01],
        "excess_return_1d": [0.01, -0.02],
        **{
            f"{prefix}_{horizon}d": [None, None]
            for horizon in (3, 5, 10, 20)
            for prefix in ("return", "benchmark_return", "excess_return")
        },
    })
    state = {
        "selection": {"seed": 1},
        "selected_signal_dates": ["2025-01-02", "2025-02-03"],
        "date_runs": {},
    }

    report = module._report(signals=signals, state=state, rows_path=Path("signals.parquet"))

    metric = report["horizons"]["T+1"]
    assert metric["return"]["mean"] == pytest.approx(0.005)
    assert metric["benchmark_return"]["mean"] == pytest.approx(0.01)
    assert metric["excess_return"]["mean"] == pytest.approx(-0.005)
    assert metric["equal_weight_by_signal_day"]["excess_return"]["n"] == 2


def test_signal_row_excludes_nested_ui_evidence() -> None:
    module = _module()

    row = module._signal_row(
        as_of=date(2025, 1, 2),
        row={
            "symbol": "000001.SZ",
            "candidate_order": 1,
            "wyckoff_v2_events": [],
            "sector_context": {},
        },
    )

    assert row == {
        "signal_date": date(2025, 1, 2),
        "symbol": "000001.SZ",
        "candidate_order": 1,
        "opportunity_score": None,
        "wyckoff_channel": None,
        "wyckoff_stage": None,
        "wyckoff_source": None,
        "wyckoff_l3_path": None,
        "vp_risk_bucket": None,
    }


def test_first_interrupted_parquet_write_is_safe_to_restart(tmp_path: Path) -> None:
    module = _module()
    incomplete = tmp_path / "signals.parquet"
    incomplete.write_bytes(b"")

    result = module._load_stored_signals(incomplete, completed_days=0)

    assert result.is_empty()
