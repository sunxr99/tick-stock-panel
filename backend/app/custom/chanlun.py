# ruff: noqa: RUF001, RUF002, RUF003
"""CZSC 缠论分析扩展：日线 V1 审计修复与 V2 多周期只读分析。

仅在个股详情按需计算，不进入选股、监控或自动交易热路径。优先使用单股按需
同步的供应商原生 15/30/60 分钟 K；原生数据不足时才降级为 1 分钟
``BarGenerator`` 聚合。日线主图仍使用本地 enriched 日 K，以保留较长结构窗口。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd
import polars as pl
from fastapi import APIRouter, HTTPException, Query, Request

from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar
from app.market_time import cn_now, cn_today

logger = logging.getLogger(__name__)

EXTENSION_ID = "local.chanlun"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION
_DAILY_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
_OHLCV_COLUMNS = ("open", "close", "high", "low", "vol", "amount")
_BUY_SELL_TYPES = frozenset({"一买", "一卖", "二买", "二卖", "三买", "三卖"})
_BUY_POINT_TYPES = frozenset({"一买", "二买", "三买"})
CZSC_EVENT_IDENTITY_VERSION = 2
_SIGNAL_SPECS = (
    ("cxt_first_buy_V221126", "D1B_BUY1", {"di": 1}),
    ("cxt_first_sell_V221126", "D1B_SELL1", {"di": 1}),
    ("cxt_second_bs_V240524", "D1W9T2_第二买卖点V240524", {"di": 1, "w": 9, "t": 2}),
    ("cxt_third_bs_V230319", "D1#SMA#34_BS3辅助V230319", {"di": 1, "ma_type": "SMA", "timeperiod": 34}),
)
_CONTEXT_SIGNAL_SPEC = ("cxt_bi_base_V230228", "D0BL9_V230228", {"bi_init_length": 9})
_QUALITY_SIGNAL_SPECS = (
    ("bi_status", "笔状态", "cxt_bi_status_V230101", "D1_表里关系V230101", {}),
    ("sma20", "SMA20", "tas_ma_base_V221101", "D1SMA#20_分类V221101", {"di": 1, "ma_type": "SMA", "timeperiod": 20}),
    ("macd", "MACD", "tas_macd_base_V221028", "D1MACD12#26#9#MACD_BS辅助V221028", {"di": 1, "fastperiod": 12, "slowperiod": 26, "signalperiod": 9, "key": "MACD"}),
    ("volume", "量能", "bar_vol_grow_V221112", "D1K5B_放量V221112", {"di": 1, "n": 5}),
)
_DISPLAY_FREQS = ("15分钟", "30分钟", "60分钟", "日线")
_NATIVE_MINUTE_FREQS = {"15分钟": "15m", "30分钟": "30m", "60分钟": "60m"}
_HIGHER_CONTEXT = {"15分钟": ("30分钟", "60分钟", "日线"), "30分钟": ("60分钟", "日线"), "60分钟": ("日线",), "日线": ()}
_MIN_SIGNAL_BARS = 10
_OHLC_FLOAT_EPSILON = 1e-8
_DAILY_CLOSE_TIME = time(15, 5)
_MINUTE_CLOSE_TIMES = {
    "15m": (time(9, 45), time(10), time(10, 15), time(10, 30), time(10, 45), time(11), time(11, 15), time(11, 30), time(13, 15), time(13, 30), time(13, 45), time(14), time(14, 15), time(14, 30), time(14, 45), time(15)),
    "30m": (time(10), time(10, 30), time(11), time(11, 30), time(13, 30), time(14), time(14, 30), time(15)),
    "60m": (time(10, 30), time(11, 30), time(14), time(15)),
}


@dataclass(frozen=True)
class MultiTimeframeCZSCResult:
    """V2 返回模型；每个周期保留独立结构，不做 BUY/SELL 投票。"""

    timeframes: dict[str, dict]
    summary: list[dict]
    base_frequency: str


def _load_czsc():
    try:
        import czsc
        from czsc.utils.plotting.lightweight import plot_czsc

        return czsc, plot_czsc
    except Exception as exc:  # pragma: no cover - runtime dependency isolation
        raise HTTPException(status_code=501, detail=f"czsc 未安装或加载失败：{exc}") from exc


def _dt_str(value) -> str:
    """保留分钟精度；日线与高周期末端均与 CZSC 原始时间轴对齐。"""
    timestamp = pd.Timestamp(value)
    return timestamp.strftime("%Y-%m-%d" if timestamp.time() == pd.Timestamp(0).time() else "%Y-%m-%d %H:%M")


def _validate_and_standardize(frame: pl.DataFrame, symbol: str, *, timestamp_col: str) -> pd.DataFrame:
    """仓库标准 K→CZSC 输入；拒绝而非用 0 掩盖金融数据错误。"""
    required = {timestamp_col, "open", "high", "low", "close", "volume", "amount"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"行情缺少 CZSC 必需字段：{', '.join(missing)}")
    if frame.is_empty():
        return pd.DataFrame()

    pdf = frame.select([timestamp_col, "open", "high", "low", "close", "volume", "amount"]).to_pandas()
    out = pd.DataFrame({"dt": pd.to_datetime(pdf[timestamp_col]), "symbol": symbol})
    for source, target in (("open", "open"), ("close", "close"), ("high", "high"), ("low", "low"), ("volume", "vol"), ("amount", "amount")):
        out[target] = pd.to_numeric(pdf[source], errors="coerce")
    out = out.sort_values("dt", kind="stable").reset_index(drop=True)
    if out["dt"].isna().any() or out["dt"].duplicated().any():
        raise ValueError("行情 datetime 为空或重复；CZSC 输入必须严格时间唯一")
    if out[list(_OHLCV_COLUMNS)].isna().any().any():
        raise ValueError("行情 OHLCV/amount 含空值；拒绝以 0 静默替代")
    if (out[["open", "close", "high", "low"]] <= 0).any().any():
        raise ValueError("行情 OHLC 需为正数")
    if (out[["vol", "amount"]] < 0).any().any():
        raise ValueError("行情 volume/amount 不可为负")
    upper = out[["open", "close", "low"]].max(axis=1)
    lower = out[["open", "close", "high"]].min(axis=1)
    # 部分分钟源在价格字符串转 Float64 后会产生 1e-15 级尾差：显示 high==open，
    # 实际 high 略小。只修正远低于最小报价单位的 epsilon，真实坏K仍拒绝。
    invalid_ohlc = (out["high"] + _OHLC_FLOAT_EPSILON < upper) | (out["low"] - _OHLC_FLOAT_EPSILON > lower)
    if invalid_ohlc.any():
        raise ValueError("行情 OHLC 关系非法（high/low 不包络 open/close）")
    out["high"] = out[["high", "open", "close"]].max(axis=1)
    out["low"] = out[["low", "open", "close"]].min(axis=1)
    return out[["dt", "symbol", "open", "close", "high", "low", "vol", "amount"]]


def _latest_completed_minute_end(now: datetime, freq: str) -> datetime | None:
    """Return the last closed A-share bucket end for a provider-end-timestamped bar."""
    if freq == "1m":
        # A one-minute row stamped with the current minute can still be receiving trades.
        return now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    ends = _MINUTE_CLOSE_TIMES[freq]
    closed = [end for end in ends if end <= now.time()]
    return datetime.combine(now.date(), closed[-1]) if closed else None


def _drop_unclosed_bars(frame: pl.DataFrame, *, timestamp_col: str, freq: str | None = None) -> pl.DataFrame:
    """Remove today's still-forming bars; stored data may be ahead of a closed-bar analysis view."""
    if frame.is_empty() or timestamp_col not in frame.columns:
        return frame
    now = cn_now().replace(tzinfo=None)
    today = now.date()
    if freq is None:
        if now.time() >= _DAILY_CLOSE_TIME:
            return frame
        return frame.filter(pl.col(timestamp_col) < today)

    cutoff = _latest_completed_minute_end(now, freq)
    if cutoff is None:
        return frame.filter(pl.col(timestamp_col).dt.date() < today)
    return frame.filter(
        (pl.col(timestamp_col).dt.date() < today)
        | ((pl.col(timestamp_col).dt.date() == today) & (pl.col(timestamp_col) <= cutoff))
    )


