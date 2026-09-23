# ruff: noqa: I001, RUF001  # Conditional import and Chinese report copy are intentional.

"""Monthly walk-forward validation for the unverified Wyckoff research rank.

This script replays the current formal funnel on dates selected before any
forward return is read.  It compares the named ``research_candidate_score``
only as a research cohort definition: it never changes the live strategy.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

import polars as pl
try:  # Package import for tests and module execution.
    from scripts.run_wyckoff_current_random12_backtest import (
        DEFAULT_START,
        _attach_forward_returns,
        _eligible_dates,
        _load_prices,
        _load_trading_dates,
        _parse_date,
        _signal_row,
        _strategy_dirs,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from run_wyckoff_current_random12_backtest import (  # type: ignore[no-redef]
        DEFAULT_START,
        _attach_forward_returns,
        _eligible_dates,
        _load_prices,
        _load_trading_dates,
        _parse_date,
        _signal_row,
        _strategy_dirs,
    )
try:  # Package import for tests and module execution.
    from scripts.run_wyckoff_top20_backtest import HORIZONS
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from run_wyckoff_top20_backtest import HORIZONS  # type: ignore[no-redef]

from app.services.screener import ScreenerService
from app.strategy import config as strategy_config
from app.strategy.engine import StrategyEngine
from app.tickflow.repository import DataStore, KlineRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_SEED = 20260921
DEFAULT_MAX_DATES = 24
DEFAULT_COHORT_SIZE = 150


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _select_monthly_dates(eligible: list[date], *, max_dates: int) -> list[date]:
    """Use each month's final eligible date, evenly downsampling if needed."""
    latest_by_month: dict[str, date] = {}
    for value in eligible:
        latest_by_month[value.strftime("%Y-%m")] = value
    monthly = [latest_by_month[key] for key in sorted(latest_by_month)]
    if max_dates <= 0 or len(monthly) <= max_dates:
        return monthly
    indexes = {
        round(index * (len(monthly) - 1) / (max_dates - 1))
        for index in range(max_dates)
    }
    return [monthly[index] for index in sorted(indexes)]


def _ranked_day_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("research_candidate_rank") or 10**9),
            str(row.get("symbol") or ""),
        ),
    )


def _assign_cohorts(signals: pl.DataFrame, *, cohort_size: int, seed: int) -> pl.DataFrame:
    """Attach non-overlapping high/low cohorts plus deterministic random control."""
    records: list[dict[str, Any]] = []
    for signal_date, frame in signals.partition_by("signal_date", as_dict=True, maintain_order=True).items():
        day = signal_date[0] if isinstance(signal_date, tuple) else signal_date
        ranked = _ranked_day_rows(frame.to_dicts())
        count = min(cohort_size, len(ranked))
        selections = {"formal_all": ranked, "high_score": ranked[:count]}
        if len(ranked) >= 2 * cohort_size:
            selections["low_score"] = ranked[-cohort_size:]
        chooser = random.Random(f"{seed}:{day}")
        selections["random_control"] = [ranked[index] for index in sorted(chooser.sample(range(len(ranked)), count))]
        for cohort, selected in selections.items():
            for row in selected:
                records.append({**row, "cohort": cohort, "cohort_size": len(selected)})
    return pl.DataFrame(records) if records else pl.DataFrame()


def _metric(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "positive_rate": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "positive_rate": sum(value > 0 for value in values) / len(values),
    }


def _max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    nav, peak, drawdown = 1.0, 1.0, 0.0
    for value in returns:
        nav *= 1.0 + value
        peak = max(peak, nav)
        drawdown = min(drawdown, nav / peak - 1.0)
    return drawdown


def _selection_turnover(frame: pl.DataFrame) -> float | None:
    selections = {
        day: set(group.get_column("symbol").cast(pl.Utf8).to_list())
        for day, group in frame.partition_by("signal_date", as_dict=True, maintain_order=True).items()
    }
    ordered = sorted(selections.items())
    if len(ordered) < 2:
        return None
    values = [
        1.0 - len(previous & current) / max(len(previous), len(current), 1)
        for (_, previous), (_, current) in pairwise(ordered)
    ]
    return statistics.fmean(values)


