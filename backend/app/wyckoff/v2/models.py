"""Immutable domain records for the standalone Wyckoff v2 engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TradingRangeSnapshot:
    range_id: str
    support: float
    resistance: float
    creek: float
    window_start: str
    window_end: str
    established_at: str
    atr: float
    width_atr: float
    width_pct: float
    tolerance: float
    support_tests: int
    resistance_tests: int
    quality: float
    age_bars: int = 0
    drift_pct: float = 0.0
    support_stability: float = 0.0
    resistance_stability: float = 0.0


@dataclass(frozen=True)
class WyckoffEvent:
    event_id: str
    symbol: str
    event_type: str
    range_id: str
    state: str
    detected_at: str
    range_snapshot: TradingRangeSnapshot
    parent_event_id: str | None = None
    confirmed_at: str | None = None
    invalidated_at: str | None = None
    invalidation: float | None = None
    reason: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    research: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntrySignal:
    event_id: str
    symbol: str
    range_id: str
    entry_type: str
    occurred_at: str
    state: str
    price: float
    invalidation: float
    parent_event_id: str | None
    reason: str
    research: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WyckoffV2Analysis:
    symbol: str
    events: tuple[WyckoffEvent, ...]
    entries: tuple[EntrySignal, ...]
    diagnostics: dict[str, Any]

    def latest_payload(self, as_of: str) -> dict[str, Any]:
        """Return only events/entries generated on the strategy's latest bar."""
        today_entries = [entry for entry in self.entries if entry.occurred_at == as_of]
        today_events = [event for event in self.events if event.detected_at == as_of]
        active = next(
            (
                event
                for event in reversed(self.events)
                if event.state not in {
                    "HARD_INVALIDATION",
                    "TEST_TIMEOUT",
                    "TEST_REJECTED",
                    "NO_FOLLOW_THROUGH",
                    "SOS_FAILED",
                    "LPS_FAILED",
                }
            ),
            None,
        )
        return {
            "signals": [entry.entry_type for entry in today_entries],
            "entries": [asdict(entry) for entry in today_entries],
            "events": [asdict(event) for event in today_events],
            "active_event": asdict(active) if active else None,
        }
