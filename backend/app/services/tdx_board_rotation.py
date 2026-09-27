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

from app.services.sector_membership import canonicalize_member_map

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
# 通达信 ``idx_type`` 不提供行业层级字段。产品已确认将 8810xx--8814xx
# 这套互斥细分行业作为 Sector / RS / Wyckoff 共振的默认行业口径。
_RESONANCE_INDUSTRY_PREFIXES = ("8810", "8811", "8812", "8813", "8814")
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


def load_category_membership(
    data_dir: Path, *, trade_date: date, category: str
) -> pl.DataFrame:
    """Return one exact-date TDX category snapshot with board identifiers.

    The API does not expose a hierarchy field for TDX industry boards.  Rows
    are therefore intentionally returned as flat board memberships instead of
    inferring parent/child links from board codes or names.
    """
    idx_type = _CATEGORY_TYPES.get(category)
    schema = {
        "trade_date": pl.Utf8,
        "ts_code": pl.Utf8,
        "name": pl.Utf8,
        "con_code": pl.Utf8,
        "con_name": pl.Utf8,
    }
    if idx_type is None:
        raise ValueError(f"unsupported TDX category: {category!r}")
    index = _read(index_path(data_dir), _INDEX_REQUIRED)
    members = _read(member_path(data_dir, trade_date=trade_date), set(_MEMBER_COLUMNS))
    if index is None or members is None:
        return pl.DataFrame(schema=schema)
    target = trade_date.strftime("%Y%m%d")
    index = index.filter(
        (pl.col("trade_date").cast(pl.Utf8) == target)
        & (pl.col("idx_type") == idx_type)
    ).select("trade_date", "ts_code", "name").unique()
    members = members.filter(pl.col("trade_date").cast(pl.Utf8) == target)
    if index.is_empty() or members.is_empty():
        return pl.DataFrame(schema=schema)
    return (
        members.join(index, on=["trade_date", "ts_code"], how="inner")
        .select("trade_date", "ts_code", "name", "con_code", "con_name")
        .unique()
        .sort(["ts_code", "con_code"])
    )


def load_industry_member_map(data_dir: Path, *, as_of: date) -> pl.DataFrame:
    """Build the canonical TDX 881 fine-industry map for one published session.

    ``tdx_industry`` stores the board code as its stable calculation key and
    keeps the human-readable board name separately.  A missing exact snapshot
    returns no mapping; it never falls back to a newer constituent list.
    """
    memberships = load_resonance_industry_membership(data_dir, trade_date=as_of)
    schema = {"_sym_up": pl.Utf8, "tdx_industry": pl.Utf8, "_sector_display_name": pl.Utf8}
    if memberships.is_empty():
        return pl.DataFrame(schema=schema)
    raw = memberships.select(
        pl.col("con_code").alias("_sym_up"),
        pl.col("ts_code").alias("tdx_industry"),
    )
    canonical = canonicalize_member_map(raw, "tdx_industry")
    display = memberships.select(
        "ts_code",
        pl.concat_str([pl.col("name"), pl.lit(" ["), pl.col("ts_code"), pl.lit("]")]).alias("_sector_display_name"),
    ).unique().rename({"ts_code": "tdx_industry"})
    return canonical.join(display, on="tdx_industry", how="left").sort(["tdx_industry", "_sym_up"])


def load_resonance_industry_membership(data_dir: Path, *, trade_date: date) -> pl.DataFrame:
    """Return the default single-taxonomy TDX industry memberships for resonance.

    ``8810xx`` through ``8814xx`` are deliberately selected after the exact-date
    industry snapshot is loaded.  No ``8802xx`` regional board, ``8803xx`` /
    ``8804xx`` parallel industry board, or future membership list can enter the
    Sector / RS / Wyckoff resonance calculation.
    """
    memberships = load_category_membership(data_dir, trade_date=trade_date, category="industry")
    if memberships.is_empty():
        return memberships
    return memberships.filter(
        pl.col("ts_code").str.slice(0, 4).is_in(_RESONANCE_INDUSTRY_PREFIXES)
    ).sort(["ts_code", "con_code"])


def top_category_board_names(
    data_dir: Path, *, trade_date: date, category: str, limit: int
) -> list[str]:
    """Return exact-date board labels ordered by the published TDX momentum."""
    if limit <= 0:
        return []
    frame = load_hot_rotation_history(data_dir)
    if frame.is_empty():
        return []
    selected = frame.filter((pl.col("date") == trade_date) & (pl.col("category") == category))
    if selected.is_empty():
        return []
    return [
        f"{row['name']} [{row['ts_code']}]"
        for row in selected.sort(["pct_change", "return_5d", "ts_code"], descending=[True, True, False])
        .head(limit)
        .iter_rows(named=True)
    ]
