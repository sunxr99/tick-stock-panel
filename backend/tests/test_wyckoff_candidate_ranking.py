from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import wyckoff_candidate_ranking

_AS_OF = date(2026, 7, 20)
_SECTOR_ID = "industry:1:Technology"


def _sector(
    score: float,
    phase: str | None,
    extension: str = "NORMAL",
    *,
    complete: bool = True,
    level: int = 1,
    name: str = "Technology",
):
    return SimpleNamespace(
        sector_id=f"industry:{level}:{name}",
        score=score,
        percentile=80.0,
        phase=phase,
        extension_state=extension,
        data_quality={"state_missing_components": [] if complete else ["extension_score"]},
    )


def _rs(
    symbol: str,
    score: float,
    state: str | None,
    extension: str = "NORMAL",
    *,
    complete: bool = True,
    level: int = 1,
    name: str = "Technology",
    market_rs: float = 90.0,
    sector_rs: float | None = None,
):
    return SimpleNamespace(
        symbol=symbol,
        sector_id=f"industry:{level}:{name}",
        sector_level=level,
        rs_score=score,
        market_rs_score=market_rs,
        sector_rs_score=score if sector_rs is None else sector_rs,
        rs_state=state,
        rs_extension_state=extension,
        data_quality={"state_missing_components": [] if complete else ["rs_change_3d"]},
    )


def _rank(monkeypatch, sector, rs_rows, candidates):
    monkeypatch.setattr(
        wyckoff_candidate_ranking, "build_sector_strength", lambda *_args, **_kwargs: [sector]
    )
    monkeypatch.setattr(
        wyckoff_candidate_ranking, "build_relative_strength", lambda *_args, **_kwargs: rs_rows
    )
    return wyckoff_candidate_ranking.rank_wyckoff_candidates(
        object(), as_of=_AS_OF, candidates=candidates
    )


def test_healthy_accelerating_candidate_outranks_exhausted_falling_candidate(monkeypatch) -> None:
    healthy_sector = _sector(82.0, "ACCELERATING")
    healthy_sector.sector_id = "industry:1:Healthy"
    risky_sector = _sector(96.0, "EXHAUSTED", "EXTREME")
    risky_sector.sector_id = "industry:1:Risky"
    healthy_rs = _rs("HEALTHY.SH", 88.0, "HIGH_AND_RISING")
    healthy_rs.sector_id = healthy_sector.sector_id
    risky_rs = _rs("RISKY.SH", 98.0, "HIGH_AND_FALLING", "EXTREME")
    risky_rs.sector_id = risky_sector.sector_id
    monkeypatch.setattr(
        wyckoff_candidate_ranking,
        "build_sector_strength",
        lambda *_args, **_kwargs: [healthy_sector, risky_sector],
    )
    monkeypatch.setattr(
        wyckoff_candidate_ranking,
        "build_relative_strength",
        lambda *_args, **_kwargs: [healthy_rs, risky_rs],
    )
    ranked = wyckoff_candidate_ranking.rank_wyckoff_candidates(
        object(),
        as_of=_AS_OF,
        candidates=[
            {"symbol": "RISKY.SH", "score": 999.0},
            {"symbol": "HEALTHY.SH", "score": -999.0},
        ],
    )
    healthy, risky = ranked

    assert healthy["final_rank_score"] == pytest.approx(105.6)
    assert risky["final_rank_score"] == pytest.approx(61.2)
    assert healthy["final_rank_score"] > risky["final_rank_score"]
    assert healthy["priority_level"] == "PRIORITY_A"
    assert risky["priority_level"] == "PRIORITY_C"


def test_extension_penalties_and_priority_rules_are_explicit(monkeypatch) -> None:
    row = _rank(
        monkeypatch,
        _sector(80.0, "LEADING", "ELEVATED"),
        [_rs("AAA.SH", 90.0, "HIGH_AND_FLAT", "EXTENDED")],
        [{"symbol": "AAA.SH"}],
    )[0]

    assert row["strength_score"] == pytest.approx(86.0)
    assert row["sector_phase_adjustment"] == 5.0
    assert row["rs_state_adjustment"] == 3.0
    assert row["sector_extension_penalty"] == 2.0
    assert row["rs_extension_penalty"] == 6.0
    assert row["final_rank_score"] == pytest.approx(86.0)
    assert row["priority_level"] == "PRIORITY_B"
    assert row["risk_reasons"] == ["sector_extension_elevated", "rs_extension_extended"]


def test_sort_tie_breakers_and_wyckoff_czsc_fields_do_not_affect_ranking(monkeypatch) -> None:
    sector = _sector(80.0, "LEADING")
    ranked = _rank(
        monkeypatch,
        sector,
        [
            _rs("AAA.SH", 90.0, "HIGH_AND_FLAT"),
            _rs("BBB.SH", 88.0, "HIGH_AND_FLAT"),
        ],
        [
            {"symbol": "BBB.SH", "score": 10_000.0, "wyckoff_v2_events": ["SOS"], "czsc_buy_types": ["一买"]},
            {"symbol": "AAA.SH", "score": -10_000.0, "wyckoff_v2_events": [], "czsc_buy_types": []},
        ],
    )

    assert [row["symbol"] for row in ranked] == ["AAA.SH", "BBB.SH"]
    assert [row["rank"] for row in ranked] == [1, 2]
    assert ranked[0]["final_rank_score"] > ranked[1]["final_rank_score"]


