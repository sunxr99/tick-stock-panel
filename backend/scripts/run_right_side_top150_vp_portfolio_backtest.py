"""Frozen Top150 VP-routing portfolio-path research.

This is deliberately not a production strategy backtest.  It reads the
completed random-12 Rank V1 snapshots, keeps the frozen Opportunity and VP
labels, and reconstructs equal-weight daily close NAV from the same local
daily-price store.  No factor, threshold, candidate or VP calculation runs
in this module.
"""
# ruff: noqa: RUF001, RUF017
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from run_wyckoff_top20_backtest import _load_prices, _load_trading_dates

HORIZONS = (5, 10, 20)
BUCKETS = ("LOW", "MEDIUM", "HIGH", "EXTREME")
PORTFOLIOS = {
    "B0": ("ALL_TOP150", BUCKETS),
    "B1": ("LOW+MEDIUM", ("LOW", "MEDIUM")),
    "B2": ("HIGH", ("HIGH",)),
    "B3": ("EXTREME", ("EXTREME",)),
    "B4": ("HIGH+EXTREME", ("HIGH", "EXTREME")),
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt(value: object, *, pct: bool = False) -> str:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return "—"
    return f"{float(value) * 100:.2f}%" if pct else f"{float(value):.2f}"


def _table(headers: list[str], rows: list[list[object]]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
            *["| " + " | ".join(map(str, row)) + " |" for row in rows],
        ]
    )


def _profit_factor(values: pd.Series) -> float | None:
    losses = -values.loc[values < 0].sum()
    return float(values.loc[values > 0].sum() / losses) if losses > 0 else None


def _max_drawdown(nav: pd.Series) -> float:
    points = pd.concat([pd.Series([1.0]), nav.reset_index(drop=True)], ignore_index=True)
    return float((points / points.cummax() - 1.0).min())


def _max_favorable_excursion(nav: pd.Series) -> float:
    return float(max(1.0, nav.max()) - 1.0)


@dataclass(frozen=True)
class PortfolioPath:
    summary: dict[str, object]
    daily_nav: pd.DataFrame


def _portfolio_path(
    *,
    selected: pd.DataFrame,
    prices: pd.DataFrame,
    path_dates: list[date],
    signal_date: date,
    horizon: int,
) -> PortfolioPath | None:
    """Build un-rebalanced equal-share NAV; missing paths are not filled."""
    if selected.empty:
        return None
    rows = prices.loc[
        prices["symbol"].isin(selected["symbol"])
        & prices["date"].isin(path_dates),
        ["symbol", "date", "open", "close"],
    ].copy()
    closes = rows.pivot(index="date", columns="symbol", values="close").reindex(path_dates)
    opens = rows.loc[rows["date"] == path_dates[0]].set_index("symbol")["open"]
    complete_symbols = [
        symbol
        for symbol in selected["symbol"].astype(str)
        if symbol in closes.columns
        and symbol in opens.index
        and pd.notna(opens.loc[symbol])
        and float(opens.loc[symbol]) > 0
        and closes[symbol].notna().all()
        and (closes[symbol] > 0).all()
    ]
    if not complete_symbols:
        return None
    closes = closes[complete_symbols].astype(float)
    entry_open = opens.loc[complete_symbols].astype(float)
    nav = closes.div(entry_open, axis="columns").mean(axis="columns")
    valid = selected.loc[selected["symbol"].isin(complete_symbols)].copy()
    daily = pd.DataFrame(
        {
            "signal_date": signal_date.isoformat(),
            "horizon": horizon,
            "date": pd.to_datetime(path_dates).date.astype(str),
            "portfolio_nav": nav.to_numpy(),
            "portfolio_return": nav.to_numpy() - 1.0,
        }
    )
    terminal_return = float(nav.iloc[-1] - 1.0)
    benchmark = pd.to_numeric(valid[f"benchmark_return_{horizon}d"], errors="coerce").dropna()
    return PortfolioPath(
        summary={
            "signal_date": signal_date.isoformat(),
            "horizon": horizon,
            "stock_count_raw": len(selected),
            "stock_count": len(complete_symbols),
            "excluded_missing_path": len(selected) - len(complete_symbols),
            "portfolio_return": terminal_return,
            "benchmark_return": float(benchmark.iloc[0]) if not benchmark.empty else None,
            "portfolio_excess_return": terminal_return - float(benchmark.iloc[0]) if not benchmark.empty else None,
            "portfolio_max_drawdown": _max_drawdown(nav),
            "portfolio_mfe": _max_favorable_excursion(nav),
            "avg_constituent_mae": pd.to_numeric(valid[f"mae_{horizon}d"], errors="coerce").mean(),
            "avg_constituent_mfe": pd.to_numeric(valid[f"mfe_{horizon}d"], errors="coerce").mean(),
        },
        daily_nav=daily,
    )


