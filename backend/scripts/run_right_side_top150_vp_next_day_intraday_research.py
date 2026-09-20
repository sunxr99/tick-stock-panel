"""Frozen random-12 next-day intraday VP-routing research.

This is deliberately a descriptive, one-session study.  It reads the frozen
Top150 snapshots and their existing risk labels.  It does not treat the
next-day high as an executable fill: high is reported solely as MFE.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl

from app.parquet import scan_enriched_parquet

BUCKETS = ("LOW", "MEDIUM", "HIGH", "EXTREME")
PORTFOLIOS = {
    "B0": ("ALL_KNOWN_TOP150", BUCKETS),
    "B2": ("HIGH", ("HIGH",)),
    "B3": ("EXTREME", ("EXTREME",)),
    "B4": ("HIGH+EXTREME", ("HIGH", "EXTREME")),
}
MINIMUM_MINUTE_BARS = 216  # Same 90% complete-day guard as the API.


def _load_trading_dates(data_dir: Path) -> list[date]:
    source = scan_enriched_parquet(str(data_dir / "kline_daily_enriched" / "**" / "*.parquet"))
    return source.select(pl.col("date").unique().sort()).collect().get_column("date").to_list()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt(value: object, *, pct: bool = False) -> str:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return "—"
    return f"{float(value) * 100:.2f}%" if pct else f"{float(value):.2f}"


def _table(headers: list[str], rows: list[list[object]]) -> str:
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *["| " + " | ".join(map(str, row)) + " |" for row in rows],
    ])


def _prepare_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["signal_date"] = pd.to_datetime(result["signal_date"]).dt.date
    result["symbol"] = result["symbol"].astype(str)
    result["v0_rank"] = pd.to_numeric(result["v0_rank"], errors="coerce")
    return result.loc[result["v0_rank"].le(150)].copy()


def _portfolio_intraday_path(selected: pd.DataFrame, minute: pd.DataFrame) -> dict[str, object] | None:
    """Return equal-weight close-NAV path and separate individual high/low MFE.

    A portfolio high cannot be manufactured by averaging each stock's daily
    high because those highs normally occur at different minutes.  Therefore
    portfolio MFE/MAE use the synchronized one-minute close NAV, while
    constituent high/low excursions are retained as descriptive fields.
    """
    if selected.empty or minute.empty:
        return None
    rows = minute.loc[minute["symbol"].isin(selected["symbol"]), ["symbol", "datetime", "open", "high", "low", "close"]].copy()
    rows["datetime"] = pd.to_datetime(rows["datetime"])
    rows = rows.sort_values(["symbol", "datetime"])
    counts = rows.groupby("symbol").size()
    valid_symbols = counts.loc[counts.ge(MINIMUM_MINUTE_BARS)].index.astype(str).tolist()
    rows = rows.loc[rows["symbol"].isin(valid_symbols)]
    if not valid_symbols:
        return None

    first = rows.groupby("symbol", sort=False).first(numeric_only=False)
    last = rows.groupby("symbol", sort=False).last(numeric_only=False)
    valid_symbols = [
        symbol for symbol in valid_symbols
        if float(first.loc[symbol, "open"]) > 0 and float(last.loc[symbol, "close"]) > 0
    ]
    rows = rows.loc[rows["symbol"].isin(valid_symbols)]
    if not valid_symbols:
        return None

    entry = first.loc[valid_symbols, "open"].astype(float)
    closes = rows.pivot(index="datetime", columns="symbol", values="close").reindex(columns=valid_symbols)
    # A stock with a gap is not made tradable by forward filling it.
    complete = closes.columns[closes.notna().all()].astype(str).tolist()
    if not complete:
        return None
    closes = closes[complete].astype(float)
    entry = entry.loc[complete]
    nav = closes.div(entry, axis="columns").mean(axis="columns")
    highs = rows.groupby("symbol")["high"].max().loc[complete].astype(float)
    lows = rows.groupby("symbol")["low"].min().loc[complete].astype(float)
    constituent_mfe = highs.div(entry).sub(1.0)
    constituent_mae = lows.div(entry).sub(1.0)
    return {
        "stock_count": len(complete),
        "excluded_incomplete": len(selected) - len(complete),
        "portfolio_return": float(nav.iloc[-1] - 1.0),
        "portfolio_close_path_mfe": float(nav.max() - 1.0),
        "portfolio_close_path_mae": float(nav.min() - 1.0),
        "portfolio_close_path_pullback": float(nav.iloc[-1] / nav.max() - 1.0),
        "avg_constituent_mfe_high": float(constituent_mfe.mean()),
        "median_constituent_mfe_high": float(constituent_mfe.median()),
        "avg_constituent_mae_low": float(constituent_mae.mean()),
        "positive_close_rate": float((last.loc[complete, "close"].astype(float).div(entry).sub(1.0) > 0).mean()),
        "positive_mfe_rate": float((constituent_mfe > 0).mean()),
    }


def _run(top150: pd.DataFrame, data_dir: Path, calendar: list[date]) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = {value: i for i, value in enumerate(calendar)}
    runs: list[dict[str, object]] = []
    coverage: list[dict[str, object]] = []
    for signal_date, day in top150.groupby("signal_date", sort=True):
        if signal_date not in index or index[signal_date] + 1 >= len(calendar):
            continue
        entry_date = calendar[index[signal_date] + 1]
        path = data_dir / "kline_minute" / f"date={entry_date.isoformat()}" / "part.parquet"
        unknown = int(day["risk_bucket"].eq("UNKNOWN").sum())
        coverage.append({
            "signal_date": signal_date.isoformat(), "entry_date": entry_date.isoformat(),
            "top150_count": len(day), "unknown_count": unknown, "minute_file_exists": path.exists(),
        })
        if not path.exists():
            continue
        symbols = day.loc[~day["risk_bucket"].eq("UNKNOWN"), "symbol"].astype(str).tolist()
        minute = pd.read_parquet(path, filters=[("symbol", "in", symbols)])
        for code, (label, buckets) in PORTFOLIOS.items():
            selected = day.loc[day["risk_bucket"].isin(buckets)].copy()
            result = _portfolio_intraday_path(selected, minute)
            if result is None:
                continue
            benchmark = pd.to_numeric(selected.get("benchmark_return_1d"), errors="coerce").dropna()
            benchmark_return = float(benchmark.iloc[0]) if not benchmark.empty else None
            runs.append({
                "signal_date": signal_date.isoformat(), "entry_date": entry_date.isoformat(),
                "portfolio": code, "portfolio_label": label, "stock_count_raw": len(selected),
                "benchmark_return": benchmark_return,
                "portfolio_excess_return": result["portfolio_return"] - benchmark_return if benchmark_return is not None else None,
                **result,
            })
    return pd.DataFrame(runs), pd.DataFrame(coverage)


def _summary_table(runs: pd.DataFrame) -> str:
    rows: list[list[object]] = []
    for code, (label, _buckets) in PORTFOLIOS.items():
        part = runs.loc[runs["portfolio"].eq(code)]
        rows.append([
            f"{code} {label}", len(part), _fmt(part["stock_count"].mean()),
            _fmt(part["portfolio_return"].mean(), pct=True), _fmt(part["portfolio_return"].median(), pct=True),
            _fmt(part["portfolio_excess_return"].mean(), pct=True), _fmt(part["portfolio_excess_return"].median(), pct=True),
            _fmt((part["portfolio_return"] > 0).mean(), pct=True),
            _fmt(part["portfolio_close_path_mfe"].mean(), pct=True), _fmt(part["portfolio_close_path_mae"].mean(), pct=True),
            _fmt(part["portfolio_close_path_pullback"].mean(), pct=True),
            _fmt(part["avg_constituent_mfe_high"].mean(), pct=True), _fmt(part["avg_constituent_mae_low"].mean(), pct=True),
            _fmt(part["positive_mfe_rate"].mean(), pct=True),
        ])
    return _table([
        "portfolio", "dates", "mean stocks", "mean close return", "median close return", "mean excess", "median excess",
        "positive close", "mean close-path MFE", "mean close-path MAE", "mean high-to-close pullback",
        "mean constituent high MFE", "mean constituent low MAE", "positive MFE rate",
    ], rows)


def _comparison_table(runs: pd.DataFrame) -> str:
    baseline = runs.loc[runs["portfolio"].eq("B0")].set_index("signal_date")
    rows: list[list[object]] = []
    for code in ("B2", "B3", "B4"):
        part = runs.loc[runs["portfolio"].eq(code)].set_index("signal_date").join(baseline, lsuffix="_group", rsuffix="_all", how="inner")
        for metric, label in (
            ("portfolio_return", "close return"),
            ("portfolio_close_path_mae", "close-path MAE"),
            ("avg_constituent_mfe_high", "constituent high MFE"),
        ):
            delta = part[f"{metric}_group"] - part[f"{metric}_all"]
            rows.append([f"{code} vs B0", label, len(delta), int((delta > 0).sum()), int((delta < 0).sum()), _fmt(delta.mean(), pct=True), _fmt(delta.median(), pct=True)])
    return _table(["comparison", "metric", "matched dates", "group better", "B0 better", "mean Δ", "median Δ"], rows)


def _date_table(runs: pd.DataFrame) -> str:
    rows: list[list[object]] = []
    for signal_date, part in runs.sort_values(["signal_date", "portfolio"]).groupby("signal_date", sort=True):
        indexed = part.set_index("portfolio")
        rows.append([
            signal_date, indexed["entry_date"].iloc[0],
            *[_fmt(indexed.loc[code, "portfolio_return"], pct=True) if code in indexed.index else "—" for code in PORTFOLIOS],
            *[_fmt(indexed.loc[code, "avg_constituent_mfe_high"], pct=True) if code in indexed.index else "—" for code in ("B2", "B3")],
        ])
    return _table(["signal date", "entry date", "B0 close", "B2 HIGH close", "B3 EXTREME close", "B4 close", "HIGH high MFE", "EXTREME high MFE"], rows)


def _render(runs: pd.DataFrame, coverage: pd.DataFrame) -> str:
    return "\n".join([
        "# Right-Side Top150 VP Next-Day Intraday Research V1", "",
        "## Frozen execution contract", "",
        "Uses the completed random-12 Top150 snapshots without rerunning Wyckoff, Sector/RS, VP, or changing RiskBucket. D close determines the risk route; D+1 Open buys an equal-weight group; D+1 Close sells. `HIGH` and `EXTREME` are never filtered or re-ranked.", "",
        "D+1 High is **not** an executable exit price. It is reported only as constituent MFE. Portfolio MFE/MAE use synchronized 1-minute close NAV, because different stocks peak at different minutes. No fees, slippage, limit-up/down execution, or intraday liquidity model is included; this is a descriptive path study, not a tradable strategy.", "",
        "## Coverage", "",
        _table(["signal date", "entry date", "Top150", "UNKNOWN", "minute partition"], [[row.signal_date, row.entry_date, row.top150_count, row.unknown_count, "present" if row.minute_file_exists else "missing"] for row in coverage.itertuples(index=False)]), "",
        "## 12-date summary", "", _summary_table(runs), "",
        "## Date-level results", "", _date_table(runs), "",
        "## Relative to all known-risk Top150", "", "For MAE, a positive delta is healthier because it is closer to zero.", "", _comparison_table(runs), "",
        "## Interpretation boundary", "",
        "This report can establish whether HIGH/EXTREME have more next-day upward excursion and whether that excursion survives to the close. It cannot claim that a trader can sell at the daily high. A real intraday exit test requires a pre-declared executable sell rule, which is intentionally outside this frozen experiment.",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen random-12 next-day intraday VP-routing research")
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--input-dir", type=Path, default=Path("../data/research/right_side_rank_research_v1_20260913"))
    parser.add_argument("--output-dir", type=Path, default=Path("../data/research/right_side_top150_vp_next_day_intraday_v1_20260913"))
    parser.add_argument("--report", type=Path, default=Path("../docs/right-side-top150-vp-next-day-intraday-v1.md"))
    args = parser.parse_args()
    data_dir, input_dir, output_dir = args.data_dir.resolve(), args.input_dir.resolve(), args.output_dir.resolve()
    state = _read_json(input_dir / "progress.json")
    if state.get("status") != "complete":
        raise ValueError("Rank Research V1 snapshots are incomplete")
    snapshots = sorted((input_dir / "snapshots").glob("signal_date=*.parquet"))
    if len(snapshots) != 12:
        raise ValueError(f"expected 12 frozen snapshots, found {len(snapshots)}")
    started = time.perf_counter()
    top150 = pd.concat([_prepare_snapshot(pd.read_parquet(path)) for path in snapshots], ignore_index=True)
    runs, coverage = _run(top150, data_dir, _load_trading_dates(data_dir))
    if runs.empty:
        raise RuntimeError("no intraday paths were produced")
    output_dir.mkdir(parents=True, exist_ok=True)
    runs.to_parquet(output_dir / "next_day_intraday_runs.parquet", index=False)
    coverage.to_parquet(output_dir / "coverage.parquet", index=False)
    _write_json(output_dir / "progress.json", {
        "status": "complete", "source": str(input_dir), "run_rows": len(runs),
        "signal_dates": sorted(runs["signal_date"].unique()), "elapsed_seconds": round(time.perf_counter() - started, 2),
    })
    args.report.resolve().write_text(_render(runs, coverage), encoding="utf-8")
    print(args.report.resolve())


if __name__ == "__main__":
    main()
