"""Read-only diagnostics for frozen Sector Strength V1.1 / RS V1.

This script deliberately calls the production calculation functions without
altering their definitions.  It prints reproducible audit evidence; it never
writes prices, memberships, scores, or strategy state.
"""
from __future__ import annotations

import argparse
from array import array
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from app.services import relative_strength, rps_rotation
from app.services.regime_builder import load_regime_history
from scripts.run_sector_rs_independent_validation import ReadOnlyRepo

HORIZONS = (1, 3, 5, 10, 20)
RS_FIELDS = (
    "vs_market_3d", "vs_market_5d", "vs_market_10d", "vs_market_20d",
    "vs_market_60d", "vs_sector_3d", "vs_sector_5d", "vs_sector_10d",
    "vs_sector_20d", "vs_sector_60d", "market_rs_score", "sector_rs_score", "rs_score",
)
SECTOR_FIELDS = (
    "relative_return_3d", "relative_return_5d", "relative_return_10d",
    "relative_return_20d", "up_ratio", "strong_stock_ratio",
    "persistence_days", "rank_std_5d",
)


def _pct(value: float | None) -> str:
    return "-" if value is None or not np.isfinite(value) else f"{value:.2%}"


def _number(value: float | None) -> str:
    return "-" if value is None or not np.isfinite(value) else f"{value:.3f}"


def _tier(percentile: float | None) -> str | None:
    if percentile is None or not np.isfinite(percentile):
        return None
    if percentile >= 90:
        return "Top 10%"
    if percentile >= 70:
        return "10%-30%"
    if percentile >= 50:
        return "30%-50%"
    return "Bottom 50%"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ])


def _load_panel(data_dir: Path, start: date, end: date) -> pl.DataFrame:
    # Extra sessions supply the 60-day signal lookback and T+20 labels.
    lower = start - timedelta(days=210)
    upper = end + timedelta(days=45)
    glob = str(data_dir / "kline_daily_enriched" / "**" / "*.parquet")
    return (
        pl.scan_parquet(glob, hive_partitioning=True)
        .filter((pl.col("date") >= lower) & (pl.col("date") <= upper))
        .select(["symbol", "date", "close", "raw_close", "volume", "amount"])
        .sort(["symbol", "date"])
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("change_pct")
        )
        .filter(pl.col("change_pct").is_not_null() & pl.col("change_pct").is_finite())
        .collect()
    )


def _build_matrix(panel: pl.DataFrame, value: str, dates: list[date]) -> tuple[np.ndarray, dict[str, int]]:
    wide = (
        panel.select(["date", "symbol", value])
        .pivot(index="date", on="symbol", values=value, aggregate_function="first")
        .sort("date")
    )
    available = wide.get_column("date").to_list()
    if available != dates:
        raise ValueError("panel date matrix is not aligned to the audit date sequence")
    symbols = [column for column in wide.columns if column != "date"]
    return wide.select(symbols).to_numpy().astype(float), {symbol: i for i, symbol in enumerate(symbols)}


