from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import polars as pl
import pytest

from app.services.volume_profile import (
    AcceptanceState,
    AllocationMode,
    DataGranularity,
    ExtensionState,
    PositionState,
    ProfileQuality,
    ProfileType,
    RangeOverlapAllocator,
    VolumeProfileEngine,
    VolumeProfileMode,
    VolumeProfileRequest,
    VolumeProfileService,
)
from app.tickflow.repository import DataStore, KlineRepository


def _bar(day: date, low: float, high: float, close: float, volume: float, minute: int | None = None) -> dict:
    row = {"date": day, "open": low, "high": high, "low": low, "close": close, "volume": volume, "amount": volume * close}
    if minute is not None:
        row["datetime"] = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=30 + minute)
    return row


def _daily_rows(count: int = 65, *, start: date = date(2025, 1, 2)) -> list[dict]:
    return [_bar(start + timedelta(days=index), 10 + index * 0.1, 10.2 + index * 0.1, 10.1 + index * 0.1, 1000) for index in range(count)]


def _minute_rows(daily_rows: list[dict], *, drop_days: set[date] | None = None) -> list[dict]:
    dropped = drop_days or set()
    rows: list[dict] = []
    for daily in daily_rows:
        if daily["date"] in dropped:
            continue
        rows.extend(
            [
                _bar(daily["date"], daily["low"], daily["close"], daily["low"] + 0.03, 400, 0),
                _bar(daily["date"], daily["close"], daily["high"], daily["close"], 600, 1),
            ]
        )
    return rows


class _Repo:
    def __init__(self, daily: list[dict], minute: list[dict]) -> None:
        self.daily = daily
        self.minute = minute

    def get_daily(self, _symbol: str, start: date, end: date, columns=None):
        return pl.DataFrame([row for row in self.daily if start <= row["date"] <= end])

    def get_minute_by_dates(self, _symbols: list[str], dates: list[date], asset_type="stock"):
        wanted = set(dates)
        return pl.DataFrame([row for row in self.minute if row["date"] in wanted])


class _BatchRepo(_Repo):
    def get_daily_batch(self, symbols: list[str], start: date, end: date, columns=None):
        rows = [row | {"symbol": symbol} for symbol in symbols for row in self.daily if start <= row["date"] <= end]
        return pl.DataFrame(rows)

    def get_minute_by_dates_and_symbols(self, dates: list[date], symbols: list[str], asset_type="stock"):
        wanted = set(dates)
        rows = [row | {"symbol": symbol} for symbol in symbols for row in self.minute if row["date"] in wanted]
        return pl.DataFrame(rows)


def _request(as_of: date, *, profile_type: ProfileType = ProfileType.VP20, mode: AllocationMode = AllocationMode.MINUTE_RANGE_OVERLAP) -> VolumeProfileRequest:
    return VolumeProfileRequest(profile_type, as_of, bin_count=10, allocation_mode=mode)


def test_range_overlap_conserves_minute_and_daily_volume() -> None:
    bars = [_bar(date(2025, 1, 2), 10, 12, 11, 1200, 0), _bar(date(2025, 1, 2), 11, 13, 12, 800, 1)]
    for close_only in (False, True):
        volumes, _ = RangeOverlapAllocator.allocate(bars, profile_low=10, profile_high=13, bin_count=6, close_only=close_only)
        assert sum(volumes) == pytest.approx(2000)


def test_close_only_baseline_places_full_bar_at_close_bin() -> None:
    bars = [_bar(date(2025, 1, 2), 10, 12, 11.9, 1000)]
    result = VolumeProfileEngine().build_profile(
        bars, _request(date(2025, 1, 2), mode=AllocationMode.CLOSE_ONLY), symbol="000001.SZ", data_granularity=DataGranularity.DAILY, required_trading_days=None, actual_trading_days=1
    )
    assert sum(item.volume > 0 for item in result.bins) == 1
    assert result.poc == pytest.approx(11.9, abs=0.21)


def test_poc_tie_uses_profile_midpoint_then_lower_bin() -> None:
    bars = [_bar(date(2025, 1, 2), 0, 0, 0, 10), _bar(date(2025, 1, 2), 2, 2, 2, 10)]
    result = VolumeProfileEngine().build_profile(
        bars, _request(date(2025, 1, 2)), symbol="000001.SZ", data_granularity=DataGranularity.DAILY, required_trading_days=None, actual_trading_days=1
    )
    assert result.poc_bin_index == 0


def test_value_area_expands_larger_adjacent_side_and_ties_high() -> None:
    low, high, volume = VolumeProfileEngine._value_area([10, 30, 20, 40, 10], 2, 0.70)
    assert (low, high, volume) == (1, 3, 90)