def _fetch_daily_frame(repo, symbol: str, days: int) -> tuple[pd.DataFrame, str]:
    asset_type = repo.resolve_asset_type(symbol)
    end = cn_today()
    frame = repo.get_daily_asset(asset_type, symbol, end - timedelta(days=days * 2 + 30), end, columns=_DAILY_COLUMNS)
    frame = _drop_unclosed_bars(frame, timestamp_col="date")
    standardized = _validate_and_standardize(frame, symbol, timestamp_col="date")
    return standardized.tail(days).reset_index(drop=True), asset_type


def _fetch_minute_frame(repo, symbol: str, asset_type: str, days: int) -> pd.DataFrame:
    """读取最近 N 个已落库交易日的一分钟 K；指数暂无本地分钟分区。"""
    if asset_type == "index":
        return pd.DataFrame()
    end = cn_today()
    frame = repo.get_minute_range([symbol], end - timedelta(days=days * 3 + 30), end, asset_type=asset_type)
    frame = _drop_unclosed_bars(frame, timestamp_col="datetime", freq="1m")
    if frame.is_empty():
        return pd.DataFrame()
    if "datetime" not in frame.columns:
        raise ValueError("分钟行情缺少 datetime")
    dates = sorted(frame.select(pl.col("datetime").dt.date()).unique().to_series().to_list())[-days:]
    return _validate_and_standardize(frame.filter(pl.col("datetime").dt.date().is_in(dates)), symbol, timestamp_col="datetime")


def _fetch_native_minute_frames(
    repo,
    symbol: str,
    asset_type: str,
    *,
    start: date,
    end: date,
    expected_dates: set[date] | None = None,
) -> dict[str, pd.DataFrame]:
    """读取三种供应商原生分钟K；缺任一种即让调用方走完整的 F1 降级路径。

    不把部分原生周期和 1 分钟聚合周期混在一次关系分析中，避免用户误以为三者
    来自同一数据口径。
    """
    if asset_type == "index":
        return {}
    frames: dict[str, pd.DataFrame] = {}
    for display_freq, provider_freq in _NATIVE_MINUTE_FREQS.items():
        frame = repo.get_czsc_minute_range(symbol, start, end, provider_freq)
        frame = _drop_unclosed_bars(frame, timestamp_col="datetime", freq=provider_freq)
        if frame.is_empty():
            return {}
        standardized = _validate_and_standardize(frame, symbol, timestamp_col="datetime")
        actual_dates = set(standardized["dt"].dt.date)
        if expected_dates and not expected_dates.issubset(actual_dates):
            logger.info(
                "CZSC native %s minute coverage incomplete for %s: missing=%s",
                provider_freq,
                symbol,
                sorted(expected_dates - actual_dates),
            )
            return {}
        frames[display_freq] = standardized
    return frames


def _to_bars(czsc, frame: pd.DataFrame, freq):
    return [] if frame.empty else czsc.format_standard_kline(frame, freq=freq)


