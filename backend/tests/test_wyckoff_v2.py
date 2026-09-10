from __future__ import annotations

import numpy as np
import pandas as pd

from app.wyckoff.v2 import WyckoffV2Config, analyze_wyckoff_v2


def _range_frame() -> pd.DataFrame:
    periods = 120
    close = 11.0 + 0.8 * np.sin(np.linspace(0, 10 * np.pi, periods))
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-01", periods=periods),
            "open": close - 0.05,
            "high": close + 0.25,
            "low": close - 0.25,
            "close": close,
            "volume": np.full(periods, 1_000.0),
        }
    )


def _append(frame: pd.DataFrame, *, open_: float, high: float, low: float, close: float, volume: float) -> pd.DataFrame:
    date = pd.Timestamp(frame["date"].iloc[-1]) + pd.offsets.BusinessDay()
    return pd.concat(
        [
            frame,
            pd.DataFrame({"date": [date], "open": [open_], "high": [high], "low": [low], "close": [close], "volume": [volume]}),
        ],
        ignore_index=True,
    )


def _config() -> WyckoffV2Config:
    return WyckoffV2Config(range_width_atr_min=3.0, range_width_atr_max=14.0, sos_volume_lookback=20)


def test_spring_test_valid_emits_separate_aggressive_and_standard_entries() -> None:
    frame = _range_frame()
    # Expected frozen support is near 10.0; this is a controlled penetration
    # with a strong recovery.  The following bar is a quiet, narrow Test.
    frame = _append(frame, open_=10.25, high=10.70, low=9.65, close=10.50, volume=1_000.0)
    frame = _append(frame, open_=10.20, high=10.70, low=9.98, close=10.48, volume=500.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())

    assert any(event.event_type.startswith("SPRING_") and event.state == "TEST_VALID" for event in analysis.events)
    assert {entry.entry_type for entry in analysis.entries} >= {"spring_aggressive", "spring_standard"}


def test_spring_failure_is_recorded_when_the_spring_low_breaks() -> None:
    frame = _range_frame()
    frame = _append(frame, open_=10.25, high=10.70, low=9.65, close=10.50, volume=1_000.0)
    frame = _append(frame, open_=9.70, high=9.90, low=9.10, close=9.45, volume=1_300.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())

    assert any(event.event_type.startswith("SPRING_") and event.state == "HARD_INVALIDATION" for event in analysis.events)


def test_low_supply_spring_test_uses_normal_volume_not_a_forced_ratio_to_spring_volume() -> None:
    frame = _range_frame()
    # 0.60x normal volume is Low Supply. The Test remains low relative to
    # normal volume (0.75x), but is deliberately higher than the Spring bar.
    frame = _append(frame, open_=10.25, high=10.70, low=9.65, close=10.50, volume=600.0)
    frame = _append(frame, open_=10.20, high=10.70, low=9.98, close=10.48, volume=750.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())

    spring = next(event for event in analysis.events if event.event_type == "SPRING_LOW_SUPPLY")
    assert spring.state == "TEST_VALID"
    assert any(entry.entry_type == "spring_standard" for entry in analysis.entries)


def test_middle_volume_spring_is_neutral_not_low_supply() -> None:
    frame = _range_frame()
    frame = _append(frame, open_=10.25, high=10.70, low=9.65, close=10.50, volume=1_000.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())

    assert any(event.event_type == "SPRING_NEUTRAL" for event in analysis.events)
    assert not any(event.event_type == "SPRING_LOW_SUPPLY" for event in analysis.events)


def test_spring_test_must_return_to_the_frozen_support_area() -> None:
    frame = _range_frame()
    frame = _append(frame, open_=10.25, high=10.70, low=9.65, close=10.50, volume=1_000.0)
    # A quiet bar far above the frozen support is not a supply Test.
    frame = _append(frame, open_=11.00, high=11.20, low=10.85, close=11.10, volume=500.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())

    spring = next(event for event in analysis.events if event.event_type == "SPRING_NEUTRAL")
    assert spring.state == "WAIT_TEST"
    assert not any(entry.entry_type == "spring_standard" for entry in analysis.entries)


