"""Read-only current-state descriptive validation for Sector Strength and RS.

This deliberately does not calculate a forward return, signal efficacy, or
candidate-pool threshold.  It asks only whether the frozen scores sort the
historical inputs they were designed to describe, using data available at each
``as_of`` close.

Example:
    uv run --frozen python scripts/run_sector_rs_description_validation.py \
        --data-dir ../data --start 2024-01-02 --end 2024-12-02 --include-samples
"""
# ruff: noqa: RUF001
from __future__ import annotations

import argparse
from array import array
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from app.services import relative_strength, rps_rotation
from scripts.run_sector_rs_independent_validation import ReadOnlyRepo

SIGNAL_START = date(2024, 1, 2)
SIGNAL_END = date(2024, 12, 2)
TIERS = ("Top 10%", "10%-30%", "30%-50%", "Bottom 50%")
SECTOR_FIELDS = (
    "return_3d", "return_5d", "return_10d", "return_20d",
    "relative_return_3d", "relative_return_5d", "relative_return_10d", "relative_return_20d",
    "up_ratio", "strong_stock_ratio", "persistence_days", "rank_std_5d",
)
RS_FIELDS = (
    "stock_return_3d", "stock_return_5d", "stock_return_10d", "stock_return_20d", "stock_return_60d",
    "vs_market_3d", "vs_market_5d", "vs_market_10d", "vs_market_20d", "vs_market_60d",
    "vs_sector_3d", "vs_sector_5d", "vs_sector_10d", "vs_sector_20d", "vs_sector_60d",
    "market_percentile", "sector_percentile",
)
SAMPLE_DATES = (
    date(2024, 1, 31), date(2024, 2, 28), date(2024, 3, 29), date(2024, 4, 30),
    date(2024, 5, 31), date(2024, 6, 28), date(2024, 7, 31), date(2024, 8, 30),
    date(2024, 9, 30), date(2024, 11, 29),
)


def _tier(percentile: float | None) -> str | None:
    if percentile is None:
        return None
    if percentile >= 90.0:
        return "Top 10%"
    if percentile >= 70.0:
        return "10%-30%"
    if percentile >= 50.0:
        return "30%-50%"
    return "Bottom 50%"


