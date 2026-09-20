from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

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
