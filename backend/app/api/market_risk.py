"""大盘风险快照 API; 只读取已持久化的日终计算结果。"""
from __future__ import annotations

from datetime import date
from typing import Annotated

import polars as pl
from fastapi import APIRouter, HTTPException, Query, Request

from app.services import market_risk

router = APIRouter(prefix="/api/market-risk", tags=["market-risk"])


def _data_dir(request: Request):
    return request.app.state.repo.store.data_dir


def _records(frame: pl.DataFrame) -> list[dict]:
    if frame.is_empty():
        return []
    rows = frame.to_dicts()
    for row in rows:
        if row.get("date") is not None:
            row["date"] = str(row["date"])
    return rows


@router.get("/history")
def history(
    request: Request,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 60,
):
    """查询指定区间, 或默认最近 ``limit`` 个已计算交易日。"""
    frame = market_risk.load_market_risk_history(_data_dir(request))
    if frame.is_empty():
        return {"rows": [], "total": 0}
    if start is not None:
        frame = frame.filter(pl.col("date") >= start)
    if end is not None:
        frame = frame.filter(pl.col("date") <= end)
    if start is None and end is None:
        frame = frame.sort("date", descending=True).head(limit)
    frame = frame.sort("date")
    return {"rows": _records(frame), "total": frame.height}


@router.get("/latest")
def latest(request: Request):
    """读取最近一个已计算交易日; 没有快照时明确返回空。"""
    frame = market_risk.load_market_risk_history(_data_dir(request))
    if frame.is_empty():
        return {"row": None}
    rows = _records(frame.sort("date", descending=True).head(1))
    return {"row": rows[0] if rows else None}


@router.get("/date/{as_of}")
def by_date(request: Request, as_of: date):
    """读取一个指定交易日; 未计算不临时补算, 避免查询请求触发重计算。"""
    frame = market_risk.load_market_risk_history(_data_dir(request))
    if frame.is_empty():
        return {"row": None}
    rows = _records(frame.filter(pl.col("date") == as_of).head(1))
    return {"row": rows[0] if rows else None}


@router.get("/coverage")
def coverage(request: Request):
    return market_risk.get_market_risk_coverage(_data_dir(request))


@router.post("/recompute")
def recompute(request: Request, start: date | None = None, end: date | None = None):
    """手动覆盖计算一个历史区间; 需要明确起止日, 避免误触发全量扫描。"""
    if start is None or end is None:
        raise HTTPException(status_code=422, detail="start 和 end 为必填交易日")
    if start > end:
        raise HTTPException(status_code=422, detail="start 不能晚于 end")
    data_dir = _data_dir(request)
    previous = market_risk.load_market_risk_history(data_dir)
    rows = market_risk.build_market_risk_rows(data_dir, start, end, previous=previous)
    if not rows.is_empty():
        market_risk.upsert_market_risk_history(data_dir, rows)
    return {"ok": True, "computed": rows.height if not rows.is_empty() else 0}
