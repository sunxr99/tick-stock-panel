from __future__ import annotations

from app.wyckoff.wyckoff_events import classify_wyckoff_event


def test_right_side_ignition_has_high_confidence_for_high_score() -> None:
    event = classify_wyckoff_event(["SOS"], stage="Markup", score=10)

    assert event.event_id == "right_side_ignition"
    assert event.confidence == "high"
    assert "阶段=Markup" in event.reasons


def test_accumulation_repair_resonance_precedes_individual_trigger() -> None:
    event = classify_wyckoff_event({"spring", "evr"}, stage="Accum_C", regime="warm")

    assert event.event_id == "accumulation_repair_resonance"
    assert event.track == "Accum"
    assert "水温=WARM" in event.reasons


def test_unknown_or_empty_signal_is_observation_only() -> None:
    event = classify_wyckoff_event(["unknown"])

    assert event.event_id == "wyckoff_watch"
    assert event.action == "观察"
    assert event.confidence == "low"
