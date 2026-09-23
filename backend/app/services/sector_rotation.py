"""Persisted, point-in-time sector rotation indicators.

This is deliberately separate from the frozen Sector Strength V1 service.
It stores explainable daily rotation inputs for the dashboard; it does not
filter Wyckoff candidates or issue trading instructions.
"""
from __future__ import annotations

import logging
from datetime import date
from math import prod
from pathlib import Path

import polars as pl

from app.services import rps_rotation
from app.services.sector_membership import resolve_history, resolve_sw_history

logger = logging.getLogger(__name__)

ROTATION_DIR = "sector_rotation_history"
_REQUIRED_COLUMNS = ("symbol", "date", "change_pct", "close", "amount")


def rotation_path(data_dir: Path) -> Path:
    return data_dir / ROTATION_DIR / "part.parquet"


def load_rotation_history(data_dir: Path, *, kind: str | None = None) -> pl.DataFrame:
    path = rotation_path(data_dir)
    if not path.exists():
        return pl.DataFrame()
    try:
        frame = pl.read_parquet(path)
    except Exception as exc:
        logger.warning("load sector rotation history failed: %s", exc)
        return pl.DataFrame()
    if kind and not frame.is_empty() and "kind" in frame.columns:
        return frame.filter(pl.col("kind") == kind)
    return frame


def _compound(values: list[float]) -> float:
    return prod(1.0 + value for value in values) - 1.0


def _window(values: dict[date, float], dates: list[date], index: int, size: int) -> float | None:
    start = index - size + 1
    if start < 0:
        return None
    selected = dates[start:index + 1]
    if any(day not in values for day in selected):
        return None
    return _compound([values[day] for day in selected])


def _average_window(values: dict[date, float], dates: list[date], start: int, size: int) -> float | None:
    if start < 0:
        return None
    selected = dates[start:start + size]
    if len(selected) != size or any(day not in values for day in selected):
        return None
    return sum(values[day] for day in selected) / size


def _percentiles(values: dict[str, float | None]) -> dict[str, float | None]:
    finite = {key: value for key, value in values.items() if value is not None}
    if not finite:
        return {key: None for key in values}
    _, ranked = rps_rotation._rank_values({key: float(value) for key, value in finite.items()})
    return {key: ranked.get(key) for key in values}


def _membership_map(repo, *, kind: str, level: int | None, as_of: date) -> tuple[pl.DataFrame, date | None, str] | None:
    if kind == "industry":
        if level not in (1, 2, 3):
            raise ValueError("industry rotation requires level 1, 2, or 3")
        resolved = resolve_sw_history(repo.store.data_dir, as_of=as_of)
        source = "tushare_sw_index_member_all"
    elif kind == "concept":
        resolved = resolve_history(repo.store.data_dir, kind="concept", as_of=as_of)
        source = "historical_membership_store"
        # A dashboard fact for date T must use a snapshot captured on T, not
        # silently reuse an older THS concept basket.
        if resolved is not None and resolved.membership_as_of != as_of:
            return None
    else:
        raise ValueError("kind must be 'industry' or 'concept'")
    if resolved is None or resolved.frame.is_empty():
        return None
    frame = rps_rotation._normalized_map(
        resolved.frame, kind, level, strict_industry_level=(kind == "industry")
    )
    if frame.is_empty():
        return None
    return frame, resolved.membership_as_of, source


def _close_breadth(
    members: list[str], close_by_symbol: dict[str, dict[date, float]], dates: list[date], index: int, window: int
) -> tuple[float | None, float | None]:
    start = index - window + 1
    if start < 0:
        return None, None
    selected = dates[start:index + 1]
    above = new_high = valid = 0
    for symbol in members:
        closes = close_by_symbol.get(symbol, {})
        if any(day not in closes for day in selected):
            continue
        current = closes[dates[index]]
        window_values = [closes[day] for day in selected]
        valid += 1
        above += int(current > sum(window_values) / len(window_values))
        new_high += int(current >= max(window_values))
    if not valid:
        return None, None
    return above / valid, new_high / valid