def _load_panel(data_dir: Path, start: date, end: date) -> tuple[pl.DataFrame, list[date]]:
    """Load enough exact prior sessions for the frozen 60d RS window."""
    glob = str(data_dir / "kline_daily_enriched" / "**" / "*.parquet")
    dates = (
        pl.scan_parquet(glob).select("date").unique().sort("date").collect()
        .get_column("date").to_list()
    )
    signals = [current for current in dates if start <= current <= end]
    if not signals:
        raise ValueError("requested period contains no enriched trading dates")
    first = dates.index(signals[0])
    # 83 is the current Sector Strength bounded historical requirement;
    # include one preceding row so change_pct can be derived from close exactly.
    raw_start = dates[max(0, first - 84)]
    panel = (
        pl.scan_parquet(glob)
        .filter(pl.col("date").is_between(raw_start, signals[-1]))
        .select(["symbol", "date", "close"])
        .sort(["symbol", "date"])
        .with_columns((pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("change_pct"))
        .filter(pl.col("date").is_between(dates[max(0, first - 83)], signals[-1]))
        .select(["symbol", "date", "close", "change_pct"])
        .collect()
    )
    return panel, signals


def _num(value: object, *, pct: bool = False) -> str:
    if value is None or not np.isfinite(float(value)):
        return "—"
    return f"{float(value) * 100:.2f}%" if pct else f"{float(value):.3f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ])


def _append(values: dict[tuple[str, str], array], tier: str | None, row, fields: tuple[str, ...]) -> None:
    if tier is None:
        return
    for field in fields:
        value = getattr(row, field)
        if value is not None and np.isfinite(float(value)):
            values[(tier, field)].append(float(value))


def _summary(values: dict[tuple[str, str], array], fields: tuple[str, ...]) -> list[list[str]]:
    rows: list[list[str]] = []
    for field in fields:
        is_percent = field not in {"persistence_days", "rank_std_5d", "market_percentile", "sector_percentile"}
        for tier in TIERS:
            raw = values[(tier, field)]
            if not raw:
                rows.append([field, tier, "0", "—", "—", "—", "—", "—", "—"])
                continue
            series = np.frombuffer(raw, dtype=np.float64)
            rows.append([
                field, tier, str(len(raw)), _num(np.mean(series), pct=is_percent),
                _num(np.median(series), pct=is_percent), _num(np.quantile(series, .10), pct=is_percent),
                _num(np.quantile(series, .25), pct=is_percent), _num(np.quantile(series, .75), pct=is_percent),
                _num(np.quantile(series, .90), pct=is_percent),
            ])
    return rows


def _sector_sample(rows, title: str) -> str:
    selected = rows[:10] if title == "Top 10" else list(reversed(rows[-10:]))
    output = []
    for row in selected:
        output.append([
            row.sector_id, row.name, _num(row.score), _num(row.rank), _num(row.percentile),
            *[_num(getattr(row, f"return_{window}d"), pct=True) for window in (3, 5, 10, 20)],
            *[_num(getattr(row, f"relative_return_{window}d"), pct=True) for window in (3, 5, 10, 20)],
            _num(row.up_ratio, pct=True), _num(row.strong_stock_ratio, pct=True),
            _num(row.persistence_days), _num(row.rank_std_5d),
        ])
    return _table(
        ["sector_id", "name", "score", "rank", "percentile", "r3", "r5", "r10", "r20",
         "rel3", "rel5", "rel10", "rel20", "up", "strong", "persistence", "rank_std_5d"], output
    )


def _rs_sample(rows, close_by_symbol: dict[str, float], title: str) -> str:
    selected = rows[:20] if title == "Top 20" else list(reversed(rows[-20:]))
    output = []
    for row in selected:
        output.append([
            row.symbol, row.sector_name, _num(close_by_symbol.get(row.symbol)), _num(row.rs_score),
            _num(row.market_rank), _num(row.market_percentile), _num(row.sector_rank), _num(row.sector_percentile),
            *[_num(getattr(row, f"stock_return_{window}d"), pct=True) for window in (3, 5, 10, 20, 60)],
            *[_num(getattr(row, f"vs_market_{window}d"), pct=True) for window in (3, 5, 10, 20, 60)],
            *[_num(getattr(row, f"vs_sector_{window}d"), pct=True) for window in (3, 5, 10, 20, 60)],
        ])
    return _table(
        ["symbol", "industry", "close", "rs_score", "market_rank", "market_pct", "sector_rank", "sector_pct",
         "r3", "r5", "r10", "r20", "r60", "vm3", "vm5", "vm10", "vm20", "vm60",
         "vs3", "vs5", "vs10", "vs20", "vs60"], output
    )


def run_validation(
    data_dir: Path, start: date, end: date, *, include_samples: bool, only_dates: set[date] | None = None
) -> str:
    panel, signal_dates = _load_panel(data_dir, start, end)
    if only_dates is not None:
        signal_dates = [current for current in signal_dates if current in only_dates]
        if not signal_dates:
            raise ValueError("none of --dates are enriched trading dates")
    repo = ReadOnlyRepo(panel.drop("close"), data_dir)
    sector_values: dict[tuple[str, str], array] = defaultdict(lambda: array("d"))
    rs_values: dict[tuple[str, str], array] = defaultdict(lambda: array("d"))
    sample_days = set(SAMPLE_DATES).intersection(signal_dates)
    sample_output: list[str] = []
    industry_ids: list[str] | None = None
    quality: dict[str, int] = defaultdict(int)

    for current in signal_dates:
        sectors = rps_rotation.build_sector_strength(repo, kind="industry", level=1, as_of=current)
        if not sectors:
            quality["missing_sector_days"] += 1
            continue
        sectors = sorted((row for row in sectors if row.score is not None), key=lambda row: (row.rank or 10**9, row.sector_id))
        if industry_ids is None:
            industry_ids = [row.sector_id for row in sectors]
        for row in sectors:
            _append(sector_values, _tier(row.percentile), row, SECTOR_FIELDS)

        rs_rows = relative_strength.build_relative_strength(repo, sector_ids=industry_ids, as_of=current)
        # Level-1 industry yields one stable context per symbol.  Keep the guard
        # explicit so an unexpected mapping issue cannot create duplicate rows.
        per_symbol = {row.symbol: row for row in rs_rows if row.sector_level == 1 and row.rs_score is not None}
        if len(per_symbol) != len([row for row in rs_rows if row.sector_level == 1 and row.rs_score is not None]):
            quality["duplicate_industry_context_dates"] += 1
        ranks, percentiles = rps_rotation._rank_values({symbol: row.rs_score for symbol, row in per_symbol.items()})
        ranked_rs = sorted(per_symbol.values(), key=lambda row: (ranks[row.symbol], row.symbol))
        for row in ranked_rs:
            _append(rs_values, _tier(percentiles[row.symbol]), row, RS_FIELDS)

        if include_samples and current in sample_days:
            close_by_symbol = {
                str(row["symbol"]).upper(): float(row["close"])
                for row in panel.filter(pl.col("date") == current).select(["symbol", "close"]).iter_rows(named=True)
                if row["close"] is not None
            }
            sample_output.extend([
                f"## 人工样本：{current}", "", "### Sector Top 10", "", _sector_sample(sectors, "Top 10"),
                "", "### Sector Bottom 10", "", _sector_sample(sectors, "Bottom 10"),
                "", "### RS Top 20", "", _rs_sample(ranked_rs, close_by_symbol, "Top 20"),
                "", "### RS Bottom 20", "", _rs_sample(ranked_rs, close_by_symbol, "Bottom 20"), "",
            ])

    lines = [
        "# Sector Strength / Relative Strength 描述正确性验证", "",
        "## 范围", "",
        f"- 信号日：{signal_dates[0]} 至 {signal_dates[-1]}，共 {len(signal_dates)} 个交易日。",
        "- 每条观测仅使用该 `as_of` 收盘时及之前的 enriched 前复权 close 派生的日收益。",
        "- 本运行器不计算未来收益、T+N、MAE/MFE、Profit Factor、阈值或候选池。",
        "- Sector 使用一级行业；RS 每个 symbol 只保留其唯一一级行业 context，避免概念多归属重复计数。",
        "- RS 分层基于同日最终 `rs_score` 的降序横截面 percentile，而不是 `market_percentile` 或 `sector_percentile` 单独分层。",
        "",
        "## Sector Score 分层：截至当日原始字段分布", "",
        _table(["field", "tier", "n", "mean", "median", "p10", "p25", "p75", "p90"], _summary(sector_values, SECTOR_FIELDS)),
        "", "## RS Score 分层：截至当日原始字段分布", "",
        _table(["field", "tier", "n", "mean", "median", "p10", "p25", "p75", "p90"], _summary(rs_values, RS_FIELDS)),
        "", "## 数据完整性", "",
        f"- 无 Sector 结果的信号日：{quality['missing_sector_days']}。",
        f"- 检测到多个一级行业 context 的信号日：{quality['duplicate_industry_context_dates']}。",
        "- 缺失窗口会令对应原始字段为 unavailable，未被伪装为零；各字段的 n 因此可能不同。",
    ]
    if include_samples:
        lines.extend(["", "# 十个交易日人工样本", "", *sample_output])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--start", type=date.fromisoformat, default=SIGNAL_START)
    parser.add_argument("--end", type=date.fromisoformat, default=SIGNAL_END)
    parser.add_argument(
        "--dates", type=str,
        help="comma-separated exact signal dates; useful for reproducible cross-quarter manual samples",
    )
    parser.add_argument("--include-samples", action="store_true", help="append ten raw Top/Bottom sample tables")
    parser.add_argument(
        "--section", choices=("all", "sector", "rs", "quality"), default="all",
        help="print one compact summary section; useful for terminal review",
    )
    args = parser.parse_args()
    only_dates = None
    if args.dates:
        requested = [date.fromisoformat(value.strip()) for value in args.dates.split(",") if value.strip()]
        if not requested:
            raise ValueError("--dates must contain at least one ISO date")
        args.start, args.end = min(requested), max(requested)
        only_dates = set(requested)
    report = run_validation(
        args.data_dir.resolve(), args.start, args.end,
        include_samples=args.include_samples, only_dates=only_dates,
    )
    if args.section == "sector":
        report = report.split("## Sector Score 分层：截至当日原始字段分布", 1)[1].split("## RS Score 分层", 1)[0]
    elif args.section == "rs":
        report = report.split("## RS Score 分层：截至当日原始字段分布", 1)[1].split("## 数据完整性", 1)[0]
    elif args.section == "quality":
        report = "## 数据完整性" + report.split("## 数据完整性", 1)[1].split("# 十个交易日人工样本", 1)[0]
    print(report, end="")


if __name__ == "__main__":
    main()
