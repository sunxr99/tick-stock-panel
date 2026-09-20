import pandas as pd
import pytest

from scripts.run_right_side_top150_vp_two_day_oracle_research import _oracle_returns


def test_oracle_return_joins_only_valid_low_and_high_prices():
    selected = pd.DataFrame({"symbol": ["A", "B", "C"]})
    entry = pd.DataFrame({"symbol": ["A", "B", "C"], "low": [10.0, 0.0, 10.0]})
    exit_ = pd.DataFrame({"symbol": ["A", "B"], "high": [12.0, 12.0]})
    result = _oracle_returns(selected, entry, exit_)
    assert result["symbol"].tolist() == ["A"]
    assert result["oracle_return"].iloc[0] == pytest.approx(0.2)
