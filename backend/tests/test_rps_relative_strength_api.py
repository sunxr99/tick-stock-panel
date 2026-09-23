from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import polars as pl
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import rps


@dataclass(frozen=True)
class _SectorRow:
    as_of: date
    sector_id: str


@dataclass(frozen=True)
class _RsRow:
    as_of: date
    symbol: str
    sector_id: str
    sector_ids: tuple[str, ...]


def _request() -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=object())))


def test_sector_strength_read_only_export_serializes_dates(monkeypatch) -> None:
    monkeypatch.setattr(
        rps.rps_rotation,
        "build_sector_strength",
        lambda repo, **kwargs: [_SectorRow(date(2026, 2, 3), "concept:all:Alpha")],
    )

    result = rps.get_sector_strength(_request(), as_of=date(2026, 2, 3), kind="concept", level=None)

    assert result == {
        "rows": [{"as_of": "2026-02-03", "sector_id": "concept:all:Alpha"}],
        "total": 1,
        "requested_as_of": "2026-02-03",
    }


def test_relative_strength_export_preserves_contexts_and_rejects_bad_ids(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _build(repo, *, sector_ids, as_of):
        seen["sector_ids"] = sector_ids
        seen["as_of"] = as_of
        return [_RsRow(
            date(2026, 2, 3),
            "AAA.SH",
            "concept:all:Alpha",
            ("concept:all:Alpha", "concept:all:Gamma"),
        )]

    monkeypatch.setattr(rps, "build_relative_strength", _build)
    result = rps.get_relative_strength(
        _request(),
        sector_id=["concept:all:Gamma", "concept:all:Alpha"],
        as_of=date(2026, 2, 3),
    )

    assert seen == {
        "sector_ids": ["concept:all:Gamma", "concept:all:Alpha"],
        "as_of": date(2026, 2, 3),
    }
    assert result["rows"][0]["sector_ids"] == ["concept:all:Alpha", "concept:all:Gamma"]
    assert result["sector_ids"] == ["concept:all:Alpha", "concept:all:Gamma"]

    monkeypatch.setattr(rps, "build_relative_strength", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("invalid sector_id")))
    with pytest.raises(HTTPException) as exc_info:
        rps.get_relative_strength(_request(), sector_id=["bad"], as_of=None)
    assert exc_info.value.status_code == 422


def test_relative_strength_http_route_accepts_repeated_sector_ids(monkeypatch) -> None:
    monkeypatch.setattr(
        rps,
        "build_relative_strength",
        lambda repo, *, sector_ids, as_of: [_RsRow(
            date(2026, 2, 3), "AAA.SH", sector_ids[0], tuple(sector_ids)
        )],
    )
    app = FastAPI()
    app.state.repo = object()
    app.include_router(rps.router)

    response = TestClient(app).get(
        "/api/rps/relative-strength",
        params=[
            ("as_of", "2026-02-03"),
            ("sector_id", "concept:all:Alpha"),
            ("sector_id", "concept:all:Gamma"),
        ],
    )

    assert response.status_code == 200
    assert response.json()["sector_ids"] == ["concept:all:Alpha", "concept:all:Gamma"]
    assert response.json()["rows"][0]["sector_ids"] == ["concept:all:Alpha", "concept:all:Gamma"]


def test_sector_rotation_latest_reads_persisted_rows_without_recomputation(monkeypatch, tmp_path) -> None:
    frame = pl.DataFrame({
        "date": [date(2026, 2, 2), date(2026, 2, 3)],
        "kind": ["industry", "industry"],
        "level": [3, 3],
        "sector_id": ["industry:3:old", "industry:3:new"],
        "sector_score": [70.0, 92.0],
    })
    seen: dict[str, object] = {}

    def _load(data_dir, *, kind=None):
        seen["data_dir"] = data_dir
        seen["kind"] = kind
        return frame

    monkeypatch.setattr(rps.sector_rotation, "load_rotation_history", _load)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        repo=SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path)),
    )))

    result = rps.get_sector_rotation_latest(request, kind="industry", level=3)

    assert seen == {"data_dir": tmp_path, "kind": "industry"}
    assert result["row_date"] == "2026-02-03"
    assert result["rows"] == [{
        "date": "2026-02-03", "kind": "industry", "level": 3,
        "sector_id": "industry:3:new", "sector_score": 92.0,
    }]


