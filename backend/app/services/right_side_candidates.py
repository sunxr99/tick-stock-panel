"""Presentation-safe Top-N and VP risk routing for Wyckoff right-side rows."""
from __future__ import annotations

from collections import Counter

VP_RESEARCH_COVERAGE_LIMIT = 150
RISK_ORDER = {"EXTREME": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}
EXTENSION_RISK = {"VP_NORMAL": 0, "VP_ELEVATED": 1, "VP_EXTENDED": 2, "VP_EXTREME": 3}
_DOWNSIDE_POSITION_RISK = 2  # HIGH: price has broken below the value area.


def risk_route(
    vp20: object,
    vp60: object,
    *,
    position20: object,
    position60: object,
    complete: bool,
) -> tuple[str, float | None]:
    """Route VP presentation risk; it never changes formal membership.

    Extension measures only upside distance above VAH.  A complete profile
    below VAL is a separate downside location, so it must not inherit the
    otherwise-normal extension state and be presented as LOW risk.
    """
    values = (str(vp20), str(vp60))
    if not complete or any(value not in EXTENSION_RISK for value in values):
        return "UNKNOWN", None
    maximum = max(EXTENSION_RISK[value] for value in values)
    extension_score = (sum(EXTENSION_RISK[value] for value in values) / 6) * 100
    if "BELOW_VAL" in (str(position20), str(position60)):
        maximum = max(maximum, _DOWNSIDE_POSITION_RISK)
        extension_score = max(extension_score, _DOWNSIDE_POSITION_RISK / 3 * 100)
    return ("LOW", "MEDIUM", "HIGH", "EXTREME")[maximum], extension_score


def order_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Order every formal row for presentation without applying a Top-N gate."""
    ranked = sorted(
        rows,
        key=lambda row: (
            -float(row.get("research_candidate_score") or float("-inf")),
            str(row.get("symbol") or ""),
        ),
    )
    for index, row in enumerate(ranked, start=1):
        row["research_candidate_rank"] = index
    return sorted(
        ranked,
        key=lambda row: (
            RISK_ORDER.get(str(row.get("vp_risk_bucket")), 4),
            -float(row.get("research_candidate_score") or float("-inf")),
            str(row.get("symbol") or ""),
        ),
    )


def industry_concentration(rows: list[dict[str, object]]) -> dict[str, dict[str, float | int]]:
    """Return formal-pool SW2/SW3 concentration without changing membership/order."""
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
