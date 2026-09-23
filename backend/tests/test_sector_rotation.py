"""板块轮动日指标的持久化与口径测试。"""
from __future__ import annotations

import time
from datetime import date, timedelta
from types import SimpleNamespace

import polars as pl

from app.services import rps_rotation, sector_rotation
from app.services.sector_membership import append_membership_history


def _repo(tmp_path, rows: list[dict]) -> SimpleNamespace:
    frame = pl.DataFrame(rows).with_columns(pl.col("date").cast(pl.Date))
    return SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        _enriched_history_cache=frame,
        get_enriched_range=lambda start, end, columns=None: frame.filter(
            (pl.col("date") >= start) & (pl.col("date") <= end)
        ).select(columns or frame.columns),
    )


def _rows(days: list[date]) -> list[dict]:
    rows: list[dict] = []
    for index, current in enumerate(days):
        rows.extend([
            {"symbol": "A.SH", "date": current, "change_pct": 0.02, "close": 10 + index, "amount": 100.0 + index},
            {"symbol": "B.SH", "date": current, "change_pct": 0.01, "close": 20 + index, "amount": 80.0 + index},
            {"symbol": "C.SZ", "date": current, "change_pct": -0.01, "close": 30 - index, "amount": 50.0},
            {"symbol": "D.SZ", "date": current, "change_pct": -0.02, "close": 40 - index, "amount": 40.0},
        ])
    return rows


def _concept_snapshot(tmp_path, as_of: date) -> None:
    rows = pl.DataFrame({
        "symbol": ["A.SH", "B.SH", "C.SZ", "D.SZ"],
        "kind": ["concept"] * 4,
        "sector": ["强概念", "强概念", "弱概念", "弱概念"],
        "effective_from": [as_of] * 4,
        "effective_to": [None] * 4,
        "membership_as_of": [as_of] * 4,
        "source": ["test"] * 4,
        "taxonomy_version": ["test"] * 4,
    }).with_columns(
        pl.col("effective_from").cast(pl.Date),
        pl.col("membership_as_of").cast(pl.Date),
        pl.col("effective_to").cast(pl.Date),
    )
    append_membership_history(tmp_path, rows)


def test_build_concept_day_uses_exact_membership_snapshot_and_cross_section_scores(tmp_path):
    days = [date(2026, 1, 2) + timedelta(days=index) for index in range(70)]
    repo = _repo(tmp_path, _rows(days))
    _concept_snapshot(tmp_path, days[-1])

    out = sector_rotation.build_rotation_day(repo, kind="concept", as_of=days[-1])

    assert out.height == 2
    strong = out.filter(pl.col("name") == "强概念").to_dicts()[0]
    weak = out.filter(pl.col("name") == "弱概念").to_dicts()[0]
    assert strong["membership_as_of"] == days[-1]
    assert strong["sector_score"] > weak["sector_score"]
    assert strong["rs20_score"] > weak["rs20_score"]
    assert strong["data_status"] == "complete"
    assert strong["score_delta_1d"] is None


def test_concept_day_fails_closed_without_same_day_snapshot(tmp_path):
    days = [date(2026, 1, 2) + timedelta(days=index) for index in range(70)]
    repo = _repo(tmp_path, _rows(days))
    _concept_snapshot(tmp_path, days[-2])

    out = sector_rotation.build_rotation_day(repo, kind="concept", as_of=days[-1])

    assert out.is_empty()


def test_upsert_replaces_same_kind_and_day_and_later_delta_is_readable(tmp_path):
    days = [date(2026, 1, 2) + timedelta(days=index) for index in range(70)]
    repo = _repo(tmp_path, _rows(days))
    for current in days[-2:]:
        _concept_snapshot(tmp_path, current)

    first = sector_rotation.build_rotation_day(repo, kind="concept", as_of=days[-2])
    sector_rotation.upsert_rotation_history(tmp_path, first)
    second = sector_rotation.build_rotation_day(repo, kind="concept", as_of=days[-1])
    sector_rotation.upsert_rotation_history(tmp_path, second)
    sector_rotation.upsert_rotation_history(tmp_path, second)

    stored = sector_rotation.load_rotation_history(tmp_path, kind="concept")
    assert stored.filter(pl.col("date") == days[-1]).height == 2
    assert stored.filter(pl.col("date") == days[-1]).get_column("score_delta_1d").drop_nulls().len() == 2


def test_upsert_accepts_industry_then_null_level_concept_for_same_day(tmp_path):
    """The normal pipeline writes SW3 before concepts on each trading day."""
    days = [date(2026, 1, 2) + timedelta(days=index) for index in range(70)]
    repo = _repo(tmp_path, _rows(days))
    _concept_snapshot(tmp_path, days[-1])
    concept = sector_rotation.build_rotation_day(repo, kind="concept", as_of=days[-1])
    industry = concept.with_columns(
        pl.lit("industry").alias("kind"),
        pl.lit(3).cast(pl.Int64).alias("level"),
    )

    sector_rotation.upsert_rotation_history(tmp_path, industry)
    sector_rotation.upsert_rotation_history(tmp_path, concept)

    stored = sector_rotation.load_rotation_history(tmp_path)
    assert stored.schema["level"] == pl.Int64
    assert stored.filter(pl.col("kind") == "industry").height == industry.height
    assert stored.filter(pl.col("kind") == "concept").height == concept.height


def test_current_concept_member_map_remains_dataframe_on_cache_hit(monkeypatch, tmp_path):
    """Daily snapshot capture must not unpack a cached DataFrame into Series."""
    cached = pl.DataFrame({"_sym_up": ["A.SH"], "concept": ["测试概念"]})
    monkeypatch.setitem(rps_rotation._map_cache, "concept", cached)
    monkeypatch.setitem(rps_rotation._map_ts, "concept", time.time())

    out = rps_rotation.load_current_member_map(
        SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path)), "concept"
    )

    assert isinstance(out, pl.DataFrame)
    assert out.columns == ["_sym_up", "concept"]
