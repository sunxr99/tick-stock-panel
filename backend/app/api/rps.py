"""涨幅轮动矩阵 API。

供「概念分析 → 涨幅RPS轮动」对话框调用。返回最近 N 个交易日的概念涨幅
排名矩阵:每列(日期)各自把所有概念按当天涨幅从高到低排序。
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated

import polars as pl
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import eastmoney_board_rotation, rps_rotation, sector_rotation, tdx_board_rotation
from app.services.concept_rotation_analyzer import analyze_rotation_stream
from app.services.relative_strength import build_relative_strength

router = APIRouter(prefix="/api/rps", tags=["rps"])


def _rotation_records(frame) -> list[dict]:
    """Serialize the persisted rotation facts without turning the API into a calculator."""
    if frame is None or frame.is_empty():
        return []
    return jsonable_encoder(frame.to_dicts())


@router.get("/rotation")
def get_rotation(
    request: Request,
    days: int = Query(12, ge=7, le=30, description="最近 N 个交易日(7-30)"),
    kind: str = Query("concept", pattern="concept|industry", description="维度: concept 概念 / industry 行业"),
    level: int | None = Query(None, ge=1, le=3, description="行业层级(仅 kind=industry): 1/2/3 级"),
) -> dict:
    """维度涨幅轮动矩阵(概念或行业)。

    Returns:
        dates: 日期字符串列表(最新在最前)
        columns: {日期: [[成员名, 涨幅小数], ...]} 每列各自降序
        concept_count: 去重维度成员总数
    """
    return rps_rotation.build_rps_rotation(request.app.state.repo, days, kind, level)


@router.get("/sector-strength")
def get_sector_strength(
    request: Request,
    as_of: Annotated[date | None, Query(description="Strict trading date; defaults to latest enriched date")] = None,
    kind: str = Query("concept", pattern="concept|industry", description="维度: concept 概念 / industry 行业"),
    level: int | None = Query(None, ge=1, le=3, description="行业层级(仅 kind=industry): 1/2/3 级"),
) -> dict:
    """只读返回指定交易日的冻结 Sector Strength V1.1 全量结果。

    返回行中的 ``sector_id`` 可原样作为 ``/relative-strength`` 的重复
    ``sector_id`` 查询参数。此接口不做 Top-N 截断或候选池过滤。
    """
    rows = rps_rotation.build_sector_strength(
        request.app.state.repo, kind=kind, level=level, as_of=as_of
    )
    return {
        "rows": jsonable_encoder([asdict(row) for row in rows]),
        "total": len(rows),
        "requested_as_of": as_of.isoformat() if as_of else None,
    }


@router.get("/sector-rotation/latest")
def get_sector_rotation_latest(
    request: Request,
    kind: str = Query("industry", pattern="concept|industry"),
    level: Annotated[int | None, Query(ge=1, le=3)] = 3,
) -> dict:
    """Return the latest persisted dashboard facts; never recomputes on read."""
    frame = sector_rotation.load_rotation_history(request.app.state.repo.store.data_dir, kind=kind)
    if frame.is_empty():
        return {"row_date": None, "rows": [], "total": 0}
    if kind == "concept":
        frame = frame.filter(pl.col("level").is_null())
    else:
        frame = frame.filter(pl.col("level") == (level or 3))
    if frame.is_empty():
        return {"row_date": None, "rows": [], "total": 0}
    latest = frame.get_column("date").max()
    rows = frame.filter(pl.col("date") == latest).sort("sector_score", descending=True)
    return {"row_date": latest.isoformat(), "rows": _rotation_records(rows), "total": rows.height}


@router.get("/sector-rotation/history")
def get_sector_rotation_history(
    request: Request,
    kind: str = Query("industry", pattern="concept|industry"),
    level: Annotated[int | None, Query(ge=1, le=3)] = 3,
    sector_id: str | None = Query(None),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    limit: int = Query(180, ge=1, le=1000),
) -> dict:
    """Return one persisted sector series or the recent fact rows for a dimension."""
    frame = sector_rotation.load_rotation_history(request.app.state.repo.store.data_dir, kind=kind)
    if frame.is_empty():
        return {"rows": [], "total": 0}
    frame = frame.filter(pl.col("level").is_null()) if kind == "concept" else frame.filter(pl.col("level") == (level or 3))
    if sector_id:
        frame = frame.filter(pl.col("sector_id") == sector_id)
    if start:
        frame = frame.filter(pl.col("date") >= start)
    if end:
        frame = frame.filter(pl.col("date") <= end)
    if start is None and end is None:
        frame = frame.sort("date", descending=True).head(limit)
    frame = frame.sort(["date", "sector_score"], descending=[False, True])
    return {"rows": _rotation_records(frame), "total": frame.height}


@router.get("/eastmoney-hot-rotation/latest")
def get_eastmoney_hot_rotation_latest(
    request: Request,
    category: str = Query("theme", pattern="theme|sentiment|style|all"),
) -> dict:
    """东方财富概念板块最新行情, 不与 SW/同花顺评分口径混用。"""
    frame = eastmoney_board_rotation.latest_hot_rotation(
        request.app.state.repo.store.data_dir, category=category
    )
    if frame.is_empty():
        return {"row_date": None, "rows": [], "total": 0}
    latest = frame.get_column("date").max()
    return {"row_date": latest.isoformat(), "rows": _rotation_records(frame), "total": frame.height}


@router.get("/eastmoney-hot-rotation/history")
def get_eastmoney_hot_rotation_history(
    request: Request,
    ts_code: str = Query(..., min_length=1),
    limit: int = Query(60, ge=1, le=180),
) -> dict:
    """东方财富单一概念板块的近期期序列。"""
    frame = eastmoney_board_rotation.hot_rotation_history(
        request.app.state.repo.store.data_dir, ts_code=ts_code, limit=limit
    )
    return {"rows": _rotation_records(frame), "total": frame.height}


@router.get("/eastmoney-hot-rotation/members")
def get_eastmoney_hot_rotation_members(
    request: Request,
    ts_code: Annotated[str, Query(min_length=1)],
    trade_date: Annotated[date, Query()],
) -> dict:
    """Point-in-time Eastmoney constituent relation for one concept board."""
    frame = eastmoney_board_rotation.load_hot_rotation_members(
        request.app.state.repo.store.data_dir, ts_code=ts_code, trade_date=trade_date
    )
    return {
        "trade_date": trade_date.isoformat(),
        "ts_code": ts_code.upper(),
        "rows": _rotation_records(frame),
        "total": frame.height,
    }


@router.get("/tdx-hot-rotation/latest")
def get_tdx_hot_rotation_latest(
    request: Request,
    category: str = Query("concept", pattern="concept|industry|style|all"),
) -> dict:
    """Latest TDX 88-board facts with the supplier's flat categories."""
    frame = tdx_board_rotation.latest_hot_rotation(
        request.app.state.repo.store.data_dir, category=category
    )
    if frame.is_empty():
        return {"row_date": None, "rows": [], "total": 0}
    latest = frame.get_column("date").max()
    return {"row_date": latest.isoformat(), "rows": _rotation_records(frame), "total": frame.height}


