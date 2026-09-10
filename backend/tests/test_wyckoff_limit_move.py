from __future__ import annotations

from app.wyckoff.limit_move import classify_limit_move, describe_limit_move, limit_pct


def test_limit_pct_obeys_board_and_st_rules() -> None:
    assert limit_pct("300001") == 20.0
    assert limit_pct("688001") == 20.0
    assert limit_pct("430001") == 30.0
    assert limit_pct("600001", "*ST 测试") == 5.0
    assert limit_pct("00700", market="hk") is None


def test_one_word_limit_down_is_not_an_ordinary_price_volume_bar() -> None:
    state = classify_limit_move(
        code="600001", name="测试", prev_close=10.0, open_=9.0, high=9.0, low=9.0, close=9.0
    )

    assert state is not None
    assert state.closed_limit_down is True
    assert state.one_word_board is True
    assert "不能视为有效" in describe_limit_move(state)


def test_opened_limit_up_is_classified_as_broken_board() -> None:
    state = classify_limit_move(
        code="600001", name="测试", prev_close=10.0, open_=10.1, high=11.0, low=10.0, close=10.5
    )

    assert state is not None
    assert state.touched_limit_up is True
    assert state.opened_then_broke is True
    assert "炸板" in describe_limit_move(state)