def _signal_config(freqs: tuple[str, ...] = _DISPLAY_FREQS) -> list[dict]:
    """CzscSignals 的运行时 config；一买/一卖使用显式参数，避免反推简写失败。"""
    specs = (*_SIGNAL_SPECS, _CONTEXT_SIGNAL_SPEC)
    configs = [{"name": name, "freq": freq, **params} for freq in freqs for name, _, params in specs]
    return configs + [
        {"name": name, "freq": freq, **params}
        for freq in freqs
        for _, _, name, _, params in _QUALITY_SIGNAL_SPECS
    ]


def _latest_fx(c) -> dict | None:
    if not c.fx_list:
        return None
    fx = c.fx_list[-1]
    return {"dt": _dt_str(fx.dt), "mark": str(fx.mark), "price": float(fx.fx), "high": float(fx.high), "low": float(fx.low), "power": str(fx.power_str)}


def _timeframe_state(czsc, c, freq: str, as_of: str, signal_state: dict | None = None) -> dict:
    """透传 cxt_bi_base 原生状态；不在关系层重算趋势、分型或笔。"""
    name, suffix, params = _CONTEXT_SIGNAL_SPEC
    key = f"{freq}_{suffix}"
    if signal_state is None:
        from czsc._native.signals import call_signal

        signal = call_signal(name, c, params)[0]
        value = signal.value
        key = signal.key
    else:
        value = signal_state.get(key, "其他_任意_任意_0")
    native = _signal_detail(name, key, params, value)
    v1, v2 = native["values"]["v1"], native["values"]["v2"]
    direction = {"向上": "BULLISH", "向下": "BEARISH"}.get(v1, "UNKNOWN")
    structure_state = {
        ("BULLISH", "中继"): "UP_CONTINUATION",
        ("BULLISH", "转折"): "UP_TURNING",
        ("BEARISH", "中继"): "DOWN_CONTINUATION",
        ("BEARISH", "转折"): "DOWN_TURNING",
    }.get((direction, v2), "UNKNOWN")
    latest_zs = c.zs_list[-1] if c.zs_list else None
    quality = []
    for identifier, label, quality_name, suffix, quality_params in _QUALITY_SIGNAL_SPECS:
        quality_key = f"{freq}_{suffix}"
        quality_value = signal_state.get(quality_key) if signal_state is not None else None
        if quality_value is None:
            from czsc._native.signals import call_signal

            values = call_signal(quality_name, c, quality_params)
            quality_value = values[0].value if values else "其他_任意_任意_0"
            quality_key = values[0].key if values else quality_key
        quality.append({
            "id": identifier,
            "label": label,
            "raw_signal": f"{quality_key}_{quality_value}",
            "raw_value": quality_value,
            "values": _split_signal_value(quality_value),
        })
    return {
        "timeframe": freq,
        "direction": direction,
        "structure_state": structure_state,
        "as_of": as_of,
        "native_state": native,
        "latest_bi": _bi_anchor(c),
        "latest_fx": _latest_fx(c),
        "latest_center": None if latest_zs is None else {"sdt": _dt_str(latest_zs.sdt), "edt": _dt_str(latest_zs.edt), "zg": float(latest_zs.zg), "zd": float(latest_zs.zd), "gg": float(latest_zs.gg), "dd": float(latest_zs.dd)},
        "quality": quality,
    }


def _serialize_czsc(c, *, confirmations: dict[tuple, str] | None = None, as_of=None, chart_bars: list | None = None) -> dict:
    """只输出 CZSC 已完成笔；event_time 与 confirmation_time 分开。"""
    confirmations = confirmations or {}
    bis = []
    for bi in c.finished_bis:
        if as_of is not None and pd.Timestamp(bi.edt) > pd.Timestamp(as_of):
            continue
        sdt, edt = _dt_str(bi.sdt), _dt_str(bi.edt)
        bis.append({"sdt": sdt, "edt": edt, "event_time": edt, "confirmation_time": confirmations.get((sdt, edt)), "status": "confirmed", "direction": str(bi.direction), "start_price": float(bi.fx_a.fx), "end_price": float(bi.fx_b.fx), "high": float(bi.high), "low": float(bi.low), "power": float(bi.power)})
    finished_end = {item["edt"] for item in bis}
    zss = []
    for zs in c.zs_list:
        if as_of is not None and pd.Timestamp(zs.edt) > pd.Timestamp(as_of):
            continue
        sdt, edt = _dt_str(zs.sdt), _dt_str(zs.edt)
        if edt not in finished_end:
            continue
        key = (sdt, edt, round(float(zs.zg), 8), round(float(zs.zd), 8))
        zss.append({"sdt": sdt, "edt": edt, "event_time": edt, "confirmation_time": confirmations.get(key), "status": "confirmed", "zg": float(zs.zg), "zd": float(zs.zd), "gg": float(zs.gg), "dd": float(zs.dd)})
    display_bars = chart_bars if chart_bars is not None else c.bars_raw
    bars = [{"dt": _dt_str(bar.dt), "open": float(bar.open), "high": float(bar.high), "low": float(bar.low), "close": float(bar.close), "vol": float(bar.vol)} for bar in display_bars if as_of is None or pd.Timestamp(bar.dt) <= pd.Timestamp(as_of)]
    return {"bars": bars, "bi": bis, "zs": zss}


