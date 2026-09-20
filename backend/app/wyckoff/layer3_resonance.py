"""Layer 3 industry/concept resonance for the Wyckoff funnel.

Migrated from the local upstream logic.  A symbol may belong to multiple
concepts; when concepts are unavailable, its industry is the fallback group.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.wyckoff.config import FunnelConfig


@dataclass(frozen=True)
class Layer3Result:
    survivors: list[str]
    top_sectors: list[str]
    paths: dict[str, str]
    used_missing_group_fallback: bool
    used_minimum_survivor_fallback: bool


def layer3_sector_resonance(
    symbols: list[str],
    sector_map: dict[str, str],
    cfg: FunnelConfig,
    *,
    base_symbols: list[str] | None = None,
    df_map: dict[str, pd.DataFrame] | None = None,
    concept_map: dict[str, list[str]] | None = None,
    hot_concepts: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return Layer-3 survivors and the selected leading sectors/concepts."""
    result = evaluate_layer3_sector_resonance(
        symbols,
        sector_map,
        cfg,
        base_symbols=base_symbols,
        df_map=df_map,
        concept_map=concept_map,
        hot_concepts=hot_concepts,
    )
    return result.survivors, result.top_sectors


def evaluate_layer3_sector_resonance(
    symbols: list[str],
    sector_map: dict[str, str],
    cfg: FunnelConfig,
    *,
    base_symbols: list[str] | None = None,
    df_map: dict[str, pd.DataFrame] | None = None,
    concept_map: dict[str, list[str]] | None = None,
    hot_concepts: list[str] | None = None,
) -> Layer3Result:
    """Run Layer 3 and preserve the exact path taken by every input symbol."""
    base_symbols = base_symbols or symbols
    use_concept = bool(cfg.use_concept_map and concept_map)
    counts, groups = _groups(symbols, sector_map, concept_map, use_concept)
    # L3 is the convergence gate, not an availability fallback.  Passing the
    # complete L2 pool when membership metadata is absent changes a data
    # outage into hundreds of apparently valid candidates.
    if not counts:
        return Layer3Result(
            survivors=[],
            top_sectors=[],
            paths={symbol: "rejected_missing_group_metadata" for symbol in symbols},
            used_missing_group_fallback=False,
            used_minimum_survivor_fallback=False,
        )
    base_counts, _ = _groups(base_symbols, sector_map, concept_map, use_concept)
    strength = _symbol_strength(symbols, df_map or {})
    sector_strength = {
        group: float(np.median([strength[symbol] for symbol in symbols if group in groups[symbol] and symbol in strength]))
        if any(group in groups[symbol] and symbol in strength for symbol in symbols)
        else 0.0
        for group in counts
    }
    keep, top = _select_groups(counts, base_counts, sector_strength, cfg, hot_concepts or [])
    top_set, keep_set = set(top), set(keep)
    hot_set = {_norm(value) for value in hot_concepts or []}
    survivors: list[str] = []
    paths: dict[str, str] = {}
    for symbol in symbols:
        membership = set(groups[symbol])
        normalized = {_norm(value) for value in membership}
        score = strength.get(symbol, 0.0)
        if membership & top_set:
            survivors.append(symbol)
            paths[symbol] = "strict_top_sector"
        elif membership & keep_set and score >= cfg.l3_keep_strength_min:
            survivors.append(symbol)
            paths[symbol] = "strict_kept_sector_strength"
        elif normalized & hot_set and score >= cfg.l3_hot_leader_strength_min:
            survivors.append(symbol)
            paths[symbol] = "strict_hot_sector_strength"
        elif score >= cfg.l3_leader_strength_min:
            survivors.append(symbol)
            paths[symbol] = "strict_leader_strength"
        else:
            paths[symbol] = "rejected"
    # A thin market group is evidence that the strict resonance predicate did
    # not find candidates.  It is never a reason to return every L2 symbol.
    minimum_survivor_fallback = False
    return Layer3Result(
        survivors=survivors,
        top_sectors=top,
        paths=paths,
        used_missing_group_fallback=False,
        used_minimum_survivor_fallback=minimum_survivor_fallback,
    )


