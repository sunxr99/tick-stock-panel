"""Read-only V1 ablation research over the completed random-12 snapshots.

This deliberately does *not* replay Wyckoff, Sector/RS, or Volume Profile.
It derives research-only ranks from the immutable, per-date frozen snapshots,
writes one derived file after each date, and can resume safely after a stop.
"""

# ruff: noqa: RUF001  # Chinese report copy intentionally uses Chinese punctuation.

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5, 10, 20)
TOP_NS = (10, 20, 50)
EXTENSION_RISK = {"VP_NORMAL": 0, "VP_ELEVATED": 1, "VP_EXTENDED": 2, "VP_EXTREME": 3}
RISK_BUCKETS = ("LOW", "MEDIUM", "HIGH", "EXTREME", "UNKNOWN")
ACCEPTANCE_PRIORITY = {"NONE": 0, "ANY_A": 1, "ANY_B_OR_C": 2, "ANY_D": 3, "BOTH_D": 4}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_full(frame: pd.DataFrame, profile: str) -> pd.Series:
    return (
        frame[f"{profile}_quality"].eq("FULL")
        & frame[f"{profile}_data_granularity"].eq("MINUTE_1M")
        & ~frame[f"{profile}_fallback_used"].fillna(True)
    )


def _acceptance_context(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Return a fixed, non-numeric semantic precedence for A/B/C/D context.

    It is a lexicographic tie-break only.  It is not added to OpportunityScore,
    and it is not a selection filter.
    """
    d_by_profile: list[pd.Series] = []
    any_b_or_c = pd.Series(False, index=frame.index)
    any_a = pd.Series(False, index=frame.index)
    for profile in ("vp20", "vp60"):
        above = frame[f"{profile}_position"].eq("ABOVE_VAH")
        b = above & frame[f"{profile}_poc_state"].eq("POC_RISING")
        c = above & frame[f"{profile}_value_area_state"].eq("VALUE_AREA_RISING")
        d_by_profile.append(b & c)
        any_b_or_c |= b | c
        any_a |= above
    both_d = d_by_profile[0] & d_by_profile[1]
    any_d = d_by_profile[0] | d_by_profile[1]
    label = np.select(
        [both_d, any_d, any_b_or_c, any_a],
        ["BOTH_D", "ANY_D", "ANY_B_OR_C", "ANY_A"],
        default="NONE",
    )
    result = pd.Series(label, index=frame.index, dtype="string")
    return result, result.map(ACCEPTANCE_PRIORITY).astype("int64")


def _risk_bucket(vp20: object, vp60: object) -> str:
    values = (str(vp20), str(vp60))
    if any(value not in EXTENSION_RISK for value in values):
        return "UNKNOWN"
    # Fixed severity rule, not fitted to subsequent returns: the worst profile
    # describes the visible extension-risk context.
    maximum = max(EXTENSION_RISK[value] for value in values)
    return ("LOW", "MEDIUM", "HIGH", "EXTREME")[maximum]


def _rank(frame: pd.DataFrame, columns: list[str], ascending: list[bool]) -> pd.Series:
    order = frame.sort_values(columns, ascending=ascending, kind="stable")
    result = pd.Series(index=frame.index, dtype="int64")
    result.loc[order.index] = np.arange(1, len(frame) + 1)
    return result


def _derive(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    # The frozen random-12 snapshot predates a dedicated breadth-context
    # column. Preserve it when present and make the missing research feature
    # explicit rather than recomputing it from later information.
    if "sector_breadth_context" not in result:
        source = next((column for column in ("sector_breadth_state", "breadth_state") if column in result), None)
        result["sector_breadth_context"] = result[source] if source else pd.NA
    sector = pd.to_numeric(result["sector_score"], errors="coerce")
    rs = pd.to_numeric(result["rs_score"], errors="coerce")
    result["opportunity_score"] = 0.40 * sector + 0.60 * rs
    result["opportunity_complete"] = result["opportunity_score"].notna()
    result["acceptance_context"], result["acceptance_context_priority"] = _acceptance_context(result)
    result["vp20_risk_raw"] = result["vp20_extension_fixed"].map(EXTENSION_RISK)
    result["vp60_risk_raw"] = result["vp60_extension_fixed"].map(EXTENSION_RISK)
    result["risk_complete"] = _is_full(result, "vp20") & _is_full(result, "vp60")
    result["risk_score_raw"] = result["vp20_risk_raw"] + result["vp60_risk_raw"]
    result.loc[~result["risk_complete"], "risk_score_raw"] = np.nan
    result["risk_score"] = result["risk_score_raw"] / 6.0 * 100.0
    result["risk_bucket"] = [
        _risk_bucket(a, b) if complete else "UNKNOWN"
        for a, b, complete in zip(result["vp20_extension_fixed"], result["vp60_extension_fixed"], result["risk_complete"], strict=True)
    ]
    result["tradable_next_open_proxy"] = (
        pd.to_numeric(result["_entry_open_1d"], errors="coerce").gt(0)
        & pd.to_numeric(result["return_20d"], errors="coerce").notna()
    )
    ranked = result.loc[result["opportunity_complete"]].copy()
    ranked["_symbol_key"] = ranked["symbol"].astype(str)
    # V0: exactly frozen raw strength; phase/state/extension adjustments are excluded.
    ranked["v0_rank"] = _rank(ranked, ["opportunity_score", "_symbol_key"], [False, True])
    # V1: context-first lexicographic ablation, with no points or deletion.
    ranked["v1_rank"] = _rank(ranked, ["acceptance_context_priority", "opportunity_score", "_symbol_key"], [False, False, True])
    # V2/V3 keep risk outside the Opportunity ordering by design.
    ranked["v2_rank"] = ranked["v0_rank"]
    ranked["v3_rank"] = ranked["v1_rank"]
    # Additional requested diagnostic: pure opportunity primary, risk secondary.
    ranked["_risk_sort"] = ranked["risk_score"].fillna(float("inf"))
    ranked["v3_risk_tiebreak_rank"] = _rank(ranked, ["opportunity_score", "_risk_sort", "_symbol_key"], [False, True, True])
    for column in ("v0_rank", "v1_rank", "v2_rank", "v3_rank", "v3_risk_tiebreak_rank"):
        result[column] = pd.Series(pd.NA, index=result.index, dtype="Int64")
        result.loc[ranked.index, column] = ranked[column].astype("int64")
    return result.drop(columns=[column for column in ("_symbol_key", "_risk_sort") if column in result], errors="ignore")


def _fmt(value: object, *, pct: bool = False, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    numeric = float(value)
    if not np.isfinite(numeric):
        return "—"
    return f"{numeric * 100:.{digits}f}%" if pct else f"{numeric:.{digits}f}"


def _table(headers: list[str], rows: list[list[object]]) -> str:
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows],
    ])


def _pf(values: pd.Series) -> float | None:
    gains = values.loc[values > 0].sum()
    losses = -values.loc[values < 0].sum()
    return float(gains / losses) if losses > 0 else None


def _metrics(frame: pd.DataFrame, horizon: int) -> dict[str, object]:
    fields = [f"return_{horizon}d", f"excess_return_{horizon}d", f"mae_{horizon}d", f"mfe_{horizon}d"]
    subset = frame.dropna(subset=fields)
    excess = subset[f"excess_return_{horizon}d"]
    return {
        "n": len(subset), "symbols": subset["symbol"].nunique(), "dates": subset["signal_date"].nunique(),
        "tradable": int(subset["tradable_next_open_proxy"].sum()),
        "mean_return": subset[f"return_{horizon}d"].mean(), "median_return": subset[f"return_{horizon}d"].median(),
        "mean_excess": excess.mean(), "median_excess": excess.median(), "positive_rate": (excess > 0).mean(),
        "pf": _pf(excess), "mae": subset[f"mae_{horizon}d"].mean(), "mfe": subset[f"mfe_{horizon}d"].mean(),
        "status": "INSUFFICIENT" if len(subset) < 20 or subset["signal_date"].nunique() <= 2 else "",
    }


def _metrics_table(groups: list[tuple[str, pd.DataFrame]]) -> str:
    rows: list[list[object]] = []
    for name, frame in groups:
        for horizon in HORIZONS:
            item = _metrics(frame, horizon)
            rows.append([name, f"T+{horizon}", item["n"], item["symbols"], item["dates"], item["tradable"], _fmt(item["mean_return"], pct=True), _fmt(item["median_return"], pct=True), _fmt(item["mean_excess"], pct=True), _fmt(item["median_excess"], pct=True), _fmt(item["positive_rate"], pct=True), _fmt(item["pf"]), _fmt(item["mae"], pct=True), _fmt(item["mfe"], pct=True), item["status"]])
    return _table(["group", "horizon", "n", "unique symbols", "unique dates", "tradable proxy", "mean return", "median return", "mean excess", "median excess", "positive excess", "PF", "mean MAE", "mean MFE", "sample"], rows)


def _date_stat(frame: pd.DataFrame, horizon: int, metric: str) -> pd.Series:
    subset = frame.dropna(subset=[f"excess_return_{horizon}d", f"mae_{horizon}d", f"mfe_{horizon}d"])
    if metric == "mean_excess":
        return subset.groupby("signal_date")[f"excess_return_{horizon}d"].mean()
    if metric == "median_excess":
        return subset.groupby("signal_date")[f"excess_return_{horizon}d"].median()
    if metric == "positive_rate":
        return subset.assign(_positive=subset[f"excess_return_{horizon}d"].gt(0)).groupby("signal_date")["_positive"].mean()
    return subset.groupby("signal_date")[f"{metric}_{horizon}d"].mean()


def _comparison(left: pd.DataFrame, right: pd.DataFrame, horizon: int, metric: str, label: str) -> dict[str, object]:
    joined = pd.concat([_date_stat(left, horizon, metric).rename("left"), _date_stat(right, horizon, metric).rename("right")], axis=1, join="inner").dropna()
    diff = joined["left"] - joined["right"]
    return {"label": label, "metric": metric, "horizon": horizon, "dates": len(diff), "wins": int((diff > 0).sum()), "losses": int((diff < 0).sum()), "ties": int((diff == 0).sum()), "win_rate": (diff > 0).mean() if len(diff) else None, "mean_diff": diff.mean() if len(diff) else None, "median_diff": diff.median() if len(diff) else None}


def _comparison_table(items: list[dict[str, object]]) -> str:
    return _table(["comparison", "metric", "horizon", "matched dates", "left wins", "right wins", "ties", "left win rate", "mean difference", "median difference"], [[item["label"], item["metric"], f"T+{item['horizon']}", item["dates"], item["wins"], item["losses"], item["ties"], _fmt(item["win_rate"], pct=True), _fmt(item["mean_diff"], pct=True), _fmt(item["median_diff"], pct=True)] for item in items])


def _month_consistency(left: pd.DataFrame, right: pd.DataFrame, *, horizon: int, metric: str, label: str) -> str:
    left_dates, right_dates = _date_stat(left, horizon, metric), _date_stat(right, horizon, metric)
    joined = pd.concat([left_dates.rename("left"), right_dates.rename("right")], axis=1, join="inner").dropna()
    if joined.empty:
        return f"{label}: 无可比月份。"
    month = pd.to_datetime(joined.index).strftime("%Y-%m")
    diff = joined.assign(month=month).groupby("month").apply(lambda group: (group["left"] - group["right"]).mean(), include_groups=False)
    return f"{label}: 左组更优 {int((diff > 0).sum())}/{len(diff)} months；月份差值 {', '.join(f'{key}={_fmt(value, pct=True)}' for key, value in diff.items())}。"


def _selection(frame: pd.DataFrame, rank: str, top_n: int) -> pd.DataFrame:
    return frame.loc[frame[rank].notna() & frame[rank].le(top_n)].copy()


def _status(alpha: dict[str, object], risk: dict[str, object], *, same_selection: bool = False) -> tuple[str, str, str]:
    if same_selection:
        return "NO_INCREMENTAL_VALUE", "NO_INCREMENTAL_VALUE", "NO_INCREMENTAL_VALUE"
    if int(alpha["dates"]) <= 2 or int(risk["dates"]) <= 2:
        return "INSUFFICIENT", "INSUFFICIENT", "INSUFFICIENT"
    alpha_ok = float(alpha["mean_diff"] or 0) > 0 and float(alpha["win_rate"] or 0) >= 2 / 3
    risk_ok = float(risk["mean_diff"] or 0) > 0 and float(risk["win_rate"] or 0) >= 2 / 3
    alpha_state = "IMPROVED" if alpha_ok else "MIXED" if float(alpha["win_rate"] or 0) > 0.5 or float(alpha["mean_diff"] or 0) > 0 else "NO_INCREMENTAL_VALUE"
    risk_state = "IMPROVED" if risk_ok else "MIXED" if float(risk["win_rate"] or 0) > 0.5 or float(risk["mean_diff"] or 0) > 0 else "NO_INCREMENTAL_VALUE"
    overall = "IMPROVED" if alpha_state == risk_state == "IMPROVED" else "MIXED" if "IMPROVED" in (alpha_state, risk_state) or "MIXED" in (alpha_state, risk_state) else "NO_INCREMENTAL_VALUE"
    return overall, alpha_state, risk_state


def _right_tail_marker(frame: pd.DataFrame, horizon: int) -> str:
    item = _metrics(frame, horizon)
    if item["mean_excess"] is not None and item["median_excess"] is not None and item["mae"] is not None and item["mfe"] is not None and item["mean_excess"] > 0 and item["median_excess"] < 0 and abs(item["mfe"]) >= abs(item["mae"]):
        return "RIGHT_TAIL_DRIVEN"
    return ""


def _render_report(frame: pd.DataFrame, source_state: dict[str, Any], rank_state: dict[str, Any]) -> str:
    dates = sorted(pd.to_datetime(frame["signal_date"]).dt.strftime("%Y-%m-%d").unique())
    months = sorted(pd.to_datetime(frame["signal_date"]).dt.strftime("%Y-%m").unique())
    full20, full60 = _is_full(frame, "vp20").sum(), _is_full(frame, "vp60").sum()
    lines = ["# Right-Side Rank Research V1", "", "## 冻结输入与双维定义", "", "本研究只读取已完成的随机 12 日 `ALL_WYCKOFF + VP` snapshot；没有重放 Wyckoff、修改 Sector/RS/VP/Acceptance/Extension，或使用未来收益拟合参数。", "", _table(["item", "value"], [["random seed", source_state["selection"]["seed"]], ["signal dates", "、".join(dates)], ["months", "、".join(months)], ["observations / unique symbols", f"{len(frame)} / {frame['symbol'].nunique()}"], ["VP20 FULL / VP60 FULL", f"{full20}/{len(frame)} ({full20/len(frame):.2%}) / {full60}/{len(frame)} ({full60/len(frame):.2%})"], ["rank-research runtime", f"{rank_state.get('elapsed_seconds', 0):.2f}s"], ["raw / tradable-next-open proxy", f"{len(frame)} / {int(frame['tradable_next_open_proxy'].sum())}"]]), "", "`OpportunityScore = 0.40 × sector_score + 0.60 × rs_score`，直接复用冻结 strength 的原始构成；不使用 `research_context_score` 或任何 phase/state/extension 调整。Sector Phase、RS State、已有 sector breadth 字段若存在均仅保留为解释字段。", "", "`RiskScoreRaw = VP20ExtensionRisk + VP60ExtensionRisk`，其中 NORMAL/ELEVATED/EXTENDED/EXTREME 固定映射为 0/1/2/3，`RiskScore = Raw/6×100`。风险桶按两个 profile 的**最严重**冻结状态固定为 LOW/MEDIUM/HIGH/EXTREME；任一 profile 不是 FULL 时标记 UNKNOWN。这是展示和消融映射，不是收益优化权重。", "", "V0 以 Opportunity 排序；V1 是不加点、不删样本的 Acceptance context-first 词典序消融（BOTH_D、ANY_D、ANY_B_OR_C、ANY_A、NONE；同一 context 内再按 Opportunity）；V2 与 V0 具有相同 Opportunity 排名而单独显示 Risk；V3 与 V1 具有相同 Opportunity 排名而单独显示 Risk。另给出 `V3 risk tie-break`（Opportunity 主排序、Risk 次排序）诊断。没有 Acceptance 加分、Risk 扣分、VP 过滤或正式 Final Rank。", "", "收益口径保持 D 收盘后信号、D+1 Open 进入、T+N Close 退出。`tradable-next-open proxy` 仅验证正开盘价和 T+20 标签；它不是涨跌停/停牌/流动性的完整成交模型。", "", "## 母样本与 V0 基线", "", _metrics_table([("ALL_WYCKOFF", frame), *[(f"V0 Top{top_n}", _selection(frame, "v0_rank", top_n)) for top_n in TOP_NS]]), ""]
    v0_comparisons: list[dict[str, object]] = []
    for top_n in TOP_NS:
        selected = _selection(frame, "v0_rank", top_n)
        for horizon in HORIZONS:
            for metric in ("mean_excess", "median_excess", "positive_rate", "mae", "mfe"):
                v0_comparisons.append(_comparison(selected, frame, horizon, metric, f"V0 Top{top_n} - ALL_WYCKOFF"))
    lines.extend(["V0 相对母样本的日期等权比较：", "", _comparison_table(v0_comparisons), ""])
    for top_n in TOP_NS:
        selected = _selection(frame, "v0_rank", top_n)
        lines.append(_month_consistency(selected, frame, horizon=10, metric="mean_excess", label=f"V0 Top{top_n} vs ALL T+10 mean excess"))
        lines.append(_month_consistency(selected, frame, horizon=10, metric="mae", label=f"V0 Top{top_n} vs ALL T+10 MAE"))
    lines.append("")

    version_ranks = {"V1 Acceptance context": "v1_rank", "V2 Risk overlay": "v2_rank", "V3 Acceptance + Risk": "v3_rank", "V3 risk tie-break": "v3_risk_tiebreak_rank"}
    lines.extend(["## V0–V3 TopN 消融", "", "每张表首先给 pooled stock-date 结果；随后给日期等权差异。MAE 的正差值表示左组 MAE 更接近零、风险路径更健康。", ""])
    status_rows: list[list[object]] = []
    for top_n in TOP_NS:
        baseline = _selection(frame, "v0_rank", top_n)
        groups = [("ALL_WYCKOFF", frame), (f"V0 Top{top_n}", baseline)] + [(f"{name} Top{top_n}", _selection(frame, rank, top_n)) for name, rank in version_ranks.items()]
        lines.extend([f"### Top{top_n}", "", _metrics_table(groups), ""])
        comparisons: list[dict[str, object]] = []
        for name, rank in version_ranks.items():
            candidate = _selection(frame, rank, top_n)
            for horizon in HORIZONS:
                for metric in ("mean_excess", "median_excess", "positive_rate", "mae", "mfe"):
                    comparisons.append(_comparison(candidate, baseline, horizon, metric, f"{name} - V0"))
            alpha = _comparison(candidate, baseline, 10, "mean_excess", f"{name} - V0")
            risk = _comparison(candidate, baseline, 10, "mae", f"{name} - V0")
            same = candidate[["signal_date", "symbol"]].sort_values(["signal_date", "symbol"]).equals(baseline[["signal_date", "symbol"]].sort_values(["signal_date", "symbol"]))
            overall, alpha_state, risk_state = _status(alpha, risk, same_selection=same)
            status_rows.append([f"{name} Top{top_n}", overall, alpha_state, risk_state, "identical selection" if same else _right_tail_marker(candidate, 10) or "—"])
        lines.extend(["日期等权比较（左组 - V0）：", "", _comparison_table(comparisons), ""])
        for name, rank in version_ranks.items():
            candidate = _selection(frame, rank, top_n)
            lines.append(_month_consistency(candidate, baseline, horizon=10, metric="mean_excess", label=f"{name} vs V0 T+10 mean excess"))
            lines.append(_month_consistency(candidate, baseline, horizon=10, metric="mae", label=f"{name} vs V0 T+10 MAE"))
        lines.append("")
    lines.extend(["## 版本状态（相对 V0 同一 TopN）", "", "状态规则预先固定：T+10 mean excess 与日期胜率 ≥2/3 才标 Alpha `IMPROVED`；T+10 MAE（更接近零）与日期胜率 ≥2/3 才标 Risk `IMPROVED`。选择集合完全相同则标 `NO_INCREMENTAL_VALUE`。", "", _table(["version", "overall", "Alpha Effect", "Risk Effect", "tail / selection note"], status_rows), ""])

    top50 = _selection(frame, "v0_rank", 50)
    risk_groups = [(f"Risk {bucket}", top50.loc[top50["risk_bucket"] == bucket]) for bucket in RISK_BUCKETS]
    lines.extend(["## V2：Opportunity Top50 内的独立 Risk Overlay", "", "此节不以 Risk 重排或过滤候选；先固定 V0 Opportunity Top50，再观察风险桶。", "", _metrics_table(risk_groups), ""])
    risk_comparisons: list[dict[str, object]] = []
    low = top50.loc[top50["risk_bucket"] == "LOW"]
    for other_name in ("HIGH", "EXTREME"):
        other = top50.loc[top50["risk_bucket"] == other_name]
        for horizon in (5, 10, 20):
            for metric in ("mean_excess", "median_excess", "positive_rate", "mae", "mfe"):
                risk_comparisons.append(_comparison(low, other, horizon, metric, f"LOW - {other_name}"))
    direct_exclusion = top50.loc[~top50["risk_bucket"].eq("EXTREME")]
    for horizon in (5, 10, 20):
        for metric in ("mean_excess", "median_excess", "positive_rate", "mae", "mfe"):
            risk_comparisons.append(_comparison(direct_exclusion, top50, horizon, metric, "exclude EXTREME (no refill) - full Top50"))
    lines.extend(["日期等权比较：", "", _comparison_table(risk_comparisons), "", _month_consistency(low, top50.loc[top50["risk_bucket"] == "EXTREME"], horizon=20, metric="mae", label="LOW vs EXTREME T+20 MAE"), "", "`exclude EXTREME` 是直接移除 Top50 内 EXTREME、**不补位**的诊断，避免把筛选结构变化伪装成 Risk 的预测收益。若 mean excess 高而 median excess 为负、且 MFE 不低于 |MAE|，表内按 `RIGHT_TAIL_DRIVEN` 解释，不宣称更优。", "", _table(["group", "T+5 marker", "T+10 marker", "T+20 marker"], [[name, _right_tail_marker(group, 5) or "—", _right_tail_marker(group, 10) or "—", _right_tail_marker(group, 20) or "—"] for name, group in risk_groups]), ""])

    lines.extend(["## 研究结论与下一阶段", "", "1. **V0 TopN 区分能力：MIXED。** V0 的 pooled T+10/T+20 mean excess 高于母样本，但 Top10/20/50 的中位 excess 仍多为负，且 MAE 比母样本更深；它表现为高机会/高弹性样本，而不是已经验证的低风险 Alpha 排名。", "2. **Acceptance 增量：MIXED，不进入 Score 或 Filter。** V1 Top20 的 T+10 MAE 由 V0 的 -11.29% 改善至 -9.41%，但 mean excess 由 3.33% 降至 2.76%，Top10/50 亦不是一致改善，并有 `RIGHT_TAIL_DRIVEN` 标记。因此仍仅保留 Acceptance context，不改正式 D，也不给 B/D 配分。", "3. **VP Extension 独立 Risk Layer：保留，但在 Opportunity Top50 内是 MIXED。** EXTREME 的 T+10 mean excess/MFE 为 5.06%/19.07%，高于 LOW 的 2.26%/16.51%；LOW 的 T+10 MAE 仅以 9/12 dates 更健康，T+20 MAE 则 6/12 打平。这支持“高弹性 + 高风险”解释，不能把 Risk 当成方向预测。", "4. **Risk 是否减少 MAE：当前 Top50 证据不足以支持直接排除。** 直接排除 EXTREME（不补位）在 T+5/T+10/T+20 的平均 excess、MFE 和日期胜率均较完整 Top50 弱，T+10/T+20 MAE 也没有稳定改善；不能创建 EXTREME filter 或惩罚。", "5. **Risk 是否参与 Opportunity Rank：NO_INCREMENTAL_VALUE。** Opportunity 主排序、Risk 次排序没有改变本样本的 Top10/20/50 选择集合；V2 也按设计不改 Opportunity。Risk 应继续作为独立展示/风险维度，而非反向扣分。", "6. **Position 与双维结构：** Position 继续只作为 Context（冻结 H1 `NOT_SUPPORTED`）。OpportunityScore 与 RiskScore 应继续独立，允许同时出现高机会/高风险；Sector Phase、RS State、breadth context 也只作解释。", "7. **下一阶段候选：** 不进入正式 `final_rank_score`。若开展后续组合层研究，仅可把 `V0 Opportunity + 独立 VP Risk disclosure` 作为描述性候选，并需在完整成交/仓位框架中验证；V1/V3 Acceptance context-first 与 Risk tie-break 没有足够跨日期、跨月的稳定增量。本报告不加入 CZSC，也不进行 Portfolio Backtest。", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Right-Side Rank Research V1")
    parser.add_argument("--input-dir", type=Path, default=Path("../data/research/right_side_random12_frozen_20260913"))
    parser.add_argument("--output-dir", type=Path, default=Path("../data/research/right_side_rank_research_v1_20260913"))
    parser.add_argument("--report", type=Path, default=Path("../docs/right-side-rank-research-v1.md"))
    parser.add_argument("--rebuild", action="store_true", help="rederive research-only checkpoints; source snapshots remain read-only")
    args = parser.parse_args()
    source = args.input_dir.resolve()
    output = args.output_dir.resolve()
    report = args.report.resolve()
    source_state = _read_json(source / "progress.json")
    if source_state.get("status") != "complete":
        raise ValueError("frozen source study is not complete; preserve and complete it first")
    source_files = sorted((source / "snapshots").glob("signal_date=*.parquet"))
    expected = source_state["selected_signal_dates"]
    if len(source_files) != len(expected):
        raise ValueError(f"expected {len(expected)} source snapshots, found {len(source_files)}")
    snapshot_dir = output / "snapshots"
    state_path = output / "progress.json"
    state = _read_json(state_path) or {"status": "running", "source": str(source), "selected_signal_dates": expected, "date_runs": {}}
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    for source_file in source_files:
        key = source_file.stem.removeprefix("signal_date=")
        target = snapshot_dir / source_file.name
        if target.exists() and not args.rebuild:
            state["date_runs"].setdefault(key, {"status": "reused", "output": str(target)})
            continue
        date_started = time.perf_counter()
        try:
            derived = _derive(pd.read_parquet(source_file))
            derived.to_parquet(target, index=False)
            state["date_runs"][key] = {"status": "complete", "rows": len(derived), "elapsed_seconds": time.perf_counter() - date_started, "output": str(target)}
        except Exception as exc:
            state["date_runs"][key] = {"status": "failed", "error": str(exc), "elapsed_seconds": time.perf_counter() - date_started}
            state["status"] = "running"
            _write_json(state_path, state)
            raise
        _write_json(state_path, state)
        print(f"completed {key}: {state['date_runs'][key]['rows']} rows")
    files = sorted(snapshot_dir.glob("signal_date=*.parquet"))
    if len(files) != len(expected):
        raise ValueError("derived checkpoints incomplete; resume without deleting completed dates")
    combined = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    combined["signal_date"] = pd.to_datetime(combined["signal_date"])
    state["status"] = "complete"
    state["elapsed_seconds"] = float(state.get("elapsed_seconds", 0)) + (time.perf_counter() - started)
    _write_json(state_path, state)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(_render_report(combined, source_state, state), encoding="utf-8")
    print(f"wrote {report}")


if __name__ == "__main__":
    main()
