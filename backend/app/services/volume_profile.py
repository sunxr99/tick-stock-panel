"""Read-only, non-repainting Volume Profile V1.

The engine deliberately knows nothing about strategies, Sector/RS, or a data
provider.  ``VolumeProfileService`` is the small repository adapter; the pure
``VolumeProfileEngine`` receives already-normalized bars and always truncates
them at ``as_of``.  This keeps daily fallback explicit and lets a future tick
source reuse the allocation/profile rules unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from math import isclose, isfinite
from time import perf_counter
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from app.tickflow.repository import KlineRepository


class ProfileType(StrEnum):
    VP20 = "VP20"
    VP60 = "VP60"
    WYCKOFF_RANGE = "WYCKOFF_RANGE"


class AllocationMode(StrEnum):
    MINUTE_RANGE_OVERLAP = "MINUTE_RANGE_OVERLAP"
    DAILY_RANGE_OVERLAP = "DAILY_RANGE_OVERLAP"
    CLOSE_ONLY = "CLOSE_ONLY"


class DataGranularity(StrEnum):
    MINUTE_1M = "MINUTE_1M"
    DAILY = "DAILY"
    NONE = "NONE"


class ProfileQuality(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    FALLBACK = "FALLBACK"
    UNAVAILABLE = "UNAVAILABLE"


class PocState(StrEnum):
    RISING = "POC_RISING"
    FLAT = "POC_FLAT"
    FALLING = "POC_FALLING"
    UNAVAILABLE = "POC_UNAVAILABLE"


class ValueAreaState(StrEnum):
    RISING = "VALUE_AREA_RISING"
    STABLE = "VALUE_AREA_STABLE"
    FALLING = "VALUE_AREA_FALLING"
    UNAVAILABLE = "VALUE_AREA_UNAVAILABLE"


class PositionState(StrEnum):
    BELOW_VAL = "BELOW_VAL"
    WITHIN_VALUE = "WITHIN_VALUE"
    ABOVE_VAH = "ABOVE_VAH"
    UNAVAILABLE = "POSITION_UNAVAILABLE"


class ProximityState(StrEnum):
    NEAR_POC = "NEAR_POC"
    NEAR_VAH = "NEAR_VAH"
    NEAR_VAL = "NEAR_VAL"


class AcceptanceState(StrEnum):
    ABOVE_VAH_ACCEPTED = "ABOVE_VAH_ACCEPTED"
    ABOVE_VAH_UNACCEPTED = "ABOVE_VAH_UNACCEPTED"
    NOT_ABOVE_VAH = "NOT_ABOVE_VAH"
    UNAVAILABLE = "ACCEPTANCE_UNAVAILABLE"


class ExtensionState(StrEnum):
    NORMAL = "VP_NORMAL"
    ELEVATED = "VP_ELEVATED"
    EXTENDED = "VP_EXTENDED"
    EXTREME = "VP_EXTREME"
    UNAVAILABLE = "VP_EXTENSION_UNAVAILABLE"


class VolumeProfileMode(StrEnum):
    """Cost-controlled orchestration; it never changes VP mathematics."""

    LITE = "VP_LITE"
    FULL = "VP_FULL"


@dataclass(frozen=True)
class PriceBin:
    index: int
    low: float
    high: float
    center: float
    volume: float


@dataclass(frozen=True)
class VolumeProfileRequest:
    profile_type: ProfileType
    as_of: date | datetime
    bin_count: int = 100
    value_area_pct: float = 0.70
    allocation_mode: AllocationMode = AllocationMode.MINUTE_RANGE_OVERLAP
    range_start: date | None = None
    range_confirmed_at: date | None = None
    allow_daily_fallback: bool = True


@dataclass(frozen=True)
class VolumeProfileResult:
    symbol: str
    profile_type: ProfileType
    as_of: date
    requested_start: date | None
    data_start: date | None
    data_end: date | None
    data_granularity: DataGranularity
    allocation_mode: AllocationMode
    required_trading_days: int | None
    actual_trading_days: int
    expected_minute_bars: int
    actual_minute_bars: int
    minute_coverage_ratio: float | None
    bin_count: int
    profile_low: float | None
    profile_high: float | None
    poc: float | None
    poc_bin_index: int | None
    poc_volume: float | None
    vah: float | None
    val: float | None
    value_area_pct: float
    value_area_pct_actual: float | None
    value_area_volume: float | None
    current_price: float | None
    distance_to_poc_pct: float | None
    distance_to_vah_pct: float | None
    distance_to_val_pct: float | None
    distance_to_poc_atr: float | None
    distance_to_vah_atr: float | None
    hvn_levels: tuple[float, ...]
    lvn_levels: tuple[float, ...]
    bins: tuple[PriceBin, ...]
    quality: ProfileQuality
    fallback_used: bool
    unavailable_reason: str | None = None
    quality_reasons: tuple[str, ...] = ()
    atr_14: float | None = None
    poc_change_1d_pct: float | None = None
    poc_change_3d_pct: float | None = None
    vah_change_1d_pct: float | None = None
    vah_change_3d_pct: float | None = None
    val_change_1d_pct: float | None = None
    val_change_3d_pct: float | None = None
    poc_state: PocState = PocState.UNAVAILABLE
    value_area_state: ValueAreaState = ValueAreaState.UNAVAILABLE
    position_context: PositionState = PositionState.UNAVAILABLE
    proximity_contexts: tuple[ProximityState, ...] = ()
    acceptance_context: AcceptanceState = AcceptanceState.UNAVAILABLE
    extension_context: ExtensionState = ExtensionState.UNAVAILABLE


@dataclass(frozen=True)
class VolumeProfileResearchContext:
    """Optional join-shaped DTO for later read-only Wyckoff/strength research."""

    symbol: str
    as_of: date
    sector_phase: str | None
    narrowing_flag: bool | None
    rs_state: str | None
    vp20: VolumeProfileResult
    vp60: VolumeProfileResult
    wyckoff_range_vp: VolumeProfileResult


@dataclass(frozen=True)
class MinuteQuality:
    expected_bars: int
    actual_bars: int
    coverage_ratio: float | None
    quality: ProfileQuality
    reasons: tuple[str, ...]


@dataclass
class BatchMinuteDataContext:
    """Run-scoped, as-of-safe daily/minute bars for a candidate batch.

    The context is deliberately in-memory only.  It is a repository-shaped
    adapter so the existing single-profile service/engine path can consume
    preloaded bars without changing any profile calculation.
    """

    as_of: date
    daily_by_symbol: dict[str, pl.DataFrame]
    minute_by_symbol_date: dict[tuple[str, date], pl.DataFrame]
    requested_minute_dates: tuple[date, ...]
    minute_partition_reads: int
    minute_rows_loaded: int
    minute_estimated_bytes: int
    timings_ms: dict[str, float] = field(default_factory=dict)

    def get_daily(
        self,
        symbol: str,
        start: date,
        end: date,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        frame = self.daily_by_symbol.get(symbol)
        if frame is None or frame.is_empty():
            return pl.DataFrame()
        output = frame.filter((pl.col("date") >= start) & (pl.col("date") <= end))
        if columns is not None:
            return output.select([column for column in columns if column in output.columns])
        return output

    def get_minute_by_dates(
        self,
        symbols: Sequence[str],
        dates: Sequence[date],
        asset_type: str = "stock",
    ) -> pl.DataFrame:
        del asset_type
        frames = [
            frame
            for symbol in symbols
            for value in dates
            if value <= self.as_of
            if (frame := self.minute_by_symbol_date.get((symbol, value))) is not None
        ]
        return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _ohlcv_price_tolerance(*prices: float) -> float:
    """Accept machine precision at an OHLC range boundary, never a price tick."""
    scale = max((abs(price) for price in prices), default=0.0)
    # 1e-8 is still six orders below the A-share 0.01 minimum price tick.
    return min(1e-8, max(1e-12, scale * 1e-12))


def _row_date(row: Mapping[str, Any]) -> date | None:
    raw = row.get("datetime", row.get("date"))
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw).date()
        except ValueError:
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                return None
    return None


def _on_or_before_as_of(row: Mapping[str, Any], as_of: date | datetime) -> bool:
    """Apply exact intraday cut-off when a caller supplies a datetime.

    A date ``as_of`` intentionally means the complete post-close session.  A
    datetime must not gain later bars from the same date.
    """
    row_day = _row_date(row)
    if row_day is None:
        return False
    if not isinstance(as_of, datetime):
        return row_day <= as_of
    stamp = _as_datetime(row.get("datetime"))
    return stamp <= as_of if stamp is not None else row_day <= as_of.date()


def _records(frame: pl.DataFrame | Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(frame, pl.DataFrame):
        return frame.to_dicts()
    return [dict(row) for row in frame]


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous * 100.0


def _distance_pct(current: float | None, reference: float | None) -> float | None:
    if current is None or reference is None or reference == 0:
        return None
    return (current - reference) / reference * 100.0


def _unavailable(
    request: VolumeProfileRequest,
    symbol: str,
    *,
    reason: str,
    required_days: int | None = None,
    actual_days: int = 0,
    expected_bars: int = 0,
    actual_bars: int = 0,
    coverage: float | None = None,
    quality: ProfileQuality = ProfileQuality.UNAVAILABLE,
    quality_reasons: tuple[str, ...] = (),
) -> VolumeProfileResult:
    return VolumeProfileResult(
        symbol=symbol,
        profile_type=request.profile_type,
        as_of=_as_date(request.as_of),
        requested_start=request.range_start,
        data_start=None,
        data_end=None,
        data_granularity=DataGranularity.NONE,
        allocation_mode=request.allocation_mode,
        required_trading_days=required_days,
        actual_trading_days=actual_days,
        expected_minute_bars=expected_bars,
        actual_minute_bars=actual_bars,
        minute_coverage_ratio=coverage,
        bin_count=request.bin_count,
        profile_low=None,
        profile_high=None,
        poc=None,
        poc_bin_index=None,
        poc_volume=None,
        vah=None,
        val=None,
        value_area_pct=request.value_area_pct,
        value_area_pct_actual=None,
        value_area_volume=None,
        current_price=None,
        distance_to_poc_pct=None,
        distance_to_vah_pct=None,
        distance_to_val_pct=None,
        distance_to_poc_atr=None,
        distance_to_vah_atr=None,
        hvn_levels=(),
        lvn_levels=(),
        bins=(),
        quality=quality,
        fallback_used=False,
        unavailable_reason=reason,
        quality_reasons=quality_reasons,
    )


class RangeOverlapAllocator:
    """Shared volume allocator for minute and daily bars.

    The sum of allocated bin volume is conserved up to floating-point error.
    """

    @staticmethod
    def allocate(
        bars: Iterable[Mapping[str, Any]],
        *,
        profile_low: float,
        profile_high: float,
        bin_count: int,
        close_only: bool,
    ) -> tuple[list[float], list[tuple[float, float]]]:
        if bin_count < 1:
            raise ValueError("bin_count must be positive")
        if profile_high < profile_low:
            raise ValueError("profile_high must not be below profile_low")
        if isclose(profile_high, profile_low, abs_tol=1e-12):
            return [
                sum(max(_as_float(row.get("volume")) or 0.0, 0.0) for row in bars)
            ], [(profile_low, profile_high)]

        width = (profile_high - profile_low) / bin_count
        edges = [
            (profile_low + index * width, profile_high if index == bin_count - 1 else profile_low + (index + 1) * width)
            for index in range(bin_count)
        ]
        volumes = [0.0] * bin_count

        def bin_index(price: float) -> int:
            raw = int((price - profile_low) / width)
            return min(max(raw, 0), bin_count - 1)

        for row in bars:
            low, high, close, volume = (
                _as_float(row.get("low")),
                _as_float(row.get("high")),
                _as_float(row.get("close")),
                _as_float(row.get("volume")),
            )
            if low is None or high is None or close is None or volume is None or volume <= 0:
                continue
            if high < low:
                continue
            if close_only or isclose(high, low, abs_tol=1e-12):
                volumes[bin_index(close)] += volume
                continue

            # Only bins that can overlap the bar are considered.  The final
            # bin is inclusive at its upper boundary; width-based allocation
            # itself is continuous so no special endpoint volume is required.
            first, last = bin_index(low), bin_index(high)
            total_allocated = 0.0
            for index in range(first, last + 1):
                bin_low, bin_high = edges[index]
                overlap = max(0.0, min(high, bin_high) - max(low, bin_low))
                if overlap <= 0:
                    continue
                allocation = volume * overlap / (high - low)
                volumes[index] += allocation
                total_allocated += allocation
            # Float arithmetic can leave a negligible remainder.  Assign it
            # deterministically to the bar close bin, preserving volume.
            remainder = volume - total_allocated
            if abs(remainder) > 1e-10:
                volumes[bin_index(close)] += remainder
        return volumes, edges


class VolumeProfileEngine:
    """Pure Volume-at-Price, POC, Value Area and node calculation."""

    def build_profile(
        self,
        bars: pl.DataFrame | Sequence[Mapping[str, Any]],
        request: VolumeProfileRequest,
        *,
        symbol: str,
        data_granularity: DataGranularity,
        required_trading_days: int | None,
        actual_trading_days: int,
        expected_minute_bars: int = 0,
        actual_minute_bars: int = 0,
        minute_coverage_ratio: float | None = None,
        quality: ProfileQuality = ProfileQuality.FULL,
        fallback_used: bool = False,
        quality_reasons: Sequence[str] = (),
        atr_14: float | None = None,
    ) -> VolumeProfileResult:
        as_of = _as_date(request.as_of)
        all_rows = _records(bars)
        rows = [row for row in all_rows if _on_or_before_as_of(row, request.as_of)]
        valid = []
        for row in rows:
            low, high, close, volume = (_as_float(row.get("low")), _as_float(row.get("high")), _as_float(row.get("close")), _as_float(row.get("volume")))
            if low is None or high is None or close is None or volume is None or high < low or volume < 0:
                continue
            valid.append(row)
        if not valid:
            return _unavailable(
                request,
                symbol,
                reason="no_valid_bars",
                required_days=required_trading_days,
                actual_days=actual_trading_days,
                expected_bars=expected_minute_bars,
                actual_bars=actual_minute_bars,
                coverage=minute_coverage_ratio,
                quality=ProfileQuality.UNAVAILABLE,
                quality_reasons=tuple(quality_reasons),
            )

        profile_low = min(float(row["low"]) for row in valid)
        profile_high = max(float(row["high"]) for row in valid)
        requested_bin_count = request.bin_count
        effective_bin_count = 1 if isclose(profile_low, profile_high, abs_tol=1e-12) else requested_bin_count
        volumes, edges = RangeOverlapAllocator.allocate(
            valid,
            profile_low=profile_low,
            profile_high=profile_high,
            bin_count=effective_bin_count,
            close_only=request.allocation_mode == AllocationMode.CLOSE_ONLY,
        )
        total_volume = sum(volumes)
        if total_volume <= 0:
            return _unavailable(
                request,
                symbol,
                reason="non_positive_profile_volume",
                required_days=required_trading_days,
                actual_days=actual_trading_days,
                expected_bars=expected_minute_bars,
                actual_bars=actual_minute_bars,
                coverage=minute_coverage_ratio,
                quality=ProfileQuality.UNAVAILABLE,
                quality_reasons=tuple(quality_reasons),
            )

        midpoint = (profile_low + profile_high) / 2.0
        max_volume = max(volumes)
        tied = [index for index, volume in enumerate(volumes) if isclose(volume, max_volume, rel_tol=1e-12, abs_tol=1e-10)]
        # Rounding removes an otherwise accidental binary-float preference
        # between mathematically equidistant bins; lower bin then wins.
        poc_index = min(
            tied,
            key=lambda index: (round(abs((edges[index][0] + edges[index][1]) / 2.0 - midpoint), 12), index),
        )
        low_index, high_index, value_area_volume = self._value_area(volumes, poc_index, request.value_area_pct)
        bins = tuple(
            PriceBin(index=index, low=low, high=high, center=(low + high) / 2.0, volume=volumes[index])
            for index, (low, high) in enumerate(edges)
        )
        current_row = max(valid, key=lambda row: (_row_date(row) or date.min, _as_datetime(row.get("datetime")) or datetime.min))
        current_price = _as_float(current_row.get("close"))
        hvn, lvn = self._nodes(bins)
        data_dates = sorted({_row_date(row) for row in valid if _row_date(row) is not None})
        poc = bins[poc_index].center
        vah, val = bins[high_index].high, bins[low_index].low
        result = VolumeProfileResult(
            symbol=symbol,
            profile_type=request.profile_type,
            as_of=as_of,
            requested_start=request.range_start,
            data_start=data_dates[0] if data_dates else None,
            data_end=data_dates[-1] if data_dates else None,
            data_granularity=data_granularity,
            allocation_mode=request.allocation_mode,
            required_trading_days=required_trading_days,
            actual_trading_days=actual_trading_days,
            expected_minute_bars=expected_minute_bars,
            actual_minute_bars=actual_minute_bars,
            minute_coverage_ratio=minute_coverage_ratio,
            bin_count=effective_bin_count,
            profile_low=profile_low,
            profile_high=profile_high,
            poc=poc,
            poc_bin_index=poc_index,
            poc_volume=volumes[poc_index],
            vah=vah,
            val=val,
            value_area_pct=request.value_area_pct,
            value_area_pct_actual=value_area_volume / total_volume,
            value_area_volume=value_area_volume,
            current_price=current_price,
            distance_to_poc_pct=_distance_pct(current_price, poc),
            distance_to_vah_pct=_distance_pct(current_price, vah),
            distance_to_val_pct=_distance_pct(current_price, val),
            distance_to_poc_atr=(current_price - poc) / atr_14 if atr_14 and current_price is not None else None,
            distance_to_vah_atr=(current_price - vah) / atr_14 if atr_14 and current_price is not None else None,
            hvn_levels=hvn,
            lvn_levels=lvn,
            bins=bins,
            quality=quality,
            fallback_used=fallback_used,
            quality_reasons=tuple(quality_reasons),
            atr_14=atr_14,
        )
        return self.with_context(result)

    @staticmethod
    def _value_area(volumes: Sequence[float], poc_index: int, target_ratio: float) -> tuple[int, int, float]:
        if not 0 < target_ratio <= 1:
            raise ValueError("value_area_pct must be in (0, 1]")
        total = sum(volumes)
        target = total * target_ratio
        low_index = high_index = poc_index
        accumulated = volumes[poc_index]
        while accumulated + 1e-12 < target and (low_index > 0 or high_index < len(volumes) - 1):
            left = volumes[low_index - 1] if low_index > 0 else None
            right = volumes[high_index + 1] if high_index < len(volumes) - 1 else None
            # Reference-compatible deterministic tie: choose the high side.
            if right is not None and (left is None or right >= left):
                high_index += 1
                accumulated += volumes[high_index]
            else:
                low_index -= 1
                accumulated += volumes[low_index]
        return low_index, high_index, accumulated

    @staticmethod
    def _nodes(bins: Sequence[PriceBin]) -> tuple[tuple[float, ...], tuple[float, ...]]:
        hvn = []
        lvn = []
        for index in range(1, len(bins) - 1):
            left, current, right = bins[index - 1].volume, bins[index].volume, bins[index + 1].volume
            if current > left and current > right:
                hvn.append(bins[index].center)
            if current < left and current < right:
                lvn.append(bins[index].center)
        return tuple(hvn), tuple(lvn)

    @staticmethod
    def with_context(result: VolumeProfileResult) -> VolumeProfileResult:
        if result.current_price is None or result.poc is None or result.vah is None or result.val is None:
            return result
        price = result.current_price
        position = PositionState.BELOW_VAL if price < result.val else PositionState.ABOVE_VAH if price > result.vah else PositionState.WITHIN_VALUE
        proximity: list[ProximityState] = []
        for level, state in ((result.poc, ProximityState.NEAR_POC), (result.vah, ProximityState.NEAR_VAH), (result.val, ProximityState.NEAR_VAL)):
            distance = _distance_pct(price, level)
            if distance is not None and abs(distance) <= 0.5:
                proximity.append(state)
        positioned = replace(result, position_context=position, proximity_contexts=tuple(proximity))
        return replace(positioned, extension_context=VolumeProfileEngine._extension_state(positioned))

    @staticmethod
    def with_dynamic_context(
        current: VolumeProfileResult,
        prior_1d: VolumeProfileResult | None,
        prior_3d: VolumeProfileResult | None,
    ) -> VolumeProfileResult:
        poc_1d = _pct_change(current.poc, prior_1d.poc) if prior_1d else None
        poc_3d = _pct_change(current.poc, prior_3d.poc) if prior_3d else None
        vah_1d = _pct_change(current.vah, prior_1d.vah) if prior_1d else None
        vah_3d = _pct_change(current.vah, prior_3d.vah) if prior_3d else None
        val_1d = _pct_change(current.val, prior_1d.val) if prior_1d else None
        val_3d = _pct_change(current.val, prior_3d.val) if prior_3d else None
        threshold = 0.5  # fixed descriptive migration threshold; not return-optimised
        if poc_3d is None:
            poc_state = PocState.UNAVAILABLE
        elif poc_3d >= threshold:
            poc_state = PocState.RISING
        elif poc_3d <= -threshold:
            poc_state = PocState.FALLING
        else:
            poc_state = PocState.FLAT
        if vah_3d is None or val_3d is None:
            value_state = ValueAreaState.UNAVAILABLE
        elif vah_3d >= threshold and val_3d >= threshold:
            value_state = ValueAreaState.RISING
        elif vah_3d <= -threshold and val_3d <= -threshold:
            value_state = ValueAreaState.FALLING
        else:
            value_state = ValueAreaState.STABLE
        if current.position_context == PositionState.ABOVE_VAH:
            acceptance = AcceptanceState.ABOVE_VAH_ACCEPTED if (poc_state == PocState.RISING and value_state == ValueAreaState.RISING) else AcceptanceState.ABOVE_VAH_UNACCEPTED
        elif current.position_context == PositionState.UNAVAILABLE:
            acceptance = AcceptanceState.UNAVAILABLE
        else:
            acceptance = AcceptanceState.NOT_ABOVE_VAH
        return replace(
            current,
            poc_change_1d_pct=poc_1d,
            poc_change_3d_pct=poc_3d,
            vah_change_1d_pct=vah_1d,
            vah_change_3d_pct=vah_3d,
            val_change_1d_pct=val_1d,
            val_change_3d_pct=val_3d,
            poc_state=poc_state,
            value_area_state=value_state,
            acceptance_context=acceptance,
        )

    @staticmethod
    def _extension_state(result: VolumeProfileResult) -> ExtensionState:
        return VolumeProfileEngine.extension_state_for(
            position_context=result.position_context,
            distance_to_vah_atr=result.distance_to_vah_atr,
            distance_to_vah_pct=result.distance_to_vah_pct,
        )

    @staticmethod
    def extension_state_for(
        *,
        position_context: PositionState,
        distance_to_vah_atr: float | None,
        distance_to_vah_pct: float | None,
    ) -> ExtensionState:
        """Classify upside extension from already-derived VP context values.

        This is intentionally pure so persisted research context can be repaired
        without rebuilding a histogram or reading minute partitions.  Percent
        distances are percent points (for example 5.2 means 5.2%), while ATR
        distances are ATR multiples.
        """
        # Extension describes movement *above* accepted value, not a sell-side
        # location below VAL.  ATR is preferred because it normalises volatility.
        if position_context != PositionState.ABOVE_VAH:
            return ExtensionState.NORMAL
        if distance_to_vah_atr is not None:
            distance = distance_to_vah_atr
            limits = (1.0, 2.0, 3.0)
        elif distance_to_vah_pct is not None:
            distance = distance_to_vah_pct
            limits = (2.0, 5.0, 8.0)
        else:
            return ExtensionState.UNAVAILABLE
        if distance <= limits[0]:
            return ExtensionState.NORMAL
        if distance <= limits[1]:
            return ExtensionState.ELEVATED
        if distance <= limits[2]:
            return ExtensionState.EXTENDED
        return ExtensionState.EXTREME


class VolumeProfileService:
    """Repository adapter for VP20, VP60 and externally supplied Range VP."""

    def __init__(self, repo: KlineRepository, *, engine: VolumeProfileEngine | None = None) -> None:
        self.repo = repo
        self.engine = engine or VolumeProfileEngine()

    def prepare_batch_context(
        self,
        *,
        symbols: Sequence[str],
        as_of: date,
        range_starts: Mapping[str, date | None] | None = None,
        range_confirmed_at: Mapping[str, date | None] | None = None,
        on_minute_partition: Callable[[int, int], None] | None = None,
    ) -> BatchMinuteDataContext:
        """Preload all daily/minute bars required by one candidate run.

        Each minute date partition is read once for the symbols that need it.
        Only dates no later than ``as_of`` enter the context, so holding a
        larger in-memory batch cannot introduce future-bar leakage.
        """
        started = perf_counter()
        unique_symbols = tuple(sorted({str(symbol) for symbol in symbols if symbol}))
        range_starts = range_starts or {}
        range_confirmed_at = range_confirmed_at or {}
        # A range start observed only after as_of is not valid input for a
        # historical RangeVP.  Filter before deriving preload dates as well.
        range_starts = {
            symbol: start
            for symbol, start in range_starts.items()
            if start is not None
            and (confirmed := range_confirmed_at.get(symbol)) is not None
            and confirmed <= as_of
        }
        earliest_range = min(
            (value for value in range_starts.values() if value is not None),
            default=as_of - timedelta(days=400),
        )
        daily_start = min(as_of - timedelta(days=400), earliest_range)
        daily_started = perf_counter()
        batch_daily_reader = getattr(self.repo, "get_daily_batch", None)
        daily_batch = batch_daily_reader(
            list(unique_symbols),
            daily_start,
            as_of,
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
        ) if callable(batch_daily_reader) else pl.DataFrame()
        daily_by_symbol = {
            str(key[0] if isinstance(key, tuple) else key): frame.sort("date")
            for key, frame in daily_batch.partition_by("symbol", as_dict=True, maintain_order=True).items()
        } if not daily_batch.is_empty() and "symbol" in daily_batch.columns else {}
        # Fall back only for a repository implementation without batch daily
        # support.  Production KlineRepository provides get_daily_batch.
        for symbol in unique_symbols:
            if symbol not in daily_by_symbol:
                daily_by_symbol[symbol] = self.repo.get_daily(
                    symbol,
                    daily_start,
                    as_of,
                    columns=["date", "open", "high", "low", "close", "volume", "amount"],
                )

        symbols_by_date: dict[date, set[str]] = defaultdict(set)
        for symbol, daily in daily_by_symbol.items():
            dates = sorted(
                {_row_date(row) for row in _records(daily) if _row_date(row) is not None and _row_date(row) <= as_of}
            )
            # Current VP60 and its D-1/D-3 dynamic predecessors need at most
            # the last 63 actual trading dates.
            for value in dates[-63:]:
                symbols_by_date[value].add(symbol)
            range_start = range_starts.get(symbol)
            if range_start is not None:
                for value in dates:
                    if range_start <= value <= as_of:
                        symbols_by_date[value].add(symbol)

        read_started = perf_counter()
        minute_by_symbol_date: dict[tuple[str, date], pl.DataFrame] = {}
        rows_loaded = 0
        bytes_loaded = 0
        ordered_dates = tuple(sorted(symbols_by_date))
        for index, value in enumerate(ordered_dates, start=1):
            batch_reader = getattr(self.repo, "get_minute_by_dates_and_symbols", None)
            if callable(batch_reader):
                batch = batch_reader([value], sorted(symbols_by_date[value]))
            else:
                batch = self.repo.get_minute_by_dates(sorted(symbols_by_date[value]), [value])
            rows_loaded += batch.height
            bytes_loaded += batch.estimated_size()
            if batch.is_empty() or "symbol" not in batch.columns:
                continue
            for key, frame in batch.partition_by("symbol", as_dict=True, maintain_order=True).items():
                symbol = str(key[0] if isinstance(key, tuple) else key)
                minute_by_symbol_date[(symbol, value)] = frame
            if on_minute_partition is not None:
                on_minute_partition(index, len(ordered_dates))
        ended = perf_counter()
        return BatchMinuteDataContext(
            as_of=as_of,
            daily_by_symbol=daily_by_symbol,
            minute_by_symbol_date=minute_by_symbol_date,
            requested_minute_dates=ordered_dates,
            minute_partition_reads=len(ordered_dates),
            minute_rows_loaded=rows_loaded,
            minute_estimated_bytes=bytes_loaded,
            timings_ms={
                "daily_batch_read_ms": (read_started - daily_started) * 1000.0,
                "minute_partition_read_and_filter_ms": (ended - read_started) * 1000.0,
                "prepare_total_ms": (ended - started) * 1000.0,
            },
        )

    def build_from_context(
        self,
        context: BatchMinuteDataContext,
        symbol: str,
        request: VolumeProfileRequest,
    ) -> VolumeProfileResult:
        """Build one profile exclusively from run-scoped preloaded bars."""
        return VolumeProfileService(context, engine=self.engine).build(symbol, request)

    def build_with_dynamic_context_from_context(
        self,
        context: BatchMinuteDataContext,
        symbol: str,
        request: VolumeProfileRequest,
    ) -> VolumeProfileResult:
        """Dynamic D/D-1/D-3 profile path with no repository disk access."""
        return VolumeProfileService(context, engine=self.engine).build_with_dynamic_context(symbol, request)

    def build_batch(
        self,
        context: BatchMinuteDataContext,
        *,
        symbols: Sequence[str],
        mode: VolumeProfileMode,
        range_starts: Mapping[str, date | None] | None = None,
        range_confirmed_at: Mapping[str, date | None] | None = None,
    ) -> dict[str, dict[str, VolumeProfileResult]]:
        """Compute LITE or FULL VP contexts from one preloaded candidate batch."""
        output: dict[str, dict[str, VolumeProfileResult]] = {}
        range_starts = range_starts or {}
        range_confirmed_at = range_confirmed_at or {}
        for symbol in symbols:
            vp20_request = VolumeProfileRequest(ProfileType.VP20, context.as_of)
            if mode == VolumeProfileMode.LITE:
                output[str(symbol)] = {"vp20": self.build_from_context(context, str(symbol), vp20_request)}
                continue
            row = {
                "vp20": self.build_with_dynamic_context_from_context(context, str(symbol), vp20_request),
                "vp60": self.build_with_dynamic_context_from_context(
                    context, str(symbol), VolumeProfileRequest(ProfileType.VP60, context.as_of)
                ),
            }
            range_start = range_starts.get(str(symbol))
            confirmed_at = range_confirmed_at.get(str(symbol))
            if range_start is not None and confirmed_at is not None and confirmed_at <= context.as_of:
                row["wyckoff_range"] = self.build_with_dynamic_context_from_context(
                    context,
                    str(symbol),
                    VolumeProfileRequest(
                        ProfileType.WYCKOFF_RANGE,
                        context.as_of,
                        range_start=range_start,
                        range_confirmed_at=confirmed_at,
                    ),
                )
            output[str(symbol)] = row
        return output

    def build_vp20(
        self,
        symbol: str,
        as_of: date,
        *,
        allocation_mode: AllocationMode = AllocationMode.MINUTE_RANGE_OVERLAP,
        allow_daily_fallback: bool = True,
    ) -> VolumeProfileResult:
        return self.build(symbol, VolumeProfileRequest(ProfileType.VP20, as_of, allocation_mode=allocation_mode, allow_daily_fallback=allow_daily_fallback))

    def build_vp60(
        self,
        symbol: str,
        as_of: date,
        *,
        allocation_mode: AllocationMode = AllocationMode.MINUTE_RANGE_OVERLAP,
        allow_daily_fallback: bool = True,
    ) -> VolumeProfileResult:
        return self.build(symbol, VolumeProfileRequest(ProfileType.VP60, as_of, allocation_mode=allocation_mode, allow_daily_fallback=allow_daily_fallback))

    def build_wyckoff_range(
        self,
        symbol: str,
        as_of: date,
        *,
        range_start: date | None,
        range_confirmed_at: date | None = None,
        allocation_mode: AllocationMode = AllocationMode.MINUTE_RANGE_OVERLAP,
        allow_daily_fallback: bool = True,
    ) -> VolumeProfileResult:
        return self.build(symbol, VolumeProfileRequest(ProfileType.WYCKOFF_RANGE, as_of, allocation_mode=allocation_mode, range_start=range_start, range_confirmed_at=range_confirmed_at, allow_daily_fallback=allow_daily_fallback))

    def build(self, symbol: str, request: VolumeProfileRequest) -> VolumeProfileResult:
        as_of = _as_date(request.as_of)
        if request.profile_type == ProfileType.WYCKOFF_RANGE and request.range_start is None:
            return _unavailable(request, symbol, reason="wyckoff_range_start_unavailable")
        if request.profile_type == ProfileType.WYCKOFF_RANGE and request.range_confirmed_at is None:
            return _unavailable(request, symbol, reason="wyckoff_range_confirmation_unavailable")
        if request.profile_type == ProfileType.WYCKOFF_RANGE and request.range_confirmed_at > as_of:
            return _unavailable(request, symbol, reason="wyckoff_range_not_as_of_confirmed")
        history_start = request.range_start if request.range_start else as_of - timedelta(days=380)
        daily = self.repo.get_daily(symbol, history_start, as_of, columns=["date", "open", "high", "low", "close", "volume", "amount"])
        daily_rows = [row for row in _records(daily) if _row_date(row) is not None and _row_date(row) <= as_of]
        daily_rows.sort(key=lambda row: _row_date(row) or date.min)
        required_days = 20 if request.profile_type == ProfileType.VP20 else 60 if request.profile_type == ProfileType.VP60 else None
        if request.profile_type in {ProfileType.VP20, ProfileType.VP60}:
            window_rows = daily_rows[-required_days:] if required_days else daily_rows
            if len(window_rows) < (required_days or 0):
                return _unavailable(request, symbol, reason="insufficient_daily_trading_history", required_days=required_days, actual_days=len(window_rows))
        else:
            window_rows = [row for row in daily_rows if _row_date(row) >= request.range_start]
            if not window_rows:
                return _unavailable(request, symbol, reason="no_daily_bars_in_wyckoff_range")
        window_dates = [_row_date(row) for row in window_rows if _row_date(row) is not None]
        atr_14 = self._atr_14(daily_rows)
        if request.allocation_mode == AllocationMode.DAILY_RANGE_OVERLAP:
            return self._daily_result(symbol, request, window_rows, required_days, atr_14, minute_quality=None)

        minute = self.repo.get_minute_by_dates([symbol], window_dates)
        minute_rows = _records(minute)
        minute_quality = self._minute_quality(minute_rows, window_rows)
        if request.allocation_mode == AllocationMode.CLOSE_ONLY:
            if minute_quality.quality in {ProfileQuality.FULL, ProfileQuality.PARTIAL}:
                source_rows, granularity, quality, fallback_used = (
                    minute_rows,
                    DataGranularity.MINUTE_1M,
                    minute_quality.quality,
                    False,
                )
            elif request.allow_daily_fallback:
                source_rows, granularity, quality, fallback_used = (
                    window_rows,
                    DataGranularity.DAILY,
                    ProfileQuality.FALLBACK,
                    True,
                )
            else:
                return _unavailable(
                    request,
                    symbol,
                    reason="minute_coverage_insufficient",
                    required_days=required_days,
                    actual_days=len(window_rows),
                    expected_bars=minute_quality.expected_bars,
                    actual_bars=minute_quality.actual_bars,
                    coverage=minute_quality.coverage_ratio,
                    quality=ProfileQuality.INSUFFICIENT,
                    quality_reasons=minute_quality.reasons,
                )
            return self.engine.build_profile(
                source_rows,
                request,
                symbol=symbol,
                data_granularity=granularity,
                required_trading_days=required_days,
                actual_trading_days=len(window_rows),
                expected_minute_bars=minute_quality.expected_bars,
                actual_minute_bars=minute_quality.actual_bars,
                minute_coverage_ratio=minute_quality.coverage_ratio,
                quality=quality,
                fallback_used=fallback_used,
                quality_reasons=minute_quality.reasons,
                atr_14=atr_14,
            )

        # Range profiles deliberately remain a partial *minute* profile when
        # the formal range predates local minute history.  Falling back would
        # silently change the meaning of an otherwise explicit Range VP.
        if request.profile_type == ProfileType.WYCKOFF_RANGE and minute_quality.actual_bars:
            quality = ProfileQuality.FULL if minute_quality.quality == ProfileQuality.FULL else ProfileQuality.PARTIAL
            return self.engine.build_profile(
                minute_rows,
                request,
                symbol=symbol,
                data_granularity=DataGranularity.MINUTE_1M,
                required_trading_days=required_days,
                actual_trading_days=len(window_rows),
                expected_minute_bars=minute_quality.expected_bars,
                actual_minute_bars=minute_quality.actual_bars,
                minute_coverage_ratio=minute_quality.coverage_ratio,
                quality=quality,
                quality_reasons=minute_quality.reasons,
                atr_14=atr_14,
            )
        if minute_quality.quality in {ProfileQuality.FULL, ProfileQuality.PARTIAL}:
            return self.engine.build_profile(
                minute_rows,
                request,
                symbol=symbol,
                data_granularity=DataGranularity.MINUTE_1M,
                required_trading_days=required_days,
                actual_trading_days=len(window_rows),
                expected_minute_bars=minute_quality.expected_bars,
                actual_minute_bars=minute_quality.actual_bars,
                minute_coverage_ratio=minute_quality.coverage_ratio,
                quality=minute_quality.quality,
                quality_reasons=minute_quality.reasons,
                atr_14=atr_14,
            )
        if request.allow_daily_fallback:
            return self._daily_result(symbol, request, window_rows, required_days, atr_14, minute_quality=minute_quality)
        return _unavailable(
            request,
            symbol,
            reason="minute_coverage_insufficient",
            required_days=required_days,
            actual_days=len(window_rows),
            expected_bars=minute_quality.expected_bars,
            actual_bars=minute_quality.actual_bars,
            coverage=minute_quality.coverage_ratio,
            quality=ProfileQuality.INSUFFICIENT,
            quality_reasons=minute_quality.reasons,
        )

    def build_with_dynamic_context(self, symbol: str, request: VolumeProfileRequest) -> VolumeProfileResult:
        current = self.build(symbol, request)
        if current.quality == ProfileQuality.UNAVAILABLE:
            return current
        history_start = _as_date(request.as_of) - timedelta(days=40)
        daily = self.repo.get_daily(symbol, history_start, _as_date(request.as_of), columns=["date"])
        dates = sorted({_row_date(row) for row in _records(daily) if _row_date(row) is not None and _row_date(row) <= _as_date(request.as_of)})
        if not dates or dates[-1] != _as_date(request.as_of):
            return current
        current_index = len(dates) - 1
        prior_1d = self.build(symbol, replace(request, as_of=dates[current_index - 1])) if current_index >= 1 else None
        prior_3d = self.build(symbol, replace(request, as_of=dates[current_index - 3])) if current_index >= 3 else None
        return self.engine.with_dynamic_context(current, prior_1d, prior_3d)

    def _daily_result(
        self,
        symbol: str,
        request: VolumeProfileRequest,
        rows: Sequence[Mapping[str, Any]],
        required_days: int | None,
        atr_14: float | None,
        *,
        minute_quality: MinuteQuality | None,
    ) -> VolumeProfileResult:
        return self.engine.build_profile(
            rows,
            request,
            symbol=symbol,
            data_granularity=DataGranularity.DAILY,
            required_trading_days=required_days,
            actual_trading_days=len(rows),
            expected_minute_bars=minute_quality.expected_bars if minute_quality else 0,
            actual_minute_bars=minute_quality.actual_bars if minute_quality else 0,
            minute_coverage_ratio=minute_quality.coverage_ratio if minute_quality else None,
            quality=ProfileQuality.FALLBACK,
            fallback_used=True,
            quality_reasons=minute_quality.reasons if minute_quality else ("daily_mode_requested",),
            atr_14=atr_14,
        )

    @staticmethod
    def _minute_quality(minute_rows: Sequence[Mapping[str, Any]], daily_rows: Sequence[Mapping[str, Any]]) -> MinuteQuality:
        active_days = {_row_date(row) for row in daily_rows if (_as_float(row.get("volume")) or 0.0) > 0 and _row_date(row) is not None}
        by_day: dict[date, list[Mapping[str, Any]]] = defaultdict(list)
        for row in minute_rows:
            day = _row_date(row)
            if day is not None:
                by_day[day].append(row)
        reasons: list[str] = []
        valid_by_day: dict[date, list[Mapping[str, Any]]] = {}
        for day, rows in by_day.items():
            timestamps = [_as_datetime(row.get("datetime")) for row in rows]
            valid_timestamps = [stamp for stamp in timestamps if stamp is not None]
            if len(valid_timestamps) != len(set(valid_timestamps)):
                reasons.append(f"duplicate_timestamp:{day.isoformat()}")
            if valid_timestamps != sorted(valid_timestamps):
                reasons.append(f"timestamp_out_of_order:{day.isoformat()}")
            if any(_row_date(row) != day for row in rows):
                reasons.append(f"wrong_trade_date:{day.isoformat()}")
            invalid_ohlcv = 0
            for row in rows:
                low, high, open_price, close, volume = (_as_float(row.get("low")), _as_float(row.get("high")), _as_float(row.get("open")), _as_float(row.get("close")), _as_float(row.get("volume")))
                if low is None or high is None or open_price is None or close is None or volume is None or volume < 0:
                    invalid_ohlcv += 1
                    continue
                tolerance = _ohlcv_price_tolerance(low, high, open_price, close)
                if (
                    low > high + tolerance
                    or open_price < low - tolerance
                    or open_price > high + tolerance
                    or close < low - tolerance
                    or close > high + tolerance
                ):
                    invalid_ohlcv += 1
            if invalid_ohlcv:
                reasons.append(f"invalid_ohlcv:{day.isoformat()}:{invalid_ohlcv}")
            zero_ratio = sum((_as_float(row.get("volume")) or 0.0) == 0 for row in rows) / len(rows) if rows else 0.0
            if zero_ratio >= 0.5:
                reasons.append(f"high_zero_volume_ratio:{day.isoformat()}:{zero_ratio:.3f}")
            gaps = [
                (right - left).total_seconds() / 60.0
                for left, right in pairwise(valid_timestamps)
            ]
            if any(5.0 < gap < 60.0 for gap in gaps):
                reasons.append(f"intraday_gap:{day.isoformat()}")
            valid_by_day[day] = rows
        missing = sorted(active_days - set(by_day))
        reasons.extend(f"missing_active_day:{day.isoformat()}" for day in missing)
        observed = [len({stamp for stamp in (_as_datetime(row.get("datetime")) for row in rows) if stamp is not None}) for day, rows in valid_by_day.items() if day in active_days]
        bars_per_active_day = max(observed, default=0)
        expected = bars_per_active_day * len(active_days)
        actual = sum(observed)
        coverage = actual / expected if expected else None
        if coverage is None or coverage < 0.90:
            quality = ProfileQuality.INSUFFICIENT
        elif coverage < 0.98 or reasons:
            quality = ProfileQuality.PARTIAL
        else:
            quality = ProfileQuality.FULL
        return MinuteQuality(expected, actual, coverage, quality, tuple(reasons))

    @staticmethod
    def _atr_14(rows: Sequence[Mapping[str, Any]]) -> float | None:
        if len(rows) < 15:
            return None
        true_ranges: list[float] = []
        previous_close: float | None = None
        for row in rows:
            high, low, close = _as_float(row.get("high")), _as_float(row.get("low")), _as_float(row.get("close"))
            if high is None or low is None or close is None or high < low:
                continue
            components = [high - low]
            if previous_close is not None:
                components.extend([abs(high - previous_close), abs(low - previous_close)])
            true_ranges.append(max(components))
            previous_close = close
        if len(true_ranges) < 14:
            return None
        atr = sum(true_ranges[-14:]) / 14.0
        return atr if atr > 0 else None


__all__ = [
    "AcceptanceState",
    "AllocationMode",
    "DataGranularity",
    "ExtensionState",
    "PocState",
    "PositionState",
    "PriceBin",
    "ProfileQuality",
    "ProfileType",
    "ProximityState",
    "RangeOverlapAllocator",
    "ValueAreaState",
    "VolumeProfileEngine",
    "VolumeProfileRequest",
    "VolumeProfileResearchContext",
    "VolumeProfileResult",
    "VolumeProfileService",
]
