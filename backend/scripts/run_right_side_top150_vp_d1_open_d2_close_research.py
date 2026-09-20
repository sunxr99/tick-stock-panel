"""Frozen random-12 VP bucket comparison: D+1 Open to D+2 Close."""
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
    "B1": ("LOW", ("LOW",)),
    "B2": ("MEDIUM", ("MEDIUM",)),
    "B3": ("HIGH", ("HIGH",)),
    "B4": ("EXTREME", ("EXTREME",)),
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


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


def _load_prices_and_calendar(data_dir: Path) -> tuple[pd.DataFrame, list[date]]:
    source = scan_enriched_parquet(str(data_dir / "kline_daily_enriched" / "**" / "*.parquet"))
    frame = source.select(["symbol", "date", "open", "close"]).collect()
    calendar = frame.select(pl.col("date").unique().sort()).get_column("date").to_list()
    return frame.to_pandas(), calendar


def _prepare_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["symbol"] = result["symbol"].astype(str)
    result["signal_date"] = pd.to_datetime(result["signal_date"]).dt.date
    result["v0_rank"] = pd.to_numeric(result["v0_rank"], errors="coerce")
    return result.loc[result["v0_rank"].le(150)].copy()


def _returns(selected: pd.DataFrame, entry_prices: pd.DataFrame, exit_prices: pd.DataFrame) -> pd.DataFrame:
    result = selected[["symbol"]].merge(entry_prices[["symbol", "open"]], on="symbol", how="inner")
    result = result.merge(exit_prices[["symbol", "close"]], on="symbol", how="inner")
    result["open"] = pd.to_numeric(result["open"], errors="coerce")
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result = result.loc[(result["open"] > 0) & (result["close"] > 0)].copy()
    result["return"] = result["close"] / result["open"] - 1.0
    return result


def _run(top150: pd.DataFrame, prices: pd.DataFrame, calendar: list[date]) -> tuple[pd.DataFrame, pd.DataFrame]:
    date_index = {value: index for index, value in enumerate(calendar)}
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    runs, coverage = [], []
    for signal_date, day in top150.groupby("signal_date", sort=True):
        if signal_date not in date_index or date_index[signal_date] + 2 >= len(calendar):
            continue
        entry_date, exit_date = calendar[date_index[signal_date] + 1], calendar[date_index[signal_date] + 2]
        entry = prices.loc[prices["date"].eq(entry_date), ["symbol", "open"]]
        exit_ = prices.loc[prices["date"].eq(exit_date), ["symbol", "close"]]
        coverage.append({"signal_date": signal_date.isoformat(), "entry_date": entry_date.isoformat(), "exit_date": exit_date.isoformat(), "top150_count": len(day), "unknown_count": int(day["risk_bucket"].eq("UNKNOWN").sum())})
        for code, (label, buckets) in PORTFOLIOS.items():
            selected = day.loc[day["risk_bucket"].isin(buckets)]
            returned = _returns(selected, entry, exit_)
            if returned.empty:
                continue
            values = returned["return"]
            # The frozen benchmark label is D+1 Open -> T+3 Close, so it is
            # deliberately not reused for this two-session execution window.
            runs.append({"signal_date": signal_date.isoformat(), "entry_date": entry_date.isoformat(), "exit_date": exit_date.isoformat(), "portfolio": code, "portfolio_label": label, "stock_count_raw": len(selected), "stock_count": len(returned), "excluded_missing_price": len(selected) - len(returned), "equal_weight_return": float(values.mean()), "median_stock_return": float(values.median()), "positive_rate": float((values > 0).mean()), "loss_rate": float((values < 0).mean()), "p25_return": float(values.quantile(.25)), "p75_return": float(values.quantile(.75))})
    return pd.DataFrame(runs), pd.DataFrame(coverage)


def _summary(runs: pd.DataFrame) -> str:
    rows = []
    for code, (label, _buckets) in PORTFOLIOS.items():
        part = runs.loc[runs["portfolio"].eq(code)]
        rows.append([f"{code} {label}", len(part), _fmt(part["stock_count"].mean()), _fmt(part["equal_weight_return"].mean(), pct=True), _fmt(part["equal_weight_return"].median(), pct=True), _fmt(part["median_stock_return"].mean(), pct=True), _fmt(part["positive_rate"].mean(), pct=True), _fmt(part["loss_rate"].mean(), pct=True), _fmt(part["p25_return"].mean(), pct=True), _fmt(part["p75_return"].mean(), pct=True)])
    return _table(["portfolio", "dates", "mean stocks", "mean return", "median date return", "mean stock median", "positive rate", "loss rate", "mean P25", "mean P75"], rows)


