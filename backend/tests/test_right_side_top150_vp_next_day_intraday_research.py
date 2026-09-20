import numpy as np
import pandas as pd
import pytest

from scripts.run_right_side_top150_vp_next_day_intraday_research import _portfolio_intraday_path


def test_portfolio_path_uses_synchronized_close_nav_not_unattainable_average_high():
    selected = pd.DataFrame({"symbol": ["A", "B"]})
    times = pd.date_range("2026-01-02 09:30", periods=216, freq="min")
    minute = pd.concat([
        pd.DataFrame({"symbol": "A", "datetime": times, "open": 10.0, "high": 12.0, "low": 10.0, "close": np.r_[12.0, np.repeat(10.0, 215)]}),
        pd.DataFrame({"symbol": "B", "datetime": times, "open": 10.0, "high": 12.0, "low": 10.0, "close": np.r_[10.0, np.repeat(12.0, 215)]}),
    ], ignore_index=True)
    result = _portfolio_intraday_path(selected, minute)
    assert result is not None
    assert result["portfolio_close_path_mfe"] == pytest.approx(0.1)
    assert result["avg_constituent_mfe_high"] == pytest.approx(0.2)
