"""Presentation-safe Top-N and VP risk routing for Wyckoff right-side rows."""
from __future__ import annotations

from collections import Counter

RIGHT_SIDE_CANDIDATE_LIMIT = 150
RISK_ORDER = {"EXTREME": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}
EXTENSION_RISK = {"VP_NORMAL": 0, "VP_ELEVATED": 1, "VP_EXTENDED": 2, "VP_EXTREME": 3}


def risk_route(vp20: object, vp60: object, *, complete: bool) -> tuple[str, float | None]:
    """Use the frozen research mapping; never alter OpportunityScore."""
    values = (str(vp20), str(vp60))
    if not complete or any(value not in EXTENSION_RISK for value in values):
        return "UNKNOWN", None
    maximum = max(EXTENSION_RISK[value] for value in values)
    return ("LOW", "MEDIUM", "HIGH", "EXTREME")[maximum], (sum(EXTENSION_RISK[value] for value in values) / 6) * 100


def order_rows(rows: list[dict[str, object]], *, limit: int = RIGHT_SIDE_CANDIDATE_LIMIT) -> list[dict[str, object]]:
    """Top-N is opportunity-only; VP changes route display, never membership."""
    ranked = sorted(rows, key=lambda row: (-float(row.get("opportunity_score") or float("-inf")), str(row.get("symbol") or "")))[:limit]
    for index, row in enumerate(ranked, start=1):
        row["opportunity_rank"] = index
    return sorted(ranked, key=lambda row: (RISK_ORDER.get(str(row.get("vp_risk_bucket")), 4), -float(row.get("opportunity_score") or float("-inf")), str(row.get("symbol") or "")))


def industry_concentration(rows: list[dict[str, object]]) -> dict[str, dict[str, float | int]]:
    """Return Top150 SW2/SW3 concentration without changing membership/order."""
    total = len(rows)
    result: dict[str, dict[str, float | int]] = {}
    for level in ("sw2", "sw3"):
        counts = Counter(
            str(row.get(f"{level}_name"))
            for row in rows
            if str(row.get(f"{level}_name") or "").strip()
        )
        ranked = counts.most_common(3)
        result[level] = {
            "total": total,
            "missing": total - sum(counts.values()),
            "industry_count": len(counts),
            "largest_count": ranked[0][1] if ranked else 0,
            "largest_share": ranked[0][1] / total if ranked and total else 0.0,
            "top3_count": sum(count for _, count in ranked),
            "top3_share": sum(count for _, count in ranked) / total if total else 0.0,
        }
    return result