def _track_structure_confirmations(czsc, bars: list) -> tuple[object, dict[tuple, str]]:
    """流式 update 时首次出现的 finished BI/ZS 是实际确认时刻。"""
    c = czsc.CZSC([bars[0]])
    confirmations: dict[tuple, str] = {}
    for bar in bars[1:]:
        c.update(bar)
        now = _dt_str(bar.dt)
        for bi in c.finished_bis:
            confirmations.setdefault((_dt_str(bi.sdt), _dt_str(bi.edt)), now)
        for zs in c.zs_list:
            confirmations.setdefault((_dt_str(zs.sdt), _dt_str(zs.edt), round(float(zs.zg), 8), round(float(zs.zd), 8)), now)
    return c, confirmations


def _split_signal_value(value: str) -> dict:
    """CZSC Signal.value 的 v1_v2_v3_score，不用前端猜测语义。"""
    v1, v2, v3, score = [*value.split("_"), "任意", "任意", "0"][:4]
    return {"v1": v1, "v2": v2, "v3": v3, "score": int(score)}


def _bi_anchor(c) -> dict | None:
    """信号函数读取 c.bi_list；保留其最新笔作为上游可复核锚点。"""
    if not c.bi_list:
        return None
    bi = c.bi_list[-1]
    return {"sdt": _dt_str(bi.sdt), "edt": _dt_str(bi.edt), "direction": str(bi.direction)}


def _signal_detail(name: str, key: str, params: dict, value: str) -> dict:
    values = _split_signal_value(value)
    return {
        "signal_name": name,
        "signal_key": key,
        "raw_signal": f"{key}_{value}",
        "raw_value": value,
        "values": values,
        "parameters": params,
        "structure_count": values["v2"] if values["v2"].endswith("笔") else None,
        "subcondition": values["v2"] if values["v2"] != "任意" else None,
    }


def _higher_context(freq: str, state: dict, point_type: str) -> dict:
    contexts = []
    missing_timeframes = []
    for higher_freq in _HIGHER_CONTEXT[freq]:
        name, suffix, params = _CONTEXT_SIGNAL_SPEC
        key = f"{higher_freq}_{suffix}"
        value = state.get(key, "其他_任意_任意_0")
        detail = _signal_detail(name, key, params, value)
        contexts.append({"timeframe": higher_freq, "values": detail["values"], "raw_signal": detail["raw_signal"]})
        if detail["values"]["v1"] not in {"向上", "向下"}:
            missing_timeframes.append(higher_freq)
    if missing_timeframes:
        summary = "上下文不明确"
    else:
        known = [item["values"]["v1"] for item in contexts]
        expected = "向上" if point_type.endswith("买") else "向下"
        opposite = "向下" if expected == "向上" else "向上"
        summary = "顺高周期结构" if all(value == expected for value in known) else "逆高周期结构" if all(value == opposite for value in known) else "高周期冲突"
    return {
        "summary": summary,
        "timeframes": contexts,
        "missing_timeframes": missing_timeframes,
    }


def _make_signal_point(c, *, name: str, key: str, params: dict, value: str, confirmation_time: str, price: float, context: dict | None = None) -> dict:
    detail = _signal_detail(name, key, params, value)
    anchor = _bi_anchor(c)
    return {
        "dt": confirmation_time,
        "confirmation_time": confirmation_time,
        "event_time": anchor["edt"] if anchor else confirmation_time,
        "type": detail["values"]["v1"],
        "price": round(price, 2),
        "status": "confirmed",
        "structure_anchor": anchor,
        "signal": detail,
        "higher_timeframe_context": context or {"summary": "上下文不明确", "timeframes": []},
    }


def _signal_occurrence_key(point: dict) -> tuple:
    anchor = point["structure_anchor"] or {}
    signal = point["signal"]
    return signal["signal_name"], signal["raw_value"], anchor.get("sdt"), anchor.get("edt")


def _find_daily_buy_sell_points(czsc, bars: list) -> list[dict]:
    """日线逐快照保留原始 Signal 字段；同一结构事件只标首次确认。"""
    from czsc._native.signals import call_signal

    points: list[dict] = []
    seen: set[tuple] = set()
    for index in range(_MIN_SIGNAL_BARS, len(bars)):
        c = czsc.CZSC(bars[: index + 1])
        now = _dt_str(bars[index].dt)
        for name, _, params in _SIGNAL_SPECS:
            for signal in call_signal(name, c, params):
                if signal.v1 not in _BUY_SELL_TYPES:
                    continue
                point = _make_signal_point(c, name=name, key=signal.key, params=params, value=signal.value, confirmation_time=now, price=float(bars[index].close))
                key = _signal_occurrence_key(point)
                if key not in seen:
                    seen.add(key)
                    points.append(point)
    return points


def _daily_buy_points_at_snapshot(czsc, c, confirmation_time: str, price: float) -> list[dict]:
    """Return the B1/B2/B3 signals visible in one closed daily-bar snapshot."""
    from czsc._native.signals import call_signal

    points = []
    for name, _, params in _SIGNAL_SPECS:
        for signal in call_signal(name, c, params):
            if signal.v1 not in _BUY_POINT_TYPES:
                continue
            points.append(
                _make_signal_point(
                    c,
                    name=name,
                    key=signal.key,
                    params=params,
                    value=signal.value,
                    confirmation_time=confirmation_time,
                    price=price,
                )
            )
    return points


