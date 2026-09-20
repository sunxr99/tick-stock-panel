# ruff: noqa: RUF002
"""CZSC 扩展契约：字段口径、确认时刻与原生多周期聚合。"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import polars as pl
import pytest

from app.custom.chanlun import (
    _analyze_minute_multi,
    _analyze_native_minute_multi,
    _analyze_resonance,
    _drop_unclosed_bars,
    _fetch_daily_frame,
    _fetch_native_minute_frames,
    _find_daily_buy_sell_points,
    _higher_context,
    _serialize_daily,
    _signal_config,
    _validate_and_standardize,
    filter_daily_czsc_buy_points,
    find_latest_daily_buy_points,
)


class _FakeRepo:
    def __init__(self, frame: pl.DataFrame) -> None:
        self.frame = frame

    def resolve_asset_type(self, symbol: str) -> str:
        del symbol
        return "stock"

    def get_daily_asset(self, asset_type, symbol, start, end, columns=None):
        del asset_type, symbol, start, end, columns
        return self.frame


def _daily_frame() -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": ["000001.SZ"] * 3,
        "date": [date(2026, 1, 7), date(2026, 1, 5), date(2026, 1, 6)],
        "open": [12.0, 10.0, 11.0], "high": [13.0, 11.0, 12.0],
        "low": [11.5, 9.5, 10.5], "close": [12.8, 10.8, 11.8],
        "volume": [3000.0, 1000.0, 2000.0], "amount": [3e6, 1e6, 2e6],
    })


def test_daily_adapter_sorts_and_maps_rawbar_contract() -> None:
    out, asset_type = _fetch_daily_frame(_FakeRepo(_daily_frame()), "000001.SZ", days=30)
    assert asset_type == "stock"
    assert list(out.columns) == ["dt", "symbol", "open", "close", "high", "low", "vol", "amount"]
    assert out["dt"].tolist() == [pd.Timestamp(2026, 1, 5), pd.Timestamp(2026, 1, 6), pd.Timestamp(2026, 1, 7)]
    assert out["vol"].tolist() == [1000.0, 2000.0, 3000.0]


def test_daily_adapter_limits_analysis_to_requested_trading_bars() -> None:
    frame = pl.concat([
        _daily_frame(),
        pl.DataFrame({
            "symbol": ["000001.SZ", "000001.SZ"],
            "date": [date(2026, 1, 8), date(2026, 1, 9)],
            "open": [13.0, 14.0], "high": [14.0, 15.0],
            "low": [12.0, 13.0], "close": [13.8, 14.8],
            "volume": [4000.0, 5000.0], "amount": [4e6, 5e6],
        }),
    ])
    out, _ = _fetch_daily_frame(_FakeRepo(frame), "000001.SZ", days=2)

    assert out["dt"].tolist() == [pd.Timestamp(2026, 1, 8), pd.Timestamp(2026, 1, 9)]


def test_unclosed_daily_and_minute_bars_are_excluded(monkeypatch) -> None:
    import app.custom.chanlun as chanlun

    monkeypatch.setattr(chanlun, "cn_now", lambda: datetime(2026, 1, 6, 14, 25))
    daily = pl.DataFrame({"date": [date(2026, 1, 5), date(2026, 1, 6)]})
    minutes = pl.DataFrame({
        "datetime": [
            datetime(2026, 1, 5, 15),
            datetime(2026, 1, 6, 14, 15),
            datetime(2026, 1, 6, 14, 30),
            datetime(2026, 1, 6, 14, 25),
        ],
    })

    assert _drop_unclosed_bars(daily, timestamp_col="date")["date"].to_list() == [date(2026, 1, 5)]
    assert _drop_unclosed_bars(minutes, timestamp_col="datetime", freq="15m")["datetime"].to_list() == [
        datetime(2026, 1, 5, 15),
        datetime(2026, 1, 6, 14, 15),
    ]
    assert _drop_unclosed_bars(minutes, timestamp_col="datetime", freq="1m")["datetime"].to_list() == [
        datetime(2026, 1, 5, 15),
        datetime(2026, 1, 6, 14, 15),
    ]


def test_adapter_rejects_missing_amount_duplicate_and_invalid_ohlc() -> None:
    with pytest.raises(ValueError, match="amount"):
        _validate_and_standardize(_daily_frame().drop("amount"), "000001.SZ", timestamp_col="date")
    duplicate = _daily_frame().with_columns(pl.lit(date(2026, 1, 5)).alias("date"))
    with pytest.raises(ValueError, match="重复"):
        _validate_and_standardize(duplicate, "000001.SZ", timestamp_col="date")
    bad = _daily_frame().with_columns(pl.lit(9.0).alias("high"))
    with pytest.raises(ValueError, match="OHLC"):
        _validate_and_standardize(bad, "000001.SZ", timestamp_col="date")


def test_adapter_normalizes_only_floating_point_ohlc_noise() -> None:
    noisy = pl.DataFrame({
        "date": [date(2026, 1, 5)], "open": [10.0], "high": [9.999999999999998],
        "low": [9.000000000000002], "close": [9.0], "volume": [1.0], "amount": [1.0],
    })
    out = _validate_and_standardize(noisy, "000001.SZ", timestamp_col="date")
    assert out.loc[0, "high"] == 10.0
    assert out.loc[0, "low"] == 9.0


def test_adapter_normalizes_only_tiny_negative_volume_amount_noise() -> None:
    noisy = pl.DataFrame({
        "date": [date(2026, 1, 5), date(2026, 1, 6)],
        "open": [10.0, 10.0], "high": [10.0, 10.0], "low": [10.0, 10.0], "close": [10.0, 10.0],
        "volume": [-1e-10, 0.0], "amount": [0.0, -3.7253e-9],
    })
    out = _validate_and_standardize(noisy, "000628.SZ", timestamp_col="date")
    assert out["vol"].tolist() == [0.0, 0.0]
    assert out["amount"].tolist() == [0.0, 0.0]

    bad = noisy.with_columns(pl.lit(-0.001).alias("amount"))
    with pytest.raises(ValueError, match="volume/amount"):
        _validate_and_standardize(bad, "000628.SZ", timestamp_col="date")


def test_daily_structure_has_event_and_confirmation_time() -> None:
    import czsc

    frame = czsc.mock.generate_symbol_kines("000001", "日线", "20240101", "20241201", seed=42)
    bars = czsc.format_standard_kline(frame, freq=czsc.Freq.D)
    data = _serialize_daily(czsc, bars)
    assert len(data["bars"]) == len(bars)
    for bi in data["bi"]:
        assert bi["status"] == "confirmed"
        assert bi["event_time"] == bi["edt"]
        assert bi["confirmation_time"] is not None
        assert bi["confirmation_time"] >= bi["event_time"]
    for point in data["buy_sell"]:
        assert point["type"] in {"一买", "一卖", "二买", "二卖", "三买", "三卖"}
        assert point["dt"] == point["confirmation_time"]
    assert data["state"]["native_state"]["signal_name"] == "cxt_bi_base_V230228"
    assert data["state"]["direction"] in {"BULLISH", "BEARISH", "UNKNOWN"}


def test_daily_marker_and_screener_do_not_duplicate_a_reappearing_structure_event(monkeypatch) -> None:
    import czsc

    import app.custom.chanlun as chanlun

    bars = [
        SimpleNamespace(dt=datetime(2026, 1, day), close=10.0)
        for day in range(1, 15)
    ]
    fake_czsc = SimpleNamespace(CZSC=lambda snapshot: SimpleNamespace(index=len(snapshot)))
    monkeypatch.setattr(
        czsc._native.signals,
        "call_signal",
        lambda name, analyzer, _params: (
            [SimpleNamespace(key="日线_TEST", value="一买_5笔_任意_0", v1="一买")]
            if name == "cxt_first_buy_V221126" and analyzer.index in {12, 14}
            else []
        ),
    )
    monkeypatch.setattr(
        chanlun,
        "_make_signal_point",
        lambda _c, **kwargs: {"dt": kwargs["confirmation_time"], "occurrence": "same-anchor"},
    )
    monkeypatch.setattr(chanlun, "_signal_occurrence_key", lambda point: (point["occurrence"],))

    points = _find_daily_buy_sell_points(fake_czsc, bars)

    assert [point["dt"] for point in points] == ["2026-01-12"]
    assert find_latest_daily_buy_points(fake_czsc, bars) == []


def test_daily_buy_screener_only_returns_a_new_final_bar_signal(monkeypatch) -> None:
    import czsc

    import app.custom.chanlun as chanlun

    source = czsc.mock.generate_symbol_kines("000001", "日线", "20240101", "20241201", seed=42)
    bars = czsc.format_standard_kline(source, freq=czsc.Freq.D)
    monkeypatch.setattr(
        chanlun,
        "_bi_anchor",
        lambda _c: {"sdt": "2024-01-01", "edt": "2024-01-02", "direction": "向下"},
    )

    def _patch_new_final_signal() -> None:
        calls = {"count": 0}

        def _new_final_signal(_name, _analyzer, _params):
            calls["count"] += 1
            # The helper evaluates all four signal definitions for current first,
            # then evaluates the previous closed-bar snapshot.
            return [SimpleNamespace(key="日线_TEST", value="一买_任意_任意_0", v1="一买")] if calls["count"] <= 4 else []

        monkeypatch.setattr(czsc._native.signals, "call_signal", _new_final_signal)

    _patch_new_final_signal()
    points = find_latest_daily_buy_points(czsc, bars)
    assert points
    assert {point["type"] for point in points} == {"一买"}
    assert {point["confirmation_time"] for point in points} == {bars[-1].dt.strftime("%Y-%m-%d")}

    history = pl.from_pandas(source).rename({"dt": "date", "vol": "volume"})
    _patch_new_final_signal()
    selected = filter_daily_czsc_buy_points(history)
    assert selected.height == 1
    assert selected["czsc_buy_types"].to_list() == [["一买"]]
    assert selected["czsc_confirmation_time"].to_list() == [bars[-1].dt.strftime("%Y-%m-%d")]
    assert selected["czsc_event_identity_version"].to_list() == [2]


def test_daily_buy_screener_does_not_repeat_an_existing_signal(monkeypatch) -> None:
    import czsc

    import app.custom.chanlun as chanlun

    source = czsc.mock.generate_symbol_kines("000001", "日线", "20240101", "20241201", seed=42)
    bars = czsc.format_standard_kline(source, freq=czsc.Freq.D)
    monkeypatch.setattr(
        chanlun,
        "_bi_anchor",
        lambda _c: {"sdt": "2024-01-01", "edt": "2024-01-02", "direction": "向下"},
    )
    monkeypatch.setattr(
        czsc._native.signals,
        "call_signal",
        lambda _name, _analyzer, _params: [SimpleNamespace(key="日线_TEST", value="一买_任意_任意_0", v1="一买")],
    )

    assert find_latest_daily_buy_points(czsc, bars) == []


def test_daily_buy_screener_excludes_a_still_open_daily_bar(monkeypatch) -> None:
    import app.custom.chanlun as chanlun

    history = pl.DataFrame({
        "symbol": ["000001.SZ"] * 12,
        "date": [date(2026, 1, index) for index in range(1, 13)],
        "open": [10.0 + index for index in range(12)],
        "high": [11.0 + index for index in range(12)],
        "low": [9.5 + index for index in range(12)],
        "close": [10.5 + index for index in range(12)],
        "volume": [1_000.0] * 12,
        "amount": [10_000.0] * 12,
    })
    monkeypatch.setattr(chanlun, "cn_now", lambda: datetime(2026, 1, 12, 14, 25))
    monkeypatch.setattr(chanlun, "cn_today", lambda: date(2026, 1, 12))
    monkeypatch.setattr(
        chanlun,
        "find_latest_daily_buy_points",
        lambda _czsc, bars: [{"type": "一买", "signal": {"raw_signal": "test"}, "confirmation_time": bars[-1].dt.strftime("%Y-%m-%d")}],
    )

    selected = filter_daily_czsc_buy_points(history)

    assert selected["date"].to_list() == [date(2026, 1, 11)]
    assert selected["czsc_confirmation_time"].to_list() == ["2026-01-11"]


def test_multitimeframe_uses_native_czscsignals_and_bar_generator() -> None:
    import czsc

    config = _signal_config()
    assert {item["freq"] for item in config} == {"15分钟", "30分钟", "60分钟", "日线"}
    assert {
        "cxt_first_buy_V221126", "cxt_first_sell_V221126",
        "cxt_second_bs_V240524", "cxt_third_bs_V230319", "cxt_bi_base_V230228",
        "cxt_bi_status_V230101", "tas_ma_base_V221101", "tas_macd_base_V221028", "bar_vol_grow_V221112",
    } <= {item["name"] for item in config}
    minute = czsc.mock.generate_symbol_kines("000001", "1分钟", "20240101", "20240110")
    result = _analyze_minute_multi(czsc, minute)
    assert result.base_frequency == "1分钟"
    assert {"15分钟", "30分钟", "60分钟", "日线"} <= set(result.timeframes)
    assert all(item["source"] == "minute_bar_generator" for item in result.summary)
    assert all(result.timeframes[freq]["bars"] for freq in ("15分钟", "30分钟", "60分钟"))
    for point in result.timeframes["15分钟"]["buy_sell"]:
        assert point["signal"]["raw_signal"].endswith(point["signal"]["raw_value"])
        assert point["signal"]["signal_name"].startswith("cxt_")
        assert point["structure_anchor"] is None or point["event_time"] == point["structure_anchor"]["edt"]
        assert point["higher_timeframe_context"]["summary"] in {"顺高周期结构", "逆高周期结构", "高周期冲突", "上下文不明确"}
    occurrences = [(point["signal"]["signal_name"], point["signal"]["raw_value"], (point["structure_anchor"] or {}).get("edt")) for point in result.timeframes["15分钟"]["buy_sell"]]
    assert len(occurrences) == len(set(occurrences))
    assert result.timeframes["15分钟"]["state"]["native_state"]["signal_name"] == "cxt_bi_base_V230228"
    assert {item["id"] for item in result.timeframes["15分钟"]["state"]["quality"]} == {
        "bi_status", "sma20", "macd", "volume",
    }


def test_f1_minute_context_uses_long_daily_history(monkeypatch) -> None:
    import czsc

    import app.custom.chanlun as chanlun

    minute = czsc.mock.generate_symbol_kines("000001", "1分钟", "20240101", "20240110", seed=42)
    daily = czsc.mock.generate_symbol_kines("000001", "日线", "20230101", "20240110", seed=42)
    daily_bars = czsc.format_standard_kline(daily, freq=czsc.Freq.D)
    observed_states: list[dict[str, str]] = []
    original = chanlun._parse_signal_points

    def capture_daily_context(*args, **kwargs):
        observed_states.append(dict(args[1]))
        return original(*args, **kwargs)

    monkeypatch.setattr(chanlun, "_parse_signal_points", capture_daily_context)

    _analyze_minute_multi(czsc, minute, daily_bars=daily_bars)

    assert observed_states
    assert all("日线_D0BL9_V230228" in state for state in observed_states)


def test_native_minute_periods_are_analyzed_independently() -> None:
    import czsc

    frames = {
        freq: czsc.mock.generate_symbol_kines("000001", freq, "20240101", "20240120", seed=42)
        for freq in ("15分钟", "30分钟")
    }
    # upstream mock 不提供 60 分钟生成器
    frames["60分钟"] = frames["30分钟"].iloc[::2].reset_index(drop=True)
    result = _analyze_native_minute_multi(czsc, frames)

    assert result.base_frequency == "TickFlow原生15/30/60分钟"
    assert set(result.timeframes) == {"15分钟", "30分钟", "60分钟"}
    assert all(item["source"] == "tickflow_native" for item in result.summary)
    assert all(result.timeframes[freq]["bars"] for freq in result.timeframes)


def test_native_minute_context_includes_previously_closed_daily_state(monkeypatch) -> None:
    import czsc

    import app.custom.chanlun as chanlun

    frames = {
        freq: czsc.mock.generate_symbol_kines("000001", freq, "20240101", "20240120", seed=42)
        for freq in ("15分钟", "30分钟")
    }
    frames["60分钟"] = frames["30分钟"].iloc[::2].reset_index(drop=True)
    daily = czsc.mock.generate_symbol_kines("000001", "日线", "20231201", "20240120", seed=42)
    daily_bars = czsc.format_standard_kline(daily, freq=czsc.Freq.D)
    observed_states: list[dict[str, str]] = []
    original = chanlun._parse_signal_points

    def capture_daily_context(*args, **kwargs):
        observed_states.append(dict(args[1]))
        return original(*args, **kwargs)

    monkeypatch.setattr(chanlun, "_parse_signal_points", capture_daily_context)

    _analyze_native_minute_multi(czsc, frames, daily_bars=daily_bars)

    assert observed_states
    assert all("日线_D0BL9_V230228" in state for state in observed_states)


def test_native_minute_reader_requires_all_three_provider_periods() -> None:
    class _NativeRepo:
        def get_czsc_minute_range(self, symbol, start, end, freq):
            del symbol, start, end
            if freq == "30m":
                return pl.DataFrame()
            return pl.DataFrame({
                "datetime": [pd.Timestamp("2026-01-05 09:45")],
                "open": [10.0], "high": [10.1], "low": [9.9], "close": [10.0],
                "volume": [1.0], "amount": [10.0],
            })

    assert _fetch_native_minute_frames(
        _NativeRepo(), "000001.SZ", "stock", start=date(2026, 1, 5), end=date(2026, 1, 5),
    ) == {}


def test_native_minute_reader_requires_each_period_to_cover_daily_window() -> None:
    class _PartialNativeRepo:
        def get_czsc_minute_range(self, symbol, start, end, freq):
            del symbol, start, end, freq
            return pl.DataFrame({
                "datetime": [pd.Timestamp("2026-01-05 09:45")],
                "open": [10.0], "high": [10.1], "low": [9.9], "close": [10.0],
                "volume": [1.0], "amount": [10.0],
            })

    assert _fetch_native_minute_frames(
        _PartialNativeRepo(),
        "000001.SZ",
        "stock",
        start=date(2026, 1, 5),
        end=date(2026, 1, 6),
        expected_dates={date(2026, 1, 5), date(2026, 1, 6)},
    ) == {}


def test_higher_context_requires_every_declared_higher_timeframe() -> None:
    """不能把缺失日线上下文的 15 分钟信号误标为逆势。"""
    state = {
        "30分钟_D0BL9_V230228": "向下_中继_任意_0",
        "60分钟_D0BL9_V230228": "向下_中继_任意_0",
    }

    context = _higher_context("15分钟", state, "一买")

    assert context["summary"] == "上下文不明确"
    assert context["missing_timeframes"] == ["日线"]


def _state(freq: str, direction: str, as_of: str) -> dict:
    native_direction = {"BULLISH": "向上", "BEARISH": "向下"}.get(direction, "其他")
    return {
        "timeframe": freq,
        "direction": direction,
        "structure_state": {"BULLISH": "UP_TURNING", "BEARISH": "DOWN_CONTINUATION"}.get(direction, "UNKNOWN"),
        "as_of": as_of,
        "native_state": {"raw_value": f"{native_direction}_转折_任意_0", "values": {"v1": native_direction, "v2": "转折", "v3": "任意", "score": 0}},
        "latest_bi": None,
        "latest_fx": None,
        "latest_center": None,
    }


@pytest.mark.parametrize(
    ("directions", "expected", "event_time"),
    [
        (("BULLISH", "BEARISH", "BULLISH", "BULLISH"), "PULLBACK_REVERSAL_BULLISH", "2026-01-05 11:00"),
        (("BULLISH", "BULLISH", "BULLISH", "BULLISH"), "TREND_CONTINUATION_BULLISH", "2026-01-05 11:00"),
        (("BEARISH", "BEARISH", "BULLISH", "BULLISH"), "COUNTERTREND_BOUNCE", "2026-01-05 11:00"),
        (("BULLISH", "BEARISH", "BEARISH", "BULLISH"), "TIMEFRAME_CONFLICT", None),
    ],
)
def test_resonance_compares_confirmed_snapshots_without_historical_replay(directions, expected, event_time) -> None:
    states = {
        freq: _state(freq, direction, as_of)
        for freq, direction, as_of in zip(
            ("日线", "60分钟", "30分钟", "15分钟"),
            directions,
            ("2026-01-05", "2026-01-05 10:30", "2026-01-05 10:30", "2026-01-05 11:00"),
            strict=True,
        )
    }
    result = _analyze_resonance("000001.SZ", states)
    assert result["resonance_type"] == expected
    assert result["resonance_time"] == event_time
    assert result["current_only"] is True
    assert (result["event"] is not None) is (event_time is not None)
    if event_time is not None:
        assert result["event"]["time"] == "2026-01-05 11:00"


def test_resonance_does_not_create_event_when_a_required_state_is_unknown() -> None:
    states = {
        "日线": _state("日线", "BULLISH", "2026-01-05"),
        "60分钟": _state("60分钟", "BEARISH", "2026-01-05 10:30"),
        "30分钟": _state("30分钟", "BULLISH", "2026-01-05 10:30"),
        "15分钟": _state("15分钟", "UNKNOWN", "2026-01-05 11:00"),
    }
    result = _analyze_resonance("000001.SZ", states)
    assert result["resonance_type"] == "TIMEFRAME_CONFLICT"
    assert result["event"] is None
    assert result["warnings"] == [{"code": "INSUFFICIENT_DATA", "timeframes": ["15分钟"]}]


def test_resonance_rejects_stale_minute_context() -> None:
    states = {
        "日线": _state("日线", "BULLISH", "2026-01-06"),
        "60分钟": _state("60分钟", "BEARISH", "2026-01-05 14:30"),
        "30分钟": _state("30分钟", "BULLISH", "2026-01-05 14:30"),
        "15分钟": _state("15分钟", "BULLISH", "2026-01-05 14:45"),
    }
    result = _analyze_resonance("000001.SZ", states)
    assert result["resonance_type"] == "TIMEFRAME_CONFLICT"
    assert result["event"] is None
    assert result["warnings"][0]["code"] == "STALE_TIMEFRAME_DATA"
