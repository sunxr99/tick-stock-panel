"""Independent, resumable SW1/SW2/SW3 Sector validation (Validation-48).

Run ``--smoke`` once, then launch without it through the companion PowerShell
starter.  Every completed signal date is checkpointed before the next starts.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import time
import traceback
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import run_right_side_sw_sector_hierarchy_common_universe_ablation as base
import run_right_side_sw_sector_single_level_ablation as single
from run_wyckoff_top20_backtest import (
    COHORT_ALL,
    HORIZONS,
    _attach_forward_returns,
    _engine,
    _load_prices,
    _load_trading_dates,
    _signal_rows,
)

from app.tickflow.repository import DataStore, KlineRepository

DISCOVERY = {
    "2025-12-15", "2025-12-18", "2026-01-30", "2026-02-26",
    "2026-03-10", "2026-03-26", "2026-04-13", "2026-05-12",
    "2026-05-21", "2026-06-17", "2026-07-20", "2026-08-10",
}
RANDOM_SEED = 20260919
BOOTSTRAP_SEED = 20260920
SAMPLE_SIZE = 48
BOOTSTRAP_REPS = 10_000
GROUPS = single.GROUPS


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path, default: object) -> object:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _log(output: Path) -> logging.Logger:
    output.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sw_sector_validation_v4")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(output, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _market_regimes(data_dir: Path, dates: list[date]) -> dict[date, str]:
    repo = KlineRepository(DataStore(data_dir))
    index = repo.get_index_daily("000001.SH", min(dates), max(dates), columns=["date", "close"])
    frame = index.to_pandas().sort_values("date")
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["return_20d"] = pd.to_numeric(frame["close"], errors="coerce").pct_change(20)
    return {
        row.date: "UP" if row.return_20d >= 0.03 else "DOWN" if row.return_20d <= -0.03 else "SIDEWAYS"
        for row in frame.itertuples(index=False) if pd.notna(row.return_20d)
    }


def _select_dates(data_dir: Path) -> dict[str, object]:
    trading = _load_trading_dates(data_dir)
    regimes = _market_regimes(data_dir, trading)
    eligible = [
        value for index, value in enumerate(trading)
        if index >= 80 and index + max(HORIZONS) < len(trading)
        and value.isoformat() not in DISCOVERY and value in regimes
        and value >= date(2023, 12, 1)
    ]
    by_month: dict[str, list[date]] = {}
    for value in eligible:
        by_month.setdefault(value.strftime("%Y-%m"), []).append(value)
    rng = random.Random(RANDOM_SEED)
    months = sorted(by_month)
    if len(months) > SAMPLE_SIZE:
        months = sorted(rng.sample(months, SAMPLE_SIZE))
    selected = [rng.choice(by_month[key]) for key in months]
    remaining = [value for value in eligible if value not in selected]
    # Fill from the currently least represented regime, then fixed-seed choice.
    while len(selected) < SAMPLE_SIZE:
        counts = {name: sum(regimes[value] == name for value in selected) for name in ("UP", "SIDEWAYS", "DOWN")}
        target = min(counts, key=lambda name: (counts[name], name))
        options = [value for value in remaining if regimes[value] == target] or remaining
        chosen = rng.choice(options)
        selected.append(chosen)
        remaining.remove(chosen)
    selected = sorted(selected)
    return {
        "random_seed": RANDOM_SEED,
        "sample_size": SAMPLE_SIZE,
        "discovery_dates_excluded": sorted(DISCOVERY),
        "selection_method": "one fixed-seed draw per available month, then fixed-seed least-regime-balanced draws",
        "eligible_count": len(eligible),
        "dates": [{"signal_date": item.isoformat(), "regime": regimes[item]} for item in selected],
    }


def _daily_frame(repo: KlineRepository, engine, label_prices: pl.DataFrame, benchmark_prices: pl.DataFrame, trading: list[date], current: date, regime: str, data_dir: Path) -> tuple[pd.DataFrame, int, pd.DataFrame]:
    # Candidate rows contain optional enum-like diagnostics.  Scan all rows so
    # Polars cannot infer a null-only column from its default first 100 rows.
    replay_rows = _signal_rows(repo=repo, engine=engine, dates=[current], chunk_size=1, progress_path=None)
    replay = pl.DataFrame(replay_rows, infer_schema_length=None)
    cohort = _attach_forward_returns(replay.filter(pl.col("cohort") == COHORT_ALL), label_prices, trading, benchmark_prices)
    if cohort.is_empty():
        raise RuntimeError(f"ALL_WYCKOFF empty: {current}")
    source = cohort.to_pandas()
    source["signal_date"] = pd.to_datetime(source["signal_date"]).dt.date
    frozen_rs = {str(row.symbol).upper(): value for row in source[["symbol", "rs_score"]].itertuples(index=False) if (value := base._finite(row.rs_score)) is not None}
    scored, _, _ = base._score_day(repo, data_dir, current, source["symbol"].tolist(), frozen_rs)
    frame = source.merge(scored, on="symbol", how="left", validate="one_to_one")
    _, common = single._build_groups(frame)
    common["regime"] = regime
    return common, len(source), frame


def _groups_from_daily(daily_dir: Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    frames = [pd.read_parquet(path) for path in sorted(daily_dir.glob("signal_date=*.parquet"))]
    if not frames:
        return {}, pd.DataFrame()
    common = pd.concat(frames, ignore_index=True)
    groups: dict[str, pd.DataFrame] = {}
    for name, suffix in zip(GROUPS, single.SUFFIXES, strict=True):
        groups[name] = pd.concat([
            day.sort_values([f"opportunity_{suffix}", "symbol"], ascending=[False, True], kind="stable").head(base.TOP_N)
            for _, day in common.groupby("signal_date", sort=True)
        ], ignore_index=True)
    return groups, common


def _bootstrap(portfolios: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    rows: list[dict[str, object]] = []
    for left, right in ((GROUPS[1], GROUPS[0]), (GROUPS[2], GROUPS[0])):
        for horizon in HORIZONS:
            merged = portfolios[left].query("horizon == @horizon").merge(portfolios[right].query("horizon == @horizon"), on="signal_date", suffixes=("_left", "_right"))
            values = (merged["portfolio_return_left"] - merged["portfolio_return_right"]).to_numpy(float)
            if not len(values):
                continue
            samples = values[rng.integers(0, len(values), size=(BOOTSTRAP_REPS, len(values)))]
            for statistic, sample_values, observed in (("mean_delta_return", samples.mean(axis=1), values.mean()), ("median_delta_return", np.median(samples, axis=1), np.median(values))):
                rows.append({"comparison": f"{left} - {right}", "horizon": horizon, "statistic": statistic, "date_count": len(values), "estimate": observed, "ci95_low": np.quantile(sample_values, .025), "ci95_high": np.quantile(sample_values, .975), "bootstrap_seed": BOOTSTRAP_SEED})
    return pd.DataFrame(rows)


def _regime_summary(groups: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for group, frame in groups.items():
        for regime in ("ALL", "UP", "SIDEWAYS", "DOWN"):
            subset = frame if regime == "ALL" else frame.loc[frame["regime"] == regime]
            for horizon in HORIZONS:
                metric = base._stock_metrics(subset, horizon)
                rows.append({"group": group, "regime": regime, "horizon": horizon, **metric})
    return pd.DataFrame(rows)


def _decision(groups: dict[str, pd.DataFrame], portfolios: dict[str, pd.DataFrame], expected: int) -> str:
    raw, _ = single._decision(groups, portfolios, expected)
    # Discovery was NO_STABLE_DIFFERENCE; a new preferred winner would not be
    # replication of that finding and is deliberately labelled as such.
    return "DISCOVERY_NOT_REPLICATED" if raw not in {"NO_STABLE_DIFFERENCE", "INSUFFICIENT"} else raw


def _report(output: Path, dates: dict[str, object], coverage: list[list[object]], groups: dict[str, pd.DataFrame], portfolios: dict[str, pd.DataFrame], final: str, bootstrap: pd.DataFrame, regime: pd.DataFrame, overlap: pd.DataFrame, concentration: pd.DataFrame, comparison: pd.DataFrame) -> None:
    lines = [
        "# Right-side SW Sector Independent Validation V4", "", f"**Final status: `{final}`**", "",
        "## Frozen contract", "", "Expanded exploratory validation: only pure SW1/SW2/SW3 SectorStrength changes. Frozen Wyckoff, Legacy snapshot RSScore, 0.40/0.60 Opportunity weights, N>=8 gate, Top150, VP, RiskBucket, labels and T+5/T+10/T+20 are unchanged. No SW2/SW3 RS, fallback, zero-fill or tuning is used.", "",
        "## Discovery Random-12", "", "Discovery dates remain immutable and excluded: " + ", ".join(sorted(DISCOVERY)) + ". Discovery concluded `NO_STABLE_DIFFERENCE`.", "",
        "## Validation sampling", "", str(dates["selection_method"]) + f" Random seed: `{RANDOM_SEED}`.", "",
        "## Validation-48 dates", "", base._markdown_table(["signal date", "regime"], [[item["signal_date"], item["regime"]] for item in dates["dates"]]), "",
        "## Coverage", "", base._markdown_table(["date", "frozen", "SW1 valid", "SW1 <8", "SW1 missing", "SW1 ambiguous", "SW1 coverage", "SW2 valid", "SW2 <8", "SW2 missing", "SW2 ambiguous", "SW2 coverage", "SW3 valid", "SW3 <8", "SW3 missing", "SW3 ambiguous", "SW3 coverage", "common sector", "common rankable", "common coverage"], coverage), "",
        "## SW1/SW2/SW3 performance", "", base._markdown_table(["group", "horizon", "n", "mean return", "median return", "mean excess", "median excess", "positive rate", "mean MAE", "mean MFE", "portfolio return", "portfolio MDD", "beat dates"], base._summary_rows(groups, portfolios)), "",
        "## Date-level comparison", "", base._markdown_table(list(comparison.columns), comparison.fillna("—").values.tolist()), "",
        "## Bootstrap CI", "", base._markdown_table(list(bootstrap.columns), [[base._fmt(value, percent=key in {"estimate", "ci95_low", "ci95_high"}) if key in {"estimate", "ci95_low", "ci95_high"} else value for key, value in row.items()] for row in bootstrap.to_dict("records")]), "",
        "## Regime results", "", "Descriptive only; no dynamic regime model is implied. Any apparent split is `FUTURE_RESEARCH`.", "", base._markdown_table(list(regime.columns), regime.fillna("—").values.tolist()), "",
        "## Top150 overlap", "", base._markdown_table(list(overlap.columns), overlap.values.tolist()), "",
        "## Industry concentration", "", base._markdown_table(list(concentration.columns), concentration.values.tolist()), "",
        "## Discovery vs Validation", "", "Compare this independent Validation-48 result with the immutable Discovery Random-12 above. No result is used to change seed, dates, weights or gate.", "",
        "## PIT limitation", "", "This is expanded exploratory validation only: the available SW2021 membership store lacks complete historical exit history, so it is not strict PIT proof.", "",
        "## Final decision", "", f"`{final}`. Sector hierarchy research is frozen after this run; no further sampling, weight, gate, horizon or regime adaptation is authorized.", "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/research/sw_sector_validation_v4"))
    parser.add_argument("--report", type=Path, default=Path("../docs/right-side-sw-sector-independent-validation-v4.md"))
    parser.add_argument("--log-file", type=Path, default=Path("../logs/sw_sector_validation_v4.log"))
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    data_dir, output, report = args.data_dir.resolve(), args.output_dir.resolve(), args.report.resolve()
    logger = _log(args.log_file.resolve())
    logger.info("START smoke=%s", args.smoke)
    dates_path, progress_path, daily_dir = output / "validation_dates.json", output / "progress.json", output / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    dates = _read_json(dates_path, None) or _select_dates(data_dir)
    _write_json(dates_path, dates)
    selected = [(date.fromisoformat(item["signal_date"]), item["regime"]) for item in dates["dates"]]
    logger.info("Validation dates %s", ",".join(item.isoformat() for item, _ in selected))
    progress = _read_json(progress_path, {"status": "running", "date_runs": {}})
    trading = _load_trading_dates(data_dir)
    label_prices = _load_prices(data_dir, min(item[0] for item in selected), trading[trading.index(max(item[0] for item in selected)) + max(HORIZONS)])
    repo = KlineRepository(DataStore(data_dir))
    benchmark_prices = repo.get_index_daily("000001.SH", min(item[0] for item in selected), trading[trading.index(max(item[0] for item in selected)) + max(HORIZONS)], columns=["date", "open", "close"])
    portfolio_prices = base._history(repo, data_dir, min(item[0] for item in selected))
    engine = _engine(data_dir)
    targets = selected[:1] if args.smoke else selected
    for ordinal, (current, regime) in enumerate(targets, 1):
        key, path = current.isoformat(), daily_dir / f"signal_date={current}.parquet"
        if path.exists() and progress.get("date_runs", {}).get(key, {}).get("status") == "complete":
            logger.info("resume %s/%s %s", ordinal, len(targets), key)
            continue
        started = time.perf_counter()
        try:
            frame, candidate_count, full_frame = _daily_frame(repo, engine, label_prices, benchmark_prices, trading, current, regime, data_dir)
            frame.to_parquet(path, index=False)
            progress.setdefault("date_runs", {})[key] = {"status": "complete", "seconds": round(time.perf_counter()-started, 2), "candidate_count": candidate_count, "common_eligible_count": len(frame), "regime": regime, "coverage": base._coverage_rows(full_frame)[0]}
            progress["completed"] = sum(item.get("status") == "complete" for item in progress["date_runs"].values())
            progress["current"] = key
            _write_json(progress_path, progress)
            logger.info("%s/%s %s seconds=%.2f candidates=%s common=%s", ordinal, len(targets), key, time.perf_counter()-started, progress["date_runs"][key]["candidate_count"], len(frame))
        except Exception:
            progress.setdefault("date_runs", {})[key] = {"status": "failed", "traceback": traceback.format_exc()}
            _write_json(progress_path, progress)
            logger.exception("date failure %s", key)
            if args.smoke:
                raise
    groups, _common = _groups_from_daily(daily_dir)
    if not groups:
        raise RuntimeError("no completed daily checkpoints")
    portfolios = base._portfolio_all(groups, portfolio_prices, sorted(portfolio_prices["date"].unique()))
    summary = pd.DataFrame(base._summary_rows(groups, portfolios), columns=["group", "horizon", "n", "mean_return", "median_return", "mean_excess", "median_excess", "positive_rate", "mean_mae", "mean_mfe", "portfolio_return", "portfolio_mdd", "beat_benchmark_dates"])
    comparison = pd.DataFrame(single._pairwise_date_rows(portfolios), columns=["comparison", "horizon", "matched_dates", "wins_ties_losses", "mean_delta_return", "median_delta_return", "healthier_mdd_dates", "mean_delta_mdd"])
    bootstrap = _bootstrap(portfolios)
    regime = _regime_summary(groups)
    _, overlap_average = single._overlap_rows(groups)
    overlap = pd.DataFrame(overlap_average, columns=["comparison", "mean_overlap", "mean_replaced", "mean_jaccard"])
    concentration = pd.DataFrame(base._concentration_rows(groups), columns=["group", "level", "largest_share", "top3_share", "industry_count", "missing"])
    for name, frame in {"summary.csv": summary, "date_comparison.csv": comparison, "bootstrap.csv": bootstrap, "regime_summary.csv": regime, "overlap.csv": overlap, "industry_concentration.csv": concentration}.items():
        frame.to_csv(output / name, index=False)
    coverage = [progress["date_runs"][item.isoformat()]["coverage"] for item, _ in selected if progress["date_runs"].get(item.isoformat(), {}).get("status") == "complete"]
    final = "INSUFFICIENT" if args.smoke else _decision(groups, portfolios, len(selected))
    final_payload = {"status": final, "smoke": args.smoke, "completed_dates": sorted(progress["date_runs"]), "random_seed": RANDOM_SEED, "bootstrap_seed": BOOTSTRAP_SEED, "generated_at": datetime.now().isoformat()}
    _write_json(output / "final_result.json", final_payload)
    _report(report, dates, coverage, groups, portfolios, final, bootstrap, regime, overlap, concentration, comparison)
    logger.info("bootstrap end; report generated %s; FINISHED", report)


if __name__ == "__main__":
    main()