@router.get("/tdx-hot-rotation/history")
def get_tdx_hot_rotation_history(
    request: Request,
    ts_code: str = Query(..., min_length=1),
    limit: int = Query(60, ge=1, le=180),
) -> dict:
    frame = tdx_board_rotation.hot_rotation_history(
        request.app.state.repo.store.data_dir, ts_code=ts_code, limit=limit
    )
    return {"rows": _rotation_records(frame), "total": frame.height}


@router.get("/tdx-hot-rotation/members")
def get_tdx_hot_rotation_members(
    request: Request,
    ts_code: Annotated[str, Query(min_length=1)],
    trade_date: Annotated[date, Query()],
) -> dict:
    frame = tdx_board_rotation.load_hot_rotation_members(
        request.app.state.repo.store.data_dir, ts_code=ts_code, trade_date=trade_date
    )
    return {
        "trade_date": trade_date.isoformat(),
        "ts_code": ts_code.upper(),
        "rows": _rotation_records(frame),
        "total": frame.height,
    }


@router.get("/relative-strength")
def get_relative_strength(
    request: Request,
    sector_id: Annotated[list[str], Query(
        min_length=1,
        description="Repeat stable Sector Strength sector_id values; industry and concept can be mixed",
    )],
    as_of: Annotated[date | None, Query(description="Strict trading date; defaults to latest enriched date")] = None,
) -> dict:
    """只读返回指定 Sector Strength 板块范围内的个股 RS V1 结果。

    概念多归属会保留为多个 ``(symbol, sector_id)`` 结果; 没有 Top-N、
    分数阈值或任何交易信号副作用。
    """
    try:
        rows = build_relative_strength(
            request.app.state.repo, sector_ids=sector_id, as_of=as_of
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "rows": jsonable_encoder([asdict(row) for row in rows]),
        "total": len(rows),
        "requested_as_of": as_of.isoformat() if as_of else None,
        "sector_ids": sorted(set(sector_id)),
    }


class AnalyzeRequest(BaseModel):
    """AI 维度轮动分析请求(概念或行业)。"""
    days: int = 12   # 分析最近 N 个交易日
    focus: str = ""  # 用户追加的关注点
    kind: str = "concept"  # "concept" 概念 / "industry" 行业
    level: int | None = None  # 行业层级(1/2/3), 仅 kind=industry 有效


@router.post("/rotation-analyze")
async def analyze_rotation(request: Request, req: AnalyzeRequest):
    """AI 维度轮动分析 — NDJSON 流式返回。

    装配轮动矩阵信号 + 大盘背景 → 分析提示词 → 流式调用 LLM →
    逐 chunk 以 NDJSON 推给前端(每行一个 JSON)。

    协议:
      {"type":"meta","days","summary"}
      {"type":"delta","content":"..."}
      {"type":"error","message":"..."}
      {"type":"done"}
    """
    repo = request.app.state.repo
    quote_service = getattr(request.app.state, "quote_service", None)
    depth_service = getattr(request.app.state, "depth_service", None)
    days = max(7, min(30, req.days))
    kind = "industry" if req.kind == "industry" else "concept"
    level = req.level if (kind == "industry" and req.level in (1, 2, 3)) else None

    async def stream_gen():
        async for chunk in analyze_rotation_stream(
            repo, days, req.focus, quote_service, depth_service, kind, level,
        ):
            yield chunk + "\n"

    return StreamingResponse(
        stream_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