def test_lps_requires_confirmed_sos_and_frozen_creek() -> None:
    frame = _range_frame()
    # SOS: prior close remains below the creek; the bar closes through it with
    # a wide spread, high CLV and high volume percentile.
    frame = _append(frame, open_=11.55, high=12.85, low=11.45, close=12.65, volume=4_000.0)
    frame = _append(frame, open_=12.20, high=12.75, low=12.05, close=12.55, volume=1_200.0)
    frame = _append(frame, open_=12.05, high=12.25, low=11.90, close=12.05, volume=900.0)
    frame = _append(frame, open_=12.00, high=12.35, low=11.95, close=12.25, volume=850.0)
    frame = _append(frame, open_=12.30, high=12.75, low=12.20, close=12.65, volume=1_300.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())
    lps = [event for event in analysis.events if event.event_type == "LPS"]

    assert lps
    assert lps[-1].state == "LPS_CONFIRMED"
    assert lps[-1].parent_event_id is not None
    assert any(event.event_type == "SOS" and event.state == "SOS_CONFIRMED" for event in analysis.events)
    assert any(entry.entry_type == "lps_standard" for entry in analysis.entries)


def test_range_bottom_shrinkage_without_sos_never_becomes_lps() -> None:
    frame = _range_frame()
    frame = _append(frame, open_=10.20, high=10.45, low=9.95, close=10.20, volume=400.0)
    frame = _append(frame, open_=10.15, high=10.35, low=10.00, close=10.25, volume=350.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())

    assert not [event for event in analysis.events if event.event_type == "LPS"]


def test_lps_requires_contraction_against_normal_volume_as_well_as_sos_volume() -> None:
    frame = _range_frame()
    frame = _append(frame, open_=11.55, high=12.85, low=11.45, close=12.65, volume=10_000.0)
    frame = _append(frame, open_=12.20, high=12.75, low=12.05, close=12.55, volume=1_200.0)
    # 0.60x SOS volume looks dry in isolation, but is six times normal volume.
    frame = _append(frame, open_=12.05, high=12.25, low=11.90, close=12.05, volume=6_000.0)
    frame = _append(frame, open_=12.00, high=12.35, low=11.95, close=12.25, volume=6_000.0)
    frame = _append(frame, open_=12.30, high=12.75, low=12.20, close=12.65, volume=6_000.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())

    lps = [event for event in analysis.events if event.event_type == "LPS"]
    assert lps and lps[-1].state == "LPS_CANDIDATE"
    assert not any(entry.entry_type == "lps_standard" for entry in analysis.entries)


def test_replay_does_not_change_an_already_detected_event_when_future_bars_are_added() -> None:
    frame = _range_frame()
    initial = _append(frame, open_=10.25, high=10.70, low=9.65, close=10.50, volume=1_000.0)
    later = _append(initial, open_=10.20, high=10.70, low=9.98, close=10.48, volume=500.0)

    first = analyze_wyckoff_v2("000001.SZ", initial, _config())
    replayed = analyze_wyckoff_v2("000001.SZ", later, _config())

    detected_ids = {event.event_id for event in first.events if event.event_type.startswith("SPRING_")}
    assert detected_ids <= {event.event_id for event in replayed.events}


def test_spring_freezes_research_features_without_turning_them_into_filters() -> None:
    frame = _range_frame()
    frame = _append(frame, open_=10.25, high=10.70, low=9.65, close=10.50, volume=1_000.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())

    spring = next(event for event in analysis.events if event.event_type.startswith("SPRING_"))
    assert spring.research["spring_penetration_atr"] > 0
    assert spring.research["spring_reclaim_atr"] > 0
    assert spring.research["background"] in {"BACKGROUND_DOWN", "BACKGROUND_SIDEWAYS", "BACKGROUND_UP"}


def test_lps_diagnostics_expose_the_classic_funnel() -> None:
    frame = _range_frame()
    frame = _append(frame, open_=11.55, high=12.85, low=11.45, close=12.65, volume=4_000.0)
    frame = _append(frame, open_=12.20, high=12.75, low=12.05, close=12.55, volume=1_200.0)
    frame = _append(frame, open_=12.05, high=12.25, low=11.90, close=12.05, volume=900.0)
    frame = _append(frame, open_=12.00, high=12.35, low=11.95, close=12.25, volume=850.0)
    frame = _append(frame, open_=12.30, high=12.75, low=12.20, close=12.65, volume=1_300.0)

    analysis = analyze_wyckoff_v2("000001.SZ", frame, _config())

    assert analysis.diagnostics["funnel"]["SOS_DETECTED"] >= 1
    assert analysis.diagnostics["funnel"]["LPS_CLASSIC_CONFIRMED"] >= 1