def _forward_metrics(matrix: np.ndarray, at: int, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    values = matrix[at + 1:at + horizon + 1]
    if len(values) != horizon:
        return np.full(matrix.shape[1], np.nan), np.full(matrix.shape[1], np.nan)
    cumulative = np.cumprod(1.0 + values, axis=0) - 1.0
    return cumulative[-1], np.nanmin(cumulative, axis=0)


def _stats(returns: np.ndarray, excess: np.ndarray, mae: np.ndarray) -> dict[str, float | int | None]:
    valid = np.isfinite(returns) & np.isfinite(excess) & np.isfinite(mae)
    if not valid.any():
        return {"n": 0, "mean_excess": None, "median_excess": None, "positive_excess": None, "mae": None, "pf": None}
    ex, adverse = excess[valid], mae[valid]
    negative = ex[ex < 0].sum()
    positive = ex[ex > 0].sum()
    return {
        "n": len(ex),
        "mean_excess": float(ex.mean()),
        "median_excess": float(np.median(ex)),
        "positive_excess": float((ex > 0).mean()),
        "mae": float(adverse.mean()),
        "pf": None if negative == 0 else float(positive / abs(negative)),
    }


def _factor_rows(
    percentiles: dict[str, array],
    returns: dict[int, array],
    excess: dict[int, array],
    mae: dict[int, array],
) -> list[list[str]]:
    rows: list[list[str]] = []
    for field, values in percentiles.items():
        p = np.frombuffer(values, dtype=np.float32)
        for tier in ("Top 10%", "10%-30%", "30%-50%", "Bottom 50%"):
            mask = np.array([_tier(float(value)) == tier for value in p])
            for horizon in HORIZONS:
                stat = _stats(
                    np.frombuffer(returns[horizon], dtype=np.float32)[mask],
                    np.frombuffer(excess[horizon], dtype=np.float32)[mask],
                    np.frombuffer(mae[horizon], dtype=np.float32)[mask],
                )
                rows.append([
                    field, tier, f"T+{horizon}", str(stat["n"]),
                    _pct(stat["mean_excess"]), _pct(stat["median_excess"]),
                    _pct(stat["positive_excess"]), _pct(stat["mae"]), _number(stat["pf"]),
                ])
    return rows


def _append_sample(
    lines: list[str], target: date, regime: str | None, rows: list[object], closes: dict[str, float]
) -> None:
    complete = [row for row in rows if row.rs_score is not None]
    ordered = sorted(complete, key=lambda row: (-float(row.rs_score), row.symbol))
    lines.extend(["", f"### {target.isoformat()} ({regime or 'unknown regime'})", ""])
    headers = ["Bucket", "Symbol", "Industry", "Close", "r3/r5/r10/r20/r60", "vm3/vm5/vm10/vm20/vm60", "vs3/vs5/vs10/vs20/vs60", "MarketRS", "SectorRS", "RS", "Mkt rank/pct", "Sector rank/pct"]
    out: list[list[str]] = []
    for bucket, sample in (("Top", ordered[:20]), ("Bottom", list(reversed(ordered[-20:])))):
        for row in sample:
            out.append([
                bucket, row.symbol, row.sector_name, _number(closes.get(row.symbol)), "/".join(_pct(getattr(row, f"stock_return_{w}d")) for w in (3, 5, 10, 20, 60)),
                "/".join(_pct(getattr(row, f"vs_market_{w}d")) for w in (3, 5, 10, 20, 60)),
                "/".join(_pct(getattr(row, f"vs_sector_{w}d")) for w in (3, 5, 10, 20, 60)),
                _number(row.market_rs_score), _number(row.sector_rs_score), _number(row.rs_score),
                f"{row.market_rank}/{_number(row.market_percentile)}", f"{row.sector_rank}/{_number(row.sector_percentile)}",
            ])
    lines.append(_table(headers, out))


def _append_sector_sample(lines: list[str], target: date, rows: list[object]) -> None:
    ordered = sorted(rows, key=lambda row: (-float(row.score), row.name))
    lines.extend(["", f"### Sector {target.isoformat()}", ""])
    headers = ["Bucket", "Sector", "r3/r5/r10/r20", "rr3/rr5/rr10/rr20", "up", "strong", "momentum", "breadth", "persist", "score", "rank/pct"]
    out: list[list[str]] = []
    for bucket, sample in (("Top", ordered[:10]), ("Bottom", list(reversed(ordered[-10:])))):
        for row in sample:
            out.append([
                bucket, row.name, "/".join(_pct(getattr(row, f"return_{w}d")) for w in (3, 5, 10, 20)),
                "/".join(_pct(getattr(row, f"relative_return_{w}d")) for w in (3, 5, 10, 20)),
                _pct(row.up_ratio), _pct(row.strong_stock_ratio), _number(row.relative_momentum_score),
                _number(row.breadth_score), _number(row.persistence_score), _number(row.score),
                f"{row.rank}/{_number(row.percentile)}",
            ])
    lines.append(_table(headers, out))


def run_audit(data_dir: Path, year: int) -> str:
    start, end = date(year, 1, 2), date(year, 12, 2)
    panel = _load_panel(data_dir, start, end)
    dates = sorted(panel.get_column("date").unique().to_list())
    signals = [day for day in dates if start <= day <= end]
    repo = ReadOnlyRepo(panel.select(["symbol", "date", "change_pct"]), data_dir)
    market_daily = (
        panel.group_by("date").agg(pl.col("change_pct").mean().alias("market"))
        .sort("date").get_column("market").to_numpy().astype(float)
    )
    stock_matrix, symbol_index = _build_matrix(panel, "change_pct", dates)
    close_matrix, _ = _build_matrix(panel, "close", dates)

    loaded = rps_rotation._load_concept_map_df(repo, "industry")
    map_df = rps_rotation._normalized_map(loaded[0], "industry", 1)
    exact_symbols = panel.select(pl.col("symbol").str.to_uppercase().alias("_sym_up")).unique()
    matched_map = map_df.join(exact_symbols, on="_sym_up", how="inner")
    sector_panel = (
        panel.with_columns(pl.col("symbol").str.to_uppercase().alias("_sym_up"))
        .join(matched_map, on="_sym_up", how="inner")
        .group_by(["date", "industry"]).agg(pl.col("change_pct").mean().alias("change_pct"))
        .rename({"industry": "symbol"})
    )
    sector_matrix, sector_index = _build_matrix(sector_panel, "change_pct", dates)

    rs_percentiles = {field: array("f") for field in RS_FIELDS}
    sector_percentiles = {field: array("f") for field in SECTOR_FIELDS}
    rs_returns = {h: array("f") for h in HORIZONS}
    rs_excess = {h: array("f") for h in HORIZONS}
    rs_mae = {h: array("f") for h in HORIZONS}
    sector_returns = {h: array("f") for h in HORIZONS}
    sector_excess = {h: array("f") for h in HORIZONS}
    sector_mae = {h: array("f") for h in HORIZONS}
    regime_map = {row["date"]: str(row["state"]) for row in load_regime_history(data_dir).iter_rows(named=True)}
    wanted = [date(year, month, day) for month, day in ((1, 31), (2, 28), (3, 29), (4, 30), (5, 31), (6, 28), (7, 31), (8, 30), (9, 30), (11, 29))]
    sample_days = {max(day for day in signals if day <= candidate) for candidate in wanted if any(day <= candidate for day in signals)}
    samples: dict[date, list[object]] = {}
    sector_samples: dict[date, list[object]] = {}
    sample_closes: dict[date, dict[str, float]] = {}
    sanity: list[list[str]] = []
    dominance_anomalies: list[str] = []

    all_sector_ids: list[str] | None = None
    for current in signals:
        index = dates.index(current)
        sector_rows = rps_rotation.build_sector_strength(repo, kind="industry", level=1, as_of=current)
        if all_sector_ids is None:
            all_sector_ids = [row.sector_id for row in sector_rows]
        rs_rows = relative_strength.build_relative_strength(repo, sector_ids=all_sector_ids or [], as_of=current)
        complete_rs = [row for row in rs_rows if row.rs_score is not None and row.symbol in symbol_index]
        complete_sector = [row for row in sector_rows if row.score is not None and row.name in sector_index]

        stock_forward = {h: _forward_metrics(stock_matrix, index, h) for h in HORIZONS}
        market_forward = {h: _forward_metrics(market_daily[:, None], index, h)[0][0] for h in HORIZONS}
        sector_forward = {h: _forward_metrics(sector_matrix, index, h) for h in HORIZONS}

        for field in RS_FIELDS:
            values = {row.symbol: float(getattr(row, field)) for row in complete_rs if getattr(row, field) is not None}
            _, ranks = rps_rotation._rank_values(values)
            for row in complete_rs:
                rs_percentiles[field].append(float(ranks.get(row.symbol, np.nan)))
        for row in complete_rs:
            position = symbol_index[row.symbol]
            for h in HORIZONS:
                forward, adverse = stock_forward[h]
                rs_returns[h].append(float(forward[position]))
                rs_excess[h].append(float(forward[position] - market_forward[h]))
                rs_mae[h].append(float(adverse[position]))

        for field in SECTOR_FIELDS:
            values = {row.name: float(getattr(row, field)) for row in complete_sector if getattr(row, field) is not None}
            _, ranks = rps_rotation._rank_values(values)
            for row in complete_sector:
                sector_percentiles[field].append(float(ranks.get(row.name, np.nan)))
        for row in complete_sector:
            position = sector_index[row.name]
            for h in HORIZONS:
                forward, adverse = sector_forward[h]
                sector_returns[h].append(float(forward[position]))
                sector_excess[h].append(float(forward[position] - market_forward[h]))
                sector_mae[h].append(float(adverse[position]))

        if current in sample_days:
            samples[current] = complete_rs
            sector_samples[current] = complete_sector
            sample_closes[current] = {symbol: float(close_matrix[index, pos]) for symbol, pos in symbol_index.items()}
            ordered = sorted(complete_rs, key=lambda row: (-float(row.rs_score), row.symbol))
            top, bottom = ordered[:20], ordered[-20:]
            def mean_attr(rows: list[object], attr: str) -> float:
                return float(np.mean([float(getattr(row, attr)) for row in rows if getattr(row, attr) is not None]))
            sanity.append([
                current.isoformat(), regime_map.get(current, "unknown"),
                _pct(mean_attr(top, "stock_return_20d")), _pct(mean_attr(bottom, "stock_return_20d")),
                _pct(mean_attr(top, "vs_market_20d")), _pct(mean_attr(bottom, "vs_market_20d")),
                _pct(mean_attr(top, "vs_sector_20d")), _pct(mean_attr(bottom, "vs_sector_20d")),
            ])
            for high in top:
                for low in bottom:
                    attrs = [f"vs_market_{w}d" for w in (3, 5, 10, 20, 60)] + [f"vs_sector_{w}d" for w in (3, 5, 10, 20, 60)]
                    if all(getattr(high, attr) is not None and getattr(low, attr) is not None and getattr(high, attr) < getattr(low, attr) for attr in attrs):
                        dominance_anomalies.append(f"{current} high={high.symbol}({high.rs_score:.2f}) dominated by bottom={low.symbol}({low.rs_score:.2f})")
                        break

    lines = [f"# {year} Sector / RS 实现与数据审计原始输出", "", "## RS Top/Bottom sanity 汇总", "", _table(["Date", "Regime", "Top r20", "Bottom r20", "Top vm20", "Bottom vm20", "Top vs20", "Bottom vs20"], sanity)]
    lines.extend(["", f"Strict dominance anomalies (Top RS lower on all 10 relative returns): {len(dominance_anomalies)}"])
    lines.extend(dominance_anomalies[:20])
    lines.extend(["", "## Sector 单因子分层", "", _table(["Factor", "Tier", "H", "n", "Mean excess", "Median excess", "+ excess", "MAE", "PF"], _factor_rows(sector_percentiles, sector_returns, sector_excess, sector_mae))])
    lines.extend(["", "## RS 单因子分层", "", _table(["Factor", "Tier", "H", "n", "Mean excess", "Median excess", "+ excess", "MAE", "PF"], _factor_rows(rs_percentiles, rs_returns, rs_excess, rs_mae))])
    lines.extend(["", "## 固定样本的 RS Top 20 / Bottom 20", ""])
    for current in sorted(samples):
        _append_sample(lines, current, regime_map.get(current), samples[current], sample_closes[current])
        _append_sector_sample(lines, current, sector_samples[current])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--year", type=int, default=2024)
    args = parser.parse_args()
    print(run_audit(args.data_dir, args.year))


if __name__ == "__main__":
    main()