def test_high_equal_low_and_zero_volume_are_handled() -> None:
    bars = [_bar(date(2025, 1, 2), 10, 10, 10, 100), _bar(date(2025, 1, 2), 10, 10, 10, 0)]
    result = VolumeProfileEngine().build_profile(
        bars, _request(date(2025, 1, 2)), symbol="000001.SZ", data_granularity=DataGranularity.DAILY, required_trading_days=None, actual_trading_days=1
    )
    assert result.bin_count == 1
    assert result.poc == 10
    assert result.poc_volume == 100


def test_bin_boundary_high_is_included_and_empty_data_is_unavailable() -> None:
    volumes, _ = RangeOverlapAllocator.allocate([_bar(date(2025, 1, 2), 10, 12, 12, 100)], profile_low=10, profile_high=12, bin_count=2, close_only=False)
    assert sum(volumes) == pytest.approx(100)
    empty = VolumeProfileEngine().build_profile([], _request(date(2025, 1, 2)), symbol="000001.SZ", data_granularity=DataGranularity.MINUTE_1M, required_trading_days=20, actual_trading_days=0)
    assert empty.quality == ProfileQuality.UNAVAILABLE


def test_vp20_and_vp60_do_not_claim_short_history_is_complete() -> None:
    daily = _daily_rows(19)
    service = VolumeProfileService(_Repo(daily, _minute_rows(daily)))
    vp20 = service.build_vp20("000001.SZ", daily[-1]["date"])
    vp60 = service.build_vp60("000001.SZ", daily[-1]["date"])
    assert vp20.unavailable_reason == "insufficient_daily_trading_history"
    assert vp60.unavailable_reason == "insufficient_daily_trading_history"


def test_incomplete_minute_coverage_uses_explicit_daily_fallback() -> None:
    daily = _daily_rows(25)
    minute = _minute_rows(daily, drop_days={daily[-1]["date"], daily[-2]["date"], daily[-3]["date"]})
    result = VolumeProfileService(_Repo(daily, minute)).build_vp20("000001.SZ", daily[-1]["date"])
    assert result.data_granularity == DataGranularity.DAILY
    assert result.quality == ProfileQuality.FALLBACK
    assert result.fallback_used is True
    assert result.minute_coverage_ratio is not None and result.minute_coverage_ratio < 0.9
    close_only = VolumeProfileService(_Repo(daily, minute)).build(
        "000001.SZ",
        _request(daily[-1]["date"], mode=AllocationMode.CLOSE_ONLY),
    )
    assert close_only.data_granularity == DataGranularity.DAILY
    assert close_only.quality == ProfileQuality.FALLBACK


def test_minute_quality_tolerates_only_machine_precision_at_ohlc_boundaries() -> None:
    daily = _daily_rows(20)
    precision_only = [dict(row) for row in _minute_rows(daily)]
    precision_only[0]["open"] = float(precision_only[0]["low"]) - 1e-14
    precision_only[1]["close"] = float(precision_only[1]["high"]) + 1e-14

    tolerated = VolumeProfileService(_Repo(daily, precision_only)).build_vp20("000001.SZ", daily[-1]["date"])

    assert tolerated.quality == ProfileQuality.FULL
    assert tolerated.data_granularity == DataGranularity.MINUTE_1M
    assert not any(reason.startswith("invalid_ohlcv:") for reason in tolerated.quality_reasons)

    truly_invalid = [dict(row) for row in _minute_rows(daily)]
    truly_invalid[0]["open"] = float(truly_invalid[0]["low"]) - 0.001

    rejected = VolumeProfileService(_Repo(daily, truly_invalid)).build_vp20("000001.SZ", daily[-1]["date"])

    assert rejected.quality == ProfileQuality.PARTIAL
    assert any(reason.startswith("invalid_ohlcv:") for reason in rejected.quality_reasons)


def test_missing_wyckoff_range_start_is_fail_closed() -> None:
    daily = _daily_rows(65)
    result = VolumeProfileService(_Repo(daily, _minute_rows(daily))).build_wyckoff_range("000001.SZ", daily[-1]["date"], range_start=None)
    assert result.quality == ProfileQuality.UNAVAILABLE
    assert result.unavailable_reason == "wyckoff_range_start_unavailable"


def test_wyckoff_range_before_minute_history_remains_partial_minute_profile() -> None:
    daily = _daily_rows(10)
    minute = _minute_rows(daily[5:])
    result = VolumeProfileService(_Repo(daily, minute)).build_wyckoff_range(
        "000001.SZ",
        daily[-1]["date"],
        range_start=daily[0]["date"],
        range_confirmed_at=daily[-1]["date"],
    )
    assert result.data_granularity == DataGranularity.MINUTE_1M
    assert result.quality == ProfileQuality.PARTIAL
    assert result.fallback_used is False
    assert result.requested_start == daily[0]["date"]
    assert result.data_start == daily[5]["date"]