def find_latest_daily_buy_points(czsc, bars: list) -> list[dict]:
    """Find CZSC B points that first become visible on the final closed daily bar.

    The detail chart replays every historical daily snapshot to draw all markers.
    A full-market screener only needs the last edge: compare the final closed-bar
    snapshot with the previous snapshot, retaining a B1/B2/B3 only when its
    signal-and-structure occurrence is new.  A raw CZSC status can disappear
    and later reappear while retaining the same old structure anchor; scan
    backwards only for those final-bar candidates so that such a reappearance
    is not misclassified as a new screening event.
    """
    if len(bars) <= _MIN_SIGNAL_BARS:
        return []
    current = czsc.CZSC(bars)
    now = _dt_str(bars[-1].dt)
    current_points = _daily_buy_points_at_snapshot(
        czsc,
        current,
        now,
        float(bars[-1].close),
    )
    previous = czsc.CZSC(bars[:-1])
    previous_points = _daily_buy_points_at_snapshot(
        czsc,
        previous,
        _dt_str(bars[-2].dt),
        float(bars[-2].close),
    )
    previous_occurrences = {_signal_occurrence_key(point) for point in previous_points}
    edge_points = [
        point
        for point in current_points
        if _signal_occurrence_key(point) not in previous_occurrences
    ]
    if not edge_points:
        return []

    earlier_occurrences: set[tuple] = set()
    pending = {_signal_occurrence_key(point) for point in edge_points}
    # Most false reappearances are near the final bar, so traverse backwards.
    # Only a small set of current B-point candidates pays this extra work; the
    # full-market scan retains its inexpensive two-snapshot fast path otherwise.
    for index in range(len(bars) - 2, _MIN_SIGNAL_BARS - 1, -1):
        c = czsc.CZSC(bars[: index + 1])
        historic_points = _daily_buy_points_at_snapshot(
            czsc,
            c,
            _dt_str(bars[index].dt),
            float(bars[index].close),
        )
        earlier_occurrences.update(_signal_occurrence_key(point) for point in historic_points)
        pending.difference_update(earlier_occurrences)
        if not pending:
            return []
    return [point for point in edge_points if _signal_occurrence_key(point) in pending]


def filter_daily_czsc_buy_points(history: pl.DataFrame, params: dict | None = None) -> pl.DataFrame:
    """Screen a daily panel for B1/B2/B3 first confirmed on its final date.

    This is deliberately daily-only and local-data-only: it never triggers a
    minute download, does not use multi-timeframe resonance, and skips a symbol
    with malformed OHLCV rather than fabricating a signal.  Returned rows retain
    the latest enriched fields, plus compact raw CZSC evidence for the screener.
    """
    del params
    required = {"symbol", "date", "open", "high", "low", "close", "volume", "amount"}
    if history.is_empty() or not required <= set(history.columns):
        return pl.DataFrame()

    # During the session, the daily bar is still mutable.  Keep the screener's
    # visibility contract identical to the chart endpoint and only use closed
    # trading days until the close cutoff has passed.
    if cn_now().time() < _DAILY_CLOSE_TIME:
        history = history.filter(pl.col("date") < cn_today())
        if history.is_empty():
            return pl.DataFrame()

    try:
        import czsc
    except Exception as exc:  # pragma: no cover - runtime dependency isolation
        raise RuntimeError(f"czsc 未安装或加载失败：{exc}") from exc

    selected: list[dict] = []
    for symbol, frame in history.partition_by("symbol", as_dict=True, maintain_order=True).items():
        # partition_by(as_dict=True) emits a one-item tuple for the string key.
        symbol_value = str(symbol[0] if isinstance(symbol, tuple) else symbol)
        frame = frame.sort("date")
        try:
            standardized = _validate_and_standardize(frame, symbol_value, timestamp_col="date")
            bars = _to_bars(czsc, standardized, czsc.Freq.D)
            points = find_latest_daily_buy_points(czsc, bars)
        except Exception as exc:
            logger.warning("CZSC daily screener skipped %s due to invalid input: %s", symbol_value, exc)
            continue
        if not points:
            continue
        row = frame.tail(1).to_dicts()[0]
        row["czsc_buy_types"] = sorted({str(point["type"]) for point in points})
        row["czsc_buy_signals"] = [str(point["signal"]["raw_signal"]) for point in points]
        row["czsc_confirmation_time"] = str(points[0]["confirmation_time"])
        row["czsc_event_identity_version"] = CZSC_EVENT_IDENTITY_VERSION
        selected.append(row)
    return pl.from_dicts(selected) if selected else pl.DataFrame()


def _serialize_daily(czsc, bars: list) -> dict:
    c, confirmations = _track_structure_confirmations(czsc, bars)
    data = _serialize_czsc(c, confirmations=confirmations, chart_bars=bars)
    data["buy_sell"] = _find_daily_buy_sell_points(czsc, bars)
    data["state"] = _timeframe_state(czsc, c, "日线", _dt_str(bars[-1].dt))
    return data


def _parse_signal_points(c, state: dict, freq: str, confirmation_time: str, price: float, seen: set[tuple]) -> list[dict]:
    points = []
    for name, suffix, params in _SIGNAL_SPECS:
        key = f"{freq}_{suffix}"
        value = state.get(key, "其他_任意_任意_0")
        if _split_signal_value(value)["v1"] not in _BUY_SELL_TYPES:
            continue
        point = _make_signal_point(c, name=name, key=key, params=params, value=value, confirmation_time=confirmation_time, price=price, context=_higher_context(freq, state, _split_signal_value(value)["v1"]))
        occurrence = _signal_occurrence_key(point)
        if occurrence not in seen:
            seen.add(occurrence)
            points.append(point)
    return points


def _resonance_evidence(code: str, state: dict) -> dict:
    return {"code": code, "timeframe": state["timeframe"], "direction": state["direction"], "structure_state": state["structure_state"], "confirmation_time": state["as_of"], "native_state": state["native_state"], "latest_bi": state["latest_bi"]}


