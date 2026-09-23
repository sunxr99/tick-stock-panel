"""Sector/RS-only ordering for already-selected Wyckoff candidates.

This module never decides whether a symbol is a Wyckoff candidate.  It only
annotates and orders the supplied candidate rows using the frozen Sector
Strength / Relative Strength outputs and their dynamic states.
"""
from __future__ import annotations

import logging
from datetime import date
from math import isfinite
from typing import Any

from app.services.relative_strength import build_relative_strength
from app.services.rps_rotation import build_sector_strength

logger = logging.getLogger(__name__)

_SECTOR_PHASE_ADJUSTMENTS = {
    "EMERGING": 6.0,
    "ACCELERATING": 10.0,
    "LEADING": 5.0,
    "EXHAUSTED": -8.0,
    "FADING": -12.0,
}
_RS_STATE_ADJUSTMENTS = {
    "LOW": -8.0,
    "RISING": 5.0,
    "HIGH_AND_RISING": 10.0,
    "HIGH_AND_FLAT": 3.0,
    "HIGH_AND_FALLING": -8.0,
    "EXTENDED": -12.0,
}
_EXTENSION_PENALTIES = {
    "NORMAL": 0.0,
    "ELEVATED": 2.0,
    "EXTENDED": 6.0,
    "EXTREME": 10.0,
}
_POSITIVE_SECTOR_PHASES = frozenset({"EMERGING", "ACCELERATING", "LEADING"})
_POSITIVE_RS_STATES = frozenset({"RISING", "HIGH_AND_RISING"})
_RISK_SECTOR_PHASES = frozenset({"EXHAUSTED", "FADING"})
_RISK_RS_STATES = frozenset({"LOW", "HIGH_AND_FALLING", "EXTENDED"})

_SECTOR_CONTEXT_FIELDS = (
    "sector_id", "name", "member_count", "valid_member_count", "coverage_ratio",
    "return_3d", "return_5d", "return_10d", "return_20d",
    "relative_return_3d", "relative_return_5d", "relative_return_10d", "relative_return_20d",
    "relative_momentum_score", "breadth_score", "persistence_score", "persistence_days",
    "score", "rank", "percentile", "score_change_1d", "score_change_3d",
    "percentile_change_1d", "percentile_change_3d", "rank_change_1d", "rank_change_3d",
    "rank_std_5d", "up_ratio", "strong_stock_ratio", "up_ratio_change_1d",
    "up_ratio_change_3d", "strong_stock_ratio_change_1d", "strong_stock_ratio_change_3d",
    "breadth_state", "return_20d_percentile", "distance_from_ma20", "distance_from_ma60",
    "consecutive_up_days", "extension_score", "extension_state", "phase", "phase_reasons",
)
_RS_CONTEXT_FIELDS = (
    "sector_id", "sector_name", "stock_return_3d", "stock_return_5d", "stock_return_10d",
    "stock_return_20d", "stock_return_60d", "vs_market_3d", "vs_market_5d",
    "vs_market_10d", "vs_market_20d", "vs_market_60d", "market_rs_score", "market_rank",
    "market_percentile", "vs_sector_3d", "vs_sector_5d", "vs_sector_10d", "vs_sector_20d",
    "vs_sector_60d", "sector_rs_score", "sector_rank", "sector_percentile", "rs_score",
    "rs_change_1d", "rs_change_3d", "market_rs_change_3d", "sector_rs_change_3d",
    "market_rank_change_3d", "sector_rank_change_3d", "stock_return_20d_percentile",
    "distance_from_ma20", "distance_from_ma60", "consecutive_up_days", "rs_extension_score",
    "rs_extension_state", "rs_state", "state_reasons",
)
_HIERARCHY_FIELDS = ("sw1_code", "sw1_name", "sw2_code", "sw2_name", "sw3_code", "sw3_name")


def _finite_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and isfinite(float(value)):
        return float(value)
    return None


def _result_sector_level(result: object) -> int | None:
    """Read the declared level, with stable-ID parsing for lightweight callers."""
    level = getattr(result, "sector_level", None)
    if level in (1, 2, 3):
        return int(level)
    parts = str(getattr(result, "sector_id", "")).split(":", 2)
    return int(parts[1]) if len(parts) == 3 and parts[0] == "industry" and parts[1] in {"1", "2", "3"} else None


def _state_data_complete(result: object) -> bool:
    data_quality = getattr(result, "data_quality", None)
    if not isinstance(data_quality, dict):
        return False
    return not data_quality.get("state_missing_components")