def _cohort_report(cohorts: pl.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cohort, frame in cohorts.partition_by("cohort", as_dict=True, maintain_order=True).items():
        label = cohort[0] if isinstance(cohort, tuple) else cohort
        result[str(label)] = {
            "observations": frame.height,
            "signal_dates": frame.get_column("signal_date").n_unique(),
            "mean_selection_turnover": _selection_turnover(frame),
            "horizons": {},
        }
        for horizon in HORIZONS:
            valid = frame.drop_nulls([f"return_{horizon}d", f"excess_return_{horizon}d"])
            by_day = valid.group_by("signal_date").agg(
                pl.col(f"return_{horizon}d").mean().alias("return"),
                pl.col(f"excess_return_{horizon}d").mean().alias("excess"),
            ).sort("signal_date")
            returns = [float(value) for value in by_day.get_column("return").to_list()]
            excess = [float(value) for value in by_day.get_column("excess").to_list()]
            result[str(label)]["horizons"][f"T+{horizon}"] = {
                "equal_weight_return": _metric(returns),
                "equal_weight_excess_return": _metric(excess),
                "event_cohort_max_drawdown": _max_drawdown(returns),
            }
    return result


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Wyckoff StrengthScore 月度滚动验证",
        "",
        "本报告是研究验证，不升级任何正式排序。信号在 D 收盘后形成，D+1 Open 买入、T+N Close 卖出；未模拟费用、滑点、涨跌停、停牌和实际成交量约束。",
        "",
        "- 正式池：仅 L3 + 基础过滤。",
        "- high_score：每个信号日未验证研究排序前 N。",
        "- formal_all：同日全部正式候选等权。",
        "- random_control：同日固定种子随机 N。",
        "- low_score：仅在候选不少于 2N 时取不与高分组重叠的后 N。",
        "",
        "`event_cohort_max_drawdown` 是按信号日等权收益串联的研究序列回撤，不是重叠持仓、真实资金曲线的组合最大回撤；`mean_selection_turnover` 是相邻信号日成分替换率。",
        "",
        "| cohort | horizon | dates | mean excess | median excess | positive rate | event-cohort MDD | mean selection turnover |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cohort, item in report["cohorts"].items():
        turnover = item["mean_selection_turnover"]
        for horizon, values in item["horizons"].items():
            excess = values["equal_weight_excess_return"]
            lines.append(
                f"| {cohort} | {horizon} | {excess['n']} | "
                f"{_pct(excess['mean'])} | {_pct(excess['median'])} | {_pct(excess['positive_rate'])} | "
                f"{_pct(values['event_cohort_max_drawdown'])} | {_pct(turnover)} |"
            )
    return "\n".join(lines) + "\n"


def _pct(value: float | int | None) -> str:
    return "—" if value is None else f"{float(value):.2%}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Wyckoff 未验证 StrengthScore 月度滚动验证")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR / "research" / "wyckoff_strength_rolling_validation_v1")
    parser.add_argument("--start", type=_parse_date, default=DEFAULT_START)
    parser.add_argument("--max-dates", type=int, default=DEFAULT_MAX_DATES)
    parser.add_argument("--cohort-size", type=int, default=DEFAULT_COHORT_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    if args.cohort_size <= 0:
        raise ValueError("--cohort-size must be positive")

    data_dir, output_dir = args.data_dir.resolve(), args.output_dir.resolve()
    state_path, rows_path = output_dir / "progress.json", output_dir / "signals.parquet"
    trading_dates = _load_trading_dates(data_dir)
    repo = KlineRepository(DataStore(data_dir))
    benchmark_coverage = repo.get_index_daily("000001.SH", args.start, trading_dates[-1], columns=["date"])
    eligible = _eligible_dates(trading_dates=trading_dates, start=args.start, benchmark_dates=set(benchmark_coverage.get_column("date").to_list()))
    selected = _select_monthly_dates(eligible, max_dates=args.max_dates)
    if not selected:
        raise ValueError("no eligible monthly signal dates")

    state = _read_json(state_path)
    if state.get("selected_signal_dates"):
        selected = [date.fromisoformat(value) for value in state["selected_signal_dates"]]
    else:
        state = {"status": "running", "selected_signal_dates": [value.isoformat() for value in selected], "date_runs": {}}
        _write_json(state_path, state)

    final_index = trading_dates.index(selected[-1])
    prices = _load_prices(data_dir, selected[0], trading_dates[final_index + max(HORIZONS)])
    benchmark_prices = repo.get_index_daily("000001.SH", selected[0], trading_dates[final_index + max(HORIZONS)], columns=["date", "open", "close"])
    engine, screener = StrategyEngine(strategy_dirs=_strategy_dirs(data_dir)), ScreenerService(repo)
    overrides = strategy_config.load_override(data_dir, "wyckoff_funnel")
    stored = pl.read_parquet(rows_path) if rows_path.exists() else pl.DataFrame()
    completed = set(stored.get_column("signal_date").to_list()) if not stored.is_empty() else set()
    skipped = {
        date.fromisoformat(value)
        for value, item in (state.get("date_runs") or {}).items()
        if item.get("status") == "skipped_benchmark_unavailable"
    }
    records = stored.to_dicts() if not stored.is_empty() else []
    started = time.perf_counter()

    for ordinal, as_of in enumerate(selected, start=1):
        if as_of in completed or as_of in skipped:
            continue
        context = screener.build_strategy_context(engine, as_of, ["wyckoff_funnel"], overrides_map={"wyckoff_funnel": overrides})
        try:
            result = engine.run("wyckoff_funnel", context, overrides=overrides)
        except ValueError as exc:
            if "requires the configured benchmark history" not in str(exc):
                raise
            state["date_runs"][as_of.isoformat()] = {
                "status": "skipped_benchmark_unavailable",
                "reason": str(exc),
            }
            _write_json(state_path, state)
            print(f"[{ordinal}/{len(selected)}] {as_of}: skipped (benchmark unavailable)", flush=True)
            continue
        evidence = result.evidence
        state["date_runs"][as_of.isoformat()] = {
            "status": "complete",
            "all_l3_candidates": evidence.get("all_wyckoff_candidate_count"),
            "after_basic_filter": evidence.get("basic_filter_candidate_count"),
            "formal_rows": result.total,
        }
        records.extend(_signal_row(as_of=as_of, row=row) for row in result.rows)
        _attach_forward_returns(pl.DataFrame(records), prices, trading_dates, benchmark_prices).write_parquet(rows_path)
        state.update({"completed_signal_dates": len(state["date_runs"]), "elapsed_seconds": round(time.perf_counter() - started, 2)})
        _write_json(state_path, state)
        print(f"[{ordinal}/{len(selected)}] {as_of}: {state['date_runs'][as_of.isoformat()]}", flush=True)

    signals = pl.read_parquet(rows_path)
    cohorts = _assign_cohorts(signals, cohort_size=args.cohort_size, seed=args.seed)
    cohort_path = output_dir / "cohorts.parquet"
    cohorts.write_parquet(cohort_path)
    report = {
        "status": "complete",
        "research_only": True,
        "selection": {
            "method": "last_eligible_day_per_month_evenly_downsampled",
            "requested_signal_dates": [value.isoformat() for value in selected],
            "completed_signal_dates": sorted(value.isoformat() for value in signals.get_column("signal_date").unique().to_list()),
            "skipped_dates": {key: value for key, value in state["date_runs"].items() if value.get("status") == "skipped_benchmark_unavailable"},
            "max_dates": args.max_dates,
            "seed": args.seed,
            "cohort_size": args.cohort_size,
        },
        "formal_strategy_contract": "L3 plus optional basic filter only; StrengthScore is unverified research ordering",
        "cohorts": _cohort_report(cohorts),
        "artifacts": {"signals": str(rows_path.resolve()), "cohorts": str(cohort_path.resolve())},
    }
    _write_json(output_dir / "report.json", report)
    (output_dir / "report.md").write_text(_render_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str((output_dir / 'report.json').resolve()), "dates": len(selected)}, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    main()
