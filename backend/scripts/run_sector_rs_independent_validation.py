"""Frozen, read-only independent validation for Sector Strength and Stock RS.

The default signal period is calendar year 2024, before the 2026 development
work.  It deliberately uses level-1 industry membership only, so concept
multi-membership cannot inflate the validation sample.
"""
# ruff: noqa: RUF001
from __future__ import annotations

import argparse
import math
from array import array
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import polars as pl

from app.services import regime_builder, relative_strength, rps_rotation

HORIZONS = (1, 3, 5, 10, 20)
SIGNAL_START = date(2024, 1, 2)
SIGNAL_END = date(2024, 12, 2)
STRONG_PERCENTILE = 70.0
MIN_REGIME_SAMPLE = 200


class ReadOnlyRepo:
    """Minimal repository adapter over a bounded, already-loaded enriched panel."""

    def __init__(self, frame: pl.DataFrame, data_dir: Path) -> None:
        self._enriched_history_cache = frame
        self.store = SimpleNamespace(data_dir=data_dir)

    def get_enriched_range(self, start, end, symbols=None, columns=None):
        frame = self._enriched_history_cache.filter(pl.col("date").is_between(start, end))
        if symbols is not None:
            frame = frame.filter(pl.col("symbol").is_in(symbols))
        if columns:
            existing = [column for column in columns if column in frame.columns]
            if "symbol" not in existing:
                existing.insert(0, "symbol")
            if "date" not in existing:
                existing.insert(1, "date")
            frame = frame.select(existing)
        return frame.sort(["symbol", "date"])


@dataclass
class Stats:
    """Exact sample statistics; arrays are compact to keep one-year panels bounded."""

    keep_returns: bool
    returns: array = field(default_factory=lambda: array("d"))
    excess: array = field(default_factory=lambda: array("d"))
    n: int = 0
    return_sum: float = 0.0
    excess_sum: float = 0.0
    positive_return_count: int = 0
    positive_excess_count: int = 0
    mae_sum: float = 0.0
    mfe_sum: float = 0.0
    positive_excess_sum: float = 0.0
    negative_excess_abs_sum: float = 0.0

    def add(self, forward_return: float, excess: float, mae: float, mfe: float) -> None:
        self.n += 1
        self.return_sum += forward_return
        self.excess_sum += excess
        self.positive_return_count += forward_return > 0
        self.positive_excess_count += excess > 0
        self.mae_sum += mae
        self.mfe_sum += mfe
        self.positive_excess_sum += max(excess, 0.0)
        self.negative_excess_abs_sum += abs(min(excess, 0.0))
        self.excess.append(excess)
        if self.keep_returns:
            self.returns.append(forward_return)

    def summary(self, distribution: bool = False) -> dict[str, float | int | None]:
        if not self.n:
            return {"n": 0}
        excess_values = np.frombuffer(self.excess, dtype=np.float64)
        return_values = np.frombuffer(self.returns, dtype=np.float64) if self.returns else None
        result: dict[str, float | int | None] = {
            "n": self.n,
            "mean_return": self.return_sum / self.n,
            "median_return": float(np.median(return_values)) if return_values is not None else None,
            "mean_excess": self.excess_sum / self.n,
            "median_excess": float(np.median(excess_values)),
            "positive_return_rate": self.positive_return_count / self.n,
            "positive_excess_rate": self.positive_excess_count / self.n,
            "mae": self.mae_sum / self.n,
            "mfe": self.mfe_sum / self.n,
            "profit_factor": (
                self.positive_excess_sum / self.negative_excess_abs_sum
                if self.negative_excess_abs_sum else None
            ),
        }
        if distribution and return_values is not None:
            std = float(np.std(excess_values, ddof=1)) if self.n > 1 else 0.0
            skew = (
                float(np.mean(((excess_values - np.mean(excess_values)) / std) ** 3))
                if self.n > 2 and std > 0 else None
            )
            positive_gross = float(np.clip(return_values, 0.0, None).sum())
            ordered = np.sort(return_values)[::-1]

            def winner_share(fraction: float) -> float | None:
                if positive_gross <= 0:
                    return None
                count = max(1, math.ceil(self.n * fraction))
                return float(np.clip(ordered[:count], 0.0, None).sum()) / positive_gross

            result.update({
                "p10": float(np.quantile(return_values, 0.10)),
                "p25": float(np.quantile(return_values, 0.25)),
                "p75": float(np.quantile(return_values, 0.75)),
                "p90": float(np.quantile(return_values, 0.90)),
                "skewness": skew,
                "top5_winner_contribution": winner_share(0.05),
                "top10_winner_contribution": winner_share(0.10),
            })
        return result