def _analyze_resonance(symbol: str, states: dict[str, dict]) -> dict:
    """只比较四个独立 CZSC snapshot 的层级关系；不产生交易指令或历史回画。"""
    required = ("日线", "60分钟", "30分钟", "15分钟")
    missing = [freq for freq in required if freq not in states or states[freq]["direction"] == "UNKNOWN"]
    if missing:
        return {"symbol": symbol, "analysis_time": max((state["as_of"] for state in states.values()), default=None), "resonance_type": "TIMEFRAME_CONFLICT", "direction": "UNKNOWN", "resonance_time": None, "timeframe_states": states, "evidence": [], "warnings": [{"code": "INSUFFICIENT_DATA", "timeframes": missing}], "summary": "周期结构数据不足，暂不形成共振结论", "current_only": True, "event": None}

    day, m60, m30, m15 = (states[freq] for freq in required)
    state_dates = {freq: states[freq]["as_of"][:10] for freq in required}
    if len(set(state_dates.values())) != 1:
        return {"symbol": symbol, "analysis_time": max(state["as_of"] for state in states.values()), "resonance_type": "TIMEFRAME_CONFLICT", "direction": "UNKNOWN", "resonance_time": None, "timeframe_states": states, "evidence": [], "warnings": [{"code": "STALE_TIMEFRAME_DATA", "dates": state_dates}], "summary": "各周期最后可用交易日不一致，暂不形成当前共振结论", "current_only": True, "event": None}

    directions = tuple(state["direction"] for state in (day, m60, m30, m15))
    if directions == ("BULLISH", "BEARISH", "BULLISH", "BULLISH"):
        resonance_type, direction, codes, warnings, summary = "PULLBACK_REVERSAL_BULLISH", "BULLISH", ("DAY_BULLISH", "M60_PULLBACK", "M30_UP_STRUCTURE", "M15_UP_CONFIRMED"), [{"code": "M60_PULLBACK_ACTIVE"}], "日线偏多背景下的回调转强"
    elif directions == ("BULLISH", "BULLISH", "BULLISH", "BULLISH"):
        resonance_type, direction, codes, warnings, summary = "TREND_CONTINUATION_BULLISH", "BULLISH", ("DAY_BULLISH", "M60_BULLISH", "M30_BULLISH", "M15_BULLISH"), [{"code": "NOT_AN_ENTRY_INSTRUCTION"}], "四周期结构一致向上；不等同最佳买点"
    elif directions == ("BEARISH", "BEARISH", "BULLISH", "BULLISH"):
        resonance_type, direction, codes, warnings, summary = "COUNTERTREND_BOUNCE", "BULLISH", ("DAY_BEARISH", "M60_WEAK", "M30_UP_STRUCTURE", "M15_UP_CONFIRMED"), [{"code": "COUNTER_TREND"}], "低周期向上，但仍处于大级别逆势反弹"
    elif directions == ("BEARISH", "BULLISH", "BEARISH", "BEARISH"):
        resonance_type, direction, codes, warnings, summary = "PULLBACK_REVERSAL_BEARISH", "BEARISH", ("DAY_BEARISH", "M60_REBOUND", "M30_DOWN_STRUCTURE", "M15_DOWN_CONFIRMED"), [{"code": "M60_REBOUND_ACTIVE"}], "日线偏空背景下的反弹转弱"
    else:
        resonance_type, direction, codes, warnings, summary = "TIMEFRAME_CONFLICT", "UNKNOWN", (), [{"code": "TIMEFRAME_CONFLICT", "directions": dict(zip(required, directions, strict=True))}], "四周期方向未形成定义的层级关系"

    evidence = (
        [_resonance_evidence(code, state) for code, state in zip(codes, (day, m60, m30, m15), strict=True)]
        if codes
        else []
    )
    resonance_time = max((item["confirmation_time"] for item in evidence), default=None)
    event = None if resonance_time is None else {"time": resonance_time, "resonance_type": resonance_type, "direction": direction, "summary": summary, "evidence": evidence, "warnings": warnings}
    return {"symbol": symbol, "analysis_time": max(state["as_of"] for state in states.values()), "resonance_type": resonance_type, "direction": direction, "resonance_time": resonance_time, "timeframe_states": states, "evidence": evidence, "warnings": warnings, "summary": summary, "current_only": True, "event": event}


