# ruff: noqa: RUF001
"""Repair Extension labels in the persisted five-day VP research checkpoints.

This script deliberately reads only existing Parquet checkpoints.  It does not
open a minute partition, rebuild a profile, or overwrite the original files.
The state is delegated to VolumeProfileEngine.extension_state_for(), which is
also the formal runtime implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from app.services.volume_profile import ExtensionState, PositionState, VolumeProfileEngine

ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = ROOT / "data" / "research" / "vp_context_random5_2026-02"
OUTPUT_DIR = ROOT / "data" / "research" / "vp_context_random5_2026-02_extension_fixed"
REPORT_PATH = ROOT / "docs" / "research" / "volume-profile" / "volume-profile-extension-fix-random5.md"
HORIZONS = (1, 3, 5, 10, 20)
EXTENSION_STATES = tuple(state.value for state in (ExtensionState.NORMAL, ExtensionState.ELEVATED, ExtensionState.EXTENDED, ExtensionState.EXTREME))


def _as_position(value: object) -> PositionState:
    try:
        return PositionState(str(value))
    except ValueError:
        return PositionState.UNAVAILABLE


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _derive_extension(frame: pd.DataFrame, profile: str) -> pd.Series:
    required = (f"{profile}_position", f"{profile}_distance_to_vah_atr", f"{profile}_distance_to_vah_pct")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{profile} cannot be repaired from persisted data; missing {missing}")
    return frame.apply(
        lambda row: VolumeProfileEngine.extension_state_for(
            position_context=_as_position(row[f"{profile}_position"]),
            distance_to_vah_atr=_optional_float(row[f"{profile}_distance_to_vah_atr"]),
            distance_to_vah_pct=_optional_float(row[f"{profile}_distance_to_vah_pct"]),
        ).value,
        axis=1,
    )


def _pct_fraction(value: float | None) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value * 100:.2f}%"


def _number(value: float | None) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.2f}"


def _markdown_table(headers: list[str], rows: Iterable[Iterable[object]]) -> str:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    output.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(output)


def _full_minute(frame: pd.DataFrame, profile: str) -> pd.DataFrame:
    return frame.loc[
        (frame[f"{profile}_quality"] == "FULL")
        & (frame[f"{profile}_data_granularity"] == "MINUTE_1M")
        & (~frame[f"{profile}_fallback_used"].fillna(True))
    ].copy()


def _pf(values: pd.Series) -> float | None:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    return gains / losses if losses else None


def _state_distribution(frame: pd.DataFrame, profile: str) -> list[list[str]]:
    extension = f"{profile}_extension_fixed"
    total = len(frame)
    rows: list[list[str]] = []
    for state in EXTENSION_STATES:
        subset = frame.loc[frame[extension] == state]
        rows.append(
            [
                profile.upper(),
                state,
                str(len(subset)),
                _pct_fraction(len(subset) / total if total else None),
                str(subset["symbol"].nunique()),
                str(subset["signal_date"].nunique()),
            ]
        )
    return rows


def _metrics(groups: Iterable[tuple[str, pd.DataFrame]]) -> str:
    rows: list[list[str]] = []
    for label, frame in groups:
        for horizon in HORIZONS:
            excess = frame[f"excess_return_{horizon}d"].dropna()
            mae = frame[f"mae_{horizon}d"].dropna()
            mfe = frame[f"mfe_{horizon}d"].dropna()
            n = len(excess)
            rows.append(
                [
                    label,
                    str(n),
                    str(frame.loc[excess.index, "symbol"].nunique()),
                    str(frame.loc[excess.index, "signal_date"].nunique()),
                    f"T+{horizon}",
                    _pct_fraction(excess.mean() if n else None),
                    _pct_fraction(excess.median() if n else None),
                    _pct_fraction((excess > 0).mean() if n else None),
                    _number(_pf(excess)),
                    _pct_fraction(mae.mean() if len(mae) else None),
                    _pct_fraction(mfe.mean() if len(mfe) else None),
                    "INSUFFICIENT" if n < 20 or frame["signal_date"].nunique() <= 2 else "",
                ]
            )
    return _markdown_table(
        ["组别", "n", "unique symbols", "unique dates", "期限", "mean excess", "median excess", "positive excess", "PF", "MAE", "MFE", "样本标记"],
        rows,
    )


def _add_rs_levels(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    percentile = result.groupby("signal_date")["rs_score"].rank(method="average", pct=True, ascending=True)
    result["rs_level"] = pd.cut(
        percentile,
        bins=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        labels=("LOW", "MID_LOW", "MID", "MID_HIGH", "HIGH"),
        include_lowest=True,
    ).astype("string")
    return result


def _extension_groups(frame: pd.DataFrame, profile: str) -> list[tuple[str, pd.DataFrame]]:
    extension = f"{profile}_extension_fixed"
    return [(f"{profile.upper()} {state}", frame.loc[frame[extension] == state]) for state in EXTENSION_STATES]


def _rs_extension_groups(frame: pd.DataFrame, profile: str) -> list[tuple[str, pd.DataFrame]]:
    extension = f"{profile}_extension_fixed"
    requested = (
        ("MID_HIGH", ExtensionState.NORMAL.value),
        ("MID_HIGH", ExtensionState.ELEVATED.value),
        ("HIGH", ExtensionState.NORMAL.value),
        ("HIGH", ExtensionState.ELEVATED.value),
        ("HIGH", ExtensionState.EXTENDED.value),
        ("HIGH", ExtensionState.EXTREME.value),
    )
    return [
        (f"{profile.upper()} RS {level} + {state}", frame.loc[(frame["rs_level"] == level) & (frame[extension] == state)])
        for level, state in requested
    ]


def main() -> None:
    source_files = sorted(INPUT_DIR.glob("signal_date=*.parquet"))
    if len(source_files) != 5:
        raise SystemExit(f"Expected five source checkpoints, found {len(source_files)} in {INPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    repaired_files: list[Path] = []
    frames: list[pd.DataFrame] = []
    for source in source_files:
        frame = pd.read_parquet(source)
        frame["vp20_extension_fixed"] = _derive_extension(frame, "vp20")
        frame["vp60_extension_fixed"] = _derive_extension(frame, "vp60")
        target = OUTPUT_DIR / source.name
        frame.to_parquet(target, index=False)
        repaired_files.append(target)
        frames.append(frame)

    all_rows = _add_rs_levels(pd.concat(frames, ignore_index=True))
    vp20 = _full_minute(all_rows, "vp20")
    vp60 = _full_minute(all_rows, "vp60")
    report = [
        "# Volume Profile Extension 修复：随机五日历史标签回填",
        "",
        "> 本报告只读取五个既有 VP Parquet，并用正式 `VolumeProfileEngine.extension_state_for()` 重新派生 Extension。没有读取分钟分区、没有重建 Histogram/POC/VAH/VAL、没有覆盖原始 Parquet 的错误 `vp*_extension` 字段。",
        "",
        "## 修复内容",
        "",
        "`VolumeProfileEngine.with_context()` 现在先写入 `position_context`，再调用 Extension 分类。分类规则与修复前完全相同：仅 `ABOVE_VAH` 才可形成上行延展；优先使用距离 VAH 的 ATR 倍数 `<=1 / <=2 / <=3 / >3` 得到 `NORMAL/ELEVATED/EXTENDED/EXTREME`；ATR 不可用时使用已冻结的 `2%/5%/8%`。",
        "",
        "`distance_to_vah_pct` 是百分数值（例如 `5.2` = 5.2%）；`distance_to_vah_atr` 是 ATR 倍数（例如 `2.5` = 2.5 ATR）。本回填只调用正式纯函数，未在脚本中复制阈值。",
        "",
        "## 数据来源与保留策略",
        "",
        "- 原始文件：`data/research/vp_context_random5_2026-02/signal_date=*.parquet`（保持不变）。",
        "- 修复文件：`data/research/vp_context_random5_2026-02_extension_fixed/signal_date=*.parquet`。",
        "- 新增列：`vp20_extension_fixed`、`vp60_extension_fixed`。旧列保留，便于审计修复影响。",
        "- 主统计仍只使用 `quality=FULL`、`data_granularity=MINUTE_1M`、`fallback_used=false`；VP20/VP60 分开。",
        "",
        "## 修复后状态分布",
        "",
        _markdown_table(["Profile", "fixed state", "n", "占比", "unique symbols", "unique dates"], [*_state_distribution(vp20, "vp20"), *_state_distribution(vp60, "vp60")]),
        "",
        "## VP20 Extension：只读未来表现",
        "",
        _metrics(_extension_groups(vp20, "vp20")),
        "",
        "**VP20 读数：PARTIALLY_SUPPORTED（风险路径，不是交易规则）。** EXTENDED 的 T+1/T+5/T+20 mean excess 为 -0.38%/-0.83%/-1.15%，且 T+20 MAE 为 -14.87%，弱于 NORMAL 的 0.16%/0.21%/0.80% 与 -10.74%。EXTREME 的 MAE 更差（T+20 -17.06%），但平均收益存在右尾，未呈现单调的收益下降，因此不能把高延展直接解释成必然下跌。",
        "",
        "## VP60 Extension：只读未来表现",
        "",
        _metrics(_extension_groups(vp60, "vp60")),
        "",
        "**VP60 读数：PARTIALLY_SUPPORTED（风险路径，不是交易规则）。** 从 NORMAL 到 EXTREME，平均 MAE 在 T+1/T+20 从 -1.77%/-10.20% 扩大到 -3.55%/-15.89%；EXTREME 的 T+20 mean/median excess 为 -0.60%/-7.66%。但 EXTENDED 在部分期限的均值较高，说明本五日没有严格单调的收益关系。",
        "",
        "## RS Strength × Extension（关键小组合）",
        "",
        "RS level 仅从保存的当日 `rs_score` 横截面派生，HIGH=80~100%、MID_HIGH=60~80%；它不是新阈值。",
        "",
        _metrics([*_rs_extension_groups(vp20, "vp20"), *_rs_extension_groups(vp60, "vp60")]),
        "",
        "**RS × Extension：INSUFFICIENT。** HIGH RS + VP20 EXTREME 仅 41 条、HIGH RS + VP60 EXTREME 为 164 条；后者 T+20 median excess 为 -7.64%、MAE 为 -16.32%，但不同期限的均值并不一致。它支持“需要继续观察风险路径”，不支持创建高 RS/高延展惩罚规则。",
        "",
        "## 结论边界",
        "",
        "1. 所有五日结果仍只有五个 signal dates，且同一股票可重复出现；n<20 或 unique dates<=2 的单元格标注 `INSUFFICIENT`。",
        "2. 本轮只修复 Extension 调用顺序并回填已有连续变量，不修改 Extension 阈值、Acceptance、Sector/RS、Wyckoff 或 `final_rank_score`。",
        "3. Extension 的研究目标是观察 MAE、MFE 与中期超额收益风险路径，不是按本样本寻找收益最高的状态。",
        "4. 本轮结果不能创建 VPScore；VP 仍为独立 Position/Risk Context。",
        "",
    ]
    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")
    print(f"repaired_files={len(repaired_files)} output={OUTPUT_DIR}")
    print(f"vp20_full={len(vp20)} vp60_full={len(vp60)} report={REPORT_PATH}")


if __name__ == "__main__":
    main()
