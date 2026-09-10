"""Event-level research backtests for Wyckoff v2.

This module evaluates independently replayed events. It never feeds outcomes
back into the live funnel or event detector.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, replace
from datetime import date, timedelta
from itertools import pairwise, product
from statistics import mean, median, pstdev

import pandas as pd

from app.wyckoff.v2.config import WyckoffV2Config
from app.wyckoff.v2.engine import analyze_wyckoff_v2
from app.wyckoff.v2.features import prepare_ohlcv

DEFAULT_HORIZONS = (1, 3, 5, 10, 20)

# The API deliberately accepts labels, not a parameter optimizer.  A label maps
# to a deterministic entry stream emitted by the independent V2 state machine.
EXPERIMENT_VARIANTS: dict[str, tuple[str, ...]] = {
    "SPRING_BASE": ("spring_aggressive",),
    "SPRING_TEST_VALID": ("spring_standard",),
    "SPRING_CONFIRM_BASE": ("spring_conservative",),
    "SPRING_CONFIRM_ATR": ("spring_confirm_atr",),
    "SPRING_CONFIRM_CLV": ("spring_confirm_clv",),
    "SPRING_CONFIRM_VOLUME": ("spring_confirm_volume",),
    "SPRING_CONFIRM_CLV_VOLUME": ("spring_confirm_clv_volume",),
    "SPRING_CONFIRM_SWING_HIGH": ("spring_confirm_swing_high",),
    "LPS_CLASSIC_BASE": ("lps_classic_standard",),
    "LPS_CLASSIC_SOS_HELD_20": ("lps_classic_sos_held_20",),
    "LPS_CLASSIC_SOS_HELD_30": ("lps_classic_sos_held_30",),
    "LPS_CLASSIC_SOS_HELD_40": ("lps_classic_sos_held_40",),
    "LPS_CLASSIC_SOS_HELD_50": ("lps_classic_sos_held_50",),
    "LPS_CLASSIC_SWING_CONFIRM": ("lps_classic_swing_high",),
    "LPS_SHALLOW_BASE": ("lps_shallow_standard",),
}


def _round(value: float) -> float:
    return round(float(value), 6)


def _outcome(
    frame: pd.DataFrame,
    signal_index: int,
    horizon: int,
    invalidation: float | None = None,
) -> dict[str, float | bool | None] | None:
    """Measure a daily-bar signal from the next tradable session's open.

    The signal uses the closing bar, so its close is not an executable price
    in a daily replay.  ``T+N`` remains relative to the signal date: T+1 is
    the next session close, entered at that session's open.
    """
    execution_index = signal_index + 1
    end = signal_index + int(horizon)
    if execution_index >= len(frame) or end >= len(frame):
        return None
    entry_price = float(frame["open"].iloc[execution_index])
    if not pd.notna(entry_price) or entry_price <= 0:
        return None
    future = frame.iloc[execution_index : end + 1]
    invalidation_hit = (
        bool((future["low"] <= float(invalidation)).any())
        if invalidation is not None and pd.notna(invalidation) and float(invalidation) > 0
        else None
    )
    return {
        "return_pct": (float(frame["close"].iloc[end]) / entry_price - 1.0) * 100.0,
        "mfe_pct": (float(future["high"].max()) / entry_price - 1.0) * 100.0,
        "mae_pct": (float(future["low"].min()) / entry_price - 1.0) * 100.0,
        "invalidation_hit": invalidation_hit,
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summarize_outcomes(outcomes: list[dict[str, object]]) -> dict[str, float | int | None]:
    if not outcomes:
        return {
            "count": 0,
            "mean_return_pct": None,
            "median_return_pct": None,
            "win_rate": None,
            "mean_mfe_pct": None,
            "mean_mae_pct": None,
            "p25_return_pct": None,
            "p75_return_pct": None,
            "std_return_pct": None,
            "profit_factor": None,
            "positive_return_rate": None,
            "median_mfe_pct": None,
            "median_mae_pct": None,
            "p75_mfe_pct": None,
            "p75_mae_pct": None,
            "max_profit_pct": None,
            "max_loss_pct": None,
            "unique_symbols": 0,
            "unique_ranges": 0,
            "invalidation_hit_rate": None,
            "mean_excess_return_pct": None,
            "median_excess_return_pct": None,
        }
    returns = [float(item["return_pct"]) for item in outcomes]
    mfes = [float(item["mfe_pct"]) for item in outcomes]
    maes = [float(item["mae_pct"]) for item in outcomes]
    invalidation_hits = [item["invalidation_hit"] for item in outcomes if item["invalidation_hit"] is not None]
    positive = [value for value in returns if value > 0]
    negative = [value for value in returns if value < 0]
    excesses = [float(item["excess_return_pct"]) for item in outcomes if item.get("excess_return_pct") is not None]
    return {
        "count": len(outcomes),
        "mean_return_pct": _round(mean(returns)),
        "median_return_pct": _round(median(returns)),
        "win_rate": _round(len(positive) / len(returns)),
        "positive_return_rate": _round(len(positive) / len(returns)),
        "mean_mfe_pct": _round(mean(mfes)),
        "mean_mae_pct": _round(mean(maes)),
        "p25_return_pct": _round(_percentile(returns, 0.25)),
        "p75_return_pct": _round(_percentile(returns, 0.75)),
        "std_return_pct": _round(pstdev(returns)),
        "profit_factor": _round(sum(positive) / abs(sum(negative))) if negative else None,
        "median_mfe_pct": _round(median(mfes)),
        "median_mae_pct": _round(median(maes)),
        "p75_mfe_pct": _round(_percentile(mfes, 0.75)),
        "p75_mae_pct": _round(_percentile(maes, 0.75)),
        "max_profit_pct": _round(max(returns)),
        "max_loss_pct": _round(min(returns)),
        "unique_symbols": len({str(item["symbol"]) for item in outcomes}),
        "unique_ranges": len({str(item["range_id"]) for item in outcomes}),
        "invalidation_hit_rate": _round(sum(bool(value) for value in invalidation_hits) / len(invalidation_hits)) if invalidation_hits else None,
        "mean_excess_return_pct": _round(mean(excesses)) if excesses else None,
        "median_excess_return_pct": _round(median(excesses)) if excesses else None,
    }


def _feature_profile(rows: list[dict[str, object]]) -> dict[str, dict[str, float | int | None]]:
    """Describe frozen numeric feature distributions without fitting a model."""
    values: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and pd.notna(value):
                values.setdefault(key, []).append(float(value))
    return {
        key: {
            "count": len(series), "mean": _round(mean(series)), "median": _round(median(series)),
            "p25": _round(_percentile(series, 0.25)), "p75": _round(_percentile(series, 0.75)),
        }
        for key, series in values.items()
    }


def run_event_backtest_frames(
    sources: Iterable[tuple[str, pd.DataFrame]],
    cfg: WyckoffV2Config | None = None,
    *,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    entries: Sequence[str] | None = None,
    benchmark_return: Callable[[str, int], float | None] | None = None,
    market_regime: Callable[[str], str] | None = None,
    event_sink: Callable[[dict[str, object]], None] | None = None,
    entry_start: date | None = None,
    entry_end: date | None = None,
    experiment_variants: Sequence[str] | None = None,
) -> dict:
    """Stream OHLCV frames one symbol at a time for memory-bounded research.

    Unlike ``run_event_backtest`` this accepts a lazy iterator, so a caller can
    load a full market in small parquet batches without holding every symbol's
    pandas frame in memory.  The output is identical to the mapping API.
    """
    cfg = cfg or WyckoffV2Config()
    normalized_horizons = tuple(sorted({int(value) for value in horizons if int(value) > 0}))
    grouped: dict[str, dict[int, list[dict[str, object]]]] = {}
    total_entries: dict[str, int] = {}
    spring_outcomes = {name: 0 for name in ("HARD_INVALIDATION", "TEST_TIMEOUT", "TEST_REJECTED", "NO_FOLLOW_THROUGH", "CONFIRMED")}
    event_symbols: set[str] = set()
    event_ranges: set[str] = set()
    events_per_symbol: list[int] = []
    events_per_range: dict[str, int] = {}
    repeats = {5: 0, 10: 0}
    skipped_symbols: dict[str, str] = {}
    symbols_requested = 0
    funnel: dict[str, int] = {}
    rejection_reasons: dict[str, int] = {}
    spring_profiles: dict[str, list[dict[str, object]]] = {}
    regime_grouped: dict[str, dict[str, dict[int, list[dict[str, object]]]]] = {}

    if experiment_variants is not None:
        unknown = sorted(set(experiment_variants) - set(EXPERIMENT_VARIANTS))
        if unknown:
            raise ValueError(f"unknown Wyckoff V2 experiment variants: {', '.join(unknown)}")
        variant_entries = {entry for variant in experiment_variants for entry in EXPERIMENT_VARIANTS[variant]}
        # Explicit baseline entries and requested experiment streams are a
        # union: selecting a baseline must never silently remove a variant.
        entries = tuple(sorted(variant_entries | set(entries or ())))

    for symbol, source in sources:
        symbols_requested += 1
        try:
            frame = prepare_ohlcv(source)
            analysis = analyze_wyckoff_v2(symbol, frame, cfg, full_replay=True)
        except (KeyError, TypeError, ValueError) as exc:
            skipped_symbols[str(symbol)] = str(exc)
            continue
        for event in analysis.events:
            event_symbols.add(symbol)
            event_ranges.add(event.range_id)
            events_per_range[event.range_id] = events_per_range.get(event.range_id, 0) + 1
            if event.event_type.startswith("SPRING_"):
                taxonomy_key = "CONFIRMED" if event.state == "SPRING_CONFIRMED" else event.state
                if taxonomy_key in spring_outcomes:
                    spring_outcomes[taxonomy_key] += 1
                spring_profiles.setdefault(taxonomy_key, []).append(event.research)
        for key, value in analysis.diagnostics.get("funnel", {}).items():
            funnel[key] = funnel.get(key, 0) + int(value)
        for key, value in analysis.diagnostics.get("rejection_reasons", {}).items():
            rejection_reasons[key] = rejection_reasons.get(key, 0) + int(value)
        events_per_symbol.append(len(analysis.events))
        for event_type, range_id in {(event.event_type, event.range_id) for event in analysis.events}:
            dates = sorted(pd.Timestamp(event.detected_at) for event in analysis.events if event.event_type == event_type and event.range_id == range_id)
            for previous, current in pairwise(dates):
                delta = (current - previous).days
                for window in repeats:
                    repeats[window] += int(delta <= window)
        indexes = {str(pd.Timestamp(value).date()): index for index, value in enumerate(frame["date"])}
        for entry in analysis.entries:
            if entries is not None and entry.entry_type not in entries:
                continue
            entry_date = date.fromisoformat(entry.occurred_at)
            if entry_start and entry_date < entry_start:
                continue
            if entry_end and entry_date > entry_end:
                continue
            total_entries[entry.entry_type] = total_entries.get(entry.entry_type, 0) + 1
            index = indexes.get(entry.occurred_at)
            if index is None:
                continue
            outcomes: dict[str, dict[str, object]] = {}
            for horizon in normalized_horizons:
                outcome = _outcome(frame, index, horizon, entry.invalidation)
                if outcome is not None:
                    benchmark = benchmark_return(entry.occurred_at, horizon) if benchmark_return else None
                    if benchmark is not None:
                        outcome["benchmark_return_pct"] = benchmark
                        outcome["excess_return_pct"] = float(outcome["return_pct"]) - benchmark
                    outcome.update(symbol=symbol, range_id=entry.range_id)
                    outcome["signal_date"] = entry.occurred_at
                    regime = market_regime(entry.occurred_at) if market_regime else "UNCLASSIFIED"
                    outcome["market_regime"] = regime
                    grouped.setdefault(entry.entry_type, {}).setdefault(horizon, []).append(outcome)
                    regime_grouped.setdefault(entry.entry_type, {}).setdefault(regime, {}).setdefault(horizon, []).append(outcome)
                    outcomes[str(horizon)] = outcome
            if event_sink is not None:
                source_event = next((item for item in analysis.events if item.event_id == entry.event_id), None)
                snapshot = source_event.range_snapshot if source_event else None
                event_sink({
                    "symbol": symbol,
                    "date": entry.occurred_at,
                    "range_id": entry.range_id,
                    "event_id": entry.event_id,
                    "entry": entry.entry_type,
                    "state": entry.state,
                    "parent_event_id": entry.parent_event_id,
                    "support": snapshot.support if snapshot else None,
                    "creek": snapshot.creek if snapshot else None,
                    "invalid_price": entry.invalidation,
                    "research": entry.research,
                    "outcomes": outcomes,
                })

    entry_types = sorted(set(total_entries) | set(grouped))
    entries = {
        entry_type: {
            "events": total_entries.get(entry_type, 0),
            "horizons": {
                str(horizon): _summarize_outcomes(grouped.get(entry_type, {}).get(horizon, []))
                for horizon in normalized_horizons
            },
        }
        for entry_type in entry_types
    }
    validation: dict[str, object] | None = None
    if entry_start is not None and entry_end is not None and entry_start < entry_end:
        split = entry_start + timedelta(days=int((entry_end - entry_start).days * 0.70))
        validation = {
            "method": "chronological_70_30_no_random_shuffle",
            "research_end": str(split),
            "validation_start": str(split + timedelta(days=1)),
            "research": {
                entry_type: {str(horizon): _summarize_outcomes([item for item in values if str(item["signal_date"]) <= str(split)]) for horizon, values in horizons_map.items()}
                for entry_type, horizons_map in grouped.items()
            },
            "validation": {
                entry_type: {str(horizon): _summarize_outcomes([item for item in values if str(item["signal_date"]) > str(split)]) for horizon, values in horizons_map.items()}
                for entry_type, horizons_map in grouped.items()
            },
        }
    return {
        "mode": "research_only",
        "affects_formal_selection": False,
        "execution": {
            "entry_timing": "next_trading_day_open",
            "exit_timing": "signal_date_plus_n_close",
            "costs_and_slippage_included": False,
        },
        "symbols_requested": symbols_requested,
        "symbols_skipped": skipped_symbols,
        "horizons": list(normalized_horizons),
        "entries": entries,
        "spring_outcomes": {
            **spring_outcomes,
            "total": sum(spring_outcomes.values()),
            "rates": {
                key: _round(value / sum(spring_outcomes.values())) if sum(spring_outcomes.values()) else 0.0
                for key, value in spring_outcomes.items()
            },
        },
        "spring_failure_profiles": {
            state: _feature_profile(records) for state, records in sorted(spring_profiles.items())
        },
        "lps_funnel": {
            name: {
                "count": count,
                "conversion_rate": _round(count / max(funnel.get("TRADING_RANGE", 1), 1)),
            }
            for name, count in funnel.items()
        },
        "lps_rejection_reasons": {
            name: {"count": count, "percentage": _round(count / max(sum(rejection_reasons.values()), 1) * 100.0)}
            for name, count in sorted(rejection_reasons.items())
        },
        "experiment_variants": list(experiment_variants or ()),
        "out_of_sample": validation,
        "market_regime": {
            entry_type: {
                regime: {str(horizon): _summarize_outcomes(values) for horizon, values in horizons_map.items()}
                for regime, horizons_map in regimes.items()
            }
            for entry_type, regimes in regime_grouped.items()
        },
        "event_statistics": {
            "total_events": sum(events_per_symbol),
            "unique_symbols": len(event_symbols),
            "unique_ranges": len(event_ranges),
            "events_per_symbol_median": _round(median(events_per_symbol)) if events_per_symbol else 0.0,
            "events_per_symbol_max": max(events_per_symbol, default=0),
            "events_per_range": _round(mean(events_per_range.values())) if events_per_range else 0.0,
            "repeat_events_within_5_days": repeats[5],
            "repeat_events_within_10_days": repeats[10],
            "duplicate_event_rate": _round(repeats[10] / sum(events_per_symbol)) if events_per_symbol else 0.0,
        },
        "config": asdict(cfg),
    }


def run_event_backtest(
    df_map: dict[str, pd.DataFrame],
    cfg: WyckoffV2Config | None = None,
    *,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    entries: Sequence[str] | None = None,
) -> dict:
    """Replay complete OHLCV histories and summarize Entry outcomes by type.

    A result only includes a horizon when that many subsequent closed bars are
    available. MFE/MAE therefore never inspect data before the Entry date.
    """
    return run_event_backtest_frames(df_map.items(), cfg, horizons=horizons, entries=entries)


def run_parameter_grid(
    df_map: dict[str, pd.DataFrame],
    parameter_values: dict[str, Iterable[float]],
    base_cfg: WyckoffV2Config | None = None,
    *,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> list[dict]:
    """Run a deliberately small, caller-supplied grid of research defaults."""
    if not isinstance(df_map, Mapping):
        raise TypeError("参数网格回测需要可重复迭代的 symbol → OHLCV 映射")
    base_cfg = base_cfg or WyckoffV2Config()
    names = sorted(parameter_values)
    invalid = [name for name in names if not hasattr(base_cfg, name)]
    if invalid:
        raise ValueError(f"未知 Wyckoff V2 参数: {', '.join(invalid)}")
    value_sets = [tuple(values) for values in (parameter_values[name] for name in names)]
    if any(not values for values in value_sets):
        raise ValueError("参数网格中的每个参数至少需要一个候选值")
    reports: list[dict] = []
    for combination in product(*value_sets):
        parameters = dict(zip(names, combination, strict=True))
        cfg = replace(base_cfg, **parameters)
        reports.append({"parameters": parameters, "report": run_event_backtest(df_map, cfg, horizons=horizons)})
    return reports
