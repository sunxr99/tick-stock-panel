import pandas as pd
import pytest

from scripts.run_right_side_top150_vp_d1_open_d2_close_research import _returns


def test_returns_uses_only_valid_open_and_close_prices():
    selected = pd.DataFrame({"symbol": ["A", "B", "C"]})
    entry = pd.DataFrame({"symbol": ["A", "B", "C"], "open": [10.0, 0.0, 10.0]})
    exit_ = pd.DataFrame({"symbol": ["A", "B"], "close": [12.0, 12.0]})
    result = _returns(selected, entry, exit_)
    assert result["symbol"].tolist() == ["A"]
    assert result["return"].iloc[0] == pytest.approx(0.2)
