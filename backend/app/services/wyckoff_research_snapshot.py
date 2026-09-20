"""Prospective, point-in-time research snapshots for Wyckoff candidates.

Snapshots are intentionally outside strategy scoring: they preserve what was
known on a live ``as_of`` date so Sector/RS context can later be evaluated
without rebuilding it from a newer membership table.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.services.rps_rotation import _latest_enriched_date, load_current_member_map
from app.services.sector_membership import capture_current_snapshot

_SNAPSHOT_DIR = "wyckoff_sector_rs_research"
_SCHEMA_VERSION = 1


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _snapshot_path(data_dir: Path, as_of: date) -> Path:
    return data_dir / "research_snapshots" / _SNAPSHOT_DIR / f"date={as_of.isoformat()}" / "snapshot.json"


def capture_current_membership_snapshots(
    repo: Any,
    *,
    as_of: date,
    kinds: tuple[str, ...] = ("concept",),
) -> dict[str, object]:
    """Persist current member maps under the completed market date.

    The caller owns the ``as_of`` validity check.  Daily pipeline callers use
    the newest on-disk enriched partition, so a weekend/manual rerun cannot
    label a current THS concept table as a non-existent future trading day.
    ``capture_current_snapshot`` de-duplicates exact source rows, making a
    same-day retry idempotent.
    """
    data_dir = Path(repo.store.data_dir)
    membership_counts: dict[str, int] = {}
    for kind in kinds:
        member_map = load_current_member_map(repo, kind)
        if member_map.is_empty():
            return {
                "status": "skipped_empty_member_map",
                "as_of": as_of.isoformat(),
                "kind": kind,
                "membership_rows": membership_counts,
            }
        membership_counts[kind] = capture_current_snapshot(
            data_dir,
            member_map,
            kind=kind,
            as_of=as_of,
            source="current_ext_snapshot",
            taxonomy_version="current",
        )
    return {
        "status": "captured",
        "as_of": as_of.isoformat(),
        "membership_rows": membership_counts,
    }


def capture_wyckoff_research_snapshot(
    repo: Any,
    *,
    as_of: date,
    rows: list[dict[str, Any]],
) -> dict[str, object]:
    """Persist current candidate context and memberships for forward research.

    Historical requests are deliberately skipped.  Capturing a current vendor
    membership table under an old ``as_of`` would create the very look-ahead
    membership history this facility exists to prevent.
    """
    latest = _latest_enriched_date(repo)
    if latest != as_of:
        return {
            "status": "skipped_nonlatest_as_of",
            "as_of": as_of.isoformat(),
            "latest_enriched_date": latest.isoformat() if latest else None,
        }

    data_dir = Path(repo.store.data_dir)
    membership_status = capture_current_membership_snapshots(
        repo, as_of=as_of, kinds=("industry", "concept")
    )
    membership_counts = membership_status["membership_rows"]

    path = _snapshot_path(data_dir, as_of)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "as_of": as_of.isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
        "strategy_id": "wyckoff_funnel",
        "research_only": True,
        "membership": {
            "source": "current_ext_snapshot",
            "membership_as_of": as_of.isoformat(),
            "history_store": "sector_membership_history/memberships.parquet",
            "captured_rows": membership_counts,
        },
        "candidate_count": len(rows),
        "rows": rows,
    }
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, default=_json_default)
    os.replace(temporary, path)
    return {
        "status": "captured",
        "as_of": as_of.isoformat(),
        "path": str(path.relative_to(data_dir)),
        "candidate_count": len(rows),
        "membership_rows": membership_counts,
    }
