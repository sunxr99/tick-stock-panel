"""Wyckoff signal-to-event classification.

Migrated from the local ``reference/WyckoffTradingAgent`` source for this
private deployment.  Events are readable observation labels, never trade
instructions by themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class WyckoffEvent:
    event_id: str
    label: str
    track: str
    action: str
    confidence: str
    reasons: tuple[str, ...]
    watch_points: tuple[str, ...]


@dataclass(frozen=True)
class _EventSpec:
    event_id: str
    label: str
    track: str
    action: str
    confidence: str
    reasons: tuple[str, ...]
    watch_points: tuple[str, ...]


_RIGHT_SIDE_IGNITION = _EventSpec("right_side_ignition", "右侧点火", "Trend", "强度观察", "medium", ("SOS 放量突破", "Markup 主升阶段"), ("次日不宜大幅回落至突破位下方", "量能需要维持或温和缩量承接"))
_ACCUM_REPAIR_RESONANCE = _EventSpec("accumulation_repair_resonance", "吸筹修复共振", "Accum", "低位观察", "medium", ("Spring 修复", "缩量回踩或放量承接共振"), ("不能再次有效跌破交易区间下沿", "后续需要从修复转向放量上攻"))
_SPRING_RECLAIM = _EventSpec("spring_reclaim", "Spring 修复", "Accum", "低位观察", "medium", ("假跌破后重新收回",), ("观察是否站回区间内部", "避免次日继续破位"))
_LPS_PULLBACK_CONFIRM = _EventSpec("lps_pullback_confirm", "LPS 回踩确认", "Accum", "支撑观察", "medium", ("缩量回踩支撑",), ("回踩不应放量跌破支撑", "后续需要重新转强"))
_VOLUME_ABSORPTION = _EventSpec("volume_absorption", "放量承接", "Accum", "承接观察", "medium", ("放量但价格不弱",), ("放量后不能快速转弱", "等待后续转为 SOS 或 LPS 确认"))
_SOS_WATCH = _EventSpec("sos_watch", "SOS 观察", "Trend", "强度观察", "medium", ("SOS 信号",), ("确认突破是否有效", "高开过多不宜追"))
_WYCKOFF_WATCH = _EventSpec("wyckoff_watch", "威科夫观察", "Watch", "观察", "low", (), ("等待更多结构确认",))


def _norm_set(values: tuple[str, ...] | list[str] | set[str]) -> set[str]:
    return {str(value or "").strip().lower() for value in values if str(value or "").strip()}


def _base_reasons(stage: str, channel: str, regime: str, score: float) -> list[str]:
    reasons: list[str] = []
    if stage:
        reasons.append(f"阶段={stage}")
    if channel:
        reasons.append(f"通道={channel}")
    if regime:
        reasons.append(f"水温={regime}")
    if score:
        reasons.append(f"分数={float(score):.2f}")
    return reasons


def _event(*, spec: _EventSpec, base_reasons: list[str]) -> WyckoffEvent:
    return WyckoffEvent(
        event_id=spec.event_id,
        label=spec.label,
        track=spec.track,
        action=spec.action,
        confidence=spec.confidence,
        reasons=tuple([*base_reasons, *spec.reasons]),
        watch_points=spec.watch_points,
    )


def _score_confidence(score: float, high_threshold: float) -> str:
    return "high" if score >= high_threshold else "medium"


def _event_spec(trigger_set: set[str], stage: str, score: float) -> _EventSpec:
    if "sos" in trigger_set and stage == "Markup":
        return replace(_RIGHT_SIDE_IGNITION, confidence=_score_confidence(score, 10))
    if "spring" in trigger_set and ("lps" in trigger_set or "evr" in trigger_set):
        return replace(_ACCUM_REPAIR_RESONANCE, confidence=_score_confidence(score, 5))
    if "spring" in trigger_set:
        return _SPRING_RECLAIM
    if "lps" in trigger_set:
        return _LPS_PULLBACK_CONFIRM
    if "evr" in trigger_set:
        return replace(_VOLUME_ABSORPTION, track="Trend" if stage == "Markup" else "Accum")
    if "sos" in trigger_set:
        return _SOS_WATCH
    return _WYCKOFF_WATCH


def classify_wyckoff_event(
    triggers: tuple[str, ...] | list[str] | set[str],
    *,
    stage: str = "",
    channel: str = "",
    score: float = 0.0,
    regime: str = "",
) -> WyckoffEvent:
    """Convert raw Wyckoff trigger facts to one readable event label."""
    stage_s = str(stage or "").strip()
    channel_s = str(channel or "").strip()
    regime_s = str(regime or "").strip().upper()
    return _event(
        spec=_event_spec(_norm_set(triggers), stage_s, score),
        base_reasons=_base_reasons(stage_s, channel_s, regime_s, score),
    )


__all__ = ["WyckoffEvent", "classify_wyckoff_event"]
