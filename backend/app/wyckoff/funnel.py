"""Composable L1-to-L4 Wyckoff funnel domain runner.

This has no API, database, scheduler, or UI dependency.  The strategy backend
will supply the market context and persist this result as one run snapshot.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

import pandas as pd

from app.wyckoff.cn_boards import is_supported_cn_board
from app.wyckoff.config import FunnelConfig
from app.wyckoff.layer2_strength import (
    build_benchmark_context,
    build_rps_context,
    evaluate_layer2_symbol,
)
from app.wyckoff.layer3_resonance import evaluate_layer3_sector_resonance
from app.wyckoff.limit_move import is_st_risk_warning
from app.wyckoff.wyckoff_structure import detect_structure_triggers


@dataclass(frozen=True)
class FunnelResult:
    layer1_symbols: list[str]
    layer2_symbols: list[str]
    layer3_symbols: list[str]
    top_sectors: list[str]
    channel_map: dict[str, str]
    pre_ignition_symbols: list[str]
    triggers: dict[str, list[tuple[str, float]]]
    stage_map: dict[str, str]
    trading_ranges: dict[str, dict]
    # Legacy L4 structure hits are a separately labelled research pool.  They
    # never expand or contract the formal L3 candidate universe.
    research_trigger_symbols: list[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    final_traces: dict[str, dict] = field(default_factory=dict)

    def to_snapshot(self) -> dict:
        """Return JSON-safe result data for a future strategy-run snapshot."""
        return {
            "layer1_symbols": self.layer1_symbols,
            "layer2_symbols": self.layer2_symbols,
            "layer3_symbols": self.layer3_symbols,
            "top_sectors": self.top_sectors,
            "channel_map": self.channel_map,
            "pre_ignition_symbols": self.pre_ignition_symbols,
            "triggers": {key: [{"symbol": symbol, "score": score} for symbol, score in hits] for key, hits in self.triggers.items()},
            "stage_map": self.stage_map,
            "trading_ranges": self.trading_ranges,
            "research_trigger_symbols": self.research_trigger_symbols,
            "diagnostics": self.diagnostics,
        }


def run_funnel(
    symbols: list[str],
    df_map: dict[str, pd.DataFrame],
    *,
    benchmark: pd.DataFrame | None,
    name_map: dict[str, str] | None = None,
    market_cap_map: dict[str, float] | None = None,
    sector_map: dict[str, str] | None = None,
    concept_map: dict[str, list[str]] | None = None,
    hot_concepts: list[str] | None = None,
    cfg: FunnelConfig | None = None,
) -> FunnelResult:
    """Run L1→L4 over a single consistent market snapshot.

    ``benchmark`` and the complete universe are intentionally explicit;
    passing a filtered candidate subset as the RPS universe changes Layer 2's
    meaning and is therefore not supported here.
    """
    config = cfg or FunnelConfig()
    names, caps, sectors = name_map or {}, market_cap_map or {}, sector_map or {}
    traces = {symbol: {"symbol": symbol, "name": names.get(symbol, "")} for symbol in symbols}
    l1 = _layer1_filter(symbols, df_map, names, caps, config, traces=traces)
    benchmark_context = build_benchmark_context(benchmark, config)
    rps_context = build_rps_context(symbols, df_map, config, rps_universe=symbols)
    l2: list[str] = []
    channels: dict[str, str] = {}
    pre_ignition: list[str] = []
    for symbol in l1:
        frame = df_map.get(symbol)
        if frame is None or len(frame) < config.ma_long:
            traces[symbol]["l2"] = "rejected_insufficient_history"
            continue
        result = evaluate_layer2_symbol(
            symbol,
            frame,
            config,
            benchmark=benchmark_context,
            rps=rps_context,
            detect_sos=lambda _frame, _cfg: None,
        )
        if result.passed:
            l2.append(symbol)
            channels[symbol] = result.channel
            traces[symbol]["l2"] = "strict_pass"
            traces[symbol]["l2_channels"] = result.channel
        elif result.pre_ignition:
            pre_ignition.append(symbol)
            traces[symbol]["l2"] = "rejected_pre_ignition_watch_only"
        else:
            traces[symbol]["l2"] = "rejected"
    l3_result = evaluate_layer3_sector_resonance(
        l2,
        sectors,
        config,
        base_symbols=l1,
        df_map=df_map,
        concept_map=concept_map,
        hot_concepts=hot_concepts,
    )
    l3, top_sectors = l3_result.survivors, l3_result.top_sectors
    for symbol in l2:
        traces[symbol]["l3"] = l3_result.paths[symbol]
    structure = detect_structure_triggers(l3, df_map, config)
    l4_hits = {symbol for hits in structure.triggers.values() for symbol, _ in hits}
    research_trigger_symbols = [symbol for symbol in l3 if symbol in l4_hits]
    final_traces: dict[str, dict] = {}
    for symbol in l3:
        l3_path = l3_result.paths.get(symbol, "unknown")
        final_traces[symbol] = {
            "symbol": symbol,
            "name": names.get(symbol, ""),
            "source": "L3 strict",
            "layers": ["L1", "L2 strict", "L3"],
            "l1": traces[symbol].get("l1", "unknown"),
            "l2": traces[symbol].get("l2", "unknown"),
            "l2_channels": traces[symbol].get("l2_channels", ""),
            "l3_path": l3_path,
            "l4": "pass" if symbol in l4_hits else "reject",
            "l4_failure": None if symbol in l4_hits else (
                "no_l4_trigger" if symbol in structure.trading_ranges else "no_trading_range"
            ),
            "research_trigger": symbol in l4_hits,
            "mainline": False,
            "fallback": l3_path.startswith("fallback"),
            "bypass": False,
            "merge": False,
            "returned_because": "formal L3 pass; any legacy L4 hit is a separate research trigger",
        }
    source_counts = {
        source: sum(trace["source"] == source for trace in final_traces.values())
        for source in ("L3 strict", "L3 fallback")
    }
    final_count = len(l3)
    stage_counts = {
        "universe": {"input": len(symbols), "pass": len(symbols), "reject": 0, "pass_rate": 1.0},
        "l1": _stage_count(len(symbols), len(l1)),
        "l2": {
            **_stage_count(len(l1), len(l2), watch_only=len(pre_ignition)),
            "strict_pass": len(l2),
            "bypass": 0,
        },
        "l3": {
            **_stage_count(len(l2), len(l3)),
            "strict_pass": source_counts["L3 strict"],
            "bypass": 0,
            "fallback_pass": source_counts["L3 fallback"],
        },
        "l4": {**_stage_count(len(l3), len(l4_hits)), "strict_pass": len(l4_hits), "bypass": 0},
        "research_trigger_pool": {
            "count": len(research_trigger_symbols),
            "affects_formal_selection": False,
        },
        "mainline": {"count": 0, "implemented": False},
        "fallback_pool": {"count": 0, "implemented": False},
        "merge": {"before": len(l3), "after": len(l3), "deduplicated": len(l3), "executed": False},
        "final": {"before_response": final_count, "api_rows": final_count, "strategy_total": final_count},
    }
    diagnostics = {
        "semantics": "formal L3 industry resonance; legacy L4 hits are research triggers only",
        "pipeline": ["Universe", "L1", "L2", "L3 formal", "L4 research triggers", "Final=L3"],
        "stage_counts": stage_counts,
        "source_counts": source_counts,
        "l3_fallback": {
            "missing_group_metadata": l3_result.used_missing_group_fallback,
            "minimum_survivors": l3_result.used_minimum_survivor_fallback,
        },
        "first_stage_equal_to_final_count": next(
            (stage for stage, count in (("L1", len(l1)), ("L2", len(l2)), ("L3", len(l3)), ("L4", len(l4_hits))) if count == final_count),
            "Final",
        ),
        "sample_final_traces": _sample_final_traces(final_traces),
    }
    return FunnelResult(
        layer1_symbols=l1,
        layer2_symbols=l2,
        layer3_symbols=l3,
        top_sectors=top_sectors,
        channel_map=channels,
        pre_ignition_symbols=pre_ignition,
        triggers=structure.triggers,
        stage_map=structure.stage_map,
        trading_ranges={symbol: asdict(value) for symbol, value in structure.trading_ranges.items()},
        research_trigger_symbols=research_trigger_symbols,
        diagnostics=diagnostics,
        final_traces=final_traces,
    )


def _layer1_filter(
    symbols: list[str],
    df_map: dict[str, pd.DataFrame],
    name_map: dict[str, str],
    market_cap_map: dict[str, float],
    cfg: FunnelConfig,
    *,
    traces: dict[str, dict] | None = None,
) -> list[str]:
    passed: list[str] = []
    for symbol in symbols:
        if cfg.require_cn_main_or_chinext and not is_supported_cn_board(symbol, include_bse=cfg.include_bse_board):
            _set_l1_trace(traces, symbol, "rejected_unsupported_board")
            continue
        if is_st_risk_warning(symbol, name_map.get(symbol, "")):
            _set_l1_trace(traces, symbol, "rejected_st")
            continue
        frame = df_map.get(symbol)
        if frame is None or frame.empty:
            _set_l1_trace(traces, symbol, "rejected_missing_history")
            continue
        sorted_frame = frame.sort_values("date", kind="stable") if "date" in frame.columns else frame
        close = pd.to_numeric(sorted_frame.get("close"), errors="coerce").dropna()
        if close.empty or float(close.iloc[-1]) < cfg.l1_min_close_price:
            _set_l1_trace(traces, symbol, "rejected_price")
            continue
        if not _liquid_enough(sorted_frame, cfg):
            _set_l1_trace(traces, symbol, "rejected_liquidity")
            continue
        if market_cap_map and not _market_cap_ok(symbol, market_cap_map, sorted_frame, cfg):
            _set_l1_trace(traces, symbol, "rejected_market_cap")
            continue
        passed.append(symbol)
        _set_l1_trace(traces, symbol, "pass")
    return passed


def _set_l1_trace(traces: dict[str, dict] | None, symbol: str, outcome: str) -> None:
    if traces is not None:
        traces[symbol]["l1"] = outcome


def _stage_count(input_count: int, passed_count: int, *, watch_only: int = 0) -> dict[str, int | float]:
    return {
        "input": input_count,
        "pass": passed_count,
        "reject": input_count - passed_count,
        "watch_only": watch_only,
        "pass_rate": round(passed_count / input_count, 6) if input_count else 0.0,
    }


def _sample_final_traces(final_traces: dict[str, dict], sample_size: int = 20) -> list[dict]:
    symbols = sorted(final_traces)
    if len(symbols) <= sample_size:
        return [final_traces[symbol] for symbol in symbols]
    randomizer = random.Random("wyckoff-diagnostic:" + ",".join(symbols))
    return [final_traces[symbol] for symbol in sorted(randomizer.sample(symbols, sample_size))]


def _amount_series(frame: pd.DataFrame) -> pd.Series:
    amount = pd.to_numeric(frame.get("amount"), errors="coerce") if "amount" in frame.columns else pd.Series(dtype=float)
    if amount.empty or (amount.fillna(0) <= 0).all():
        amount = pd.to_numeric(frame.get("close"), errors="coerce") * pd.to_numeric(frame.get("volume"), errors="coerce")
    return amount.dropna()


def _liquid_enough(frame: pd.DataFrame, cfg: FunnelConfig, *, threshold_wan: float | None = None) -> bool:
    amount = _amount_series(frame).tail(max(cfg.amount_avg_window, 1))
    if amount.empty:
        return True
    threshold = (threshold_wan if threshold_wan is not None else cfg.min_avg_amount_wan) * 10_000
    if amount.mean() < threshold:
        return False
    if not cfg.amount_skew_check_enabled or len(amount) < 5:
        return True
    positive = amount[amount > 0]
    if len(positive) < 5:
        return True
    distorted = positive.skew() >= cfg.amount_skew_max
    weak_median = positive.median() < threshold * cfg.amount_median_min_ratio
    weak_days = float((positive >= threshold).mean()) < cfg.amount_pass_days_min_ratio
    return not (distorted and (weak_median or weak_days))


def _market_cap_ok(symbol: str, caps: dict[str, float], frame: pd.DataFrame, cfg: FunnelConfig) -> bool:
    cap = float(caps.get(symbol, 0.0) or 0.0)
    if cap < cfg.l1_delist_risk_cap_floor_yi:
        return False
    return cap >= cfg.min_market_cap_yi or _liquid_enough(frame, cfg, threshold_wan=cfg.l1_cap_bypass_amount_wan)


__all__ = ["FunnelResult", "run_funnel"]
