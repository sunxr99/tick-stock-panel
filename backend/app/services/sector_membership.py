"""Point-in-time sector membership storage and canonical symbol handling.

The existing extension-data member table is a *current* snapshot.  This
module keeps that useful read path, while providing a separate durable history
table for research that requires membership known at ``as_of``.  It never
pretends a current snapshot was historical membership.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

_HISTORY_DIR = "sector_membership_history"
_HISTORY_FILE = "memberships.parquet"
_SW_HISTORY_FILE = "sw_memberships.parquet"
_SW_SOURCE_PREFIX = "tushare_sw_index_member_all"
_VALID_KINDS = {"concept", "industry"}
_HISTORY_SCHEMA = {
    "symbol": pl.Utf8,
    "kind": pl.Utf8,
    "sector": pl.Utf8,
    "effective_from": pl.Date,
    "effective_to": pl.Date,
    "membership_as_of": pl.Date,
    "source": pl.Utf8,
    "taxonomy_version": pl.Utf8,
}
_SW_HIERARCHY_COLUMNS = (
    "sw1_code", "sw1_name",
    "sw2_code", "sw2_name",
    "sw3_code", "sw3_name",
)
_SW_HISTORY_SCHEMA = {**_HISTORY_SCHEMA, **{column: pl.Utf8 for column in _SW_HIERARCHY_COLUMNS}}


@dataclass(frozen=True)
class MembershipResolution:
    """Canonical member map plus its point-in-time provenance."""

    frame: pl.DataFrame
    membership_as_of: date | None
    source: str
    strict_historical: bool
    note: str


def canonical_symbol(value: object) -> str | None:
    """Return one A-share symbol key, or preserve a non-A-share qualified key.

    Extension rows often contain both ``600000`` and ``600000.SH``.  The
    former must never be counted as a second constituent.  Bare codes with an
    unambiguous mainland-board prefix are qualified; unknown bare identifiers
    are retained so custom mappings/tests are not silently discarded.
    """
    text = str(value or "").strip().upper()
    if not text:
        return None
    code, separator, exchange = text.partition(".")
    if separator:
        return f"{code}.{exchange}" if code and exchange in {"SH", "SZ", "BJ"} else text
    if not code.isdigit() or len(code) != 6:
        return text
    if code.startswith(("4", "8", "92")):
        return f"{code}.BJ"
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    return text


def canonicalize_member_map(frame: pl.DataFrame, kind: str) -> pl.DataFrame:
    """Canonicalize and de-duplicate a raw extension membership map."""
    if kind not in _VALID_KINDS:
        raise ValueError(f"unsupported membership kind: {kind!r}")
    schema = {"_sym_up": pl.Utf8, kind: pl.Utf8}
    if frame.is_empty() or not {"_sym_up", kind}.issubset(frame.columns):
        return pl.DataFrame(schema=schema)
    rows = [
        {"_sym_up": symbol, kind: str(row[kind]).strip()}
        for row in frame.select(["_sym_up", kind]).iter_rows(named=True)
        if (symbol := canonical_symbol(row["_sym_up"])) is not None and str(row[kind]).strip()
    ]
    return pl.DataFrame(rows, schema=schema).unique().sort([kind, "_sym_up"]) if rows else pl.DataFrame(schema=schema)


def _history_path(data_dir: Path) -> Path:
    return data_dir / _HISTORY_DIR / _HISTORY_FILE


def _empty_history() -> pl.DataFrame:
    return pl.DataFrame(schema=_HISTORY_SCHEMA)


def _with_sw_hierarchy_columns(frame: pl.DataFrame) -> pl.DataFrame:
    """Keep pre-V2 SW files readable while exposing a stable hierarchy schema."""
    missing = [
        pl.lit(None).cast(pl.Utf8).alias(column)
        for column in _SW_HIERARCHY_COLUMNS
        if column not in frame.columns
    ]
    return frame.with_columns(missing) if missing else frame


def append_membership_history(data_dir: Path, rows: pl.DataFrame) -> int:
    """Append canonical historical membership intervals to the local Parquet store.

    The caller supplies vendor data with a real effective date.  Overlapping
    rows are intentionally retained as source records; resolver selection is
    date-exact and callers can audit the source/version fields.
    """
    required = set(_HISTORY_SCHEMA)
    if not required.issubset(rows.columns):
        missing = sorted(required.difference(rows.columns))
        raise ValueError(f"membership history missing columns: {missing}")
    normalized_rows = []
    for row in rows.select(list(_HISTORY_SCHEMA)).iter_rows(named=True):
        kind = str(row["kind"])
        if kind not in _VALID_KINDS:
            raise ValueError(f"unsupported membership kind: {kind!r}")
        symbol = canonical_symbol(row["symbol"])
        if symbol is None or not str(row["sector"] or "").strip() or row["effective_from"] is None:
            continue
        normalized_rows.append({**row, "symbol": symbol, "sector": str(row["sector"]).strip()})
    incoming = pl.DataFrame(normalized_rows, schema=_HISTORY_SCHEMA) if normalized_rows else _empty_history()
    if incoming.is_empty():
        return 0
    path = _history_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = pl.read_parquet(path) if path.exists() else _empty_history()
    combined = pl.concat([existing, incoming], how="vertical").unique()
    temporary = path.with_suffix(".tmp")
    combined.write_parquet(temporary)
    temporary.replace(path)
    return incoming.height


def replace_sw_membership_history(data_dir: Path, rows: pl.DataFrame) -> int:
    """Replace the dedicated Tushare SW interval store with validated rows.

    SW ``index_member_all`` supplies effective intervals rather than daily
    snapshots.  Keeping it in a separate file prevents it from being mixed
    with current THS snapshots and makes reruns idempotent.
    """
    required = set(_HISTORY_SCHEMA)
    if not required.issubset(rows.columns):
        missing = sorted(required.difference(rows.columns))
        raise ValueError(f"membership history missing columns: {missing}")
    source_rows = _with_sw_hierarchy_columns(rows)
    normalized_rows = []
    for row in source_rows.select(list(_SW_HISTORY_SCHEMA)).iter_rows(named=True):
        if str(row["kind"]) != "industry":
            raise ValueError("Tushare SW membership history must use kind='industry'")
        symbol = canonical_symbol(row["symbol"])
        if symbol is None or not str(row["sector"] or "").strip() or row["effective_from"] is None:
            continue
        normalized_rows.append({
            **row,
            "symbol": symbol,
            "sector": str(row["sector"]).strip(),
            **{
                column: str(row[column]).strip() if row[column] is not None and str(row[column]).strip() else None
                for column in _SW_HIERARCHY_COLUMNS
            },
        })
    incoming = pl.DataFrame(normalized_rows, schema=_SW_HISTORY_SCHEMA) if normalized_rows else pl.DataFrame(schema=_SW_HISTORY_SCHEMA)
    path = data_dir / _HISTORY_DIR / _SW_HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    incoming.unique().write_parquet(temporary)
    temporary.replace(path)
    return incoming.height


def resolve_sw_history(data_dir: Path, *, as_of: date) -> MembershipResolution | None:
    """Resolve the Tushare SW interval store for a historical date."""
    path = data_dir / _HISTORY_DIR / _SW_HISTORY_FILE
    if not path.exists():
        return None
    history = _with_sw_hierarchy_columns(pl.read_parquet(path)).filter(
        (pl.col("kind") == "industry")
        & (pl.col("effective_from") <= as_of)
        & (pl.col("effective_to").is_null() | (pl.col("effective_to") >= as_of))
    )
    if history.is_empty():
        return None
    rows = []
    for row in history.select(["symbol", "sector", *_SW_HIERARCHY_COLUMNS]).iter_rows(named=True):
        symbol = canonical_symbol(row["symbol"])
        sector = str(row["sector"] or "").strip()
        if symbol is None or not sector:
            continue
        parts = [part.strip() for part in sector.split("-") if part.strip()]
        rows.append({
            "_sym_up": symbol,
            "industry": sector,
            # Old SW stores only retained the concatenated name.  Treat their
            # lone value as SW1 only; never manufacture SW2/SW3 membership.
            "sw1_code": row["sw1_code"],
            "sw1_name": row["sw1_name"] or (parts[0] if parts else None),
            "sw2_code": row["sw2_code"],
            "sw2_name": row["sw2_name"] or (parts[1] if len(parts) >= 2 else None),
            "sw3_code": row["sw3_code"],
            "sw3_name": row["sw3_name"] or (parts[2] if len(parts) >= 3 else None),
        })
    frame = (
        pl.DataFrame(rows, schema={"_sym_up": pl.Utf8, "industry": pl.Utf8, **{column: pl.Utf8 for column in _SW_HIERARCHY_COLUMNS}})
        .unique()
        .sort(["industry", "_sym_up"])
        if rows else pl.DataFrame(schema={"_sym_up": pl.Utf8, "industry": pl.Utf8, **{column: pl.Utf8 for column in _SW_HIERARCHY_COLUMNS}})
    )
    return MembershipResolution(
        frame=frame,
        membership_as_of=as_of,
        source=_SW_SOURCE_PREFIX,
        strict_historical=True,
        note="成员关系来自申万 index_member_all 的 in_date/out_date 区间",
    )


def capture_current_snapshot(
    data_dir: Path, frame: pl.DataFrame, *, kind: str, as_of: date, source: str, taxonomy_version: str = "current"
) -> int:
    """Persist a point snapshot for forward research; it is not backfilled."""
    canonical = canonicalize_member_map(frame, kind)
    if canonical.is_empty():
        return 0
    rows = canonical.rename({"_sym_up": "symbol", kind: "sector"}).with_columns(
        pl.lit(kind).alias("kind"),
        pl.lit(as_of).cast(pl.Date).alias("effective_from"),
        pl.lit(None).cast(pl.Date).alias("effective_to"),
        pl.lit(as_of).cast(pl.Date).alias("membership_as_of"),
        pl.lit(source).alias("source"),
        pl.lit(taxonomy_version).alias("taxonomy_version"),
    ).select(list(_HISTORY_SCHEMA))
    return append_membership_history(data_dir, rows)


def resolve_history(data_dir: Path, *, kind: str, as_of: date) -> MembershipResolution | None:
    """Resolve only member records provably known no later than ``as_of``."""
    if kind not in _VALID_KINDS:
        raise ValueError(f"unsupported membership kind: {kind!r}")
    path = _history_path(data_dir)
    if not path.exists():
        return None
    history = pl.read_parquet(path).filter(
        (pl.col("kind") == kind)
        & (pl.col("membership_as_of") <= as_of)
        & (pl.col("effective_from") <= as_of)
        & (pl.col("effective_to").is_null() | (pl.col("effective_to") >= as_of))
    )
    if history.is_empty():
        return None
    # If several vendor rows apply, preserve same-symbol multi-sector concept
    # membership but retain the newest source snapshot for duplicates.
    latest_known = history.get_column("membership_as_of").max()
    chosen = history.filter(pl.col("membership_as_of") == latest_known)
    frame = canonicalize_member_map(chosen.rename({"symbol": "_sym_up", "sector": kind}), kind)
    return MembershipResolution(
        frame=frame,
        membership_as_of=latest_known,
        source="historical_membership_store",
        strict_historical=True,
        note="成员关系来自点时历史存储; 只使用 membership_as_of 不晚于 as_of 的记录",
    )
