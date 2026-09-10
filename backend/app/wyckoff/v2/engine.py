# ruff: noqa: RUF001
"""Closed-bar event state machine for the independent Wyckoff v2 engine."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pandas as pd

from app.wyckoff.v2.config import WyckoffV2Config
from app.wyckoff.v2.diagnostics import summarize_events
from app.wyckoff.v2.entry_policy import entry_from_event
from app.wyckoff.v2.event_detector import evr_candidate, sos_candidate, spring_candidate
from app.wyckoff.v2.features import clv, median_volume_before, numeric, prepare_ohlcv
from app.wyckoff.v2.models import EntrySignal, TradingRangeSnapshot, WyckoffEvent, WyckoffV2Analysis
from app.wyckoff.v2.range_engine import identify_range_before, prepare_range_inputs
from app.wyckoff.v2.research_features import finite_research, spring_snapshot, test_snapshot
from app.wyckoff.v2.state_machine import is_terminal


def _date(frame: pd.DataFrame, index: int) -> str:
    return str(pd.Timestamp(frame["date"].iloc[index]).date())


def _event_id(symbol: str, event_type: str, occurred_at: str) -> str:
    return f"{symbol}:{event_type}:{occurred_at}"


def _event(
    symbol: str,
    event_type: str,
    state: str,
    occurred_at: str,
    trading_range: TradingRangeSnapshot,
    *,
    parent_event_id: str | None = None,
    invalidation: float | None = None,
    reason: str = "",
    metrics: dict[str, float] | None = None,
    research: dict[str, object] | None = None,
) -> WyckoffEvent:
    return WyckoffEvent(
        event_id=_event_id(symbol, event_type, occurred_at),
        symbol=symbol,
        event_type=event_type,
        range_id=trading_range.range_id,
        state=state,
        detected_at=occurred_at,
        range_snapshot=trading_range,
        parent_event_id=parent_event_id,
        invalidation=invalidation,
        reason=reason,
        metrics=metrics or {},
        research=finite_research(research or {}),
    )


def _replace_event(events: list[WyckoffEvent], event_id: str, **changes: Any) -> WyckoffEvent:
    for position, event in enumerate(events):
        if event.event_id == event_id:
            updated = replace(event, **changes)
            events[position] = updated
            return updated
    raise KeyError(event_id)


def _bar(frame: pd.DataFrame, index: int) -> tuple[float, float, float, float, float]:
    row = frame.iloc[index]
    return tuple(float(row[column]) for column in ("open", "high", "low", "close", "volume"))


def _expired(index: int, start_index: int, bars: int) -> bool:
    return index - start_index > max(int(bars), 0)


def _ranges_match(current: TradingRangeSnapshot, previous: TradingRangeSnapshot) -> bool:
    """Recognize a rolling observation of the same structural trading range."""
    scale = max(current.atr, previous.atr, 1e-9)
    support_distance = abs(current.support - previous.support) / scale
    resistance_distance = abs(current.resistance - previous.resistance) / scale
    current_start = pd.Timestamp(current.window_start)
    current_end = pd.Timestamp(current.window_end)
    previous_start = pd.Timestamp(previous.window_start)
    previous_end = pd.Timestamp(previous.window_end)
    overlap = max(0, (min(current_end, previous_end) - max(current_start, previous_start)).days + 1)
    shortest = max(1, min((current_end - current_start).days + 1, (previous_end - previous_start).days + 1))
    return support_distance <= 1.0 and resistance_distance <= 1.0 and overlap / shortest >= 0.60


def _identify_range_id(
    symbol: str,
    current: TradingRangeSnapshot,
    known_ranges: list[TradingRangeSnapshot],
) -> TradingRangeSnapshot:
    for previous in reversed(known_ranges):
        if _ranges_match(current, previous):
            return replace(current, range_id=previous.range_id)
    range_id = f"{symbol}:range:{len(known_ranges) + 1}:{current.window_start}"
    identified = replace(current, range_id=range_id)
    known_ranges.append(identified)
    return identified


def analyze_wyckoff_v2(
    symbol: str,
    source: pd.DataFrame,
    cfg: WyckoffV2Config | None = None,
    *,
    full_replay: bool = False,
) -> WyckoffV2Analysis:
    """Replay OHLCV in order and return independently-derived event chains.

    Every range is built from bars strictly before its event bar.  The function
    has no dependency on legacy trigger/stage/score output.
    """
    cfg = cfg or WyckoffV2Config()
    frame = prepare_ohlcv(source)
    # A parent SOS cannot produce an LPS after its configured horizon.  Older
    # bars therefore cannot alter any active chain and need not be replayed on
    # every all-market scan.
    replay_tail = cfg.range_lookback + max(
        cfg.spring_test_max_bars,
        cfg.sos_follow_through_max_bars + cfg.lps_max_bars_after_sos,
    ) + 2
    if not full_replay and len(frame) > replay_tail:
        frame = frame.tail(replay_tail).reset_index(drop=True)
    range_inputs = prepare_range_inputs(frame, cfg)
    event_horizon = max(cfg.spring_test_max_bars, cfg.sos_follow_through_max_bars + cfg.lps_max_bars_after_sos)
    scan_start = cfg.range_min_bars if full_replay else max(cfg.range_min_bars, len(frame) - event_horizon - 1)
    events: list[WyckoffEvent] = []
    entries: list[EntrySignal] = []
    ranges = 0
    spring_trackers: dict[str, dict[str, Any]] = {}
    sos_trackers: dict[str, dict[str, Any]] = {}
    lps_trackers: dict[str, dict[str, Any]] = {}
    shallow_lps_trackers: dict[str, dict[str, Any]] = {}
    known_ranges: list[TradingRangeSnapshot] = []
    funnel = {name: 0 for name in (
        "TRADING_RANGE", "SOS_DETECTED", "SOS_HELD", "SOS_CONFIRMED",
        "LPS_CLASSIC_CANDIDATE", "LPS_SHALLOW_CANDIDATE", "LPS_SUPPLY_TEST",
        "LPS_CLASSIC_CONFIRMED", "LPS_SHALLOW_CONFIRMED",
    )}
    rejection_reasons: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

    for index in range(scan_start, len(frame)):
        trading_range = identify_range_before(range_inputs, index, cfg)
        if trading_range is not None:
            ranges += 1
            funnel["TRADING_RANGE"] += 1
            trading_range = _identify_range_id(symbol, trading_range, known_ranges)
        occurred_at = _date(frame, index)
        atr = float(range_inputs.atr[index])
        if atr <= 0:
            continue
        _open, high, low, close, volume = _bar(frame, index)
        spread = high - low

        # Spring state machine.  The frozen range and Spring low are retained
        # so later K lines cannot move the original reference boundary.
        for event_id, tracker in list(spring_trackers.items()):
            event = tracker["event"]
            if index <= tracker["index"] or is_terminal(event.state):
                continue
            frozen = event.range_snapshot
            if low < tracker["spring_low"] - frozen.tolerance:
                event = _replace_event(events, event_id, state="HARD_INVALIDATION", invalidated_at=occurred_at)
                tracker["event"] = event
                continue
            if event.state == "TEST_VALID" and _expired(index, tracker["test_index"], cfg.spring_test_max_bars):
                tracker["event"] = _replace_event(events, event_id, state="NO_FOLLOW_THROUGH")
                continue
            if event.state in {"SPRING_DETECTED", "WAIT_TEST"} and _expired(index, tracker["index"], cfg.spring_test_max_bars):
                state = "TEST_REJECTED" if tracker.get("test_rejected") else "TEST_TIMEOUT"
                tracker["event"] = _replace_event(events, event_id, state=state)
                continue
            normal_volume = median_volume_before(frame, index, cfg.spring_test_normal_volume_window)
            normal_volume_ok = normal_volume is not None and volume / normal_volume <= cfg.spring_test_normal_volume_ratio
            spring_volume_ok = (
                event.event_type == "SPRING_LOW_SUPPLY" or volume < tracker["spring_volume"]
            )
            distance_to_support_atr = abs(low - frozen.support) / frozen.atr
            test_ok = (
                low >= tracker["spring_low"] - frozen.tolerance
                and normal_volume_ok
                and spring_volume_ok
                and spread <= tracker["spring_spread"] * cfg.spring_test_spread_ratio_max
                and close >= frozen.support
                and clv(_open, high, low, close) >= cfg.spring_test_min_clv
                and distance_to_support_atr <= cfg.spring_test_max_distance_atr
            )
            test_probe = low >= tracker["spring_low"] - frozen.tolerance and distance_to_support_atr <= cfg.spring_test_max_distance_atr
            if event.state in {"SPRING_DETECTED", "WAIT_TEST"} and test_probe and not test_ok:
                tracker["test_rejected"] = True
                tracker["event"] = _replace_event(
                    events,
                    event_id,
                    research={
                        **event.research,
                        **test_snapshot(
                            frame,
                            index,
                            spring_index=tracker["index"],
                            spring_low=tracker["spring_low"],
                            trading_range=frozen,
                            atr=atr,
                        ),
                    },
                )
            if event.state in {"SPRING_DETECTED", "WAIT_TEST"} and test_ok:
                test_research = test_snapshot(
                    frame,
                    index,
                    spring_index=tracker["index"],
                    spring_low=tracker["spring_low"],
                    trading_range=frozen,
                    atr=atr,
                )
                event = _replace_event(
                    events,
                    event_id,
                    state="TEST_VALID",
                    confirmed_at=occurred_at,
                    metrics={
                        **event.metrics,
                        "test_volume_to_normal": volume / float(normal_volume),
                        "test_volume_to_spring": volume / tracker["spring_volume"],
                        "test_distance_to_support_atr": distance_to_support_atr,
                    },
                    research={**event.research, **test_research},
                )
                tracker.update(event=event, test_high=high, test_index=index)
                entries.append(
                    entry_from_event(
                        event,
                        entry_type="spring_standard",
                        occurred_at=occurred_at,
                        price=close,
                        invalidation=tracker["spring_low"] - frozen.tolerance,
                        reason="Spring Test 在冻结支撑附近缩量、缩幅且收盘位置未破坏供应测试",
                    )
                )
            elif event.state == "TEST_VALID" and close > float(tracker["test_high"]):
                confirm_normal_volume = median_volume_before(frame, index, cfg.demand_confirm_volume_window)
                confirm_clv = clv(_open, high, low, close)
                structure_highs = numeric(frame.iloc[tracker["test_index"] : index], "high")
                swing_high = float(structure_highs.max()) if not structure_highs.empty else float(tracker["test_high"])
                variants = {
                    "SPRING_CONFIRM_BASE": True,
                    "SPRING_CONFIRM_ATR": close > float(tracker["test_high"]) + cfg.demand_confirm_atr_buffer * atr,
                    "SPRING_CONFIRM_CLV": confirm_clv >= cfg.demand_confirm_min_clv,
                    "SPRING_CONFIRM_VOLUME": confirm_normal_volume is not None and volume >= confirm_normal_volume,
                    "SPRING_CONFIRM_CLV_VOLUME": (
                        confirm_clv >= cfg.demand_confirm_min_clv
                        and confirm_normal_volume is not None
                        and volume >= confirm_normal_volume
                    ),
                    "SPRING_CONFIRM_SWING_HIGH": close > swing_high,
                }
                event = _replace_event(events, event_id, state="SPRING_CONFIRMED", confirmed_at=occurred_at)
                tracker["event"] = event
                entries.append(
                    entry_from_event(
                        event,
                        entry_type="spring_conservative",
                        occurred_at=occurred_at,
                        price=close,
                        invalidation=tracker["spring_low"] - frozen.tolerance,
                        reason="收盘突破已验证 Test 的高点，需求获得后续确认",
                        research={
                            **event.research,
                            "confirm_clv": confirm_clv,
                            "confirm_volume_ratio_vs_normal": volume / confirm_normal_volume if confirm_normal_volume else None,
                            "confirm_breakout_atr": (close - float(tracker["test_high"])) / atr,
                            "confirm_swing_high": swing_high,
                            "experiment_variants": [name for name, eligible in variants.items() if eligible],
                        },
                    )
                )
                for variant, eligible in variants.items():
                    if variant == "SPRING_CONFIRM_BASE" or not eligible:
                        continue
                    entries.append(
                        entry_from_event(
                            event,
                            entry_type=variant.lower(),
                            occurred_at=occurred_at,
                            price=close,
                            invalidation=tracker["spring_low"] - frozen.tolerance,
                            reason=f"研究变体：{variant}",
                            research={**event.research, "experiment_variants": [variant]},
                        )
                    )
            elif event.state == "SPRING_DETECTED":
                tracker["event"] = _replace_event(events, event_id, state="WAIT_TEST")

        # SOS must receive one subsequent closed-bar follow-through before it
        # becomes eligible as a parent of an LPS chain.
        for event_id, tracker in list(sos_trackers.items()):
            event = tracker["event"]
            if index <= tracker["index"]:
                continue
            frozen = event.range_snapshot
            if event.state == "SOS_CONFIRMED":
                if index - tracker["index"] <= 3:
                    impulse = max(float(tracker["sos_close"]) - frozen.creek, 1e-9)
                    retention = (close - frozen.creek) / impulse
                    tracker.setdefault("retentions", []).append(retention)
                    tracker.setdefault("closes", []).append(close)
                    research = {
                        **event.research,
                        "sos_retention_min": min(tracker["retentions"]),
                        "sos_retention_mean": sum(tracker["retentions"]) / len(tracker["retentions"]),
                        "sos_min_close_distance_atr": min((value - frozen.creek) / frozen.atr for value in tracker.get("closes", [close])),
                        "sos_back_in_range": any(value < frozen.creek for value in tracker.get("closes", [close])),
                    }
                    tracker["event"] = _replace_event(events, event_id, research=research)
                continue
            if close < frozen.creek - frozen.tolerance:
                tracker["event"] = _replace_event(events, event_id, state="SOS_FAILED", invalidated_at=occurred_at)
                reject("SOS_BACK_IN_RANGE")
            elif close >= frozen.creek:
                funnel["SOS_HELD"] += 1
                funnel["SOS_CONFIRMED"] += 1
                retention = (close - frozen.creek) / max(float(tracker["sos_close"]) - frozen.creek, 1e-9)
                tracker["event"] = _replace_event(
                    events,
                    event_id,
                    state="SOS_CONFIRMED",
                    confirmed_at=occurred_at,
                    research={**event.research, "sos_retention_1": retention, "sos_held": True},
                )
                tracker["confirmed_index"] = index
            elif _expired(index, tracker["index"], cfg.sos_follow_through_max_bars):
                tracker["event"] = _replace_event(events, event_id, state="SOS_FAILED", invalidated_at=occurred_at)
                reject("SOS_NOT_HELD")

        # LPS is impossible without a confirmed, frozen SOS parent.  A single
        # tracker is retained per parent event to prevent rolling recalculation
        # from producing duplicate daily LPS signals.
        for sos_id, sos_tracker in list(sos_trackers.items()):
            parent = sos_tracker["event"]
            if parent.state != "SOS_CONFIRMED" or index <= sos_tracker.get("confirmed_index", sos_tracker["index"]):
                continue
            if _expired(index, sos_tracker["index"], cfg.lps_max_bars_after_sos):
                if sos_id not in lps_trackers:
                    reject("NO_PULLBACK")
                    lps_trackers[sos_id] = {"expired": True}
                elif "event" in lps_trackers[sos_id] and not is_terminal(lps_trackers[sos_id]["event"].state):
                    reject("NO_DEMAND_CONFIRMATION")
                    lps_trackers[sos_id]["event"] = _replace_event(
                        events,
                        lps_trackers[sos_id]["event"].event_id,
                        state="LPS_FAILED",
                        invalidated_at=occurred_at,
                    )
                continue
            frozen = parent.range_snapshot
            tracker = lps_trackers.get(sos_id)
            if tracker is None:
                if low <= frozen.creek + cfg.lps_pullback_distance_atr * atr:
                    event = _event(
                        symbol,
                        "LPS",
                        "LPS_CANDIDATE",
                        occurred_at,
                        frozen,
                        parent_event_id=parent.event_id,
                        invalidation=frozen.creek - cfg.lps_close_below_creek_atr * atr,
                        reason="已确认 SOS 后首次回到冻结 Creek 附近，等待供应测试和转强",
                    )
                    events.append(event)
                    tracker = {"event": event, "index": index, "sos_volume": sos_tracker["volume"]}
                    lps_trackers[sos_id] = tracker
                    funnel["LPS_CLASSIC_CANDIDATE"] += 1
                continue
            event = tracker["event"]
            if is_terminal(event.state):
                continue
            if close < float(event.invalidation or frozen.creek):
                tracker["event"] = _replace_event(events, event.event_id, state="LPS_FAILED", invalidated_at=occurred_at)
                reject("CREEK_INVALIDATED")
                continue
            start = tracker["index"]
            pullback_lows = numeric(frame.iloc[start : index + 1], "low")
            pullback_volumes = numeric(frame.iloc[start : index + 1], "volume")
            pullback_depth = (frozen.creek - float(pullback_lows.min())) / atr
            volume_to_sos = float(pullback_volumes.median()) / float(tracker["sos_volume"])
            normal_volume = median_volume_before(frame, index, cfg.lps_normal_volume_window)
            volume_to_normal = float(pullback_volumes.median()) / float(normal_volume) if normal_volume else None
            if pullback_depth > cfg.lps_pullback_depth_atr_max:
                tracker["event"] = _replace_event(events, event.event_id, state="LPS_FAILED", invalidated_at=occurred_at)
                reject("CLASSIC_PULLBACK_TOO_DEEP")
                continue
            if (
                volume_to_sos <= cfg.lps_volume_to_sos_max
                and volume_to_normal is not None
                and volume_to_normal <= cfg.lps_volume_to_normal_max
                and event.state == "LPS_CANDIDATE"
            ):
                event = _replace_event(
                    events,
                    event.event_id,
                    state="SUPPLY_TEST",
                    metrics={
                        "pullback_depth_atr": pullback_depth,
                        "volume_to_sos": volume_to_sos,
                        "volume_to_normal": volume_to_normal,
                    },
                )
                tracker["event"] = event
                funnel["LPS_SUPPLY_TEST"] += 1
            elif event.state == "LPS_CANDIDATE" and volume_to_sos > cfg.lps_volume_to_sos_max:
                reject("VOLUME_NOT_CONTRACTED_VS_SOS")
            elif event.state == "LPS_CANDIDATE" and volume_to_normal is not None and volume_to_normal > cfg.lps_volume_to_normal_max:
                reject("VOLUME_NOT_CONTRACTED_VS_NORMAL")
            previous_highs = numeric(frame.iloc[max(start, index - cfg.lps_turning_lookback) : index], "high")
            if event.state == "SUPPLY_TEST" and not previous_highs.empty and close > float(previous_highs.max()):
                event = _replace_event(events, event.event_id, state="LPS_CONFIRMED", confirmed_at=occurred_at)
                tracker["event"] = event
                entries.append(
                    entry_from_event(
                        event,
                        entry_type="lps_classic_standard",
                        occurred_at=occurred_at,
                        price=close,
                        invalidation=float(event.invalidation or frozen.creek),
                        reason="确认 SOS 后回踩 Creek 相对 SOS 与正常量均收缩，且突破回踩局部高点",
                    )
                )
                # Kept as a compatibility alias for saved P0 UI selections.
                entries.append(
                    entry_from_event(
                        event,
                        entry_type="lps_standard",
                        occurred_at=occurred_at,
                        price=close,
                        invalidation=float(event.invalidation or frozen.creek),
                        reason="P0 compatibility alias of lps_classic_standard",
                    )
                )
                pullback_swing_highs = numeric(frame.iloc[start:index], "high")
                if not pullback_swing_highs.empty and close > float(pullback_swing_highs.max()):
                    entries.append(
                        entry_from_event(
                            event,
                            entry_type="lps_classic_swing_high",
                            occurred_at=occurred_at,
                            price=close,
                            invalidation=float(event.invalidation or frozen.creek),
                            reason="Classic LPS 研究变体：突破完整回撤结构的 swing high",
                        )
                    )
                held_retention = float(parent.research.get("sos_retention_min", parent.research.get("sos_retention_1", 0.0)) or 0.0)
                for threshold in cfg.sos_held_retention_thresholds:
                    if held_retention >= threshold:
                        entries.append(
                            entry_from_event(
                                event,
                                entry_type=f"lps_classic_sos_held_{int(threshold * 100):02d}",
                                occurred_at=occurred_at,
                                price=close,
                                invalidation=float(event.invalidation or frozen.creek),
                                reason=f"Classic LPS 研究变体：SOS 最低 retention ≥ {threshold:.0%}",
                                research={**event.research, "sos_held_threshold": threshold},
                            )
                        )
                funnel["LPS_CLASSIC_CONFIRMED"] += 1

        # Shallow LPS is intentionally a separate experiment, not a loosened
        # Classic Creek-retest rule.  It requires a retained SOS, a measurable
        # post-breakout impulse, no return to the old range, contracted supply,
        # and the same later demand confirmation.
        for sos_id, sos_tracker in list(sos_trackers.items()):
            parent = sos_tracker["event"]
            if parent.state != "SOS_CONFIRMED" or index <= sos_tracker.get("confirmed_index", sos_tracker["index"]):
                continue
            if _expired(index, sos_tracker["index"], cfg.lps_max_bars_after_sos):
                continue
            frozen = parent.range_snapshot
            tracker = shallow_lps_trackers.setdefault(
                sos_id,
                {"peak_high": float(sos_tracker["sos_high"]), "peak_index": sos_tracker["index"]},
            )
            if tracker.get("failed"):
                continue
            if low < frozen.creek:
                tracker["failed"] = True
                reject("SOS_BACK_IN_RANGE")
                continue
            tracker["peak_high"] = max(float(tracker["peak_high"]), high)
            impulse = float(tracker["peak_high"]) - frozen.creek
            if impulse < cfg.lps_shallow_min_impulse_atr * atr:
                continue
            retracement = (float(tracker["peak_high"]) - low) / impulse
            event = tracker.get("event")
            if event is None:
                if cfg.lps_shallow_retracement_min <= retracement <= cfg.lps_shallow_retracement_max:
                    event = _event(
                        symbol,
                        "LPS_SHALLOW",
                        "LPS_SHALLOW_CANDIDATE",
                        occurred_at,
                        frozen,
                        parent_event_id=parent.event_id,
                        invalidation=frozen.creek,
                        reason="SOS 后未回到旧区间的浅回撤，等待缩量与需求确认",
                        research={"sos_impulse_atr": impulse / atr, "pullback_retracement_ratio": retracement},
                    )
                    events.append(event)
                    tracker.update(event=event, index=index)
                    funnel["LPS_SHALLOW_CANDIDATE"] += 1
                elif retracement > cfg.lps_shallow_retracement_max:
                    tracker["failed"] = True
                    reject("SHALLOW_RETRACE_TOO_DEEP")
                continue
            if event.state in {"LPS_SHALLOW_CONFIRMED", "LPS_FAILED"}:
                continue
            start = int(tracker["index"])
            pullback_volumes = numeric(frame.iloc[start : index + 1], "volume")
            volume_to_sos = float(pullback_volumes.median()) / float(sos_tracker["volume"])
            normal_volume = median_volume_before(frame, index, cfg.lps_normal_volume_window)
            volume_to_normal = float(pullback_volumes.median()) / float(normal_volume) if normal_volume else None
            if volume_to_sos > cfg.lps_shallow_volume_to_sos_max:
                reject("VOLUME_NOT_CONTRACTED_VS_SOS")
                continue
            if volume_to_normal is None or volume_to_normal > cfg.lps_shallow_volume_to_normal_max:
                reject("VOLUME_NOT_CONTRACTED_VS_NORMAL")
                continue
            previous_highs = numeric(frame.iloc[max(start, index - cfg.lps_turning_lookback) : index], "high")
            if not previous_highs.empty and close > float(previous_highs.max()):
                event = _replace_event(
                    events,
                    event.event_id,
                    state="LPS_SHALLOW_CONFIRMED",
                    confirmed_at=occurred_at,
                    research={**event.research, "volume_to_sos": volume_to_sos, "volume_to_normal": volume_to_normal},
                )
                tracker["event"] = event
                entries.append(
                    entry_from_event(
                        event,
                        entry_type="lps_shallow_standard",
                        occurred_at=occurred_at,
                        price=close,
                        invalidation=frozen.creek,
                        reason="Shallow LPS 缩量回撤后突破局部高点",
                    )
                )
                funnel["LPS_SHALLOW_CONFIRMED"] += 1

        # New events are evaluated after updates, so they cannot confirm or
        # invalidate themselves on their own bar.
        if trading_range is None:
            continue
        spring = spring_candidate(frame, index, trading_range, atr, cfg)
        active_spring_in_range = any(
            tracker_event.event_type.startswith("SPRING_")
            and tracker_event.range_id == trading_range.range_id
            and not is_terminal(tracker_event.state)
            for tracker in spring_trackers.values()
            for tracker_event in [tracker["event"]]
        )
        if spring is not None and not active_spring_in_range:
            event_type, metrics = spring
            event = _event(
                symbol,
                event_type,
                "SPRING_DETECTED",
                occurred_at,
                trading_range,
                invalidation=low - trading_range.tolerance,
                reason="刺穿支撑后收回，穿透幅度与收盘位置满足 Spring 候选条件",
                metrics=metrics,
                research=spring_snapshot(frame, index, trading_range, atr),
            )
            events.append(event)
            spring_trackers[event.event_id] = {
                "event": event,
                "index": index,
                "spring_low": low,
                "spring_volume": volume,
                "spring_spread": spread,
                "test_rejected": False,
            }
            entries.append(
                entry_from_event(
                    event,
                    entry_type="spring_aggressive",
                    occurred_at=occurred_at,
                    price=close,
                    invalidation=low - trading_range.tolerance,
                    reason="Spring 当日收回支撑；仅适用于激进、较小仓位的介入策略",
                )
            )

        sos = sos_candidate(frame, index, trading_range, atr, cfg)
        if sos is not None:
            event = _event(
                symbol,
                "SOS",
                "SOS_DETECTED",
                occurred_at,
                trading_range,
                invalidation=trading_range.creek - trading_range.tolerance,
                reason="真实穿越冻结 Creek，价格推进、收盘位置和自身历史量能均达标",
                metrics=sos,
            )
            events.append(event)
            sos_trackers[event.event_id] = {"event": event, "index": index, "volume": volume, "sos_close": close, "sos_high": high, "closes": [close]}
            funnel["SOS_DETECTED"] += 1

        evr = evr_candidate(frame, index, trading_range, atr, cfg)
        if evr is not None:
            event_type, metrics = evr
            events.append(
                _event(
                    symbol,
                    event_type,
                    "OBSERVATION",
                    occurred_at,
                    trading_range,
                    reason="高 effort、低 result 的量价异常，按位置和收盘位置归类为供需证据",
                    metrics=metrics,
                )
            )

    return WyckoffV2Analysis(
        symbol=symbol,
        events=tuple(events),
        entries=tuple(entries),
        diagnostics=summarize_events(
            events,
            bars=len(frame),
            range_evaluations=ranges,
            funnel=funnel,
            rejection_reasons=rejection_reasons,
        ),
    )