def test_wyckoff_range_confirmation_is_service_level_fail_closed() -> None:
    daily = _daily_rows(65)
    service = VolumeProfileService(_Repo(daily, _minute_rows(daily)))
    as_of = daily[-1]["date"]
    missing = service.build_wyckoff_range("000001.SZ", as_of, range_start=daily[-20]["date"])
    future = service.build_wyckoff_range(
        "000001.SZ",
        as_of,
        range_start=daily[-20]["date"],
        range_confirmed_at=as_of + timedelta(days=1),
    )
    assert missing.unavailable_reason == "wyckoff_range_confirmation_unavailable"
    assert future.unavailable_reason == "wyckoff_range_not_as_of_confirmed"


def test_future_bars_are_isolated_and_prefix_consistent() -> None:
    today = date(2025, 1, 2)
    future = today + timedelta(days=1)
    request = _request(today)
    engine = VolumeProfileEngine()
    prefix = [_bar(today, 10, 11, 10.5, 100)]
    with_future = [*prefix, _bar(future, 20, 21, 20.5, 10000)]
    common = dict(symbol="000001.SZ", data_granularity=DataGranularity.DAILY, required_trading_days=None, actual_trading_days=1)
    first = engine.build_profile(prefix, request, **common)
    second = engine.build_profile(with_future, request, **common)
    assert [(item.low, item.high, item.volume) for item in second.bins] == [(item.low, item.high, item.volume) for item in first.bins]
    assert (second.poc, second.vah, second.val, second.position_context) == (first.poc, first.vah, first.val, first.position_context)


def test_intraday_as_of_excludes_later_same_day_bar() -> None:
    day = date(2025, 1, 2)
    request = VolumeProfileRequest(ProfileType.VP20, datetime(2025, 1, 2, 9, 30), bin_count=10)
    bars = [_bar(day, 10, 11, 10.5, 100, 0), _bar(day, 20, 21, 20.5, 10000, 1)]
    result = VolumeProfileEngine().build_profile(
        bars,
        request,
        symbol="000001.SZ",
        data_granularity=DataGranularity.MINUTE_1M,
        required_trading_days=None,
        actual_trading_days=1,
    )
    assert result.profile_high == 11


def test_minute_daily_and_close_only_modes_all_produce_explicit_results() -> None:
    daily = _daily_rows(65)
    service = VolumeProfileService(_Repo(daily, _minute_rows(daily)))
    as_of = daily[-1]["date"]
    minute = service.build_vp20("000001.SZ", as_of)
    daily_result = service.build("000001.SZ", _request(as_of, mode=AllocationMode.DAILY_RANGE_OVERLAP))
    close_only = service.build("000001.SZ", _request(as_of, mode=AllocationMode.CLOSE_ONLY))
    assert minute.data_granularity == DataGranularity.MINUTE_1M
    assert daily_result.data_granularity == DataGranularity.DAILY
    assert close_only.allocation_mode == AllocationMode.CLOSE_ONLY
    assert minute.poc is not None and daily_result.poc is not None and close_only.poc is not None


def test_dynamic_context_identifies_above_vah_acceptance_only_when_value_migrates() -> None:
    engine = VolumeProfileEngine()
    common = dict(symbol="000001.SZ", data_granularity=DataGranularity.DAILY, required_trading_days=None, actual_trading_days=1)
    prior = engine.build_profile([_bar(date(2025, 1, 2), 10, 11, 10.5, 100)], _request(date(2025, 1, 2)), **common)
    current = engine.build_profile(
        [
            _bar(date(2025, 1, 5), 11, 11.1, 11.05, 1000, 0),
            _bar(date(2025, 1, 5), 12, 12.2, 12.1, 10, 1),
        ],
        _request(date(2025, 1, 5)),
        **common,
    )
    contextual = engine.with_dynamic_context(current, prior, prior)
    assert contextual.acceptance_context == AcceptanceState.ABOVE_VAH_ACCEPTED


@pytest.mark.parametrize(
    ("distance_to_vah_atr", "expected"),
    [
        (1.5, ExtensionState.ELEVATED),
        (2.5, ExtensionState.EXTENDED),
        (3.1, ExtensionState.EXTREME),
    ],
)
def test_extension_is_derived_after_above_vah_position_is_set(distance_to_vah_atr: float, expected: ExtensionState) -> None:
    engine = VolumeProfileEngine()
    base = engine.build_profile(
        [_bar(date(2025, 1, 2), 8, 10, 9, 100)],
        _request(date(2025, 1, 2)),
        symbol="000001.SZ",
        data_granularity=DataGranularity.DAILY,
        required_trading_days=None,
        actual_trading_days=1,
    )
    contextual = engine.with_context(
        replace(
            base,
            current_price=13,
            poc=9,
            vah=10,
            val=8,
            distance_to_vah_atr=distance_to_vah_atr,
        )
    )
    assert contextual.position_context == PositionState.ABOVE_VAH
    assert contextual.extension_context == expected