def _analyze_minute_multi(
    czsc,
    frame: pd.DataFrame,
    *,
    daily_bars: list | None = None,
) -> MultiTimeframeCZSCResult:
    """使用原生 CzscSignals 驱动 F1→15/30/60/D；未完成桶不确认信号。

    分钟信号的日线上下文来自主分析使用的长日K快照，而不是由短分钟窗口
    临时聚合出的日线。每个分钟时点只暴露此前已收盘的日K，避免历史回放时
    读取后来的日线状态。
    """
    from czsc._native.signals import call_signal

    raw_bars = _to_bars(czsc, frame, czsc.Freq.F1)
    if len(raw_bars) < 3:
        return MultiTimeframeCZSCResult({}, [], "1分钟")
    freqs = [czsc.Freq.F15, czsc.Freq.F30, czsc.Freq.F60, czsc.Freq.D]
    bg = czsc.BarGenerator(czsc.Freq.F1, freqs, market="A股")
    # CzscSignals 在 native 边界接管传入 BG；绘图需独立保留聚合 K 线，不能再读 bg.bars。
    chart_bg = czsc.BarGenerator(czsc.Freq.F1, freqs, max_count=max(len(raw_bars), 2000), market="A股")
    signals = czsc.CzscSignals(bg, _signal_config())
    confirmations = {freq: {} for freq in _DISPLAY_FREQS}
    points = {freq: [] for freq in _DISPLAY_FREQS}
    seen = {freq: set() for freq in _DISPLAY_FREQS}
    daily_context = None
    daily_index = 0
    daily_context_value: str | None = None

    def with_daily_context(now: pd.Timestamp, state: dict[str, str]) -> dict[str, str]:
        """Overlay the long daily state available before this intraday date."""
        nonlocal daily_context, daily_context_value, daily_index
        if not daily_bars:
            return state
        name, suffix, params = _CONTEXT_SIGNAL_SPEC
        while daily_index < len(daily_bars) and pd.Timestamp(daily_bars[daily_index].dt).date() < now.date():
            daily_bar = daily_bars[daily_index]
            if daily_context is None:
                daily_context = czsc.CZSC([daily_bar])
            else:
                daily_context.update(daily_bar)
            daily_index += 1
            values = call_signal(name, daily_context, params)
            if values:
                daily_context_value = values[0].value
        if daily_context_value is None:
            return state
        merged = dict(state)
        merged[f"日线_{suffix}"] = daily_context_value
        return merged

    for raw in raw_bars:
        signals.update_signals(raw)
        chart_bg.update(raw)
        now = _dt_str(raw.dt)
        signal_state = with_daily_context(pd.Timestamp(raw.dt), signals.s)
        for freq, c in signals.kas.items():
            if freq not in confirmations or not c.bars_raw or _dt_str(c.bars_raw[-1].dt) != now:
                continue
            for bi in c.finished_bis:
                confirmations[freq].setdefault((_dt_str(bi.sdt), _dt_str(bi.edt)), now)
            for zs in c.zs_list:
                confirmations[freq].setdefault((_dt_str(zs.sdt), _dt_str(zs.edt), round(float(zs.zg), 8), round(float(zs.zd), 8)), now)
            points[freq].extend(_parse_signal_points(c, signal_state, freq, now, float(raw.close), seen[freq]))
    output, summary = {}, []
    for freq in _DISPLAY_FREQS:
        c = signals.kas.get(freq)
        if c is None or not c.bars_raw:
            continue
        data = _serialize_czsc(c, confirmations=confirmations[freq], as_of=raw_bars[-1].dt, chart_bars=chart_bg.bars[freq])
        data.update({"buy_sell": points[freq], "timeframe": freq, "source": "minute_bar_generator", "state": _timeframe_state(czsc, c, freq, _dt_str(c.bars_raw[-1].dt), signals.s)})
        output[freq] = data
        summary.append({"timeframe": freq, "bars_count": len(data["bars"]), "bi_count": len(data["bi"]), "zs_count": len(data["zs"]), "signal_count": len(data["buy_sell"]), "source": data["source"]})
    return MultiTimeframeCZSCResult(output, summary, "1分钟")


def _analyze_native_minute_multi(
    czsc,
    frames: dict[str, pd.DataFrame],
    *,
    daily_bars: list | None = None,
) -> MultiTimeframeCZSCResult:
    """用提供商原生 15/30/60 分钟K做独立 CZSC，再按真实时间维护上下文。

    各周期不再经 F1 ``BarGenerator`` 生成；同一时刻先处理高周期收盘K，因而
    低周期 signal 的上下文只使用当时已经闭合的高周期结构，不读取未来状态。
    """
    from czsc._native.signals import call_signal

    raw_by_freq = {
        display_freq: _to_bars(
            czsc,
            frame,
            {"15分钟": czsc.Freq.F15, "30分钟": czsc.Freq.F30, "60分钟": czsc.Freq.F60}[display_freq],
        )
        for display_freq, frame in frames.items()
    }
    if any(len(bars) < 3 for bars in raw_by_freq.values()):
        return MultiTimeframeCZSCResult({}, [], "TickFlow原生分钟K")

    analyzers = {freq: czsc.CZSC([bars[0]]) for freq, bars in raw_by_freq.items()}
    confirmations = {freq: {} for freq in raw_by_freq}
    points = {freq: [] for freq in raw_by_freq}
    seen = {freq: set() for freq in raw_by_freq}
    signal_state: dict[str, str] = {}
    daily_context = None
    daily_index = 0

    def advance_daily_context(now: pd.Timestamp) -> None:
        """Expose only daily bars closed before the intraday signal date."""
        nonlocal daily_context, daily_index
        if not daily_bars:
            return
        name, suffix, params = _CONTEXT_SIGNAL_SPEC
        while daily_index < len(daily_bars) and pd.Timestamp(daily_bars[daily_index].dt).date() < now.date():
            daily_bar = daily_bars[daily_index]
            if daily_context is None:
                daily_context = czsc.CZSC([daily_bar])
            else:
                daily_context.update(daily_bar)
            daily_index += 1
            values = call_signal(name, daily_context, params)
            if values:
                signal_state[f"日线_{suffix}"] = values[0].value

    # 同一结束时刻的高周期结构先可知，再作为低周期 signal 的可用上下文。
    priority = {"60分钟": 0, "30分钟": 1, "15分钟": 2}
    timeline = sorted(
        (
            (pd.Timestamp(bar.dt), priority[freq], freq, index, bar)
            for freq, bars in raw_by_freq.items()
            for index, bar in enumerate(bars[1:], start=1)
        ),
        key=lambda item: (item[0], item[1]),
    )
    for timestamp, _, freq, index, bar in timeline:
        advance_daily_context(timestamp)
        analyzer = analyzers[freq]
        analyzer.update(bar)
        now = _dt_str(bar.dt)
        for bi in analyzer.finished_bis:
            confirmations[freq].setdefault((_dt_str(bi.sdt), _dt_str(bi.edt)), now)
        for zs in analyzer.zs_list:
            confirmations[freq].setdefault(
                (_dt_str(zs.sdt), _dt_str(zs.edt), round(float(zs.zg), 8), round(float(zs.zd), 8)),
                now,
            )
        # 仅在当前周期已有足够结构输入时调用买卖点 signal，和日线实现一致。
        if index < _MIN_SIGNAL_BARS:
            continue
        for name, suffix, params in (*_SIGNAL_SPECS, _CONTEXT_SIGNAL_SPEC):
            values = call_signal(name, analyzer, params)
            if values:
                signal_state[f"{freq}_{suffix}"] = values[0].value
        for _, _, name, suffix, params in _QUALITY_SIGNAL_SPECS:
            values = call_signal(name, analyzer, params)
            if values:
                signal_state[f"{freq}_{suffix}"] = values[0].value
        points[freq].extend(
            _parse_signal_points(
                analyzer,
                signal_state,
                freq,
                now,
                float(bar.close),
                seen[freq],
            )
        )

    output, summary = {}, []
    for freq in ("15分钟", "30分钟", "60分钟"):
        analyzer = analyzers[freq]
        bars = raw_by_freq[freq]
        last_time = _dt_str(bars[-1].dt)
        data = _serialize_czsc(
            analyzer,
            confirmations=confirmations[freq],
            as_of=bars[-1].dt,
            chart_bars=bars,
        )
        data.update({
            "buy_sell": points[freq],
            "timeframe": freq,
            "source": "tickflow_native",
            "state": _timeframe_state(czsc, analyzer, freq, last_time, signal_state),
        })
        output[freq] = data
        summary.append({
            "timeframe": freq,
            "bars_count": len(data["bars"]),
            "bi_count": len(data["bi"]),
            "zs_count": len(data["zs"]),
            "signal_count": len(data["buy_sell"]),
            "source": data["source"],
        })
    return MultiTimeframeCZSCResult(output, summary, "TickFlow原生15/30/60分钟")


