# ruff: noqa: RUF001
"""Re-tabulate the persisted five-day VP research cohort without recomputing VP.

The input consists solely of the five existing signal_date parquet checkpoints.
It does not instantiate a repository, read minute partitions, or rerun Wyckoff.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = ROOT / "data" / "research" / "vp_context_random5_2026-02"
OUTPUT_PATH = ROOT / "docs" / "research" / "volume-profile" / "volume-profile-v1-vp-first-random5-analysis.md"
HORIZONS = (1, 3, 5, 10, 20)
LEVELS = ("LOW", "MID_LOW", "MID", "MID_HIGH", "HIGH")


@dataclass(frozen=True)
class GroupSpec:
    label: str
    frame: pd.DataFrame


def _pct(value: float | None) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value * 100:.2f}%"


def _percent_points(value: float | None) -> str:
    """Format a value already expressed as percent points by the VP DTO."""
    return "—" if value is None or not np.isfinite(value) else f"{value:.2f}%"


def _number(value: float | None) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.2f}"


def _markdown_table(headers: list[str], rows: Iterable[Iterable[object]]) -> str:
    rendered = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        rendered.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(rendered)


def _pf(values: pd.Series) -> float | None:
    positive = float(values[values > 0].sum())
    negative = float(-values[values < 0].sum())
    if negative == 0:
        return None
    return positive / negative


def _metric_rows(groups: Iterable[GroupSpec]) -> list[list[str]]:
    rows: list[list[str]] = []
    for group in groups:
        for horizon in HORIZONS:
            excess = group.frame[f"excess_return_{horizon}d"].dropna()
            mae = group.frame[f"mae_{horizon}d"].dropna()
            mfe = group.frame[f"mfe_{horizon}d"].dropna()
            n = len(excess)
            confidence = "INSUFFICIENT" if n < 20 or group.frame["signal_date"].nunique() <= 2 else ""
            rows.append(
                [
                    group.label,
                    str(n),
                    str(group.frame.loc[excess.index, "symbol"].nunique()),
                    str(group.frame.loc[excess.index, "signal_date"].nunique()),
                    f"T+{horizon}",
                    _pct(excess.mean() if n else None),
                    _pct(excess.median() if n else None),
                    _pct((excess > 0).mean() if n else None),
                    _number(_pf(excess)),
                    _pct(mae.mean() if len(mae) else None),
                    _pct(mfe.mean() if len(mfe) else None),
                    confidence,
                ]
            )
    return rows


def _metric_table(groups: Iterable[GroupSpec]) -> str:
    return _markdown_table(
        [
            "组别",
            "n",
            "unique symbols",
            "unique dates",
            "期限",
            "mean excess",
            "median excess",
            "positive excess",
            "PF",
            "MAE",
            "MFE",
            "样本标记",
        ],
        _metric_rows(groups),
    )


def _quantile_rows(frame: pd.DataFrame, profile: str, label: str) -> list[list[str]]:
    columns = (
        f"{profile}_distance_to_vah_pct",
        f"{profile}_distance_to_poc_pct",
        f"{profile}_distance_to_vah_atr",
        f"{profile}_distance_to_poc_atr",
    )
    rows: list[list[str]] = []
    for column in columns:
        value = frame[column].dropna()
        if value.empty:
            rows.append([label, column, "missing", "—", "—", "—", "—", "—", "—", "—", "—", "—"])
            continue
        quantiles = value.quantile([0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
        rows.append(
            [
                label,
                column,
                str(len(value)),
                _percent_points(value.min()) if column.endswith("pct") else _number(value.min()),
                _percent_points(quantiles.loc[0.25]) if column.endswith("pct") else _number(quantiles.loc[0.25]),
                _percent_points(quantiles.loc[0.5]) if column.endswith("pct") else _number(quantiles.loc[0.5]),
                _percent_points(quantiles.loc[0.75]) if column.endswith("pct") else _number(quantiles.loc[0.75]),
                _percent_points(quantiles.loc[0.9]) if column.endswith("pct") else _number(quantiles.loc[0.9]),
                _percent_points(quantiles.loc[0.95]) if column.endswith("pct") else _number(quantiles.loc[0.95]),
                _percent_points(quantiles.loc[0.99]) if column.endswith("pct") else _number(quantiles.loc[0.99]),
                _percent_points(value.max()) if column.endswith("pct") else _number(value.max()),
            ]
        )
    return rows


def _add_levels(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for score, output in (("rs_score", "rs_level"), ("sector_score", "sector_level")):
        # Higher frozen score is stronger.  Percentile is calculated only inside
        # the same signal date, so no cross-date information enters the bucket.
        percentile = result.groupby("signal_date")[score].rank(method="average", pct=True, ascending=True)
        result[f"{output}_percentile"] = percentile
        result[output] = pd.cut(
            percentile,
            bins=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            labels=LEVELS,
            include_lowest=True,
        ).astype("string")
    group_sizes = result.groupby("signal_date")["symbol"].transform("size")
    # Preserve the previous study's deterministic floor(30% * daily cohort) rule
    # so the preselection comparison uses its exact same cohort definition.
    result["is_sector_rs_top30"] = result["research_context_rank"] <= np.floor(group_sizes * 0.30)
    return result


def _profile_full(frame: pd.DataFrame, profile: str) -> pd.DataFrame:
    return frame.loc[
        (frame[f"{profile}_quality"] == "FULL")
        & (frame[f"{profile}_data_granularity"] == "MINUTE_1M")
        & (~frame[f"{profile}_fallback_used"].fillna(True))
    ].copy()


def _groups_by_value(frame: pd.DataFrame, column: str, prefix: str) -> list[GroupSpec]:
    return [
        GroupSpec(f"{prefix}: {value}", subset)
        for value, subset in frame.groupby(column, dropna=False, observed=True)
    ]


def _acceptance_groups(frame: pd.DataFrame, profile: str, prefix: str) -> list[GroupSpec]:
    accepted = frame.loc[frame[f"{profile}_acceptance"] == "ABOVE_VAH_ACCEPTED"]
    unaccepted = frame.loc[frame[f"{profile}_acceptance"] == "ABOVE_VAH_UNACCEPTED"]
    return [
        GroupSpec(f"{prefix}: ABOVE_VAH_ACCEPTED", accepted),
        GroupSpec(f"{prefix}: ABOVE_VAH_UNACCEPTED", unaccepted),
    ]


def _acceptance_by_level(frame: pd.DataFrame, profile: str, level: str) -> list[GroupSpec]:
    groups: list[GroupSpec] = []
    for acceptance in ("ABOVE_VAH_ACCEPTED", "ABOVE_VAH_UNACCEPTED"):
        for bucket in LEVELS:
            groups.append(
                GroupSpec(
                    f"{acceptance} × {bucket}",
                    frame.loc[(frame[f"{profile}_acceptance"] == acceptance) & (frame[level] == bucket)],
                )
            )
    return groups


def _acceptance_by_state(frame: pd.DataFrame, profile: str, state: str) -> list[GroupSpec]:
    groups: list[GroupSpec] = []
    states = sorted(str(value) for value in frame[state].dropna().unique())
    for acceptance in ("ABOVE_VAH_ACCEPTED", "ABOVE_VAH_UNACCEPTED"):
        for value in states:
            groups.append(
                GroupSpec(
                    f"{acceptance} × {value}",
                    frame.loc[(frame[f"{profile}_acceptance"] == acceptance) & (frame[state] == value)],
                )
            )
    return groups


def _component_groups(frame: pd.DataFrame, profile: str) -> list[GroupSpec]:
    above = frame[f"{profile}_position"] == "ABOVE_VAH"
    poc = frame[f"{profile}_poc_state"] == "POC_RISING"
    value_area = frame[f"{profile}_value_area_state"] == "VALUE_AREA_RISING"
    return [
        GroupSpec("A: price > VAH", frame.loc[above]),
        GroupSpec("B: A + POC_RISING", frame.loc[above & poc]),
        GroupSpec("C: A + VALUE_AREA_RISING", frame.loc[above & value_area]),
        GroupSpec("D: A + POC_RISING + VALUE_AREA_RISING", frame.loc[above & poc & value_area]),
    ]


def _field_inventory(frame: pd.DataFrame) -> str:
    requested = [
        "vp20_position", "vp20_acceptance", "vp20_poc_state", "vp20_value_area_state", "vp20_extension",
        "vp60_position", "vp60_acceptance", "vp60_poc_state", "vp60_value_area_state", "vp60_extension",
        "vp20_distance_to_poc_pct", "vp20_distance_to_vah_pct", "vp20_distance_to_poc_atr", "vp20_distance_to_vah_atr",
        "sector_score", "sector_percentile", "sector_phase", "narrowing_flag",
        "rs_score", "rs_percentile", "rs_state", "rs_change_1d", "rs_change_3d",
        "sector_score_change_1d", "sector_score_change_3d",
    ]
    found = [name for name in requested if name in frame.columns]
    missing = [name for name in requested if name not in frame.columns]
    return "\n".join(
        [
            f"- 已保存：`{', '.join(found)}`。",
            f"- 未保存：`{', '.join(missing)}`。",
            "- `sector_percentile` 与 `rs_percentile` 未落盘；本报告仅以同一 signal_date 内的冻结 score 横截面排名在内存中生成五档 level。",
            "- `narrowing_flag`、`rs_change_1d`、`rs_change_3d` 与 Sector score change 未落盘，且不能只由当前快照安全推导；因此不伪造这些分组。`rs_state` 和 `sector_phase` 仍可直接研究。",
        ]
    )


def main() -> None:
    files = sorted(INPUT_DIR.glob("signal_date=*.parquet"))
    if len(files) != 5:
        raise SystemExit(f"Expected five persisted checkpoints, found {len(files)} in {INPUT_DIR}")
    frame = pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)
    frame["signal_date"] = pd.to_datetime(frame["signal_date"]).dt.date
    frame = _add_levels(frame)
    vp20 = _profile_full(frame, "vp20")
    vp60 = _profile_full(frame, "vp60")
    top30_vp20 = vp20.loc[vp20["is_sector_rs_top30"]]
    top30_vp60 = vp60.loc[vp60["is_sector_rs_top30"]]

    position20 = _groups_by_value(vp20, "vp20_position", "VP20 Position")
    acceptance20 = _acceptance_groups(vp20, "vp20", "VP20 ALL_WYCKOFF")
    position60 = _groups_by_value(vp60, "vp60_position", "VP60 Position")
    acceptance60 = _acceptance_groups(vp60, "vp60", "VP60 ALL_WYCKOFF")
    preselect_groups = [
        *_acceptance_groups(vp20, "vp20", "VP20 ALL_WYCKOFF"),
        *_acceptance_groups(top30_vp20, "vp20", "VP20 Sector/RS Top30%"),
        *_acceptance_groups(vp60, "vp60", "VP60 ALL_WYCKOFF"),
        *_acceptance_groups(top30_vp60, "vp60", "VP60 Sector/RS Top30%"),
    ]

    sections = [
        "# Volume Profile V1：VP-first 随机五日再分析",
        "",
        "> 本报告只复用既有五个 signal-date Parquet 的 VP 结果；没有重新计算 Volume Profile、没有读取分钟分区、没有重放 Wyckoff，也没有改变任何正式评分规则。唯一改变是统计母样本从 Sector/RS Top30% 改回 ALL_WYCKOFF，再叠加 Sector/RS 分层。",
        "",
        "## 固定样本与口径",
        "",
        "- 信号日：2026-02-02、2026-02-03、2026-02-05、2026-02-10、2026-02-24。",
        "- 母样本：2,824 条 ALL_WYCKOFF 股票×signal-date 观测，1,518 个 unique symbol，5 个 signal date。",
        "- 收益：信号日收盘后产生、下一交易日开盘进入、T+N 收盘退出；超额收益 = 股票收益 - `000001.SH` 同窗口收益。",
        "- VP 主结果仅使用 `quality=FULL`、`data_granularity=MINUTE_1M`、`fallback_used=false`；VP20 与 VP60 永不合并。",
        "- `mean/median excess`、MAE、MFE 均为百分比；PF 为正超额收益总和 / 负超额收益绝对值总和。`INSUFFICIENT` 表示 n<20 或 unique signal dates<=2。",
        "",
        "## 已落盘字段审计",
        "",
        _field_inventory(frame),
        "",
        "## 读前结论",
        "",
        "- **VP20 Position：PARTIALLY_SUPPORTED（仅描述性）。** `ABOVE_VAH` 的 T+3/T+5/T+10/T+20 mean excess 为 0.34%/0.44%/2.19%/1.58%，高于 `BELOW_VAL` 的 0.04%/-0.22%/0.17%/-2.06%；但两者中位数多数为负，不能升级为入场规则。",
        "- **Acceptance：PRESELECTION_EFFECT_NOT_SUPPORTED（本五日）。** 在 ALL_WYCKOFF 中，VP20 Accepted 的 T+1/3/5/10/20 mean excess 全部低于 Unaccepted；原 Sector/RS Top30% 中方向也相同。VP60 的 ALL_WYCKOFF 方向同样一致，而 Top30% 的 Accepted 只有 17 条，仍为 INSUFFICIENT。故前 30% 预筛选会改变幅度和样本组成，但本五日没有出现“全体正向、Top30% 反向”的翻转。",
        "- **RS/Sector 成熟度：PARTIALLY_SUPPORTED。** VP20 Accepted 的 RS HIGH 组（44 条）在 T+1/3/5/10/20 均低于 MID_HIGH（48 条）；Sector HIGH 的 Accepted 组（32 条）也弱于部分中间层。但它们来自同一五日窗口，不能排除市场环境或重复股票解释。",
        "- **严格 Acceptance 是否确认过晚：PARTIALLY_SUPPORTED。** 只含 `price > VAH + POC_RISING` 的 VP20 B 组（256 条）没有复现严格 D 组（116 条）的明显弱势；但 A--D 是重叠集合，不能据此替换或放宽正式 Acceptance。",
        "- **Extension：UNAVAILABLE FOR INFERENCE。** 已落盘标签全为 `VP_NORMAL`，但这是实现顺序问题：`VolumeProfileEngine._contextualize` 在设置 `position_context` 前调用 `_extension_state`，后者因此总按非 `ABOVE_VAH` 返回 NORMAL。连续 distance 字段仍由 Profile 原始价格计算而来，可以只读展示；历史 extension 标签不能用于本报告的有效性结论。本轮未修改该实现，也未重跑 VP。",
        "",
        "## VP20：先在 ALL_WYCKOFF 做 Position 与 Acceptance 研究",
        "",
        _metric_table([*position20, *acceptance20]),
        "",
        "## VP60：先在 ALL_WYCKOFF 做 Position 与 Acceptance 研究",
        "",
        _metric_table([*position60, *acceptance60]),
        "",
        "## ALL_WYCKOFF 与 Sector/RS Top30% 的直接对照",
        "",
        "Top30% 只用于判断预筛选是否改变 VP 结论，不是新候选阈值。",
        "",
        _metric_table(preselect_groups),
        "",
        "## VP20 Acceptance × RS strength level",
        "",
        "RS level 根据同一 signal_date 内 `rs_score` 升序百分位生成：HIGH=80~100%（强），LOW=0~20%。",
        "",
        _metric_table(_acceptance_by_level(vp20, "vp20", "rs_level")),
        "",
        "## VP60 Acceptance × RS strength level",
        "",
        _metric_table(_acceptance_by_level(vp60, "vp60", "rs_level")),
        "",
        "## VP20 Acceptance × Sector strength level",
        "",
        "Sector level 同样按当日 `sector_score` 横截面生成；HIGH=80~100%（强）。",
        "",
        _metric_table(_acceptance_by_level(vp20, "vp20", "sector_level")),
        "",
        "## VP60 Acceptance × Sector strength level",
        "",
        _metric_table(_acceptance_by_level(vp60, "vp60", "sector_level")),
        "",
        "## VP20 Acceptance × RS State",
        "",
        _metric_table(_acceptance_by_state(vp20, "vp20", "rs_state")),
        "",
        "## VP20 Acceptance × Sector Phase",
        "",
        _metric_table(_acceptance_by_state(vp20, "vp20", "sector_phase")),
        "",
        "## VP20 Acceptance 条件的只读拆解",
        "",
        "A--D 是重叠的描述性集合，不是修改后的 Acceptance 规则，也不能据结果挑选较早确认条件。",
        "",
        _metric_table(_component_groups(vp20, "vp20")),
        "",
        "## VP60 Acceptance 条件的只读拆解",
        "",
        _metric_table(_component_groups(vp60, "vp60")),
        "",
        "## Extension 连续变量分布",
        "",
        "已落盘 `vp*_extension` 全为 `VP_NORMAL`，但上方“读前结论”已说明该标签当前不可用于推断。这里仅审计未依赖该标签的连续距离；这不改变 Extension 阈值。距离字段以前缀 `vp20_` 为准，且 DTO 中 pct 是百分数值（不再乘以 100）。",
        "",
        _markdown_table(
            ["样本", "字段", "n", "min", "P25", "P50", "P75", "P90", "P95", "P99", "max"],
            [
                *_quantile_rows(vp20, "vp20", "ALL_WYCKOFF / VP20 FULL"),
                *_quantile_rows(vp20.loc[vp20["rs_level"] == "HIGH"], "vp20", "RS HIGH / VP20 FULL"),
                *_quantile_rows(vp20.loc[vp20["rs_level"] == "MID_HIGH"], "vp20", "RS MID_HIGH / VP20 FULL"),
                *_quantile_rows(vp20.loc[vp20["sector_level"] == "HIGH"], "vp20", "Sector HIGH / VP20 FULL"),
            ],
        ),
        "",
        "## 结论与边界",
        "",
        "1. 本报告必须与原 Top30% 研究一起阅读；只有五个日期，不能把任何单元格的收益方向升级为 VPScore、排序加减分或交易规则。",
        "2. 对 All_Wyckoff、Top30%、不同 RS/Sector level 的 Accepted/Unaccepted 差异，仅是预筛选敏感性检查。若方向变动，同时存在市场阶段、同股重复出现和小样本效应等竞争解释。",
        "3. `rs_change_*`、`narrowing_flag` 未在本次已落盘 Parquet 中保存，故本轮不以代理变量填补，也不宣称完成 RS Change 或 NARROWING 联合检验。",
        "4. 已落盘 Extension 标签存在实现顺序缺陷，必须在单独修复、加入回归测试并重算相关历史 VP 后，才能研究其阈值或风险识别能力；本轮不处理该修复。",
        "5. 当前结论：**INSUFFICIENT**。VP 应继续保持独立 Position/Risk Context，不进入 `final_rank_score`。下一次验证应扩展独立、分钟 FULL 的信号日，并保持本报告的 VP-first 母样本设计。",
        "",
    ]
    OUTPUT_PATH.write_text("\n".join(sections), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")
    print(f"rows={len(frame)} vp20_full={len(vp20)} vp60_full={len(vp60)} top30_vp20={len(top30_vp20)}")


if __name__ == "__main__":
    main()