def _groups(symbols: list[str], sector_map: dict[str, str], concept_map: dict[str, list[str]] | None, use_concept: bool) -> tuple[dict[str, int], dict[str, list[str]]]:
    counts: dict[str, int] = {}
    groups: dict[str, list[str]] = {}
    for symbol in symbols:
        values = list(dict.fromkeys(str(value).strip() for value in (concept_map or {}).get(symbol, []) if str(value).strip())) if use_concept else []
        if not values and sector_map.get(symbol):
            values = [sector_map[symbol]]
        groups[symbol] = values
        for value in values:
            counts[value] = counts.get(value, 0) + 1
    return counts, groups


def _symbol_strength(symbols: list[str], df_map: dict[str, pd.DataFrame]) -> dict[str, float]:
    rows: list[tuple[str, float, float, float]] = []
    for symbol in symbols:
        frame = df_map.get(symbol)
        if frame is None or frame.empty:
            continue
        close = pd.to_numeric(frame.sort_values("date").get("close") if "date" in frame.columns else frame.get("close"), errors="coerce").dropna()
        if len(close) <= 20 or close.iloc[-21] <= 0:
            continue
        ret20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100
        ret5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) > 5 and close.iloc[-6] > 0 else ret20
        ret3 = (close.iloc[-1] / close.iloc[-4] - 1) * 100 if len(close) > 3 and close.iloc[-4] > 0 else ret5
        rows.append((symbol, ret20, ret5, ret3))
    if not rows:
        return {}
    data = pd.DataFrame(rows, columns=["symbol", "ret20", "ret5", "ret3"])
    return (0.4 * data.set_index("symbol")["ret20"].rank(pct=True) + 0.3 * data.set_index("symbol")["ret5"].rank(pct=True) + 0.3 * data.set_index("symbol")["ret3"].rank(pct=True)).to_dict()


def _select_groups(counts: dict[str, int], base_counts: dict[str, int], strength: dict[str, float], cfg: FunnelConfig, hot: list[str]) -> tuple[list[str], list[str]]:
    sizes = np.array(list(counts.values()), dtype=float)
    quantile = min(max(float(cfg.sector_count_quantile), 0.0), 1.0)
    count_threshold = max(int(cfg.sector_min_count), math.ceil(float(np.quantile(sizes, quantile))))
    pass_ratio = {group: count / max(base_counts.get(group, 0), 1) for group, count in counts.items()}
    pass_threshold = float(np.quantile(list(pass_ratio.values()), quantile))
    values = list(strength.values())
    strength_threshold = float(np.quantile(values, quantile))
    super_threshold = float(np.quantile(values, min(max(cfg.sector_super_strength_quantile, 0.0), 1.0)))
    normalized_hot = {_norm(value) for value in hot}
    bypass = {group for group, count in counts.items() if cfg.sector_heat_bypass_min_count > 0 and count >= cfg.sector_heat_bypass_min_count}
    keep = set(bypass)
    for group, count in counts.items():
        normal = count >= count_threshold and pass_ratio[group] >= pass_threshold and strength[group] >= strength_threshold
        super_strong = count >= cfg.sector_min_count and strength[group] >= super_threshold
        hot_group = _norm(group) in normalized_hot and count >= cfg.sector_min_count
        if normal or super_strong or hot_group:
            keep.add(group)
    if not keep:
        largest = max(counts.values())
        keep = {group for group, count in counts.items() if count == largest}
    ranked = sorted(keep, key=lambda group: (-(_norm(group) in normalized_hot), -strength[group], -counts[group], group))
    return ranked, ranked[: max(int(cfg.top_n_sectors), 0)] if cfg.top_n_sectors > 0 else ranked


def _norm(value: str) -> str:
    return "".join(str(value).strip().lower().split())


__all__ = ["Layer3Result", "evaluate_layer3_sector_resonance", "layer3_sector_resonance"]
