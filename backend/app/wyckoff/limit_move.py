# ruff: noqa: RUF001
"""A-share limit-move recognition used by Wyckoff price/volume diagnostics.

Migrated from the local ``reference/WyckoffTradingAgent`` source.  It only
classifies an exchange-rule state and does not make a trading decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.wyckoff.cn_boards import cn_board

_LIMIT_TOUCH_TOLERANCE_PCT = 0.15


def is_st_name(name: str) -> bool:
    text = str(name or "").strip().upper()
    return text.startswith("ST") or text.startswith("*ST")


def is_st_risk_warning(code: str, name: str) -> bool:
    if cn_board(code) == "unknown":
        return False
    return is_st_name(name) or "ST" in str(name or "").upper()


def limit_pct(code: str, name: str = "", *, market: str = "cn") -> float | None:
    """Return the applicable A-share daily price-limit percentage."""
    if market != "cn":
        return None
    board = cn_board(code)
    if board == "bse":
        return 30.0
    if board in {"chinext", "star"}:
        return 20.0
    return 5.0 if is_st_name(name) else 10.0


@dataclass(frozen=True)
class LimitMoveState:
    limit_pct: float
    limit_up_price: float
    limit_down_price: float
    touched_limit_up: bool
    touched_limit_down: bool
    closed_limit_up: bool
    closed_limit_down: bool
    one_word_board: bool
    opened_then_broke: bool


def classify_limit_move(
    *,
    code: str,
    name: str,
    prev_close: float,
    open_: float,
    high: float,
    low: float,
    close: float,
    market: str = "cn",
) -> LimitMoveState | None:
    """Classify one OHLC bar against its market-specific price limits."""
    if prev_close <= 0:
        return None
    pct = limit_pct(code, name, market=market)
    if pct is None:
        return None
    limit_up = round(float(prev_close * (1 + pct / 100.0)), 2)
    limit_down = round(float(prev_close * (1 - pct / 100.0)), 2)
    tolerance = pct * _LIMIT_TOUCH_TOLERANCE_PCT / 100.0 * prev_close
    touched_up = high >= limit_up - tolerance
    touched_down = low <= limit_down + tolerance
    closed_up = close >= limit_up - tolerance
    closed_down = close <= limit_down + tolerance
    near_zero_range = max(high - low, 0.0) <= tolerance * 2
    one_word_up = closed_up and open_ >= limit_up - tolerance and near_zero_range
    one_word_down = closed_down and open_ <= limit_down + tolerance and near_zero_range
    opened_then_broke = (touched_up or touched_down) and not (closed_up or closed_down)
    return LimitMoveState(
        limit_pct=pct,
        limit_up_price=limit_up,
        limit_down_price=limit_down,
        touched_limit_up=touched_up,
        touched_limit_down=touched_down,
        closed_limit_up=closed_up,
        closed_limit_down=closed_down,
        one_word_board=bool(one_word_up or one_word_down),
        opened_then_broke=bool(opened_then_broke),
    )


def describe_limit_move(state: LimitMoveState | None) -> str:
    """Return a short diagnostic explanation suitable for strategy evidence."""
    if state is None:
        return ""
    if state.one_word_board and state.closed_limit_down:
        return f"一字跌停(±{state.limit_pct:.0f}%)，全天几乎无真实换手，不能视为有效缩量/放量信号"
    if state.one_word_board and state.closed_limit_up:
        return f"一字涨停(±{state.limit_pct:.0f}%)，封板惜售，量能参考意义有限"
    if state.closed_limit_down:
        return f"收盘跌停(±{state.limit_pct:.0f}%)，盘中曾打开过，有真实换手"
    if state.closed_limit_up:
        return f"收盘涨停(±{state.limit_pct:.0f}%)"
    if state.touched_limit_down and state.opened_then_broke:
        return "盘中触及跌停后打开（烂板），未能封住"
    if state.touched_limit_up and state.opened_then_broke:
        return "盘中触及涨停后炸板，未能封住"
    return ""


__all__ = [
    "LimitMoveState",
    "classify_limit_move",
    "describe_limit_move",
    "is_st_name",
    "is_st_risk_warning",
    "limit_pct",
]