def _context_values(result: object, fields: tuple[str, ...]) -> dict[str, object]:
    """Make every ranking input inspectable without exposing a mutable DTO."""
    values: dict[str, object] = {}
    for field in fields:
        value = getattr(result, field, None)
        values[field] = list(value) if isinstance(value, tuple) else value
    data_quality = getattr(result, "data_quality", {})
    values["state_missing_components"] = (
        list(data_quality.get("state_missing_components") or [])
        if isinstance(data_quality, dict) else []
    )
    return values


def _unknown_row(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **row,
        "sector_score_legacy": None,
        "rs_score_legacy": None,
        "opportunity_score_legacy": None,
        "sw1_sector_score": None,
        "sw2_sector_score": None,
        "sw3_sector_score": None,
        "sector_score_v2": None,
        "market_rs": None,
        "sw2_rs": None,
        "sw3_rs": None,
        "rs_score_v2": None,
        "opportunity_score_v2": None,
        "opportunity_score_basis": None,
        "sector_hierarchy_state": "SW2_UNKNOWN_SW3_UNKNOWN",
        "sw2_available": False,
        "sw3_available": False,
        **{field: None for field in _HIERARCHY_FIELDS},
        "sector_score": None,
        "sector_phase": None,
        "sector_phase_adjustment": None,
        "sector_extension_state": None,
        "sector_extension_penalty": None,
        "rs_score": None,
        "rs_state": None,
        "rs_state_adjustment": None,
        "rs_extension_state": None,
        "rs_extension_penalty": None,
        "strength_score": None,
        "final_rank_score": None,
        "priority_level": "UNKNOWN",
        "ranking_reasons": [],
        "risk_reasons": [],
        "sector_context": None,
        "rs_context": None,
        "ranking_status": "unknown",
        "ranking_unavailable_reason": reason,
    }


