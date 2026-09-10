"""Stable aggregate diagnostics for parallel legacy-versus-v2 evaluation."""

from __future__ import annotations

from app.wyckoff.v2.models import WyckoffEvent


def summarize_events(
    events: list[WyckoffEvent],
    *,
    bars: int,
    range_evaluations: int,
    funnel: dict[str, int] | None = None,
    rejection_reasons: dict[str, int] | None = None,
) -> dict[str, object]:
    event_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1
        state_counts[event.state] = state_counts.get(event.state, 0) + 1
    return {
        "bars": bars,
        "range_evaluations": range_evaluations,
        "event_counts": event_counts,
        "state_counts": state_counts,
        "funnel": funnel or {},
        "rejection_reasons": rejection_reasons or {},
    }