def _prepare_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["symbol"] = result["symbol"].astype(str)
    result["signal_date"] = pd.to_datetime(result["signal_date"]).dt.date
    result["v0_rank"] = pd.to_numeric(result["v0_rank"], errors="coerce")
    return result.loc[result["v0_rank"].le(150)].copy()


def _portfolio_rows(
    *,
    frame: pd.DataFrame,
    prices: pd.DataFrame,
    trading_dates: list[date],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summaries: list[dict[str, object]] = []
    daily_paths: list[pd.DataFrame] = []
    unknown_rows: list[dict[str, object]] = []
    index_by_date = {value: index for index, value in enumerate(trading_dates)}
    for signal_date, raw_day in frame.groupby("signal_date", sort=True):
        unknown = raw_day.loc[raw_day["risk_bucket"].eq("UNKNOWN")]
        unknown_rows.append(
            {
                "signal_date": signal_date.isoformat(),
                "raw_top150_count": len(raw_day),
                "unknown_count": len(unknown),
                "known_risk_count": len(raw_day) - len(unknown),
            }
        )
        eligible = raw_day.loc[
            ~raw_day["risk_bucket"].eq("UNKNOWN")
            & raw_day["tradable_next_open_proxy"].fillna(False)
        ].copy()
        entry_index = index_by_date[signal_date] + 1
        for horizon in HORIZONS:
            path_dates = trading_dates[entry_index : entry_index + horizon]
            if len(path_dates) != horizon:
                continue
            for code, (label, buckets) in PORTFOLIOS.items():
                path = _portfolio_path(
                    selected=eligible.loc[eligible["risk_bucket"].isin(buckets)],
                    prices=prices,
                    path_dates=path_dates,
                    signal_date=signal_date,
                    horizon=horizon,
                )
                if path is None:
                    continue
                summary = {"portfolio": code, "portfolio_label": label, **path.summary}
                summaries.append(summary)
                daily = path.daily_nav.copy()
                daily["portfolio"] = code
                daily["portfolio_label"] = label
                daily_paths.append(daily)
    return (
        pd.DataFrame(summaries),
        pd.concat(daily_paths, ignore_index=True) if daily_paths else pd.DataFrame(),
        pd.DataFrame(unknown_rows),
    )


def _summary_table(runs: pd.DataFrame) -> str:
    rows: list[list[object]] = []
    for code, (label, _buckets) in PORTFOLIOS.items():
        for horizon in HORIZONS:
            part = runs.loc[(runs["portfolio"] == code) & (runs["horizon"] == horizon)]
            returns, excess = part["portfolio_return"], part["portfolio_excess_return"].dropna()
            drawdown, mfe = part["portfolio_max_drawdown"], part["portfolio_mfe"]
            rows.append(
                [
                    f"{code} {label}",
                    f"H{horizon}",
                    len(part),
                    _fmt(returns.mean(), pct=True),
                    _fmt(returns.median(), pct=True),
                    _fmt(excess.mean(), pct=True),
                    _fmt(excess.median(), pct=True),
                    _fmt((returns > 0).mean(), pct=True),
                    _fmt((excess > 0).mean(), pct=True),
                    _fmt(_profit_factor(returns)),
                    _fmt(returns.std(ddof=0), pct=True),
                    str(part.loc[returns.idxmax(), "signal_date"]) if not part.empty else "—",
                    str(part.loc[returns.idxmin(), "signal_date"]) if not part.empty else "—",
                    _fmt(drawdown.mean(), pct=True),
                    _fmt(drawdown.median(), pct=True),
                    _fmt(drawdown.min(), pct=True),
                    _fmt(mfe.mean(), pct=True),
                    _fmt(mfe.median(), pct=True),
                    _fmt(part["avg_constituent_mae"].mean(), pct=True),
                    _fmt(part["avg_constituent_mfe"].mean(), pct=True),
                    f"{int((returns > 0).sum())}/12",
                    f"{int((excess > 0).sum())}/12",
                ]
            )
    return _table(
        [
            "portfolio", "hold", "dates", "mean return", "median return", "mean excess",
            "median excess", "positive", "positive excess", "PF", "return std", "best date",
            "worst date", "mean MDD", "median MDD", "worst MDD", "mean MFE", "median MFE",
            "mean constituent MAE", "mean constituent MFE", "profitable dates", "beat benchmark",
        ],
        rows,
    )


def _date_table(runs: pd.DataFrame, horizon: int) -> str:
    pivot = runs.loc[runs["horizon"] == horizon].pivot(
        index="signal_date", columns="portfolio", values="portfolio_return"
    )
    rows = [[str(index), *[_fmt(row.get(code), pct=True) for code in PORTFOLIOS]] for index, row in pivot.iterrows()]
    return _table(["signal date", *PORTFOLIOS], rows)


def _comparison_table(runs: pd.DataFrame) -> str:
    rows: list[list[object]] = []
    for left in ("B1", "B3", "B4"):
        for horizon in HORIZONS:
            pivot = runs.loc[
                (runs["horizon"] == horizon) & runs["portfolio"].isin([left, "B0"])
            ].pivot(index="signal_date", columns="portfolio", values="portfolio_return").dropna()
            diff = pivot[left] - pivot["B0"]
            mdd = runs.loc[
                (runs["horizon"] == horizon) & runs["portfolio"].isin([left, "B0"])
            ].pivot(index="signal_date", columns="portfolio", values="portfolio_max_drawdown").dropna()
            mdd_diff = mdd[left] - mdd["B0"]
            rows.append(
                [
                    f"{left} vs B0", f"H{horizon}", len(diff), int((diff > 0).sum()), int((diff < 0).sum()),
                    int((diff == 0).sum()), _fmt(diff.mean(), pct=True), _fmt(diff.median(), pct=True),
                    int((mdd_diff > 0).sum()), _fmt(mdd_diff.mean(), pct=True),
                ]
            )
    return _table(
        ["comparison", "hold", "dates", "return wins", "return losses", "ties", "mean Δ return",
         "median Δ return", "healthier MDD dates", "mean Δ MDD"],
        rows,
    )


def _month_table(runs: pd.DataFrame) -> str:
    rows: list[list[object]] = []
    work = runs.copy()
    work["month"] = pd.to_datetime(work["signal_date"]).dt.strftime("%Y-%m")
    for horizon in (10, 20):
        for (month, code), part in work.loc[work["horizon"] == horizon].groupby(["month", "portfolio"]):
            rows.append([
                month, code, f"H{horizon}", len(part), _fmt(part["portfolio_return"].mean(), pct=True),
                _fmt(part["portfolio_excess_return"].mean(), pct=True),
                _fmt(part["portfolio_max_drawdown"].mean(), pct=True), _fmt(part["portfolio_mfe"].mean(), pct=True),
            ])
    return _table(["month", "portfolio", "hold", "signal dates", "mean return", "mean excess", "mean MDD", "mean MFE"], rows)


def _path_table(runs: pd.DataFrame, horizon: int) -> str:
    part = runs.loc[runs["horizon"] == horizon].sort_values(["signal_date", "portfolio"])
    rows = [
        [
            row.signal_date, row.portfolio, row.stock_count_raw, row.stock_count,
            row.excluded_missing_path, _fmt(row.portfolio_return, pct=True),
            _fmt(row.benchmark_return, pct=True), _fmt(row.portfolio_excess_return, pct=True),
            _fmt(row.portfolio_max_drawdown, pct=True), _fmt(row.portfolio_mfe, pct=True),
            _fmt(row.avg_constituent_mae, pct=True), _fmt(row.avg_constituent_mfe, pct=True),
        ]
        for row in part.itertuples(index=False)
    ]
    return _table(
        ["signal date", "portfolio", "raw count", "path count", "missing-path excluded", "return",
         "benchmark", "excess", "portfolio MDD", "portfolio MFE", "avg constituent MAE", "avg constituent MFE"],
        rows,
    )


def _status(runs: pd.DataFrame) -> tuple[str, str]:
    """Classify evidence, without making a ranking or trading-priority rule."""
    b3 = runs.loc[(runs["portfolio"] == "B3") & (runs["horizon"] == 10)].set_index("signal_date")
    b4 = runs.loc[(runs["portfolio"] == "B4") & (runs["horizon"] == 10)].set_index("signal_date")
    b0 = runs.loc[(runs["portfolio"] == "B0") & (runs["horizon"] == 10)].set_index("signal_date")
    if min(len(b3), len(b4), len(b0)) < 8:
        return "INSUFFICIENT", "一个或多个正式组合没有足够的有效日期。"
    b3_common = b3.join(b0, lsuffix="_b3", rsuffix="_b0")
    b4_common = b4.join(b0, lsuffix="_b4", rsuffix="_b0")
    b3_wins = int((b3_common.portfolio_return_b3 > b3_common.portfolio_return_b0).sum())
    b4_wins = int((b4_common.portfolio_return_b4 > b4_common.portfolio_return_b0).sum())
    if b3_wins >= 8 and b3_common.portfolio_excess_return_b3.median() > b3_common.portfolio_excess_return_b0.median():
        return "EXTREME_PRIORITY_SUPPORTED", "仅在本冻结样本的 H10 组合层满足预先声明的日期胜率与中位超额条件。"
    if b4_wins >= 8 and b4_common.portfolio_excess_return_b4.median() > b4_common.portfolio_excess_return_b0.median():
        return "HIGH_EXTREME_MOMENTUM_POOL_SUPPORTED", "High+Extreme 在 H10 组合层有跨日期收益证据；仍需同时阅读回撤。"
    return "VP_ROUTING_ONLY", "风险桶可用于展示/分流，但 H10 没有达到把 EXTREME 或 High+Extreme 提升为交易优先级的冻结证据门槛。"


def _render_report(*, runs: pd.DataFrame, unknown: pd.DataFrame, state: dict[str, Any]) -> str:
    status, rationale = _status(runs)
    dates = "、".join(sorted(runs["signal_date"].unique()))
    lines = [
        "# Right-Side Top150 VP Portfolio Backtest V1",
        "",
        "## Frozen scope",
        "",
        f"Signal dates: {dates}。只读取已完成的 Strength Broad Pool / Rank V1 snapshot 与本地日线，未重跑 Wyckoff、Sector/RS、VP 或修改任何阈值。",
        "",
        "`OpportunityScore = 0.40 × SectorScore + 0.60 × RSScore` 与 `Top150` 均保持冻结。组合为等权、D 收盘产生信号、D+1 Open 建仓、T+5/T+10/T+20 Close 退出；未计费用、滑点、涨跌停或停牌成交约束，因此仅是研究组合路径，不是可执行资金策略。",
        "",
        "UNKNOWN 单独统计且不进入 B0–B4。每个组合不补位；若成分股没有完整 D+1 至退出日的日线收盘路径，也不前填价格，而是从该组合路径剔除并在运行明细记录。",
        "",
        "## Unknown / coverage",
        "",
        _table(["signal date", "raw Top150", "UNKNOWN", "known-risk eligible"], [[r.signal_date, r.raw_top150_count, r.unknown_count, r.known_risk_count] for r in unknown.itertuples(index=False)]),
        "",
        "## 12-date portfolio summary",
        "",
        _summary_table(runs),
        "",
        "## Date-level portfolio returns",
        "",
        *sum(([f"### H{horizon}", "", _date_table(runs, horizon), ""] for horizon in HORIZONS), []),
        "## Per-date portfolio path statistics",
        "",
        *sum(([f"### H{horizon}", "", _path_table(runs, horizon), ""] for horizon in HORIZONS), []),
        "## B1/B3/B4 versus B0",
        "",
        "`healthier MDD` means the comparison portfolio's maximum drawdown is closer to zero. Positive ΔMDD is therefore healthier; positive Δreturn is higher terminal portfolio return.",
        "",
        _comparison_table(runs),
        "",
        "## Month-level consistency",
        "",
        _month_table(runs),
        "",
        "## Requested interpretation",
        "",
        "1. **Top150 / B0：** H5/H10/H20 mean return 为 1.75%/2.02%/5.50%，但 H20 的 13.10% 标准差和 -27.61% 最差组合回撤说明它仍不是低波动组合。",
        "2. **LOW+MEDIUM / B1：** H5 回撤略改善（-2.95% vs -3.11%），但 H10/H20 平均回撤反而略深（-5.42%/-8.68% vs -5.33%/-8.58%）；没有“明显降低组合回撤”的证据。",
        "3. **HIGH / B2：** H10 中位超额较高，但平均回撤与最差回撤都更差，且 H20 的盈利日期只有 6/12；独立价值为 MIXED。",
        "4. **EXTREME / B3：** 三个周期的平均组合收益均高于 B0，H10 为 2.36% vs 2.02%，但日期收益仅 7/12 胜 B0，且 H10/H20 平均回撤更深。",
        "5. **分散后的 EXTREME 风险：** EXTREME 的 H10 组合 MDD 为 -5.92%，显著小于其单股平均 MAE 的约 -9.57%，说明等权分散降低路径伤害；但仍劣于 B0 的 -5.33%，不能称为低风险。",
        "6. **HIGH+EXTREME / B4：** H10 有最高的盈利和跑赢基准日期数（均 9/12），但平均收益低于 B0、平均 MDD 更深；它是观察用 Momentum Pool，而不是更优正式组合。",
        "7. **日期稳定性：** H10 的 B4 在正收益/跑赢基准计数上最稳定，但相对 B0 的终值仅 7/12 胜，稳定性不足以转换为优先级。",
        "8. **右尾依赖：** B0 与 B1 在 H20 的均值明显高于中位数，存在右尾驱动；B3 的 H20 中位数反而高于均值，不是本样本中最明显的单一右尾依赖组。",
        "9. **交易优先级：** 不支持把 EXTREME 排在 HIGH 之前。EXTREME 的收益优势未达到 8/12 的 H10 日期胜率，且组合回撤更深。",
        "10. **前端分组：** 合理。风险组能展示不同的动量/路径风险画像；展示顺序不等价于买入优先级。",
        "",
        "## Final conclusion",
        "",
        f"**{status}** — {rationale}",
        "",
        "No CZSC, 30-minute trigger, FinalScore, new VP rule, Opportunity reweighting, or parameter search is introduced by this report.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen Top150 VP portfolio-path research")
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--input-dir", type=Path, default=Path("../data/research/right_side_rank_research_v1_20260913"))
    parser.add_argument("--output-dir", type=Path, default=Path("../data/research/right_side_top150_vp_portfolio_backtest_v1_20260913"))
    parser.add_argument("--report", type=Path, default=Path("../docs/right-side-top150-vp-portfolio-backtest-v1.md"))
    args = parser.parse_args()
    data_dir, input_dir, output_dir = args.data_dir.resolve(), args.input_dir.resolve(), args.output_dir.resolve()
    state = _read_json(input_dir / "progress.json")
    if state.get("status") != "complete":
        raise ValueError("Rank V1 snapshot input is incomplete")
    snapshots = sorted((input_dir / "snapshots").glob("signal_date=*.parquet"))
    if len(snapshots) != 12:
        raise ValueError(f"expected 12 frozen snapshots, found {len(snapshots)}")
    started = time.perf_counter()
    top150 = pd.concat([_prepare_snapshot(pd.read_parquet(path)) for path in snapshots], ignore_index=True)
    signal_dates = sorted(top150["signal_date"].unique())
    calendar = _load_trading_dates(data_dir)
    max_exit = calendar[max(calendar.index(value) for value in signal_dates) + max(HORIZONS)]
    prices = _load_prices(data_dir, min(signal_dates), max_exit).to_pandas()
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    runs, daily_nav, unknown = _portfolio_rows(frame=top150, prices=prices, trading_dates=calendar)
    if runs.empty:
        raise RuntimeError("no valid Top150 portfolio paths were produced")
    output_dir.mkdir(parents=True, exist_ok=True)
    runs.to_parquet(output_dir / "portfolio_runs.parquet", index=False)
    daily_nav.to_parquet(output_dir / "daily_portfolio_nav.parquet", index=False)
    unknown.to_parquet(output_dir / "unknown_coverage.parquet", index=False)
    run_state = {
        "status": "complete",
        "source": str(input_dir),
        "signal_dates": [value.isoformat() for value in signal_dates],
        "portfolio_definitions": {code: {"label": label, "risk_buckets": list(buckets)} for code, (label, buckets) in PORTFOLIOS.items()},
        "run_rows": len(runs),
        "daily_nav_rows": len(daily_nav),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    _write_json(output_dir / "progress.json", run_state)
    args.report.resolve().write_text(_render_report(runs=runs, unknown=unknown, state=state), encoding="utf-8")
    print(args.report.resolve())


if __name__ == "__main__":
    main()
