from app.services.right_side_candidates import (
    VP_RESEARCH_COVERAGE_LIMIT,
    industry_concentration,
    order_rows,
    risk_route,
)


def test_formal_candidate_order_keeps_every_row_and_marks_research_rank() -> None:
    rows = [
        {
            "symbol": f"000{i:03d}.SZ",
            "research_candidate_score": float(i),
            "vp_risk_bucket": "EXTREME" if i == 200 else "LOW",
        }
        for i in range(1, 202)
    ]

    ordered = order_rows(rows)

    assert VP_RESEARCH_COVERAGE_LIMIT == 150
    assert len(ordered) == 201
    assert {row["symbol"] for row in ordered} == {f"000{i:03d}.SZ" for i in range(1, 202)}
    assert ordered[0]["symbol"] == "000200.SZ"
    # Presentation groups VP risk first; the research rank itself remains the
    # score-only rank across every formal candidate.
    assert ordered[0]["research_candidate_rank"] == 2
    assert next(row for row in ordered if row["symbol"] == "000001.SZ")["research_candidate_rank"] == 201


def test_risk_route_and_group_order_are_frozen_and_stable() -> None:
    assert risk_route("VP_NORMAL", "VP_ELEVATED", position20="WITHIN_VALUE", position60="WITHIN_VALUE", complete=True) == ("MEDIUM", 16.666666666666664)
    assert risk_route("VP_EXTREME", "VP_NORMAL", position20="ABOVE_VAH", position60="WITHIN_VALUE", complete=True) == ("EXTREME", 50.0)
    assert risk_route("VP_NORMAL", "VP_NORMAL", position20="BELOW_VAL", position60="WITHIN_VALUE", complete=True) == ("HIGH", 66.66666666666666)
    assert risk_route("VP_EXTREME", "VP_NORMAL", position20="BELOW_VAL", position60="WITHIN_VALUE", complete=True) == ("EXTREME", 66.66666666666666)
    assert risk_route("VP_EXTREME", "VP_NORMAL", position20="ABOVE_VAH", position60="WITHIN_VALUE", complete=False) == ("UNKNOWN", None)

    ordered = order_rows([
        {"symbol": "B.SZ", "research_candidate_score": 90, "vp_risk_bucket": "LOW"},
        {"symbol": "C.SZ", "research_candidate_score": 80, "vp_risk_bucket": "EXTREME"},
        {"symbol": "A.SZ", "research_candidate_score": 90, "vp_risk_bucket": "LOW"},
        {"symbol": "D.SZ", "research_candidate_score": 85, "vp_risk_bucket": "HIGH"},
    ])

    assert [row["symbol"] for row in ordered] == ["C.SZ", "D.SZ", "A.SZ", "B.SZ"]
    assert [row["research_candidate_rank"] for row in ordered] == [4, 3, 1, 2]


def test_industry_concentration_is_diagnostic_only_and_counts_missing_levels() -> None:
    summary = industry_concentration([
        {"sw2_name": "电子", "sw3_name": "半导体设备"},
        {"sw2_name": "电子", "sw3_name": "半导体设备"},
        {"sw2_name": "医药", "sw3_name": "医疗服务"},
        {"sw2_name": None, "sw3_name": None},
    ])

    assert summary["sw2"] == {
        "total": 4,
        "missing": 1,
        "industry_count": 2,
        "largest_count": 2,
        "largest_share": 0.5,
        "top3_count": 3,
        "top3_share": 0.75,
    }
    assert summary["sw3"]["industry_count"] == 2
    assert summary["sw3"]["missing"] == 1