def _date_table(runs: pd.DataFrame) -> str:
    rows = []
    for signal_date, part in runs.sort_values(["signal_date", "portfolio"]).groupby("signal_date", sort=True):
        indexed = part.set_index("portfolio")
        rows.append([signal_date, indexed["entry_date"].iloc[0], indexed["exit_date"].iloc[0], *[_fmt(indexed.loc[code, "equal_weight_return"], pct=True) if code in indexed.index else "—" for code in PORTFOLIOS]])
    return _table(["signal date", "entry D+1", "exit D+2", "B0 all", "B1 LOW", "B2 MEDIUM", "B3 HIGH", "B4 EXTREME"], rows)


def _comparison(runs: pd.DataFrame) -> str:
    baseline = runs.loc[runs["portfolio"].eq("B0")].set_index("signal_date")
    rows = []
    for code in ("B1", "B2", "B3", "B4"):
        part = runs.loc[runs["portfolio"].eq(code)].set_index("signal_date").join(baseline, lsuffix="_group", rsuffix="_all", how="inner")
        delta = part["equal_weight_return_group"] - part["equal_weight_return_all"]
        rows.append([f"{code} vs B0", len(delta), int((delta > 0).sum()), int((delta < 0).sum()), _fmt(delta.mean(), pct=True), _fmt(delta.median(), pct=True)])
    return _table(["comparison", "matched dates", "group return wins", "B0 wins", "mean Δ return", "median Δ return"], rows)


def _render(runs: pd.DataFrame, coverage: pd.DataFrame) -> str:
    return "\n".join([
        "# Right-Side Top150 VP D+1 Open to D+2 Close V1", "",
        "## Frozen execution contract", "", "D close selects the frozen Top150 and its existing VP RiskBucket. The equal-weight portfolio buys at each constituent's D+1 Open and sells at D+2 Close. This is a two-session, executable-price research return; no fees, slippage, limit-price, suspension, or liquidity execution model is included.", "", "No Wyckoff, OpportunityScore, Top150 size, VP state, or risk bucket is recalculated. UNKNOWN is excluded from every formal group. The frozen benchmark labels use a different horizon, so this focused comparison reports raw portfolio returns rather than mismatched excess returns.", "",
        "## Coverage", "", _table(["signal date", "entry D+1", "exit D+2", "Top150", "UNKNOWN"], [[row.signal_date, row.entry_date, row.exit_date, row.top150_count, row.unknown_count] for row in coverage.itertuples(index=False)]), "",
        "## 12-date summary", "", _summary(runs), "",
        "## Date-level returns", "", _date_table(runs), "",
        "## Relative to all known-risk Top150", "", _comparison(runs), "",
        "## Boundary", "", "This is not a claim that any RiskBucket should receive trading priority. It is a fixed, two-session comparison on the existing random-12 sample only.",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen Top150 VP D+1 Open to D+2 Close research")
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--input-dir", type=Path, default=Path("../data/research/right_side_rank_research_v1_20260913"))
    parser.add_argument("--output-dir", type=Path, default=Path("../data/research/right_side_top150_vp_d1_open_d2_close_v1_20260913"))
    parser.add_argument("--report", type=Path, default=Path("../docs/right-side-top150-vp-d1-open-d2-close-v1.md"))
    args = parser.parse_args()
    data_dir, input_dir, output_dir = args.data_dir.resolve(), args.input_dir.resolve(), args.output_dir.resolve()
    if _read_json(input_dir / "progress.json").get("status") != "complete":
        raise ValueError("Rank Research V1 snapshots are incomplete")
    snapshots = sorted((input_dir / "snapshots").glob("signal_date=*.parquet"))
    if len(snapshots) != 12:
        raise ValueError(f"expected 12 frozen snapshots, found {len(snapshots)}")
    started = time.perf_counter()
    top150 = pd.concat([_prepare_snapshot(pd.read_parquet(path)) for path in snapshots], ignore_index=True)
    prices, calendar = _load_prices_and_calendar(data_dir)
    runs, coverage = _run(top150, prices, calendar)
    if runs.empty:
        raise RuntimeError("no executable two-session paths were produced")
    output_dir.mkdir(parents=True, exist_ok=True)
    runs.to_parquet(output_dir / "runs.parquet", index=False)
    coverage.to_parquet(output_dir / "coverage.parquet", index=False)
    (output_dir / "progress.json").write_text(json.dumps({"status": "complete", "run_rows": len(runs), "elapsed_seconds": round(time.perf_counter() - started, 2)}, ensure_ascii=False, indent=2), encoding="utf-8")
    args.report.resolve().write_text(_render(runs, coverage), encoding="utf-8")
    print(args.report.resolve())


if __name__ == "__main__":
    main()
