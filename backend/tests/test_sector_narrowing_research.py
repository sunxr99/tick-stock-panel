from __future__ import annotations

from scripts.run_sector_narrowing_research import _analysis_phase, _research_phase


def test_narrowing_is_high_strength_contracting_and_not_formally_risk_labeled() -> None:
    assert _research_phase(80.0, "CONTRACTING", None) == "NARROWING"
    assert _research_phase(100.0, "CONTRACTING", "LEADING") == "NARROWING"


def test_narrowing_does_not_override_formal_fading_or_exhausted() -> None:
    assert _research_phase(95.0, "CONTRACTING", "FADING") is None
    assert _research_phase(95.0, "CONTRACTING", "EXHAUSTED") is None


def test_narrowing_requires_existing_high_and_contracting_thresholds() -> None:
    assert _research_phase(79.99, "CONTRACTING", None) is None
    assert _research_phase(90.0, "STABLE", None) is None
    assert _research_phase(None, "CONTRACTING", None) is None


def test_analysis_phase_preserves_official_phase_when_no_research_label() -> None:
    assert _analysis_phase("LEADING", None) == "LEADING"
    assert _analysis_phase(None, "NARROWING") == "NARROWING"
    assert _analysis_phase(None, None) == "UNCLASSIFIED"
