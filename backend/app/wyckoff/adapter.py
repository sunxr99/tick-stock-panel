# ruff: noqa: RUF002
"""TSP 标准日线数据到 Wyckoff 核心输入的显式适配。

上游 WyckoffTradingAgent 的确定性核心使用 pandas DataFrame，列名为
``date/open/high/low/close/volume/amount``。本模块只接收已由仓库层读取的
Polars 数据，禁止在领域层绕过 Provider 或 KlineRepository 自行取数。
"""
from __future__ import annotations

import pandas as pd
import polars as pl

_REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "volume", "amount")


def to_wyckoff_ohlcv(frame: pl.DataFrame, *, symbol: str) -> pd.DataFrame:
    """返回升序、唯一且通过 OHLCV 基础校验的 Wyckoff 日线输入。

    价格保留仓库提供的前复权口径；本函数不混入原始价或推断成交量单位。
    """
    missing = [column for column in _REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"威克夫分析缺少必需行情字段: {', '.join(missing)}")
    if frame.is_empty():
        return pd.DataFrame(columns=["symbol", *_REQUIRED_COLUMNS])

    source = frame.select(_REQUIRED_COLUMNS).sort("date")
    if source.get_column("date").null_count() or source.get_column("date").n_unique() != source.height:
        raise ValueError("威克夫分析要求 date 非空且唯一")

    result = source.to_pandas()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.date
    for column in _REQUIRED_COLUMNS[1:]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result[list(_REQUIRED_COLUMNS[1:])].isna().any().any():
        raise ValueError("威克夫分析要求 OHLCV/amount 不含空值")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("威克夫分析要求 OHLC 为正数")
    if (result[["volume", "amount"]] < 0).any().any():
        raise ValueError("威克夫分析要求 volume/amount 非负")
    envelope_error = (result["high"] < result[["open", "close", "low"]].max(axis=1)) | (
        result["low"] > result[["open", "close", "high"]].min(axis=1)
    )
    if envelope_error.any():
        raise ValueError("威克夫分析要求 high/low 包络 open/close")

    result.insert(0, "symbol", symbol)
    return result.reset_index(drop=True)
