"""Read-only 通达信 88 板块轮动事实。

TDX concept, industry, style, and region boards are flat categories, not a
hierarchy. Facts and membership are saved by ``trade_date`` so historical
pages never join current members to an earlier board date.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

TDX_RECENT_DIR = "tdx_board_history_recent"
_INDEX_FILE = "tdx_index.parquet"
_DAILY_FILE = "tdx_daily.parquet"
_MEMBER_COLUMNS = ("trade_date", "ts_code", "con_code", "con_name")
_CATEGORY_TYPES = {
    "concept": "概念板块",
    "industry": "行业板块",
    "style": "风格板块",
}
_INDEX_REQUIRED = {"ts_code", "trade_date", "name", "idx_type"}
_DAILY_REQUIRED = {"ts_code", "trade_date", "close", "pct_change", "amount", "turnover_rate", "up_num", "down_num"}


def index_path(data_dir: Path) -> Path:
    return data_dir / TDX_RECENT_DIR / _INDEX_FILE


def daily_path(data_dir: Path) -> Path:
    return data_dir / TDX_RECENT_DIR / _DAILY_FILE


def member_path(data_dir: Path, *, trade_date: date) -> Path:
    return data_dir / TDX_RECENT_DIR / "tdx_members" / f"trade_date={trade_date:%Y%m%d}" / "part.parquet"


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema={
        "date": pl.Date,
        "ts_code": pl.Utf8,
        "name": pl.Utf8,
        "category": pl.Utf8,
        "idx_type": pl.Utf8,
        "close": pl.Float64,
        "pct_change": pl.Float64,
        "amount": pl.Float64,
        "turnover_rate": pl.Float64,
        "up_num": pl.Int64,
        "down_num": pl.Int64,
        "return_5d": pl.Float64,
        "return_5d_percentile": pl.Float64,
    })


def _read(path: Path, required: set[str]) -> pl.DataFrame | None:
    if not path.exists():
        return None
    try:
        frame = pl.read_parquet(path)
    except Exception as exc:
        logger.warning("load TDX board file failed (%s): %s", path, exc)
        return None
    if not required.issubset(frame.columns):
        logger.warning("TDX board file has incompatible schema (%s): %s", path, frame.columns)
        return None
    return frame


def load_hot_rotation_history(data_dir: Path) -> pl.DataFrame:
    """Load persisted TDX board facts and calculate a five-session return."""
    index = _read(index_path(data_dir), _INDEX_REQUIRED)
    daily = _read(daily_path(data_dir), _DAILY_REQUIRED)
    if index is None or daily is None:
        return _empty()
    index = index.select("ts_code", "trade_date", "name", "idx_type").unique()
    frame = daily.join(index, on=["ts_code", "trade_date"], how="inner").with_columns(
        pl.col("trade_date").cast(pl.Utf8).str.strptime(pl.Date, "%Y%m%d", strict=False).alias("date"),
        pl.col("pct_change").cast(pl.Float64, strict=False),
        pl.col("close").cast(pl.Float64, strict=False),
        pl.col("amount").cast(pl.Float64, strict=False),
        pl.col("turnover_rate").cast(pl.Float64, strict=False),
        pl.col("up_num").cast(pl.Int64, strict=False),
        pl.col("down_num").cast(pl.Int64, strict=False),
    ).drop_nulls(["date", "ts_code", "name", "idx_type"])
    if frame.is_empty():
        return _empty()
    frame = frame.with_columns(
        pl.when(pl.col("idx_type") == _CATEGORY_TYPES["concept"]).then(pl.lit("concept"))
        .when(pl.col("idx_type") == _CATEGORY_TYPES["industry"]).then(pl.lit("industry"))
        .when(pl.col("idx_type") == _CATEGORY_TYPES["style"]).then(pl.lit("style"))
        .otherwise(pl.lit("region"))
        .alias("category")
    ).sort(["ts_code", "date"])
    frame = frame.with_columns(
        (
            ((pl.lit(1.0) + pl.col("pct_change") / 100.0).log().rolling_sum(window_size=5, min_samples=5).over("ts_code").exp() - 1.0)
            * 100.0
        ).alias("return_5d")
    )
    return frame.with_columns(
        pl.when(pl.col("return_5d").is_not_null() & (pl.col("return_5d").count().over("date") > 1))
        .then((pl.col("return_5d").rank(method="average").over("date") - 1.0) / (pl.col("return_5d").count().over("date") - 1.0) * 100.0)
        .otherwise(None)
        .alias("return_5d_percentile")
    ).select(_empty().columns).sort(["date", "pct_change", "ts_code"], descending=[False, True, False])


def latest_hot_rotation(data_dir: Path, *, category: str = "concept") -> pl.DataFrame:
    frame = load_hot_rotation_history(data_dir)
    if frame.is_empty():
        return frame
    latest = frame.get_column("date").max()
    frame = frame.filter(pl.col("date") == latest)
    if category != "all":
        frame = frame.filter(pl.col("category") == category)
    return frame.sort(["pct_change", "return_5d", "ts_code"], descending=[True, True, False])


def hot_rotation_history(data_dir: Path, *, ts_code: str, limit: int) -> pl.DataFrame:
    return load_hot_rotation_history(data_dir).filter(
        pl.col("ts_code") == ts_code.upper()
    ).sort("date", descending=True).head(limit).sort("date")


def load_hot_rotation_members(data_dir: Path, *, trade_date: date, ts_code: str) -> pl.DataFrame:
    """Return exact-date TDX members for one 88xxxx.TDX board."""
    frame = _read(member_path(data_dir, trade_date=trade_date), set(_MEMBER_COLUMNS))
    if frame is None:
        return pl.DataFrame(schema={column: pl.Utf8 for column in _MEMBER_COLUMNS})
    return frame.filter(
        (pl.col("trade_date") == trade_date.strftime("%Y%m%d")) & (pl.col("ts_code") == ts_code.upper())
    ).select(_MEMBER_COLUMNS).unique().sort("con_code")
