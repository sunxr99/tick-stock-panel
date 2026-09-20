from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import polars as pl

from app.services import wyckoff_research_snapshot
from app.services.sector_membership import resolve_history


def _repo(tmp_path, latest: date):
    return SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        _enriched_history_cache=pl.DataFrame({"date": [latest]}),
    )


def test_capture_wyckoff_research_snapshot_persists_latest_context_and_membership(monkeypatch, tmp_path):
    as_of = date(2026, 9, 12)
    maps = {
        "industry": pl.DataFrame({"_sym_up": ["000001.SZ"], "industry": ["银行"]}),
        "concept": pl.DataFrame({"_sym_up": ["000001.SZ"], "concept": ["金融科技"]}),
    }
    monkeypatch.setattr(
        wyckoff_research_snapshot, "load_current_member_map", lambda _repo, kind: maps[kind]
    )

    status = wyckoff_research_snapshot.capture_wyckoff_research_snapshot(
        _repo(tmp_path, as_of),
        as_of=as_of,
        rows=[{
            "symbol": "000001.SZ",
            "candidate_order": 1,
            "research_context_score": 73.5,
            "sector_context": {"score": 60.0},
            "rs_context": {"rs_score": 82.5},
        }],
    )

    assert status["status"] == "captured"
    snapshot_path = tmp_path / status["path"]
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["research_only"] is True
    assert payload["as_of"] == "2026-09-12"
    assert payload["rows"][0]["research_context_score"] == 73.5
    assert payload["membership"]["captured_rows"] == {"industry": 1, "concept": 1}
    industry = resolve_history(tmp_path, kind="industry", as_of=as_of)
    assert industry is not None
    assert industry.membership_as_of == as_of
    assert industry.frame.to_dicts() == [{"_sym_up": "000001.SZ", "industry": "银行"}]


def test_capture_wyckoff_research_snapshot_never_backfills_current_membership(monkeypatch, tmp_path):
    latest = date(2026, 9, 12)
    monkeypatch.setattr(
        wyckoff_research_snapshot,
        "load_current_member_map",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not load historical membership")),
    )

    status = wyckoff_research_snapshot.capture_wyckoff_research_snapshot(
        _repo(tmp_path, latest), as_of=date(2024, 1, 2), rows=[]
    )

    assert status["status"] == "skipped_nonlatest_as_of"
    assert not (tmp_path / "research_snapshots").exists()
    assert resolve_history(tmp_path, kind="industry", as_of=latest) is None


def test_daily_concept_capture_uses_the_completed_enriched_date(monkeypatch, tmp_path):
    from app.jobs import daily_pipeline

    as_of = date(2026, 9, 18)
    captured: dict[str, object] = {}
    repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        latest_enriched_date=lambda: as_of,
    )

    def _capture(received_repo, *, as_of, kinds):
        captured.update({"repo": received_repo, "as_of": as_of, "kinds": kinds})
        return {"status": "captured", "as_of": as_of.isoformat(), "membership_rows": {"concept": 2}}

    monkeypatch.setattr(
        wyckoff_research_snapshot, "capture_current_membership_snapshots", _capture
    )

    result = daily_pipeline._capture_daily_concept_membership_snapshot(
        repo, expected_as_of=as_of
    )

    assert captured == {"repo": repo, "as_of": as_of, "kinds": ("concept",)}
    assert result["membership_rows"] == {"concept": 2}


def test_daily_concept_capture_skips_without_completed_enriched_date(tmp_path):
    from app.jobs import daily_pipeline

    repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        latest_enriched_date=lambda: None,
    )

    assert daily_pipeline._capture_daily_concept_membership_snapshot(
        repo, expected_as_of=date(2026, 9, 18)
    ) == {
        "status": "skipped_missing_enriched_date"
    }


def test_daily_concept_capture_never_labels_current_membership_as_an_old_date(tmp_path):
    from app.jobs import daily_pipeline

    repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        latest_enriched_date=lambda: date(2026, 9, 17),
    )

    assert daily_pipeline._capture_daily_concept_membership_snapshot(
        repo, expected_as_of=date(2026, 9, 18)
    ) == {
        "status": "skipped_stale_enriched_date",
        "latest_enriched_date": "2026-09-17",
        "expected_as_of": "2026-09-18",
    }
