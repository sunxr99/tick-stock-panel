"""Pure OHLCV feature functions owned by Wyckoff v2."""

from __future__ import annotations

import pandas as pd


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def prepare_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    required = ("date", "open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Wyckoff v2 缺少 OHLCV 字段: {', '.join(missing)}")
    result = frame.loc[:, required].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for column in required[1:]:
        result[column] = numeric(result, column)
    result = result.dropna().sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    return result.reset_index(drop=True)


def true_range(frame: pd.DataFrame) -> pd.Series:
    high, low, close = (numeric(frame, column) for column in ("high", "low", "close"))
    return pd.concat((high - low, (high - close.shift()).abs(), (low - close.shift()).abs()), axis=1).max(axis=1)


def atr_at(frame: pd.DataFrame, index: int, window: int) -> float | None:
    if index < 1:
        return None
    values = true_range(frame.iloc[: index + 1]).tail(max(int(window), 1)).dropna()
    if values.empty:
        return None
    value = float(values.mean())
    return value if value > 0 else None


def clv(open_: float, high: float, low: float, close: float) -> float:
    del open_  # The close location value is defined by the day's high-low range.
    spread = high - low
    return 0.5 if spread <= 0 else max(0.0, min(1.0, (close - low) / spread))


def volume_ratio(frame: pd.DataFrame, index: int, window: int, *, median: bool = False) -> float | None:
    ref = numeric(frame.iloc[max(0, index - max(int(window), 1)) : index], "volume").dropna()
    if ref.empty:
        return None
    baseline = float(ref.median() if median else ref.mean())
    volume = float(numeric(frame, "volume").iloc[index])
    return volume / baseline if baseline > 0 else None


def volume_percentile(frame: pd.DataFrame, index: int, window: int) -> float | None:
    ref = numeric(frame.iloc[max(0, index - max(int(window), 1)) : index], "volume").dropna()
    if ref.empty:
        return None
    current = float(numeric(frame, "volume").iloc[index])
    return float((ref <= current).mean())


def median_volume_before(frame: pd.DataFrame, index: int, window: int) -> float | None:
    """Median volume from closed bars strictly before ``index``."""
    ref = numeric(frame.iloc[max(0, index - max(int(window), 1)) : index], "volume").dropna()
    if ref.empty:
        return None
    value = float(ref.median())
    return value if value > 0 else None


def swing_values(series: pd.Series, *, kind: str, window: int) -> list[float]:
    values = pd.to_numeric(series, errors="coerce").reset_index(drop=True)
    width = max(int(window), 1)
    result: list[float] = []
    for index in range(width, len(values) - width):
        value = values.iloc[index]
        around = values.iloc[index - width : index + width + 1].dropna()
        if pd.isna(value) or around.empty:
            continue
        boundary = around.min() if kind == "low" else around.max()
        if float(value) == float(boundary):
            result.append(float(value))
    return result