def setup(registrar: BackendExtensionRegistrar) -> None:
    router = APIRouter(prefix="/api/chan", tags=["chanlun"])

    @router.get("/plot")
    def chan_plot(request: Request, symbol: str = Query(...), days: int = Query(250, ge=30, le=2000), theme: str = Query("dark", pattern="^(light|dark)$")) -> dict:
        czsc, plot_czsc = _load_czsc()
        try:
            frame, asset_type = _fetch_daily_frame(request.app.state.repo, symbol, days)
            bars = _to_bars(czsc, frame, czsc.Freq.D)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if len(bars) < 10:
            raise HTTPException(status_code=404, detail="本地无足够日K数据，请先同步日K")
        c = czsc.CZSC(bars)
        return {"symbol": symbol, "asset_type": asset_type, "bars": len(bars), "bi_count": len(c.finished_bis), "zs_count": len(c.zs_list), "html": plot_czsc(c, output="html", theme=theme, tail_bars=days)}

    @router.get("/analyze")
    def chan_analyze(request: Request, symbol: str = Query(...), days: int = Query(250, ge=30, le=2000), minute_days: int = Query(60, ge=5, le=120)) -> dict:
        czsc, _ = _load_czsc()
        repo = request.app.state.repo
        try:
            daily_frame, asset_type = _fetch_daily_frame(repo, symbol, days)
            daily_bars = _to_bars(czsc, daily_frame, czsc.Freq.D)
            native_frames = _fetch_native_minute_frames(
                repo,
                symbol,
                asset_type,
                start=daily_frame["dt"].iloc[0].date() if not daily_frame.empty else cn_today(),
                end=daily_frame["dt"].iloc[-1].date() if not daily_frame.empty else cn_today(),
                expected_dates=set(daily_frame["dt"].dt.date) if not daily_frame.empty else set(),
            )
            minute_frame = pd.DataFrame() if native_frames else _fetch_minute_frame(repo, symbol, asset_type, minute_days)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if len(daily_bars) < 10:
            raise HTTPException(status_code=404, detail="本地无足够日K数据，请先同步日K")
        daily = _serialize_daily(czsc, daily_bars)
        timeframes = {"日线": {**daily, "timeframe": "日线", "source": "daily_enriched"}}
        summary = [{"timeframe": "日线", "bars_count": len(daily["bars"]), "bi_count": len(daily["bi"]), "zs_count": len(daily["zs"]), "signal_count": len(daily["buy_sell"]), "source": "daily_enriched"}]
        if native_frames:
            multi = _analyze_native_minute_multi(czsc, native_frames, daily_bars=daily_bars)
            timeframes.update(multi.timeframes)
            summary.extend(multi.summary)
        elif not minute_frame.empty:
            multi = _analyze_minute_multi(czsc, minute_frame, daily_bars=daily_bars)
            timeframes.update({key: value for key, value in multi.timeframes.items() if key != "日线"})
            summary.extend(item for item in multi.summary if item["timeframe"] != "日线")
        states = {freq: data["state"] for freq, data in timeframes.items() if "state" in data}
        resonance = _analyze_resonance(symbol, states)
        minute_available = bool(native_frames) or not minute_frame.empty
        base_frequency = (
            "TickFlow原生15/30/60分钟" if native_frames else "1分钟" if not minute_frame.empty else "日线"
        )
        return {"symbol": symbol, "asset_type": asset_type, "bars_count": len(daily["bars"]), "bi_count": len(daily["bi"]), "zs_count": len(daily["zs"]), "buy_sell_count": len(daily["buy_sell"]), "timeframe": "日线", "source": "daily_enriched", **daily, "timeframes": timeframes, "multi_timeframe_summary": summary, "base_frequency": base_frequency, "minute_data_available": minute_available, "resonance": resonance}

    registrar.include_router(router)
