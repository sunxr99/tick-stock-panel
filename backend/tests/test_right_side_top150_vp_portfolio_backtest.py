from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


def _module():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "top150_vp_portfolio",
            scripts_dir / "run_right_side_top150_vp_portfolio_backtest.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts_dir))


def test_portfolio_path_uses_daily_equal_weight_nav_for_drawdown() -> None:
    module = _module()
    entry, exit_date = date(2026, 1, 2), date(2026, 1, 5)
    selected = pd.DataFrame({
        "symbol": ["A", "B"],
        "benchmark_return_2d": [0.01, 0.01],
        "mae_2d": [-0.2, -0.2],
        "mfe_2d": [0.3, 0.3],
    })
    prices = pd.DataFrame({
        "symbol": ["A", "A", "B", "B"],
        "date": [entry, exit_date, entry, exit_date],
        "open": [10.0, 10.0, 10.0, 10.0],
        "close": [9.0, 12.0, 9.0, 12.0],
    })

    result = module._portfolio_path(
        selected=selected,
        prices=prices,
        path_dates=[entry, exit_date],
        signal_date=date(2026, 1, 1),
        horizon=2,
    )

    assert result is not None
    assert result.summary["portfolio_return"] == pytest.approx(0.2)
    assert result.summary["portfolio_max_drawdown"] == pytest.approx(-0.1)
    assert result.summary["portfolio_mfe"] == pytest.approx(0.2)
    assert result.daily_nav["portfolio_nav"].tolist() == pytest.approx([0.9, 1.2])
