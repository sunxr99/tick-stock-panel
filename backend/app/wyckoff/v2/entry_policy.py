"""Entry records are policy outputs, intentionally separate from event state."""

from __future__ import annotations

from app.wyckoff.v2.models import EntrySignal, WyckoffEvent


def entry_from_event(
    event: WyckoffEvent,
    *,
    entry_type: str,
    occurred_at: str,
    price: float,
    invalidation: float,
    reason: str,
    research: dict[str, object] | None = None,
) -> EntrySignal:
    return EntrySignal(
        event_id=event.event_id,
        symbol=event.symbol,
        range_id=event.range_id,
        entry_type=entry_type,
        occurred_at=occurred_at,
        state=event.state,
        price=price,
        invalidation=invalidation,
        parent_event_id=event.parent_event_id,
        reason=reason,
        research=research or event.research,
    )
