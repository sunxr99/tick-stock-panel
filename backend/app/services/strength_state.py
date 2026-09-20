"""Fixed, explainable dynamic-state rules shared by Sector Strength and RS.

These rules deliberately consume frozen static scores.  They do not alter
Sector Strength V1.1 / Relative Strength V1 weights and have no trading side
effects.
"""
from __future__ import annotations


def extension_state(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 95.0:
        return "EXTREME"
    if score >= 85.0:
        return "EXTENDED"
    if score >= 70.0:
        return "ELEVATED"
    return "NORMAL"


def breadth_state(
    up_ratio_change_3d: float | None, strong_stock_ratio_change_3d: float | None
) -> str | None:
    """Classify internal participation, not price direction.

    Five percentage points of advancing-member change and two points of
    >=3%-member change are intentionally fixed descriptive thresholds.
    """
    if up_ratio_change_3d is None or strong_stock_ratio_change_3d is None:
        return None
    if up_ratio_change_3d >= 0.05 and strong_stock_ratio_change_3d >= 0.02:
        return "EXPANDING"
    if up_ratio_change_3d <= -0.05 and strong_stock_ratio_change_3d <= -0.02:
        return "CONTRACTING"
    return "STABLE"


def sector_phase(
    *,
    percentile: float | None,
    score_change_3d: float | None,
    rank_change_3d: int | None,
    breadth: str | None,
    extension: str | None,
) -> tuple[str | None, tuple[str, ...]]:
    """Return a deterministic phase and the exact conditions that triggered it."""
    if None in {percentile, score_change_3d, rank_change_3d, breadth, extension}:
        return None, ("state_history_incomplete",)
    assert percentile is not None and score_change_3d is not None and rank_change_3d is not None
    assert breadth is not None and extension is not None
    high = percentile >= 80.0
    improving = score_change_3d >= 5.0 and rank_change_3d >= 3
    weakening = score_change_3d <= -5.0 and rank_change_3d <= -3
    if high and extension in {"EXTENDED", "EXTREME"} and score_change_3d <= 0 and breadth != "EXPANDING":
        return "EXHAUSTED", ("score_high", "extension_high", "score_not_improving", f"breadth_{breadth.lower()}")
    if weakening and breadth == "CONTRACTING":
        return "FADING", ("score_change_negative", "rank_falling", "breadth_contracting")
    if high and improving and breadth == "EXPANDING":
        return "ACCELERATING", ("score_high", "score_improving", "rank_improving", "breadth_expanding")
    if high and breadth != "CONTRACTING" and extension in {"NORMAL", "ELEVATED"}:
        return "LEADING", ("score_high", "breadth_healthy", "extension_not_extreme")
    if percentile >= 50.0 and improving and breadth == "EXPANDING":
        return "EMERGING", ("score_not_yet_high", "score_improving", "rank_improving", "breadth_expanding")
    return None, ("no_fixed_phase_condition",)


def relative_strength_state(
    *,
    rs_score: float | None,
    rs_change_3d: float | None,
    extension: str | None,
) -> tuple[str | None, tuple[str, ...]]:
    """Classify RS trajectory without treating it as a buy/sell instruction."""
    if rs_score is None or rs_change_3d is None or extension is None:
        return None, ("state_history_incomplete",)
    if rs_score >= 80.0 and extension in {"EXTENDED", "EXTREME"}:
        return "EXTENDED", ("rs_high", "extension_high")
    if rs_score >= 80.0 and rs_change_3d >= 3.0:
        return "HIGH_AND_RISING", ("rs_high", "rs_improving")
    if rs_score >= 80.0 and rs_change_3d <= -3.0:
        return "HIGH_AND_FALLING", ("rs_high", "rs_falling")
    if rs_score >= 80.0:
        return "HIGH_AND_FLAT", ("rs_high", "rs_change_flat")
    if rs_change_3d >= 5.0:
        return "RISING", ("rs_not_yet_high", "rs_improving")
    return "LOW", ("rs_not_high",)