def _tier(percentile: float | None) -> str | None:
    if percentile is None:
        return None
    if percentile >= 90.0:
        return "Top 10%"
    if percentile >= 70.0:
        return "10%-30%"
    if percentile >= 50.0:
        return "30%-50%"
    return "Bottom 50%"


def _stats_bucket(store, *parts: str, keep_returns: bool) -> Stats:
    key = tuple(parts)
    if key not in store:
        store[key] = Stats(keep_returns=keep_returns)
    return store[key]


def _forward_metrics(matrix: np.ndarray, index: int, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Next-session-through-T+h return and close-to-close MAE/MFE, no intraday proxy."""
    changes = matrix[index + 1:index + horizon + 1]
    complete = np.isfinite(changes).all(axis=0)
    cumulative = np.cumprod(1.0 + changes, axis=0) - 1.0
    forward = np.where(complete, cumulative[-1], np.nan)
    mae = np.where(complete, np.min(cumulative, axis=0), np.nan)
    mfe = np.where(complete, np.max(cumulative, axis=0), np.nan)
    return forward, mae, mfe


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def _num(value: float | int | None) -> str:
    return "—" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


def _load_panel(data_dir: Path, signal_start: date, signal_end: date) -> tuple[pl.DataFrame, list[date], list[date]]:
    glob = str(data_dir / "kline_daily_enriched" / "**" / "*.parquet")
    all_dates = pl.scan_parquet(glob).select("date").unique().sort("date").collect().get_column("date").to_list()
    signal_dates = [current for current in all_dates if signal_start <= current <= signal_end]
    if not signal_dates:
        raise ValueError("requested signal period has no enriched trading dates")
    first_index = all_dates.index(signal_dates[0])
    last_index = all_dates.index(signal_dates[-1])
    if first_index < 83 or last_index + max(HORIZONS) >= len(all_dates):
        raise ValueError("insufficient enriched lookback or forward coverage for validation period")
    context_start = all_dates[first_index - 83]
    raw_start = all_dates[first_index - 84]
    forward_end = all_dates[last_index + max(HORIZONS)]
    panel = (
        pl.scan_parquet(glob)
        .filter(pl.col("date").is_between(raw_start, forward_end))
        .select(["symbol", "date", "close"])
        .sort(["symbol", "date"])
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("change_pct")
        )
        .filter(pl.col("date").is_between(context_start, forward_end))
        .select(["symbol", "date", "change_pct"])
        .collect()
    )
    return panel, signal_dates, all_dates


def run_validation(data_dir: Path, signal_start: date, signal_end: date) -> str:
    panel, signal_dates, _all_dates = _load_panel(data_dir, signal_start, signal_end)
    repo = ReadOnlyRepo(panel, data_dir)
    finite = panel.filter(pl.col("change_pct").is_finite()).with_columns(
        pl.col("symbol").str.to_uppercase().alias("_sym_up")
    )
    wide = finite.pivot(index="date", on="_sym_up", values="change_pct", aggregate_function="first").sort("date")
    dates = wide.get_column("date").to_list()
    symbols = [column for column in wide.columns if column != "date"]
    matrix = wide.select(symbols).to_numpy().astype(float)
    market_daily = np.nanmean(matrix, axis=1)
    market_counts = np.isfinite(matrix).sum(axis=1)
    market_daily[market_counts < 2] = np.nan

    sector_stats: dict[tuple[str, ...], Stats] = {}
    rs_stats: dict[tuple[str, ...], Stats] = {}
    comparison_stats: dict[tuple[str, ...], Stats] = {}
    regime_stats: dict[tuple[str, ...], Stats] = {}
    time_stats: dict[tuple[str, ...], Stats] = {}
    daily_counts: dict[tuple[str, int], list[int]] = defaultdict(list)
    quality = defaultdict(int)
    regime = regime_builder.load_regime_history(data_dir)
    regime_by_date = {
        row["date"]: str(row["state"])
        for row in regime.iter_rows(named=True)
        if row.get("state") is not None
    }

    selected_membership: dict[str, str] | None = None
    all_industry_ids: list[str] | None = None
    for signal_date in signal_dates:
        index = dates.index(signal_date)
        sector_rows = rps_rotation.build_sector_strength(
            repo, kind="industry", level=1, as_of=signal_date
        )
        if not sector_rows:
            quality["missing_sector_strength_dates"] += 1
            continue
        if all_industry_ids is None:
            all_industry_ids = [row.sector_id for row in sector_rows]
            membership = relative_strength._selected_membership(repo, all_industry_ids)
            counts = membership.group_by("_sym_up").len()
            ambiguous = set(counts.filter(pl.col("len") > 1).get_column("_sym_up").to_list())
            selected_membership = {
                str(row["_sym_up"]): str(row["sector_id"])
                for row in membership.iter_rows(named=True)
                if str(row["_sym_up"]) not in ambiguous
            }
            quality["industry_mapping_ambiguous_symbols_excluded"] = len(ambiguous)
            quality["industry_mapping_symbols"] = len(selected_membership)
        assert selected_membership is not None and all_industry_ids is not None
        sector_tiers = {
            row.sector_id: _tier(row.percentile)
            for row in sector_rows if row.score is not None and row.percentile is not None
        }
        strong_sector_ids = {
            sector_id for sector_id, tier in sector_tiers.items()
            if tier in {"Top 10%", "10%-30%"}
        }
        rs_rows = relative_strength.build_relative_strength(
            repo, sector_ids=all_industry_ids, as_of=signal_date
        )
        rs_by_symbol = {
            row.symbol: row for row in rs_rows
            if row.symbol in selected_membership and row.sector_id == selected_membership[row.symbol]
        }
        strong_rs_scores = {
            symbol: row.rs_score for symbol, row in rs_by_symbol.items()
            if selected_membership[symbol] in strong_sector_ids and row.rs_score is not None
        }
        _, rs_percentiles = rps_rotation._rank_values(strong_rs_scores) if strong_rs_scores else ({}, {})
        rs_tiers = {symbol: _tier(percentile) for symbol, percentile in rs_percentiles.items()}
        date_regime = regime_by_date.get(signal_date, "missing")
        quarter = f"{signal_date.year}-Q{((signal_date.month - 1) // 3) + 1}"

        for horizon in HORIZONS:
            forward, mae, mfe = _forward_metrics(matrix, index, horizon)
            market_slice = market_daily[index + 1:index + horizon + 1]
            market_forward = np.prod(1.0 + market_slice) - 1.0 if np.isfinite(market_slice).all() else np.nan
            if not np.isfinite(market_forward):
                quality[f"benchmark_missing_{horizon}d"] += 1
                continue
            counts_today = {"All Market": 0, "Sector": 0, "Sector + RS": 0}
            for position, symbol in enumerate(symbols):
                stock_forward = forward[position]
                if not np.isfinite(stock_forward):
                    continue
                stock_mae = mae[position]
                stock_mfe = mfe[position]
                excess = stock_forward - market_forward
                _stats_bucket(comparison_stats, "All Market", str(horizon), keep_returns=True).add(
                    stock_forward, excess, stock_mae, stock_mfe
                )
                counts_today["All Market"] += 1
                sector_id = selected_membership.get(symbol)
                sector_tier = sector_tiers.get(sector_id) if sector_id else None
                if sector_tier is None:
                    continue
                _stats_bucket(sector_stats, sector_tier, str(horizon), keep_returns=True).add(
                    stock_forward, excess, stock_mae, stock_mfe
                )
                if sector_id not in strong_sector_ids:
                    continue
                _stats_bucket(comparison_stats, "Sector", str(horizon), keep_returns=True).add(
                    stock_forward, excess, stock_mae, stock_mfe
                )
                _stats_bucket(regime_stats, "Sector", date_regime, str(horizon), keep_returns=False).add(
                    stock_forward, excess, stock_mae, stock_mfe
                )
                _stats_bucket(time_stats, "Sector", quarter, str(horizon), keep_returns=False).add(
                    stock_forward, excess, stock_mae, stock_mfe
                )
                counts_today["Sector"] += 1
                rs_tier = rs_tiers.get(symbol)
                if rs_tier is None:
                    continue
                _stats_bucket(rs_stats, rs_tier, str(horizon), keep_returns=True).add(
                    stock_forward, excess, stock_mae, stock_mfe
                )
                if rs_tier not in {"Top 10%", "10%-30%"}:
                    continue
                _stats_bucket(comparison_stats, "Sector + RS", str(horizon), keep_returns=True).add(
                    stock_forward, excess, stock_mae, stock_mfe
                )
                _stats_bucket(regime_stats, "Sector + RS", date_regime, str(horizon), keep_returns=False).add(
                    stock_forward, excess, stock_mae, stock_mfe
                )
                _stats_bucket(time_stats, "Sector + RS", quarter, str(horizon), keep_returns=False).add(
                    stock_forward, excess, stock_mae, stock_mfe
                )
                counts_today["Sector + RS"] += 1
            for group, count in counts_today.items():
                daily_counts[(group, horizon)].append(count)

    lines = [
        "# Sector / RS 独立历史验证",
        "",
        "## 冻结实验协议",
        "",
        f"- 信号区间：{signal_dates[0]} 至 {signal_dates[-1]}，共 {len(signal_dates)} 个交易日；",
        "- 独立性：该区间为 2026 年公式开发与调试之前的 2024 年历史；",
        "- 行业口径：仅一级行业；同一股票出现多个一级行业映射时排除，避免重复计数；",
        "- 标签：信号日收盘后，以 T+1 至 T+h 的精确交易日 `change_pct` 复合收益；",
        "- 基准：同日全市场有效股票等权复合收益；excess = stock forward return - market forward return；",
        "- 对照组预先声明：Sector = Sector percentile >= 70（Top 30%）；Sector + RS = 其内 RSScore 横截面 percentile >= 70（Top 30%）。该设置仅用于三组对照，不是候选池阈值；",
        "- 分层固定为 Top 10%、10%-30%、30%-50%、Bottom 50%，不依验证结果调整。",
        "",
        "## Sector Strength percentile 分层",
        "",
    ]
    tier_rows = []
    for tier in ("Top 10%", "10%-30%", "30%-50%", "Bottom 50%"):
        for horizon in HORIZONS:
            value = sector_stats.get((tier, str(horizon)), Stats(True)).summary()
            tier_rows.append([tier, f"T+{horizon}", _num(value.get("n")), _pct(value.get("mean_return")), _pct(value.get("median_return")), _pct(value.get("mean_excess")), _pct(value.get("median_excess")), _pct(value.get("positive_return_rate")), _pct(value.get("positive_excess_rate")), _pct(value.get("mae")), _pct(value.get("mfe")), _num(value.get("profit_factor"))])
    lines.append(_markdown_table(["Tier", "Horizon", "n", "Mean return", "Median return", "Mean excess", "Median excess", "Positive return", "Positive excess", "MAE", "MFE", "Profit factor"], tier_rows))
    lines.extend(["", "## 强 Sector 内 RS percentile 分层", ""])
    rs_rows_out = []
    for tier in ("Top 10%", "10%-30%", "30%-50%", "Bottom 50%"):
        for horizon in HORIZONS:
            value = rs_stats.get((tier, str(horizon)), Stats(True)).summary()
            rs_rows_out.append([tier, f"T+{horizon}", _num(value.get("n")), _pct(value.get("mean_return")), _pct(value.get("median_return")), _pct(value.get("mean_excess")), _pct(value.get("median_excess")), _pct(value.get("positive_return_rate")), _pct(value.get("positive_excess_rate")), _pct(value.get("mae")), _pct(value.get("mfe")), _num(value.get("profit_factor"))])
    lines.append(_markdown_table(["RS tier", "Horizon", "n", "Mean return", "Median return", "Mean excess", "Median excess", "Positive return", "Positive excess", "MAE", "MFE", "Profit factor"], rs_rows_out))
    lines.extend(["", "## 三组直接对照与收益分布", ""])
    comparison_rows = []
    distribution_rows = []
    for group in ("All Market", "Sector", "Sector + RS"):
        for horizon in HORIZONS:
            value = comparison_stats.get((group, str(horizon)), Stats(True)).summary(distribution=True)
            average = np.mean(daily_counts[(group, horizon)]) if daily_counts[(group, horizon)] else None
            comparison_rows.append([group, f"T+{horizon}", _num(value.get("n")), _num(float(average) if average is not None else None), _pct(value.get("mean_excess")), _pct(value.get("median_excess")), _pct(value.get("positive_excess_rate")), _pct(value.get("mae")), _pct(value.get("mfe")), _num(value.get("profit_factor"))])
            distribution_rows.append([group, f"T+{horizon}", _pct(value.get("median_return")), _pct(value.get("p10")), _pct(value.get("p25")), _pct(value.get("p75")), _pct(value.get("p90")), _num(value.get("skewness")), _pct(value.get("top5_winner_contribution")), _pct(value.get("top10_winner_contribution"))])
    lines.append(_markdown_table(["Group", "Horizon", "n", "Avg daily candidates", "Mean excess", "Median excess", "Positive excess", "MAE", "MFE", "Profit factor"], comparison_rows))
    lines.extend(["", "Top 5% / Top 10% winner contribution = the share of gross positive forward return supplied by the best 5% / 10% observations.", ""])
    lines.append(_markdown_table(["Group", "Horizon", "Median return", "P10", "P25", "P75", "P90", "Excess skew", "Top 5% contribution", "Top 10% contribution"], distribution_rows))
    lines.extend(["", "## 市场环境稳定性", ""])
    regime_rows_out = []
    for group in ("Sector", "Sector + RS"):
        regimes = sorted({key[1] for key in regime_stats if key[0] == group})
        for state in regimes:
            for horizon in HORIZONS:
                value = regime_stats.get((group, state, str(horizon)), Stats(False)).summary()
                label = "insufficient sample" if value.get("n", 0) < MIN_REGIME_SAMPLE else ""
                regime_rows_out.append([group, state, f"T+{horizon}", _num(value.get("n")), _pct(value.get("mean_excess")), _pct(value.get("median_excess")), _pct(value.get("positive_excess_rate")), _pct(value.get("mae")), _num(value.get("profit_factor")), label])
    lines.append(_markdown_table(["Group", "Regime", "Horizon", "n", "Mean excess", "Median excess", "Positive excess", "MAE", "Profit factor", "Status"], regime_rows_out))
    lines.extend(["", "## 时间稳定性", ""])
    time_rows_out = []
    for group in ("Sector", "Sector + RS"):
        quarters = sorted({key[1] for key in time_stats if key[0] == group})
        for quarter in quarters:
            for horizon in HORIZONS:
                value = time_stats.get((group, quarter, str(horizon)), Stats(False)).summary()
                time_rows_out.append([group, quarter, f"T+{horizon}", _num(value.get("n")), _pct(value.get("mean_excess")), _pct(value.get("median_excess")), _pct(value.get("positive_excess_rate"))])
    lines.append(_markdown_table(["Group", "Quarter", "Horizon", "n", "Mean excess", "Median excess", "Positive excess"], time_rows_out))
    lines.extend([
        "",
        "## 数据质量与限制",
        "",
        f"- 一级行业唯一映射样本：{quality['industry_mapping_symbols']}；因多个一级行业映射排除：{quality['industry_mapping_ambiguous_symbols_excluded']}；",
        f"- 无 Sector Strength 结果的信号日：{quality['missing_sector_strength_dates']}；",
        "- 新股、停牌、交易日缺失和 NaN：任一未来窗口缺值即不计入该 horizon 的 n；",
        "- benchmark：窗口任一日全市场有效样本不足 2 只即不计入该 horizon；",
        "- membership：使用当前扩展数据快照回看 2024，存在归属漂移与 survivorship bias；因此结论仅是当前成员口径下的研究证据；",
        "- look-ahead：信号只由 as_of 及之前数据生成；前向标签从下一交易日开始；",
        "- MAE/MFE：基于收盘到收盘的每日累计收益，不是盘中 high/low 的真实路径。",
        "",
        "## 解释规则",
        "",
        "若 mean excess 为正而 median excess 为负，必须解释为“可能存在右尾收益特征，但不是广泛稳定 edge”。本报告不据单一 horizon、单一 percentile 或单一 regime 设定候选池阈值。",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--start", type=date.fromisoformat, default=SIGNAL_START)
    parser.add_argument("--end", type=date.fromisoformat, default=SIGNAL_END)
    args = parser.parse_args()
    print(run_validation(args.data_dir.resolve(), args.start, args.end), end="")


if __name__ == "__main__":
    main()