def test_eastmoney_hot_rotation_routes_serialize_persisted_facts(monkeypatch, tmp_path) -> None:
    frame = pl.DataFrame({
        "date": [date(2026, 9, 22)], "ts_code": ["BK0001.DC"], "name": ["测试概念"],
        "pct_change": [3.2], "return_5d": [8.4],
    })
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        repo=SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path)),
    )))
    monkeypatch.setattr(rps.eastmoney_board_rotation, "latest_hot_rotation", lambda data_dir, *, category: frame)
    monkeypatch.setattr(rps.eastmoney_board_rotation, "hot_rotation_history", lambda data_dir, *, ts_code, limit: frame)

    latest = rps.get_eastmoney_hot_rotation_latest(request)
    history = rps.get_eastmoney_hot_rotation_history(request, ts_code="BK0001.DC", limit=30)

    assert latest == {
        "row_date": "2026-09-22",
        "rows": [{"date": "2026-09-22", "ts_code": "BK0001.DC", "name": "测试概念", "pct_change": 3.2, "return_5d": 8.4}],
        "total": 1,
    }
    assert history["rows"] == latest["rows"]


def test_eastmoney_hot_rotation_category_is_forwarded(monkeypatch, tmp_path) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        rps.eastmoney_board_rotation,
        "latest_hot_rotation",
        lambda data_dir, *, category: seen.update({"data_dir": data_dir, "category": category}) or pl.DataFrame(),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        repo=SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path)),
    )))

    result = rps.get_eastmoney_hot_rotation_latest(request, category="sentiment")

    assert seen == {"data_dir": tmp_path, "category": "sentiment"}
    assert result == {"row_date": None, "rows": [], "total": 0}


def test_eastmoney_hot_rotation_members_route_uses_requested_point_in_time(monkeypatch, tmp_path) -> None:
    seen: dict[str, object] = {}
    frame = pl.DataFrame({"trade_date": ["20260922"], "ts_code": ["BK0001.DC"], "con_code": ["000001.SZ"], "name": ["平安银行"]})
    monkeypatch.setattr(
        rps.eastmoney_board_rotation,
        "load_hot_rotation_members",
        lambda data_dir, *, trade_date, ts_code: seen.update({"data_dir": data_dir, "trade_date": trade_date, "ts_code": ts_code}) or frame,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        repo=SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path)),
    )))

    result = rps.get_eastmoney_hot_rotation_members(request, ts_code="bk0001.dc", trade_date=date(2026, 9, 22))

    assert seen == {"data_dir": tmp_path, "trade_date": date(2026, 9, 22), "ts_code": "bk0001.dc"}
    assert result["total"] == 1
    assert result["rows"][0]["con_code"] == "000001.SZ"


def test_tdx_hot_rotation_routes_serialize_requested_category_and_members(monkeypatch, tmp_path) -> None:
    seen: dict[str, object] = {}
    frame = pl.DataFrame({"date": [date(2026, 9, 22)], "ts_code": ["880001.TDX"], "name": ["测试概念"], "category": ["concept"]})
    members = pl.DataFrame({"trade_date": ["20260922"], "ts_code": ["880001.TDX"], "con_code": ["000001.SZ"], "con_name": ["平安银行"]})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path)))))
    monkeypatch.setattr(rps.tdx_board_rotation, "latest_hot_rotation", lambda data_dir, *, category: seen.update({"category": category}) or frame)
    monkeypatch.setattr(rps.tdx_board_rotation, "hot_rotation_history", lambda data_dir, *, ts_code, limit: frame)
    monkeypatch.setattr(rps.tdx_board_rotation, "load_hot_rotation_members", lambda data_dir, *, ts_code, trade_date: members)

    latest = rps.get_tdx_hot_rotation_latest(request, category="industry")
    history = rps.get_tdx_hot_rotation_history(request, ts_code="880001.TDX", limit=10)
    result = rps.get_tdx_hot_rotation_members(request, ts_code="880001.TDX", trade_date=date(2026, 9, 22))

    assert seen == {"category": "industry"}
    assert latest["row_date"] == "2026-09-22"
    assert history["total"] == 1
    assert result["rows"][0]["con_name"] == "平安银行"
