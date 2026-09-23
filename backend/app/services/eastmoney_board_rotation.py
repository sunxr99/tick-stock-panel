"""Read-only 东方财富概念板块轮动 facts.

The downloader stores ``dc_index`` independently from the existing SW and
同花顺 membership stores.  This service intentionally consumes the supplied
Eastmoney board facts directly: it does not turn the vendor's percentage
change into the project's frozen Sector Strength score, and it never joins a
current member basket onto a historical board date.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from app.services.eastmoney_concept_taxonomy import TAXONOMY_VERSION, classify_concept

logger = logging.getLogger(__name__)

EASTMONEY_RECENT_DIR = "eastmoney_board_history_recent"
_INDEX_FILE = "dc_index.parquet"
_CONCEPT_TYPE = "概念板块"
_MEMBER_COLUMNS = ("trade_date", "ts_code", "con_code", "name")
_REQUIRED_COLUMNS = {
    "ts_code", "trade_date", "name", "leading", "leading_code", "pct_change",
    "leading_pct", "total_mv", "turnover_rate", "up_num", "down_num", "idx_type",
}


def index_path(data_dir: Path) -> Path:
    return data_dir / EASTMONEY_RECENT_DIR / _INDEX_FILE


def member_path(data_dir: Path, *, trade_date: date) -> Path:
    return data_dir / EASTMONEY_RECENT_DIR / "dc_members" / f"trade_date={trade_date:%Y%m%d}" / "part.parquet"


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema={
        "date": pl.Date,
        "ts_code": pl.Utf8,
        "name": pl.Utf8,
        "category": pl.Utf8,
        "classification_reason": pl.Utf8,
        "taxonomy_version": pl.Utf8,
        "leading": pl.Utf8,
        "leading_code": pl.Utf8,
        "pct_change": pl.Float64,
        "leading_pct": pl.Float64,
        "total_mv": pl.Float64,
        "turnover_rate": pl.Float64,
        "up_num": pl.Int64,
        "down_num": pl.Int64,
        "return_5d": pl.Float64,
        "return_5d_percentile": pl.Float64,
    })


def _session_dates(frame: pl.DataFrame) -> pl.DataFrame:
    """Remove calendar-day copies emitted by ``dc_index`` on non-sessions.

    The endpoint publishes unchanged board snapshots for weekends and some
    holidays.  A five-*session* return must not count those copies as extra
    observations.  Comparing aggregate facts across all boards is robust to a
    single board being unchanged on a real session while still retaining the
    first available snapshot.
    """
    daily = frame.group_by("date").agg(
        pl.len().alias("_rows"),
        pl.col("pct_change").sum().alias("_pct_sum"),
        pl.col("pct_change").pow(2).sum().alias("_pct_square_sum"),
        pl.col("leading_pct").sum().alias("_leading_pct_sum"),
        pl.col("leading_pct").pow(2).sum().alias("_leading_pct_square_sum"),
        pl.col("up_num").sum().alias("_up_sum"),
        pl.col("down_num").sum().alias("_down_sum"),
    ).sort("date")
    changed = pl.any_horizontal(*[
        pl.col(column).ne(pl.col(column).shift(1))
        for column in (
            "_rows", "_pct_sum", "_pct_square_sum", "_leading_pct_sum",
            "_leading_pct_square_sum", "_up_sum", "_down_sum",
        )
    ]).fill_null(True)
    return daily.filter(changed).select("date")


def load_hot_rotation_history(data_dir: Path) -> pl.DataFrame:
    """Load point-in-time 东方财富概念板块 facts and five-session return."""
    path = index_path(data_dir)
    if not path.exists():
        return _empty()
    try:
        raw = pl.read_parquet(path)
    except Exception as exc:
        logger.warning("load Eastmoney board history failed: %s", exc)
        return _empty()
    if not _REQUIRED_COLUMNS.issubset(raw.columns):
        logger.warning("Eastmoney board history has an incompatible schema: %s", raw.columns)
        return _empty()
    frame = raw.filter(pl.col("idx_type") == _CONCEPT_TYPE).with_columns(
        pl.col("trade_date").cast(pl.Utf8).str.strptime(pl.Date, "%Y%m%d", strict=False).alias("date"),
        pl.col("pct_change").cast(pl.Float64, strict=False),
        pl.col("leading_pct").cast(pl.Float64, strict=False),
        pl.col("turnover_rate").cast(pl.Float64, strict=False),
        pl.col("total_mv").cast(pl.Float64, strict=False),
    ).drop_nulls(["date", "ts_code"])
    if frame.is_empty():
        return _empty()
    classifications = [classify_concept(str(name)) for name in frame.get_column("name").to_list()]
    frame = frame.with_columns(
        pl.Series("category", [item.category for item in classifications]),
        pl.Series("classification_reason", [item.reason for item in classifications]),
        pl.lit(TAXONOMY_VERSION).alias("taxonomy_version"),
    )
    frame = frame.join(_session_dates(frame), on="date", how="inner").sort(["ts_code", "date"])
    frame = frame.with_columns(
        (
            (
                (pl.lit(1.0) + pl.col("pct_change") / 100.0)
                .log()
                .rolling_sum(window_size=5, min_samples=5)
                .over("ts_code")
                .exp()
                - 1.0
            )
            * 100.0
        ).alias("return_5d")
    )
    return frame.with_columns(
        pl.when(pl.col("return_5d").is_not_null() & (pl.col("return_5d").count().over("date") > 1))
        .then(
            (
                pl.col("return_5d").rank(method="average").over("date") - 1.0
            ) / (pl.col("return_5d").count().over("date") - 1.0) * 100.0
        )
        .otherwise(None)
        .alias("return_5d_percentile")
    ).select(_empty().columns).sort(["date", "pct_change", "ts_code"], descending=[False, True, False])


def latest_hot_rotation(data_dir: Path, *, category: str = "theme") -> pl.DataFrame:
    """Return all concept boards on the latest available Eastmoney session."""
    frame = load_hot_rotation_history(data_dir)
    if frame.is_empty():
        return frame
    latest = frame.get_column("date").max()
    latest_frame = frame.filter(pl.col("date") == latest)
    if category != "all":
        latest_frame = latest_frame.filter(pl.col("category") == category)
    return latest_frame.sort(["pct_change", "return_5d", "ts_code"], descending=[True, True, False])


def hot_rotation_history(data_dir: Path, *, ts_code: str, limit: int) -> pl.DataFrame:
    """Return one board's available session series, oldest first."""
    return load_hot_rotation_history(data_dir).filter(
        pl.col("ts_code") == ts_code.upper()
    ).sort("date", descending=True).head(limit).sort("date")


def load_hot_rotation_members(data_dir: Path, *, trade_date: date, ts_code: str) -> pl.DataFrame:
    """Return the exact-date Eastmoney member relation for one concept board."""
    path = member_path(data_dir, trade_date=trade_date)
    if not path.exists():
        return pl.DataFrame(schema={column: pl.Utf8 for column in _MEMBER_COLUMNS})
    try:
        frame = pl.read_parquet(path)
    except Exception as exc:
        logger.warning("load Eastmoney board members failed: %s", exc)
        return pl.DataFrame(schema={column: pl.Utf8 for column in _MEMBER_COLUMNS})
    if not set(_MEMBER_COLUMNS).issubset(frame.columns):
        logger.warning("Eastmoney board member history has an incompatible schema: %s", frame.columns)
        return pl.DataFrame(schema={column: pl.Utf8 for column in _MEMBER_COLUMNS})
    trade_date_text = trade_date.strftime("%Y%m%d")
    return frame.filter(
        (pl.col("trade_date") == trade_date_text) & (pl.col("ts_code") == ts_code.upper())
    ).select(_MEMBER_COLUMNS).unique().sort("con_code")
