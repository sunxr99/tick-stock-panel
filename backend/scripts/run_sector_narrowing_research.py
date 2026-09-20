"""Read-only NARROWING research over saved Wyckoff Sector/RS cohorts.

This script never changes the formal Sector Phase or candidate ranking. It
adds an independent ``research_phase`` field only to its research artifacts.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import polars as pl

from app.services.rps_rotation import build_sector_strength
from app.services.screener import ScreenerService
from app.tickflow.repository import DataStore, KlineRepository
from scripts.run_wyckoff_top20_backtest import (
    COHORT_ALL,
    COHORT_TOP,
    HORIZONS,
    _cohort_horizon_metrics,
    _distribution,
    _engine,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
_OFFICIAL_PHASES = (
    "EMERGING",
    "ACCELERATING",
    "LEADING",
    "EXHAUSTED",
    "FADING",
)
_ANALYSIS_PHASES = ("ACCELERATING", "LEADING", "NARROWING", "EMERGING", "EXHAUSTED", "FADING", "UNCLASSIFIED")
_EXTENSION_STATES = ("NORMAL", "ELEVATED", "EXTENDED", "EXTREME")


def _research_phase(
    percentile: float | None,
    breadth_state: str | None,
    official_phase: str | None,
) -> str | None:
    """Classify the fixed high-strength, contracting-breadth research state."""
    if percentile is None or breadth_state is None:
        return None
    if (
        percentile >= 80.0
        and breadth_state == "CONTRACTING"
        and official_phase not in {"FADING", "EXHAUSTED"}
    ):
        return "NARROWING"
    return None


def _analysis_phase(official_phase: str | None, research_phase: str | None) -> str:
    """Prefer the read-only research label without mutating the official one."""
    return research_phase or official_phase or "UNCLASSIFIED"


def _state_context(repo: KlineRepository, data_dir: Path, dates: list[date]) -> pl.DataFrame:
    """Rebuild only point-in-time Sector context for the supplied signal dates."""
    engine = _engine(data_dir)
    screener = ScreenerService(repo)
    context = screener.build_strategy_context(engine, dates[-1], ["wyckoff_funnel"])
    if context.history is None or context.history.is_empty():
        raise RuntimeError(f"无法加载 Sector 研究历史窗口: {dates[-1]}")
    # Sector Strength filters all calculations to each as_of date. The cache
    # only avoids repeated I/O; it is not an input beyond that as_of date.
    repo._enriched_history_cache = context.history
    repo._enriched_history_generation = repo.get_matrix_data_generation("stock")
    rows: list[dict[str, object]] = []
    for as_of in dates:
        for result in build_sector_strength(repo, kind="industry", level=1, as_of=as_of):
            rows.append({
                "signal_date": as_of,
                "industry_id": result.sector_id,
                "sector_percentile": result.percentile,
                "sector_score_rebuilt": result.score,
                "sector_score_change_3d": result.score_change_3d,
                "sector_rank_change_3d": result.rank_change_3d,
                "sector_up_ratio": result.up_ratio,
                "sector_up_ratio_change_3d": result.up_ratio_change_3d,
                "sector_strong_stock_ratio": result.strong_stock_ratio,
                "sector_strong_stock_ratio_change_3d": result.strong_stock_ratio_change_3d,
                "sector_breadth_state": result.breadth_state,
                "sector_extension_state_rebuilt": result.extension_state,
                "official_sector_phase_rebuilt": result.phase,
                "official_sector_phase_reasons": list(result.phase_reasons),
            })
    return pl.DataFrame(rows)


def _label_research_phase(rows: pl.DataFrame, contexts: pl.DataFrame) -> pl.DataFrame:
    enriched = rows.join(contexts, on=["signal_date", "industry_id"], how="left")
    research_columns = [
        "sector_percentile",
        "sector_breadth_state",
        "official_sector_phase_rebuilt",
    ]
    enriched = enriched.with_columns(
        pl.struct(research_columns)
        .map_elements(
            lambda value: _research_phase(
                value["sector_percentile"],
                value["sector_breadth_state"],
                value["official_sector_phase_rebuilt"],
            ),
            return_dtype=pl.String,
        )
        .alias("research_phase")
    )
    return enriched.with_columns(
        pl.struct(["official_sector_phase_rebuilt", "research_phase"])
        .map_elements(
            lambda value: _analysis_phase(
                value["official_sector_phase_rebuilt"], value["research_phase"]
            ),
            return_dtype=pl.String,
        )
        .alias("analysis_phase")
    )


def _percent(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _phase_performance(frame: pl.DataFrame) -> dict[str, object]:
    output: dict[str, object] = {}
    for phase in _ANALYSIS_PHASES:
        subset = frame.filter(pl.col("analysis_phase") == phase)
        output[phase] = {
            "n": subset.height,
            "horizons": {
                f"T+{horizon}": _cohort_horizon_metrics(subset, horizon)
                for horizon in HORIZONS
            },
        }
    return output


def _daily_frequency(frame: pl.DataFrame) -> list[dict[str, object]]:
    daily: list[dict[str, object]] = []
    for (signal_date,), group in frame.group_by("signal_date", maintain_order=True):
        narrowing = group.filter(pl.col("research_phase") == "NARROWING").height
        daily.append({
            "signal_date": signal_date,
            "narrowing_n": narrowing,
            "total_n": group.height,
            "narrowing_ratio": _percent(narrowing, group.height),
        })
    return daily


def _industry_distribution(frame: pl.DataFrame) -> list[dict[str, object]]:
    narrowed = frame.filter(pl.col("research_phase") == "NARROWING")
    total = narrowed.height
    if not total:
        return []
    return [
        {
            "industry_id": row["industry_id"],
            "industry_name": row["industry_name"],
            "n": int(row["n"]),
            "ratio": int(row["n"]) / total,
        }
        for row in (
            narrowed.group_by(["industry_id", "industry_name"])
            .len()
            .rename({"len": "n"})
            .sort(["n", "industry_name"], descending=[True, False])
            .iter_rows(named=True)
        )
    ]


def _narrowing_features(frame: pl.DataFrame) -> dict[str, object]:
    narrowed = frame.filter(pl.col("research_phase") == "NARROWING")
    numeric = (
        "sector_percentile",
        "sector_score_rebuilt",
        "sector_score_change_3d",
        "sector_rank_change_3d",
        "sector_up_ratio",
        "sector_up_ratio_change_3d",
        "sector_strong_stock_ratio",
        "sector_strong_stock_ratio_change_3d",
    )
    extension_counts = {
        state: narrowed.filter(pl.col("sector_extension_state_rebuilt") == state).height
        for state in _EXTENSION_STATES
    }
    return {
        "n": narrowed.height,
        "numeric": {
            column: _distribution(narrowed.get_column(column))
            for column in numeric
        },
        "breadth_state_counts": {
            state: narrowed.filter(pl.col("sector_breadth_state") == state).height
            for state in ("EXPANDING", "STABLE", "CONTRACTING")
        },
        "extension_state_counts": extension_counts,
        "extension_state_percentages": {
            state: _percent(count, narrowed.height)
            for state, count in extension_counts.items()
        },
    }


def _report(rows: pl.DataFrame, *, source: Path, artifact: Path) -> dict[str, object]:
    cohorts: dict[str, object] = {}
    for cohort in (COHORT_ALL, COHORT_TOP):
        subset = rows.filter(pl.col("cohort") == cohort)
        narrowing_n = subset.filter(pl.col("research_phase") == "NARROWING").height
        cohorts[cohort] = {
            "n": subset.height,
            "narrowing_n": narrowing_n,
            "narrowing_ratio": _percent(narrowing_n, subset.height),
            "daily_narrowing_frequency": _daily_frequency(subset),
            "narrowing_industry_distribution": _industry_distribution(subset),
            "narrowing_features": _narrowing_features(subset),
            "phase_performance": _phase_performance(subset),
        }
    unmatched = rows.filter(pl.col("sector_percentile").is_null()).height
    return {
        "status": "complete",
        "research_only": True,
        "definition": {
            "research_phase": "NARROWING",
            "formula": "sector_percentile >= 80 and breadth_state == CONTRACTING and official_phase not in {FADING, EXHAUSTED}",
            "formal_phase_mutated": False,
            "final_rank_score_mutated": False,
        },
        "source_cohort_artifact": str(source.resolve()),
        "research_artifact": str(artifact.resolve()),
        "unmatched_sector_context_rows": unmatched,
        "cohorts": cohorts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sector NARROWING 只读研究")
    parser.add_argument("--input", type=Path, required=True, help="已有 Wyckoff cohort parquet")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    rows = pl.read_parquet(args.input)
    required = {"signal_date", "industry_id", "cohort", "sector_phase"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"cohort 输入缺少字段: {missing}")
    dates = sorted(rows.get_column("signal_date").unique().to_list())
    repo = KlineRepository(DataStore(args.data_dir))
    contexts = _state_context(repo, args.data_dir, dates)
    labeled = _label_research_phase(rows, contexts)

    output_dir = args.data_dir / "research"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.input.stem.replace("wyckoff_sector_rs_cohorts_", "sector_narrowing_research_")
    artifact = output_dir / f"{stem}.parquet"
    labeled.write_parquet(artifact)
    report = _report(labeled, source=args.input, artifact=artifact)
    report_path = args.output or output_dir / f"{stem}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "cohorts": {
        cohort: {
            "narrowing_n": report["cohorts"][cohort]["narrowing_n"],
            "narrowing_ratio": report["cohorts"][cohort]["narrowing_ratio"],
        }
        for cohort in (COHORT_ALL, COHORT_TOP)
    }}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
