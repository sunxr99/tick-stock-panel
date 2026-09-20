"""Render the report for the frozen random-12 right-side VP study.

The input is the per-date snapshot output of
``run_right_side_random12_frozen_validation.py``.  This script is deliberately
read-only: it does not recreate a profile, alter a label, or select a result
based on subsequent returns.
"""

# ruff: noqa: RUF001  # Chinese report copy intentionally uses Chinese punctuation.

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5, 10, 20)
LEVELS = ("LOW", "MID_LOW", "MID", "MID_HIGH", "HIGH")
FULL_FILTER = "quality == 'FULL' and data_granularity == 'MINUTE_1M' and fallback_used == False"


def _fmt(value: object, *, pct: bool = False, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(numeric):
        return "—"
    if pct:
        return f"{numeric * 100:.{digits}f}%"
    return f"{numeric:.{digits}f}"


def _md_table(headers: list[str], rows: list[list[object]]) -> str:
    body = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    body.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(body)


def _profile_full(frame: pd.DataFrame, profile: str) -> pd.DataFrame:
    return frame.loc[
        (frame[f"{profile}_quality"] == "FULL")
        & (frame[f"{profile}_data_granularity"] == "MINUTE_1M")
        & (~frame[f"{profile}_fallback_used"].fillna(True))
    ].copy()


def _add_levels(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for source, target in (("rs_score", "rs_level"), ("sector_score", "sector_level")):
        rank = result.groupby("signal_date")[source].rank(method="first", pct=True)
        result[target] = pd.cut(rank, bins=[0, 0.2, 0.4, 0.6, 0.8, 1.0], labels=LEVELS, include_lowest=True)
    result["tradable_next_open_proxy"] = (
        pd.to_numeric(result["_entry_open_1d"], errors="coerce").gt(0)
        & pd.to_numeric(result["return_20d"], errors="coerce").notna()
    )
    return result


def _acceptance_states(frame: pd.DataFrame, profile: str) -> dict[str, pd.DataFrame]:
    above = frame[f"{profile}_position"].eq("ABOVE_VAH")
    poc = frame[f"{profile}_poc_state"].eq("POC_RISING")
    value = frame[f"{profile}_value_area_state"].eq("VALUE_AREA_RISING")
    return {
        "A": frame.loc[above],
        "B": frame.loc[above & poc],
        "C": frame.loc[above & value],
        "D": frame.loc[above & poc & value],
    }


def _sample_status(frame: pd.DataFrame) -> str:
    if len(frame) < 20 or frame["signal_date"].nunique() <= 2:
        return "INSUFFICIENT"
    return ""


def _pf(values: pd.Series) -> float | None:
    positive = values.loc[values > 0].sum()
    negative = -values.loc[values < 0].sum()
    if negative == 0:
        return None
    return float(positive / negative)


def _metrics(frame: pd.DataFrame, horizon: int) -> dict[str, float | int | str | None]:
    subset = frame.dropna(subset=[f"excess_return_{horizon}d", f"mae_{horizon}d", f"mfe_{horizon}d"])
    excess = subset[f"excess_return_{horizon}d"]
    return {
        "n": len(subset),
        "symbols": subset["symbol"].nunique(),
        "dates": subset["signal_date"].nunique(),
        "mean_excess": float(excess.mean()) if len(excess) else None,
        "median_excess": float(excess.median()) if len(excess) else None,
        "positive_rate": float((excess > 0).mean()) if len(excess) else None,
        "pf": _pf(excess),
        "mae": float(subset[f"mae_{horizon}d"].mean()) if len(subset) else None,
        "mfe": float(subset[f"mfe_{horizon}d"].mean()) if len(subset) else None,
        "status": _sample_status(subset),
    }


def _metric_table(groups: list[tuple[str, pd.DataFrame]]) -> str:
    rows: list[list[object]] = []
    for name, frame in groups:
        for horizon in HORIZONS:
            metrics = _metrics(frame, horizon)
            rows.append(
                [
                    name,
                    f"T+{horizon}",
                    metrics["n"],
                    metrics["symbols"],
                    metrics["dates"],
                    _fmt(metrics["mean_excess"], pct=True),
                    _fmt(metrics["median_excess"], pct=True),
                    _fmt(metrics["positive_rate"], pct=True),
                    _fmt(metrics["pf"]),
                    _fmt(metrics["mae"], pct=True),
                    _fmt(metrics["mfe"], pct=True),
                    metrics["status"],
                ]
            )
    return _md_table(
        ["group", "horizon", "n", "unique symbols", "unique dates", "mean excess", "median excess", "positive rate", "PF", "mean MAE", "mean MFE", "sample"],
        rows,
    )


def _date_stat(frame: pd.DataFrame, horizon: int, field: str) -> pd.Series:
    needed = [f"excess_return_{horizon}d", f"mae_{horizon}d", f"mfe_{horizon}d"]
    subset = frame.dropna(subset=needed)
    if field == "mean_excess":
        return subset.groupby("signal_date")[f"excess_return_{horizon}d"].mean()
    if field == "median_excess":
        return subset.groupby("signal_date")[f"excess_return_{horizon}d"].median()
    if field == "positive_rate":
        return subset.assign(_positive=subset[f"excess_return_{horizon}d"].gt(0)).groupby("signal_date")["_positive"].mean()
    if field == "mae":
        return subset.groupby("signal_date")[f"mae_{horizon}d"].mean()
    if field == "mfe":
        return subset.groupby("signal_date")[f"mfe_{horizon}d"].mean()
    raise ValueError(field)


def _date_comparison(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    horizon: int,
    field: str,
    left_label: str,
    right_label: str,
) -> dict[str, Any]:
    joined = pd.concat(
        [_date_stat(left, horizon, field).rename("left"), _date_stat(right, horizon, field).rename("right")],
        axis=1,
        join="inner",
    ).dropna()
    difference = joined["left"] - joined["right"]
    wins = int((difference > 0).sum())
    losses = int((difference < 0).sum())
    ties = int((difference == 0).sum())
    return {
        "comparison": f"{left_label} - {right_label}",
        "field": field,
        "horizon": horizon,
        "matched_dates": len(difference),
        "left_wins": wins,
        "right_wins": losses,
        "ties": ties,
        "win_rate": wins / len(difference) if len(difference) else None,
        "mean_difference": float(difference.mean()) if len(difference) else None,
        "median_difference": float(difference.median()) if len(difference) else None,
    }


def _date_comparison_table(comparisons: list[dict[str, Any]]) -> str:
    return _md_table(
        ["comparison", "metric", "horizon", "matched dates", "left wins", "right wins", "ties", "left win rate", "mean difference", "median difference"],
        [
            [
                item["comparison"],
                item["field"],
                f"T+{item['horizon']}",
                item["matched_dates"],
                item["left_wins"],
                item["right_wins"],
                item["ties"],
                _fmt(item["win_rate"], pct=True),
                _fmt(item["mean_difference"], pct=True),
                _fmt(item["median_difference"], pct=True),
            ]
            for item in comparisons
        ],
    )


def _month_direction(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    horizon: int,
    field: str,
    left_label: str,
    right_label: str,
) -> str:
    left_month = left.assign(month=left["signal_date"].dt.strftime("%Y-%m"))
    right_month = right.assign(month=right["signal_date"].dt.strftime("%Y-%m"))
    left_values = _date_stat(left_month, horizon, field).rename("left")
    right_values = _date_stat(right_month, horizon, field).rename("right")
    # First aggregate equally weighted dates inside each month, then compare months.
    left_values.index = pd.to_datetime(left_values.index)
    right_values.index = pd.to_datetime(right_values.index)
    left_by_month = left_values.groupby(left_values.index.strftime("%Y-%m")).mean()
    right_by_month = right_values.groupby(right_values.index.strftime("%Y-%m")).mean()
    joined = pd.concat([left_by_month, right_by_month], axis=1, join="inner").dropna()
    diff = joined["left"] - joined["right"]
    return (
        f"{left_label} 优于 {right_label}：{int((diff > 0).sum())}/{len(diff)} months "
        f"（T+{horizon} {field}，月内先按日期等权）。"
        if len(diff)
        else "没有同时具备两组的月份，无法评估月度一致性。"
    )


def _verdict(comparison: dict[str, Any], *, left: pd.DataFrame, right: pd.DataFrame) -> str:
    if _sample_status(left) or _sample_status(right) or comparison["matched_dates"] <= 2:
        return "INSUFFICIENT"
    if comparison["mean_difference"] is None or comparison["win_rate"] is None:
        return "INSUFFICIENT"
    if comparison["mean_difference"] > 0 and comparison["win_rate"] >= 2 / 3:
        return "SUPPORTED"
    if comparison["mean_difference"] > 0 and comparison["win_rate"] > 0.5:
        return "PARTIALLY_SUPPORTED"
    return "NOT_SUPPORTED"


def _combined_verdict(values: list[str]) -> str:
    if values and all(value == "SUPPORTED" for value in values):
        return "SUPPORTED"
    if any(value == "SUPPORTED" for value in values) or any(value == "PARTIALLY_SUPPORTED" for value in values):
        return "PARTIALLY_SUPPORTED"
    if values and all(value == "INSUFFICIENT" for value in values):
        return "INSUFFICIENT"
    return "NOT_SUPPORTED"


def _load(input_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    state = json.loads((input_dir / "progress.json").read_text(encoding="utf-8"))
    if state.get("status") != "complete":
        raise ValueError("research run is not complete; preserve checkpoints and resume the runner first")
    files = sorted((input_dir / "snapshots").glob("signal_date=*.parquet"))
    selected = state["selected_signal_dates"]
    if len(files) != len(selected):
        raise ValueError(f"expected {len(selected)} snapshots, found {len(files)}")
    frame = pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    return _add_levels(frame), state


def _append_h1(lines: list[str], frame: pd.DataFrame) -> str:
    verdicts: list[str] = []
    lines.extend(["## H1：VP Position", "", "VP20 与 VP60 分开统计；比较的是 `ABOVE_VAH` 相对 `BELOW_VAL` 的健康风险收益。状态判断同时要求 T+5 mean excess 与 T+20 mean MAE 不恶化，不能只因收益均值而忽略风险路径。", ""])
    for profile in ("vp20", "vp60"):
        full = _profile_full(frame, profile)
        groups = [(state, full.loc[full[f"{profile}_position"] == state]) for state in ("BELOW_VAL", "WITHIN_VALUE", "ABOVE_VAH")]
        comparison = _date_comparison(groups[2][1], groups[0][1], horizon=5, field="mean_excess", left_label="ABOVE_VAH", right_label="BELOW_VAL")
        risk = _date_comparison(groups[2][1], groups[0][1], horizon=20, field="mae", left_label="ABOVE_VAH", right_label="BELOW_VAL")
        date_comparisons = [
            _date_comparison(groups[2][1], groups[0][1], horizon=horizon, field=field, left_label="ABOVE_VAH", right_label="BELOW_VAL")
            for horizon in HORIZONS
            for field in ("mean_excess", "median_excess", "positive_rate", "mae", "mfe")
        ]
        reward_verdict = _verdict(comparison, left=groups[2][1], right=groups[0][1])
        risk_verdict = _verdict(risk, left=groups[2][1], right=groups[0][1])
        if "INSUFFICIENT" in (reward_verdict, risk_verdict):
            verdict = "INSUFFICIENT"
        elif risk["mean_difference"] is None or risk["mean_difference"] <= 0 or (risk["win_rate"] or 0) <= 0.5:
            verdict = "NOT_SUPPORTED"
        else:
            verdict = reward_verdict
        verdicts.append(verdict)
        lines.extend([f"### {profile.upper()}（{verdict}）", "", _metric_table(groups), "", "日期等权比较（差值为左组减右组；MAE 越高/越接近零越健康）：", "", _date_comparison_table(date_comparisons), "", _month_direction(groups[2][1], groups[0][1], horizon=5, field="mean_excess", left_label="ABOVE_VAH", right_label="BELOW_VAL"), ""])
    return _combined_verdict(verdicts)


def _append_h2(lines: list[str], frame: pd.DataFrame) -> str:
    verdicts: list[str] = []
    lines.extend(["## H2：Acceptance Timing", "", "A/B/C/D 均是冻结研究状态；D 仍是正式 Acceptance，本节不改变它。", ""])
    for profile in ("vp20", "vp60"):
        groups = _acceptance_states(_profile_full(frame, profile), profile)
        comparisons = [
            _date_comparison(groups["B"], groups["D"], horizon=horizon, field=field, left_label="B", right_label="D")
            for horizon in (3, 5, 10)
            for field in ("median_excess", "positive_rate", "mae", "mfe")
        ]
        primary = _date_comparison(groups["B"], groups["D"], horizon=5, field="median_excess", left_label="B", right_label="D")
        verdict = _verdict(primary, left=groups["B"], right=groups["D"])
        verdicts.append(verdict)
        lines.extend([f"### {profile.upper()}（{verdict}）", "", _metric_table(list(groups.items())), "", "B vs D 日期等权比较：", "", _date_comparison_table(comparisons), "", _month_direction(groups["B"], groups["D"], horizon=5, field="median_excess", left_label="B", right_label="D"), ""])
    return _combined_verdict(verdicts)


def _append_h3(lines: list[str], frame: pd.DataFrame) -> str:
    verdicts: list[str] = []
    lines.extend(["## H3：Strength Maturity", "", "五档由每个 signal date 内的完整 ALL_WYCKOFF 横截面固定派生；不按本轮收益重新切分。", ""])
    for profile in ("vp20", "vp60"):
        full = _profile_full(frame, profile)
        states = _acceptance_states(full, profile)
        comparisons: list[dict[str, Any]] = []
        groups: list[tuple[str, pd.DataFrame]] = []
        for label, source in (("RS", full), ("Sector", full), ("RS + B", states["B"]), ("RS + D", states["D"]), ("Sector + B", states["B"])):
            column = "sector_level" if label.startswith("Sector") else "rs_level"
            mid_high = source.loc[source[column].astype(str) == "MID_HIGH"]
            high = source.loc[source[column].astype(str) == "HIGH"]
            groups.extend([(f"{label} MID_HIGH", mid_high), (f"{label} HIGH", high)])
            comparisons.append(_date_comparison(mid_high, high, horizon=10, field="mean_excess", left_label=f"{label} MID_HIGH", right_label=f"{label} HIGH"))
            comparisons.append(_date_comparison(mid_high, high, horizon=10, field="mae", left_label=f"{label} MID_HIGH", right_label=f"{label} HIGH"))
        primary = comparisons[0]
        verdict = _verdict(primary, left=groups[0][1], right=groups[1][1])
        verdicts.append(verdict)
        lines.extend([f"### {profile.upper()}（RS MID_HIGH vs HIGH：{verdict}）", "", _metric_table(groups), "", "日期等权比较：", "", _date_comparison_table(comparisons), "", _month_direction(groups[0][1], groups[1][1], horizon=10, field="mean_excess", left_label="RS MID_HIGH", right_label="RS HIGH"), ""])
    return _combined_verdict(verdicts)


def _append_h4(lines: list[str], frame: pd.DataFrame) -> str:
    verdicts: list[str] = []
    lines.extend(["## H4：Extension Risk", "", "使用 snapshot 中由正式 `extension_state_for()` 纯函数重派生的 `*_extension_fixed`；不读取或相信修复前的旧标签。", ""])
    for profile in ("vp20", "vp60"):
        full = _profile_full(frame, profile)
        column = f"{profile}_extension_fixed"
        groups = [(state, full.loc[full[column] == state]) for state in ("VP_NORMAL", "VP_ELEVATED", "VP_EXTENDED", "VP_EXTREME")]
        normal, extended, extreme = groups[0][1], groups[2][1], groups[3][1]
        comparisons = [
            _date_comparison(normal, extreme, horizon=horizon, field=field, left_label="NORMAL", right_label="EXTREME")
            for horizon in HORIZONS
            for field in ("mean_excess", "mae", "median_excess", "positive_rate", "mfe")
        ] + [
            _date_comparison(normal, extended, horizon=horizon, field=field, left_label="NORMAL", right_label="EXTENDED")
            for horizon in HORIZONS
            for field in ("mean_excess", "mae", "median_excess", "positive_rate", "mfe")
        ]
        primary = _date_comparison(normal, extreme, horizon=20, field="mae", left_label="NORMAL", right_label="EXTREME")
        verdict = _verdict(primary, left=normal, right=extreme)
        verdicts.append(verdict)
        high_extreme = full.loc[(full["rs_level"].astype(str) == "HIGH") & (full[column] == "VP_EXTREME")]
        lines.extend([f"### {profile.upper()}（{verdict}）", "", _metric_table([*groups, ("RS HIGH + VP_EXTREME", high_extreme)]), "", "日期等权比较（NORMAL - EXTREME 为正，表示 EXTREME 的该风险收益指标更差；MAE 主比较）：", "", _date_comparison_table(comparisons), "", _month_direction(normal, extreme, horizon=20, field="mae", left_label="NORMAL", right_label="EXTREME"), ""])
    return _combined_verdict(verdicts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze frozen random-12 right-side validation snapshots")
    parser.add_argument("--input-dir", type=Path, default=Path("../data/research/right_side_random12_frozen_20260913"))
    parser.add_argument("--output", type=Path, default=Path("../docs/right-side-random12-frozen-validation.md"))
    args = parser.parse_args()

    frame, state = _load(args.input_dir.resolve())
    date_runs = state["date_runs"]
    elapsed = float(state.get("elapsed_seconds") or sum(item.get("elapsed_seconds", 0) for item in date_runs.values()))
    vp20_full = len(_profile_full(frame, "vp20"))
    vp60_full = len(_profile_full(frame, "vp60"))
    raw = len(frame)
    tradable = int(frame["tradable_next_open_proxy"].sum())
    lines = [
        "# Right-Side 随机 12 日冻结验证",
        "",
        "## 冻结与样本",
        "",
        "本报告只读取逐日期落盘的完整 `ALL_WYCKOFF` snapshot。Wyckoff、Sector Strength、RS、VP bin/窗口/POC/VA、Acceptance、Extension 阈值、基准与 next-open 收益口径均未在本轮修改。",
        "",
        _md_table(
            ["item", "value"],
            [
                ["random seed", state["selection"]["seed"]],
                ["actual signal dates", "、".join(state["selected_signal_dates"])],
                ["date coverage", "、".join(state["selection"]["eligible_months"])],
                ["month stratification", state["selection"]["selection_method"] + f"；extra months: {', '.join(state['selection']['extra_months']) or 'none'}"],
                ["total observations", raw],
                ["unique symbols", frame["symbol"].nunique()],
                ["VP20 FULL rate", f"{vp20_full}/{raw} ({vp20_full / raw:.2%})"],
                ["VP60 FULL rate", f"{vp60_full}/{raw} ({vp60_full / raw:.2%})"],
                ["total runtime", f"{elapsed:.2f}s"],
                ["average per signal date", f"{elapsed / len(state['selected_signal_dates']):.2f}s"],
                ["run failure dates", state.get("failure_count", 0)],
                ["raw / tradable-next-open proxy", f"{raw} / {tradable}"],
            ],
        ),
        "",
        "收益口径是 D 收盘形成信号、D+1 open 假定进入、T+N close 退出；stock / benchmark / excess、MAE、MFE 均保存在 snapshot。`tradable_next_open_proxy` 仅确认 D+1 有正开盘价且 T+20 标签完整；当前冻结基础设施没有涨跌停、停牌或盘口成交可行性的完整历史模拟，因此它不是完整的可交易性判定，组合回测阶段需补齐。",
        "",
        "逐日运行明细：",
        "",
        _md_table(["signal date", "seconds", "candidates", "VP20 FULL", "VP60 FULL", "VP20 not FULL", "VP60 not FULL", "failures"], [[key, value.get("elapsed_seconds"), value.get("candidates"), value.get("vp20_full"), value.get("vp60_full"), value.get("vp20_not_full"), value.get("vp60_not_full"), value.get("failure_count")] for key, value in sorted(date_runs.items())]),
        "",
        "表内 `INSUFFICIENT` 表示该 horizon 的 n<20 或 unique dates<=2。日期比较先在每个 signal date 内等权聚合，随后比较各日期；只有两个组同日存在时，该日才进入比较分母。",
        "",
    ]
    h1 = _append_h1(lines, frame)
    h2 = _append_h2(lines, frame)
    h3 = _append_h3(lines, frame)
    h4 = _append_h4(lines, frame)
    lines.extend([
        "## 最终冻结结论",
        "",
        _md_table(["hypothesis", "status"], [["H1 Position", h1], ["H2 Acceptance Timing", h2], ["H3 Strength Maturity", h3], ["H4 Extension Risk", h4]]),
        "",
        "## 进入 Right-Side Final Rank 下一阶段的候选结论",
        "",
        "本报告仅提供冻结验证证据。即使某个关系被标记为 `SUPPORTED`，它也只是进入下一阶段、更严格的候选研究条件，而不是创建 VPScore、Final Rank、RightSideRank、惩罚规则或 TopN 组合回测的授权。本轮不改变任何正式 Acceptance 或 Extension 规则。",
        "",
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":  # pragma: no cover - command-line entrypoint
    main()
