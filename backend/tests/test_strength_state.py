from __future__ import annotations

from app.services.strength_state import (
    breadth_state,
    extension_state,
    relative_strength_state,
    sector_phase,
)


def test_sector_phase_distinguishes_equal_strength_rising_from_fading() -> None:
    rising, rising_reasons = sector_phase(
        percentile=90.0,
        score_change_3d=9.0,
        rank_change_3d=4,
        breadth="EXPANDING",
        extension="NORMAL",
    )
    fading, fading_reasons = sector_phase(
        percentile=90.0,
        score_change_3d=-9.0,
        rank_change_3d=-4,
        breadth="CONTRACTING",
        extension="NORMAL",
    )

    assert rising == "ACCELERATING"
    assert "score_improving" in rising_reasons
    assert fading == "FADING"
    assert "breadth_contracting" in fading_reasons


def test_sector_phase_recognizes_exhaustion_and_emergence_without_score_tuning() -> None:
    exhausted, exhausted_reasons = sector_phase(
        percentile=95.0,
        score_change_3d=-1.0,
        rank_change_3d=0,
        breadth="STABLE",
        extension="EXTREME",
    )
    emerging, emerging_reasons = sector_phase(
        percentile=65.0,
        score_change_3d=7.0,
        rank_change_3d=3,
        breadth="EXPANDING",
        extension="NORMAL",
    )

    assert exhausted == "EXHAUSTED"
    assert {"score_high", "extension_high", "score_not_improving"} <= set(exhausted_reasons)
    assert emerging == "EMERGING"
    assert "rank_improving" in emerging_reasons


def test_breadth_state_requires_both_raw_breadth_inputs_to_move_together() -> None:
    assert breadth_state(0.06, 0.03) == "EXPANDING"
    assert breadth_state(-0.06, -0.03) == "CONTRACTING"
    assert breadth_state(0.06, -0.03) == "STABLE"
    assert breadth_state(None, 0.03) is None


def test_rs_state_distinguishes_high_rising_falling_and_extended() -> None:
    rising, _ = relative_strength_state(
        rs_score=95.0, rs_change_3d=5.0, extension="NORMAL"
    )
    falling, _ = relative_strength_state(
        rs_score=95.0, rs_change_3d=-5.0, extension="NORMAL"
    )
    extended, extended_reasons = relative_strength_state(
        rs_score=95.0, rs_change_3d=5.0, extension="EXTENDED"
    )

    assert rising == "HIGH_AND_RISING"
    assert falling == "HIGH_AND_FALLING"
    assert extended == "EXTENDED"
    assert "extension_high" in extended_reasons
    assert extension_state(95.0) == "EXTREME"
    assert extension_state(85.0) == "EXTENDED"
    assert extension_state(70.0) == "ELEVATED"
    assert extension_state(69.9) == "NORMAL"