@pytest.mark.parametrize("current_price", [9, 7])
def test_non_above_vah_positions_are_not_upside_extension(current_price: float) -> None:
    engine = VolumeProfileEngine()
    base = engine.build_profile(
        [_bar(date(2025, 1, 2), 8, 10, 9, 100)],
        _request(date(2025, 1, 2)),
        symbol="000001.SZ",
        data_granularity=DataGranularity.DAILY,
        required_trading_days=None,
        actual_trading_days=1,
    )
    contextual = engine.with_context(
        replace(base, current_price=current_price, poc=9, vah=10, val=8, distance_to_vah_atr=4.0)
    )
    assert contextual.position_context in {PositionState.WITHIN_VALUE, PositionState.BELOW_VAL}
    assert contextual.extension_context == ExtensionState.NORMAL


def test_extension_pct_fallback_uses_percent_points_not_fractional_units() -> None:
    assert (
        VolumeProfileEngine.extension_state_for(
            position_context=PositionState.ABOVE_VAH,
            distance_to_vah_atr=None,
            distance_to_vah_pct=5.2,
        )
        == ExtensionState.EXTENDED
    )


def test_exact_minute_date_read_uses_platform_safe_partition_path(tmp_path) -> None:
    target = tmp_path / "kline_minute" / "date=2025-01-02"
    target.mkdir(parents=True)
    pl.DataFrame([_bar(date(2025, 1, 2), 10, 10.1, 10.05, 100, 0) | {"symbol": "000001.SZ"}]).write_parquet(target / "part.parquet")
    repo = KlineRepository(DataStore(tmp_path))
    result = repo.get_minute_by_dates(["000001.SZ"], [date(2025, 1, 2)])
    assert result.height == 1
    assert result.item(0, "symbol") == "000001.SZ"
    batch = repo.get_minute_by_dates_and_symbols([date(2025, 1, 2)], ["000001.SZ"])
    assert batch.equals(result)


def test_preloaded_batch_context_matches_single_symbol_and_stays_as_of_safe() -> None:
    daily = _daily_rows(65)
    service = VolumeProfileService(_BatchRepo(daily, _minute_rows(daily)))
    as_of = daily[-1]["date"]
    request = _request(as_of)
    single = service.build_with_dynamic_context("000001.SZ", request)
    context = service.prepare_batch_context(symbols=["000001.SZ"], as_of=as_of)
    batched = service.build_with_dynamic_context_from_context(context, "000001.SZ", request)
    assert (batched.poc, batched.vah, batched.val) == pytest.approx((single.poc, single.vah, single.val))
    assert batched.bins == single.bins
    assert batched.position_context == single.position_context
    assert batched.acceptance_context == single.acceptance_context
    assert all(value <= as_of for value in context.requested_minute_dates)


def test_batch_preload_excludes_range_not_confirmed_as_of() -> None:
    daily = _daily_rows(65)
    service = VolumeProfileService(_BatchRepo(daily, _minute_rows(daily)))
    as_of = daily[-1]["date"]
    baseline = service.prepare_batch_context(symbols=["000001.SZ"], as_of=as_of)
    future_confirmed = service.prepare_batch_context(
        symbols=["000001.SZ"],
        as_of=as_of,
        range_starts={"000001.SZ": daily[0]["date"]},
        range_confirmed_at={"000001.SZ": as_of + timedelta(days=1)},
    )
    assert future_confirmed.requested_minute_dates == baseline.requested_minute_dates


def test_vp_lite_and_full_reuse_preloaded_context_without_changing_profiles() -> None:
    daily = _daily_rows(65)
    service = VolumeProfileService(_BatchRepo(daily, _minute_rows(daily)))
    as_of = daily[-1]["date"]
    context = service.prepare_batch_context(
        symbols=["000001.SZ"],
        as_of=as_of,
        range_starts={"000001.SZ": daily[-20]["date"]},
        range_confirmed_at={"000001.SZ": as_of},
    )
    lite = service.build_batch(context, symbols=["000001.SZ"], mode=VolumeProfileMode.LITE)
    full = service.build_batch(
        context,
        symbols=["000001.SZ"],
        mode=VolumeProfileMode.FULL,
        range_starts={"000001.SZ": daily[-20]["date"]},
        range_confirmed_at={"000001.SZ": as_of},
    )
    assert set(lite["000001.SZ"]) == {"vp20"}
    assert {"vp20", "vp60", "wyckoff_range"}.issubset(full["000001.SZ"])
    assert lite["000001.SZ"]["vp20"].poc == pytest.approx(full["000001.SZ"]["vp20"].poc)
