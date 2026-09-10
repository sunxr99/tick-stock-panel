"""Research-only HTTP API for the standalone Wyckoff V2 backtest service."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/wyckoff/v2/backtest", tags=["wyckoff-v2-research"])


class RunRequest(BaseModel):
    start_date: date
    end_date: date
    entries: list[str] = Field(default_factory=lambda: ["spring_aggressive", "spring_standard", "spring_conservative", "lps_classic_standard", "lps_shallow_standard"])
    experiment_variants: list[str] = Field(default_factory=list)
    universe: Literal["all"] = "all"
    benchmark: Literal["all_a", "000300.SH", "none"] = "all_a"
    horizons: list[int] = Field(default_factory=lambda: [1, 3, 5, 10, 20])
    force_recompute: bool = False


def _service(request: Request):
    return request.app.state.wyckoff_v2_research_service


def _run_or_404(request: Request, run_id: str):
    run = _service(request).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Wyckoff V2 research run not found")
    return run


@router.post("/run")
def run(payload: RunRequest, request: Request):
    if payload.start_date > payload.end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")
    result = _service(request).start(payload.model_dump(mode="json"), force_recompute=payload.force_recompute)
    return {"run_id": result["run_id"], "status": result["status"], "reused": result["reused"]}


@router.get("/{run_id}")
def get_run(run_id: str, request: Request):
    run = _run_or_404(request, run_id)
    return {key: run.get(key) for key in ("run_id", "status", "progress", "started_at", "finished_at", "elapsed_seconds", "error", "engine_version", "config_hash")}


@router.get("/{run_id}/summary")
def summary(run_id: str, request: Request):
    _run_or_404(request, run_id)
    result = _service(request).summary(run_id)
    if result is None:
        raise HTTPException(status_code=409, detail="research run is not complete")
    return result


@router.get("/{run_id}/events")
def events(run_id: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    _run_or_404(request, run_id)
    items, total = _service(request).events(run_id, offset, limit)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/{run_id}/export")
def export(run_id: str, request: Request):
    _run_or_404(request, run_id)
    path = _service(request).export_path(run_id)
    if path is None:
        raise HTTPException(status_code=409, detail="research export is not ready")
    return FileResponse(path, media_type="text/csv", filename=f"wyckoff-v2-{run_id}.csv")


@router.get("/{run_id}/report")
def report(run_id: str, request: Request):
    _run_or_404(request, run_id)
    path = _service(request).report_path(run_id)
    if path is None:
        raise HTTPException(status_code=409, detail="research report is not ready")
    return FileResponse(path, media_type="text/markdown", filename=f"wyckoff-v2-{run_id}-report.md")