def _prior_changes(
    history: pl.DataFrame, *, sector_ids: list[str], dates: list[date], index: int
) -> dict[str, dict[str, float | None]]:
    result = {sector_id: {"score_delta_1d": None, "score_delta_3d": None, "score_delta_5d": None, "up_ratio_delta_3d": None} for sector_id in sector_ids}
    if history.is_empty() or index < 1:
        return result
    for lag, _score_key in ((1, "score_delta_1d"), (3, "score_delta_3d"), (5, "score_delta_5d")):
        if index < lag:
            continue
        previous = history.filter(pl.col("date") == dates[index - lag])
        for row in previous.select(["sector_id", "sector_score", "up_ratio"]).iter_rows(named=True):
            item = result.get(str(row["sector_id"]))
            if item is None:
                continue
            item[f"previous_{lag}"] = row["sector_score"]
            if lag == 3:
                item["previous_up_ratio_3d"] = row["up_ratio"]
    return result


def build_rotation_day(repo, *, kind: str, level: int | None = None, as_of: date | None = None) -> pl.DataFrame:
    """Build one exact-session dashboard fact set without writing it.

    Concept output is fail-closed unless an exact same-day THS membership
    snapshot exists. Industry output uses the SW interval member store.
    """
    dates, target = rps_rotation._history_dates(repo, as_of)
    if target is None:
        return pl.DataFrame()
    resolved = _membership_map(repo, kind=kind, level=level, as_of=target)
    if resolved is None:
        return pl.DataFrame()
    member_map, membership_as_of, membership_source = resolved
    start = dates[max(0, len(dates) - 80)]
    panel = repo.get_enriched_range(start, target, columns=list(_REQUIRED_COLUMNS))
    if panel is None or panel.is_empty() or not set(_REQUIRED_COLUMNS).issubset(panel.columns):
        return pl.DataFrame()
    panel = panel.with_columns(pl.col("symbol").cast(pl.Utf8).str.to_uppercase().alias("_sym_up"))
    joined = panel.join(member_map.select(["_sym_up", kind]).unique(), on="_sym_up", how="inner")
    if joined.is_empty():
        return pl.DataFrame()

    used_dates = [day for day in dates if day >= start and day <= target]
    target_index = used_dates.index(target)
    member_sets = {
        str(sector): sorted(set(symbols))
        for sector, symbols in member_map.group_by(kind).agg(pl.col("_sym_up")).iter_rows()
    }
    display_column = "_sector_display_name"
    names = {
        str(row[kind]): str(row.get(display_column) or row[kind])
        for row in member_map.select([kind, *([display_column] if display_column in member_map.columns else [])]).unique().iter_rows(named=True)
    }
    close_by_symbol: dict[str, dict[date, float]] = {}
    for row in panel.select(["_sym_up", "date", "close"]).iter_rows(named=True):
        value = row["close"]
        if value is not None:
            close_by_symbol.setdefault(str(row["_sym_up"]), {})[row["date"]] = float(value)
    market_daily = {
        row["date"]: float(row["market_return"])
        for row in panel.filter(pl.col("change_pct").is_not_null() & pl.col("change_pct").is_finite())
        .group_by("date").agg(pl.col("change_pct").mean().alias("market_return")).iter_rows(named=True)
    }
    benchmark = {window: _window(market_daily, used_dates, target_index, window) for window in (5, 20, 60)}
    daily = joined.group_by(["date", kind]).agg(
        pl.col("change_pct").filter(pl.col("change_pct").is_finite()).mean().alias("daily_return"),
        pl.col("amount").filter(pl.col("amount").is_not_null() & pl.col("amount").is_finite()).sum().alias("daily_amount"),
    )
    current = joined.filter(pl.col("date") == target)
    current_stats = {
        str(row[kind]): row
        for row in current.group_by(kind).agg(
            pl.col("change_pct").filter(pl.col("change_pct").is_finite()).len().alias("valid_member_count"),
            pl.col("change_pct").filter(pl.col("change_pct").is_finite()).mean().alias("avg_return_1d"),
            pl.col("change_pct").filter(pl.col("change_pct").is_finite()).median().alias("median_return_1d"),
            pl.col("change_pct").filter(pl.col("change_pct").is_finite()).gt(0).mean().alias("up_ratio"),
            pl.col("amount").filter(pl.col("amount").is_not_null() & pl.col("amount").is_finite()).sum().alias("amount"),
        ).iter_rows(named=True)
    }
    by_sector: dict[str, dict[date, dict[str, float]]] = {}
    for row in daily.iter_rows(named=True):
        sector = str(row[kind])
        values: dict[str, float] = {}
        if row["daily_return"] is not None:
            values["return"] = float(row["daily_return"])
        if row["daily_amount"] is not None:
            values["amount"] = float(row["daily_amount"])
        by_sector.setdefault(sector, {})[row["date"]] = values

    raw: dict[str, dict[str, object]] = {}
    for sector, members in member_sets.items():
        daily_values = by_sector.get(sector, {})
        returns = {day: values["return"] for day, values in daily_values.items() if "return" in values}
        amounts = {day: values["amount"] for day, values in daily_values.items() if "amount" in values}
        stat = current_stats.get(sector, {})
        ma5, _high5 = _close_breadth(members, close_by_symbol, used_dates, target_index, 5)
        ma20, high20 = _close_breadth(members, close_by_symbol, used_dates, target_index, 20)
        ma60, high60 = _close_breadth(members, close_by_symbol, used_dates, target_index, 60)
        amount_5 = _average_window(amounts, used_dates, target_index - 4, 5)
        amount_prior_20 = _average_window(amounts, used_dates, target_index - 24, 20)
        return_5 = _window(returns, used_dates, target_index, 5)
        return_20 = _window(returns, used_dates, target_index, 20)
        return_60 = _window(returns, used_dates, target_index, 60)
        raw[sector] = {
            "member_count": len(members),
            "valid_member_count": int(stat.get("valid_member_count") or 0),
            "avg_return_1d": stat.get("avg_return_1d"),
            "median_return_1d": stat.get("median_return_1d"),
            "up_ratio": stat.get("up_ratio"),
            "amount": stat.get("amount"),
            "amount_ratio": amount_5 / amount_prior_20 if amount_5 is not None and amount_prior_20 not in (None, 0) else None,
            "return_5d": return_5,
            "return_20d": return_20,
            "return_60d": return_60,
            "relative_return_5d": return_5 - benchmark[5] if return_5 is not None and benchmark[5] is not None else None,
            "relative_return_20d": return_20 - benchmark[20] if return_20 is not None and benchmark[20] is not None else None,
            "relative_return_60d": return_60 - benchmark[60] if return_60 is not None and benchmark[60] is not None else None,
            "breadth_ma5": ma5,
            "breadth_ma20": ma20,
            "breadth_ma60": ma60,
            "new_high_20_ratio": high20,
            "new_high_60_ratio": high60,
        }

    rs5 = _percentiles({key: value["relative_return_5d"] for key, value in raw.items()})
    rs20 = _percentiles({key: value["relative_return_20d"] for key, value in raw.items()})
    rs60 = _percentiles({key: value["relative_return_60d"] for key, value in raw.items()})
    return20 = _percentiles({key: value["return_20d"] for key, value in raw.items()})
    ma20 = _percentiles({key: value["breadth_ma20"] for key, value in raw.items()})
    ma60 = _percentiles({key: value["breadth_ma60"] for key, value in raw.items()})
    high20 = _percentiles({key: value["new_high_20_ratio"] for key, value in raw.items()})
    up = _percentiles({key: value["up_ratio"] for key, value in raw.items()})
    amount_ratio = _percentiles({key: value["amount_ratio"] for key, value in raw.items()})
    amount_rank = _percentiles({key: value["amount"] for key, value in raw.items()})
    for sector, value in raw.items():
        trend_parts = (return20[sector], ma20[sector], ma60[sector], high20[sector])
        breadth_parts = (up[sector], ma20[sector], ma60[sector], high20[sector])
        volume_parts = (amount_ratio[sector], amount_rank[sector])
        value["rs5_score"] = rs5[sector]
        value["rs20_score"] = rs20[sector]
        value["rs60_score"] = rs60[sector]
        value["trend_score"] = sum(weight * float(part) for weight, part in zip((0.4, 0.3, 0.2, 0.1), trend_parts, strict=True)) if all(part is not None for part in trend_parts) else None
        value["breadth_score"] = sum(weight * float(part) for weight, part in zip((0.3, 0.35, 0.2, 0.15), breadth_parts, strict=True)) if all(part is not None for part in breadth_parts) else None
        value["volume_score"] = 0.6 * float(volume_parts[0]) + 0.4 * float(volume_parts[1]) if all(part is not None for part in volume_parts) else None
        value["sector_score"] = (
            0.3 * float(rs20[sector]) + 0.25 * float(value["trend_score"])
            + 0.25 * float(value["breadth_score"]) + 0.2 * float(value["volume_score"])
            if rs20[sector] is not None and value["trend_score"] is not None and value["breadth_score"] is not None and value["volume_score"] is not None else None
        )

    history = load_rotation_history(repo.store.data_dir, kind=kind)
    sector_ids = [f"{kind}:{level or 'all'}:{sector}" for sector in raw]
    prior = _prior_changes(history, sector_ids=sector_ids, dates=used_dates, index=target_index)
    rows: list[dict[str, object]] = []
    for sector, value in raw.items():
        sector_id = f"{kind}:{level or 'all'}:{sector}"
        previous = prior[sector_id]
        for lag, key in ((1, "score_delta_1d"), (3, "score_delta_3d"), (5, "score_delta_5d")):
            old = previous.get(f"previous_{lag}")
            value[key] = float(value["sector_score"]) - float(old) if value["sector_score"] is not None and old is not None else None
        old_up = previous.get("previous_up_ratio_3d")
        value["up_ratio_delta_3d"] = float(value["up_ratio"]) - float(old_up) if value["up_ratio"] is not None and old_up is not None else None
        complete = all(value.get(key) is not None for key in ("rs20_score", "trend_score", "breadth_score", "volume_score", "sector_score"))
        rows.append({
            "date": target,
            "kind": kind,
            "level": level if kind == "industry" else None,
            "sector_id": sector_id,
            "name": names.get(sector, sector),
            "membership_as_of": membership_as_of,
            "membership_source": membership_source,
            "benchmark_id": "all_stock_equal_weight",
            "data_status": "complete" if complete else "partial",
            **value,
        })
    # `level` is null for concepts, but must still retain the nullable integer
    # dtype used by industry facts.  Otherwise the first same-day industry
    # write (Int64) makes the following concept upsert (Null) fail on its
    # composite join key.
    return (
        pl.DataFrame(rows).with_columns(pl.col("level").cast(pl.Int64)).sort(
            ["kind", "sector_score", "sector_id"], descending=[False, True, False]
        )
        if rows
        else pl.DataFrame()
    )