def rank_wyckoff_candidates(
    repo,
    *,
    as_of: date,
    candidates: list[dict[str, Any]],
    _min_industry_members: int = 0,
    _require_full_v2_levels: bool = False,
) -> list[dict[str, Any]]:
    """Annotate candidates with frozen legacy and SW2+SW3 Opportunity scores.

    The Sector Strength and RS engines keep their own frozen formulas.  This
    layer only composes independently ranked SW levels: SW2 is the primary
    industry context and SW3 is a lower-weight refinement.  SW1 remains an
    observable legacy/research context and never contributes to V2.
    """
    if not candidates:
        return []
    if _min_industry_members < 0:
        raise ValueError("_min_industry_members must be non-negative")

    try:
        sector_results_by_level = {
            level: build_sector_strength(
                repo, kind="industry", level=level, as_of=as_of,
                _strict_industry_level=True,
                _min_industry_members=_min_industry_members,
            )
            for level in (1, 2, 3)
        }
    except Exception as exc:  # fail closed; Wyckoff selection remains intact
        logger.warning("Wyckoff Sector/RS ranking skipped: sector strength failed: %s", exc)
        ranked = [_unknown_row(dict(row), "sector_strength_unavailable") for row in candidates]
        return _assign_ranks(ranked)

    sector_by_id = {
        result.sector_id: result
        for results in sector_results_by_level.values()
        for result in results
    }
    sector_ids = tuple(sorted(sector_by_id))
    if not sector_ids:
        ranked = [_unknown_row(dict(row), "sector_strength_unavailable") for row in candidates]
        return _assign_ranks(ranked)

    try:
        rs_results = build_relative_strength(
            repo,
            sector_ids=sector_ids,
            as_of=as_of,
            _strict_industry_level=True,
        )
    except Exception as exc:  # fail closed; no fallback to a made-up zero score
        logger.warning("Wyckoff Sector/RS ranking skipped: relative strength failed: %s", exc)
        ranked = [_unknown_row(dict(row), "relative_strength_unavailable") for row in candidates]
        return _assign_ranks(ranked)

    rs_by_symbol_level: dict[str, dict[int, object]] = {}
    for result in rs_results:
        level = _result_sector_level(result)
        if level is not None:
            rs_by_symbol_level.setdefault(str(result.symbol), {})[level] = result

    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        row = dict(candidate)
        symbol = str(row.get("symbol") or "")
        contexts = rs_by_symbol_level.get(symbol, {})
        legacy_rs, sw2_rs_result, sw3_rs_result = (
            contexts.get(1), contexts.get(2), contexts.get(3)
        )
        legacy_sector = sector_by_id.get(str(getattr(legacy_rs, "sector_id", "")))
        sw2_sector = sector_by_id.get(str(getattr(sw2_rs_result, "sector_id", "")))
        sw3_sector = sector_by_id.get(str(getattr(sw3_rs_result, "sector_id", "")))

        legacy_sector_score = _finite_number(getattr(legacy_sector, "score", None))
        legacy_rs_score = _finite_number(getattr(legacy_rs, "rs_score", None))
        legacy_opportunity = (
            0.40 * legacy_sector_score + 0.60 * legacy_rs_score
            if legacy_sector_score is not None and legacy_rs_score is not None else None
        )
        sw1_sector_score = legacy_sector_score
        sw2_sector_score = _finite_number(getattr(sw2_sector, "score", None))
        sw3_sector_score = _finite_number(getattr(sw3_sector, "score", None))
        market_rs = _finite_number(getattr(sw2_rs_result or sw3_rs_result or legacy_rs, "market_rs_score", None))
        sw2_rs_score = _finite_number(getattr(sw2_rs_result, "sector_rs_score", None))
        sw3_rs_score = _finite_number(getattr(sw3_rs_result, "sector_rs_score", None))
        sw2_available = sw2_sector_score is not None and sw2_rs_score is not None
        sw3_available = sw3_sector_score is not None and sw3_rs_score is not None

        # The frozen weights apply when all requested inputs exist.  A missing
        # SW3 never receives a fabricated industry assignment: the available
        # SW2 / Market weights are simply renormalized and the basis is exposed.
        if _require_full_v2_levels and (not sw2_available or not sw3_available or market_rs is None):
            sector_score_v2 = None
            rs_score_v2 = None
            opportunity_basis = "insufficient_members" if _min_industry_members else "missing_required_v2_level"
        elif sw2_available and sw3_available and market_rs is not None:
            sector_score_v2 = 0.70 * sw2_sector_score + 0.30 * sw3_sector_score
            rs_score_v2 = 0.40 * market_rs + 0.40 * sw2_rs_score + 0.20 * sw3_rs_score
            opportunity_basis = "sw2_sw3"
        elif sw2_available and market_rs is not None:
            sector_score_v2 = sw2_sector_score
            rs_score_v2 = 0.50 * market_rs + 0.50 * sw2_rs_score
            opportunity_basis = "sw2_only_missing_sw3"
        else:
            sector_score_v2 = legacy_sector_score
            rs_score_v2 = legacy_rs_score
            opportunity_basis = "legacy_fallback_missing_sw2" if legacy_opportunity is not None else "unavailable"
        opportunity_score_v2 = (
            0.40 * sector_score_v2 + 0.60 * rs_score_v2
            if sector_score_v2 is not None and rs_score_v2 is not None else None
        )
        hierarchy_source = sw2_rs_result or sw3_rs_result or legacy_rs
        hierarchy = {field: getattr(hierarchy_source, field, None) for field in _HIERARCHY_FIELDS}
        sw2_percentile = getattr(sw2_sector, "percentile", None)
        sw3_percentile = getattr(sw3_sector, "percentile", None)
        sw2_label = "STRONG" if sw2_percentile is not None and sw2_percentile >= 50 else "WEAK" if sw2_sector is not None else "UNKNOWN"
        sw3_label = "STRONG" if sw3_percentile is not None and sw3_percentile >= 50 else "WEAK" if sw3_sector is not None else "UNKNOWN"
        sector_hierarchy_state = f"SW2_{sw2_label}_SW3_{sw3_label}"

        # Existing phase/state diagnostics deliberately retain their SW1
        # context.  They are not inputs to OpportunityScore or V2 composition.
        sector = legacy_sector
        rs = legacy_rs
        sector_phase = getattr(sector, "phase", None)
        rs_state = getattr(rs, "rs_state", None)
        sector_extension = getattr(sector, "extension_state", None)
        rs_extension = getattr(rs, "rs_extension_state", None)
        dynamic_complete = sector is not None and rs is not None and _state_data_complete(sector) and _state_data_complete(rs)
        if sector_extension not in _EXTENSION_PENALTIES or rs_extension not in _EXTENSION_PENALTIES:
            sector_extension = None
            rs_extension = None

        sector_adjustment = _SECTOR_PHASE_ADJUSTMENTS.get(sector_phase, 0.0) if dynamic_complete else None
        rs_adjustment = _RS_STATE_ADJUSTMENTS.get(rs_state, 0.0) if dynamic_complete else None
        sector_penalty = _EXTENSION_PENALTIES.get(sector_extension) if dynamic_complete else None
        rs_penalty = _EXTENSION_PENALTIES.get(rs_extension) if dynamic_complete else None
        final_rank_score = (
            opportunity_score_v2 + sector_adjustment + rs_adjustment - sector_penalty - rs_penalty
            if opportunity_score_v2 is not None and None not in (sector_adjustment, rs_adjustment, sector_penalty, rs_penalty)
            else None
        )
        risk = (
            sector_phase in _RISK_SECTOR_PHASES
            or rs_state in _RISK_RS_STATES
            or sector_extension == "EXTREME"
            or rs_extension == "EXTREME"
        )
        if not dynamic_complete:
            priority = "UNKNOWN"
        elif risk:
            priority = "PRIORITY_C"
        elif (
            sector_phase in _POSITIVE_SECTOR_PHASES
            and rs_state in _POSITIVE_RS_STATES
            and sector_extension != "EXTREME"
            and rs_extension != "EXTREME"
        ):
            priority = "PRIORITY_A"
        else:
            priority = "PRIORITY_B"
        ranking_reasons = [
            f"sector_{str(sector_phase).lower()}"
            for sector_phase in [sector_phase]
            if sector_phase in _POSITIVE_SECTOR_PHASES
        ] + [
            f"rs_{str(rs_state).lower()}"
            for rs_state in [rs_state]
            if rs_state in _POSITIVE_RS_STATES
        ]
        risk_reasons = [
            f"sector_{str(sector_phase).lower()}"
            for sector_phase in [sector_phase]
            if sector_phase in _RISK_SECTOR_PHASES
        ] + [
            f"rs_{str(rs_state).lower()}"
            for rs_state in [rs_state]
            if rs_state in _RISK_RS_STATES
        ] + [
            f"sector_extension_{sector_extension.lower()}"
            for _ in [None]
            if sector_penalty is not None and sector_penalty > 0
        ] + [
            f"rs_extension_{rs_extension.lower()}"
            for _ in [None]
            if rs_penalty is not None and rs_penalty > 0
        ]
        ranked.append({
            **row,
            "sector_score_legacy": legacy_sector_score,
            "rs_score_legacy": legacy_rs_score,
            "opportunity_score_legacy": legacy_opportunity,
            "sw1_sector_score": sw1_sector_score,
            "sw2_sector_score": sw2_sector_score,
            "sw3_sector_score": sw3_sector_score,
            "sector_score_v2": sector_score_v2,
            "market_rs": market_rs,
            "sw2_rs": sw2_rs_score,
            "sw3_rs": sw3_rs_score,
            "rs_score_v2": rs_score_v2,
            "opportunity_score_v2": opportunity_score_v2,
            "opportunity_score_basis": opportunity_basis,
            "sector_hierarchy_state": sector_hierarchy_state,
            "sw2_available": sw2_available,
            "sw3_available": sw3_available,
            **hierarchy,
            # V2 is fully calculated and exposed above, but remains a
            # research-only field until its frozen ablation supports promotion.
            "sector_score": legacy_sector_score,
            "sector_phase": sector_phase,
            "sector_phase_adjustment": sector_adjustment,
            "sector_extension_state": sector_extension,
            "sector_extension_penalty": sector_penalty,
            "rs_score": legacy_rs_score,
            "rs_state": rs_state,
            "rs_state_adjustment": rs_adjustment,
            "rs_extension_state": rs_extension,
            "rs_extension_penalty": rs_penalty,
            "strength_score": legacy_opportunity,
            "final_rank_score": final_rank_score,
            "priority_level": priority,
            "ranking_reasons": ranking_reasons,
            "risk_reasons": risk_reasons,
            "sector_context": _context_values(sector, _SECTOR_CONTEXT_FIELDS) if sector is not None else None,
            "rs_context": _context_values(rs, _RS_CONTEXT_FIELDS) if rs is not None else None,
            "sw2_sector_context": _context_values(sw2_sector, _SECTOR_CONTEXT_FIELDS) if sw2_sector is not None else None,
            "sw3_sector_context": _context_values(sw3_sector, _SECTOR_CONTEXT_FIELDS) if sw3_sector is not None else None,
            "sw2_rs_context": _context_values(sw2_rs_result, _RS_CONTEXT_FIELDS) if sw2_rs_result is not None else None,
            "sw3_rs_context": _context_values(sw3_rs_result, _RS_CONTEXT_FIELDS) if sw3_rs_result is not None else None,
            "ranking_status": "complete" if dynamic_complete and opportunity_basis == "sw2_sw3" else "partial",
            "ranking_unavailable_reason": None if opportunity_score_v2 is not None else "sector_or_relative_strength_incomplete",
        })
    missing_sw2 = sum(not bool(row.get("sw2_available")) for row in ranked)
    missing_sw3 = sum(not bool(row.get("sw3_available")) for row in ranked)
    if missing_sw2 or missing_sw3:
        logger.warning(
            "Wyckoff Sector/RS hierarchy diagnostics as_of=%s candidates=%s missing_sw2=%s missing_sw3=%s",
            as_of, len(ranked), missing_sw2, missing_sw3,
        )
    return _assign_ranks(ranked)


def _assign_ranks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            row.get("final_rank_score") is None,
            -(row.get("final_rank_score") or 0.0),
            -(row.get("rs_score") or 0.0),
            -(row.get("sector_score") or 0.0),
            str(row.get("symbol") or ""),
        ),
    )
    return [{**row, "rank": index} for index, row in enumerate(ordered, start=1)]