def test_missing_dynamic_or_sector_rs_data_is_unknown_and_after_normal_candidates(monkeypatch) -> None:
    complete = _rank(
        monkeypatch,
        _sector(80.0, "LEADING"),
        [_rs("GOOD.SH", 90.0, "HIGH_AND_FLAT")],
        [{"symbol": "GOOD.SH"}, {"symbol": "MISSING.SH"}],
    )
    by_symbol = {row["symbol"]: row for row in complete}

    assert by_symbol["GOOD.SH"]["ranking_status"] == "partial"
    assert by_symbol["GOOD.SH"]["priority_level"] == "PRIORITY_B"
    assert by_symbol["MISSING.SH"]["priority_level"] == "UNKNOWN"
    assert by_symbol["MISSING.SH"]["final_rank_score"] is None
    assert by_symbol["GOOD.SH"]["rank"] < by_symbol["MISSING.SH"]["rank"]


def test_sw2_sw3_v2_uses_frozen_weights_and_preserves_legacy(monkeypatch) -> None:
    sectors = {
        1: [_sector(60.0, "LEADING", level=1, name="SW1")],
        2: [_sector(80.0, "LEADING", level=2, name="SW2")],
        3: [_sector(90.0, "LEADING", level=3, name="SW3")],
    }
    rs_rows = [
        _rs("AAA.SH", 70.0, "HIGH_AND_FLAT", level=1, name="SW1", market_rs=80.0, sector_rs=70.0),
        _rs("AAA.SH", 0.0, "HIGH_AND_FLAT", level=2, name="SW2", market_rs=80.0, sector_rs=60.0),
        _rs("AAA.SH", 0.0, "HIGH_AND_FLAT", level=3, name="SW3", market_rs=80.0, sector_rs=50.0),
    ]
    monkeypatch.setattr(
        wyckoff_candidate_ranking,
        "build_sector_strength",
        lambda *_args, **kwargs: sectors[kwargs["level"]],
    )
    monkeypatch.setattr(
        wyckoff_candidate_ranking,
        "build_relative_strength",
        lambda *_args, **_kwargs: rs_rows,
    )

    row = wyckoff_candidate_ranking.rank_wyckoff_candidates(
        object(), as_of=_AS_OF, candidates=[{"symbol": "AAA.SH"}]
    )[0]

    assert row["sector_score_legacy"] == 60.0
    assert row["rs_score_legacy"] == 70.0
    assert row["opportunity_score_legacy"] == pytest.approx(66.0)
    assert row["sector_score_v2"] == pytest.approx(83.0)
    assert row["rs_score_v2"] == pytest.approx(66.0)
    assert row["opportunity_score_v2"] == pytest.approx(72.8)
    assert row["sector_score"] == 60.0
    assert row["rs_score"] == 70.0
    assert row["strength_score"] == pytest.approx(66.0)
    assert row["opportunity_score_basis"] == "sw2_sw3"
    assert row["sw2_available"] is True
    assert row["sw3_available"] is True


def test_sw3_missing_uses_explicit_sw2_only_basis(monkeypatch) -> None:
    sectors = {
        1: [_sector(60.0, "LEADING", level=1, name="SW1")],
        2: [_sector(80.0, "LEADING", level=2, name="SW2")],
        3: [],
    }
    rs_rows = [
        _rs("AAA.SH", 70.0, "HIGH_AND_FLAT", level=1, name="SW1", market_rs=80.0, sector_rs=70.0),
        _rs("AAA.SH", 0.0, "HIGH_AND_FLAT", level=2, name="SW2", market_rs=80.0, sector_rs=60.0),
    ]
    monkeypatch.setattr(wyckoff_candidate_ranking, "build_sector_strength", lambda *_args, **kwargs: sectors[kwargs["level"]])
    monkeypatch.setattr(wyckoff_candidate_ranking, "build_relative_strength", lambda *_args, **_kwargs: rs_rows)

    row = wyckoff_candidate_ranking.rank_wyckoff_candidates(
        object(), as_of=_AS_OF, candidates=[{"symbol": "AAA.SH"}]
    )[0]

    assert row["sector_score_v2"] == 80.0
    assert row["rs_score_v2"] == 70.0
    assert row["opportunity_score_v2"] == pytest.approx(74.0)
    assert row["opportunity_score_basis"] == "sw2_only_missing_sw3"
    assert row["sw2_available"] is True
    assert row["sw3_available"] is False


def test_research_gate_fails_closed_when_sw3_is_unavailable(monkeypatch) -> None:
    sectors = {
        1: [_sector(60.0, "LEADING", level=1, name="SW1")],
        2: [_sector(80.0, "LEADING", level=2, name="SW2")],
        3: [],
    }
    rs_rows = [
        _rs("AAA.SH", 70.0, "HIGH_AND_FLAT", level=1, name="SW1", market_rs=80.0, sector_rs=70.0),
        _rs("AAA.SH", 0.0, "HIGH_AND_FLAT", level=2, name="SW2", market_rs=80.0, sector_rs=60.0),
    ]
    monkeypatch.setattr(wyckoff_candidate_ranking, "build_sector_strength", lambda *_args, **_kwargs: sectors[_kwargs["level"]])
    monkeypatch.setattr(wyckoff_candidate_ranking, "build_relative_strength", lambda *_args, **_kwargs: rs_rows)

    row = wyckoff_candidate_ranking.rank_wyckoff_candidates(
        object(),
        as_of=_AS_OF,
        candidates=[{"symbol": "AAA.SH"}],
        _min_industry_members=8,
        _require_full_v2_levels=True,
    )[0]

    assert row["opportunity_score_v2"] is None
    assert row["opportunity_score_basis"] == "insufficient_members"