def upsert_rotation_history(data_dir: Path, new_rows: pl.DataFrame) -> None:
    """Replace complete `(date, kind, level)` fact sets atomically by key."""
    if new_rows.is_empty():
        return
    # Keep the public write boundary robust for callers that construct a
    # concept-only frame (where Polars otherwise infers the all-null column as
    # `Null`).
    new_rows = new_rows.with_columns(pl.col("level").cast(pl.Int64))
    path = rotation_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = load_rotation_history(data_dir)
    if old.is_empty():
        combined = new_rows
    else:
        keys = new_rows.select(["date", "kind", "level"]).unique()
        kept = old.join(keys, on=["date", "kind", "level"], how="anti", nulls_equal=True)
        combined = pl.concat([kept.select(new_rows.columns), new_rows], how="vertical_relaxed")
    temporary = path.with_suffix(".tmp")
    combined.sort(["date", "kind", "level", "sector_id"]).write_parquet(temporary)
    temporary.replace(path)


def compute_rotation_incremental(repo, data_dir: Path, *, as_of: date | None = None) -> dict[str, int]:
    """Compute current daily facts after the THS snapshot capture succeeds."""
    _dates, target = rps_rotation._history_dates(repo, as_of)
    if target is None:
        return {"industry": 0, "concept": 0}
    counts: dict[str, int] = {}
    for kind, level in (("industry", 3), ("concept", None)):
        rows = build_rotation_day(repo, kind=kind, level=level, as_of=target)
        if not rows.is_empty():
            upsert_rotation_history(data_dir, rows)
        counts[kind] = rows.height
    return counts
