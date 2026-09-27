"""可解释的大盘风险日终快照。

本模块只读取已落盘的 ``kline_daily`` / ``kline_index_daily``, 不发网络请求,
并按交易日覆盖写入 ``market_risk_history/part.parquet``。它不产出未经验证的
加权总分。风险等级由相互独立的风险维度数量和指数趋势破位规则得出, 并保留
全部原始线索供复核。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

logger = logging.getLogger(__name__)

MARKET_RISK_DIR = "market_risk_history"
METHODOLOGY_VERSION = "market_risk_v1.6"
PRICE_BASIS = "raw_unadjusted"
INITIAL_HISTORY_DAYS = 60
_INDEX_SPECS = {
    "csi_all": "000985.SH",
    "csi300": "000300.SH",
}


def market_risk_path(data_dir: Path) -> Path:
    return data_dir / MARKET_RISK_DIR / "part.parquet"


def load_market_risk_history(data_dir: Path) -> pl.DataFrame:
    """读取已保存的风险快照; 文件不存在或不可读时返回空表。"""
    path = market_risk_path(data_dir)
    if not path.exists():
        return pl.DataFrame()
    try:
        return pl.read_parquet(path)
    except Exception as exc:
        logger.warning("load_market_risk_history failed: %s", exc)
        return pl.DataFrame()


def upsert_market_risk_history(data_dir: Path, new_rows: pl.DataFrame) -> None:
    """按交易日覆盖快照, 保证同一输入日期不会累积重复记录。"""
    if new_rows.is_empty() or "date" not in new_rows.columns:
        return
    path = market_risk_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = load_market_risk_history(data_dir)
    if old.is_empty():
        combined = new_rows
    else:
        target_columns = new_rows.columns
        new_dates = new_rows.get_column("date").to_list()
        kept = old.filter(~pl.col("date").is_in(new_dates))
        kept = kept.select([
            pl.col(column) if column in kept.columns else pl.lit(None).alias(column)
            for column in target_columns
        ])
        combined = pl.concat([kept, new_rows.select(target_columns)], how="vertical_relaxed")
    combined.sort("date").unique(subset=["date"], keep="last").write_parquet(path)


def get_market_risk_coverage(data_dir: Path) -> dict[str, object]:
    history = load_market_risk_history(data_dir)
    if history.is_empty():
        return {"rows": 0, "earliest_date": None, "latest_date": None, "methodology_version": METHODOLOGY_VERSION}
    return {
        "rows": history.height,
        "earliest_date": str(history.get_column("date").min()),
        "latest_date": str(history.get_column("date").max()),
        "methodology_version": METHODOLOGY_VERSION,
    }


def _daily_part_dates(data_dir: Path) -> list[date]:
    base = data_dir / "kline_daily"
    if not base.exists():
        return []
    dates: list[date] = []
    for part in base.glob("date=*/part.parquet"):
        try:
            dates.append(date.fromisoformat(part.parent.name.removeprefix("date=")))
        except ValueError:
            continue
    return sorted(set(dates))


def _history_start(trading_dates: list[date], start: date, lookback: int = 250) -> date:
    """取 start 前足够的交易日, 而不是按自然日回退。"""
    index = next((i for i, value in enumerate(trading_dates) if value >= start), None)
    if index is None:
        return start
    return trading_dates[max(0, index - lookback)]


def _raw_stock_frame(data_dir: Path, start: date, end: date) -> pl.DataFrame:
    path = data_dir / "kline_daily" / "**" / "*.parquet"
    return (
        pl.scan_parquet(str(path))
        .filter(pl.col("date").is_between(start, end))
        .select(["symbol", "date", "open", "high", "low", "close", "volume", "amount"])
        .collect()
    )


def _raw_index_frame(data_dir: Path, start: date, end: date) -> pl.DataFrame:
    base = data_dir / "kline_index_daily"
    if not base.exists() or not any(base.glob("date=*/part.parquet")):
        return pl.DataFrame()
    path = base / "**" / "*.parquet"
    return (
        pl.scan_parquet(str(path))
        .filter(
            pl.col("date").is_between(start, end)
            & pl.col("symbol").is_in(list(_INDEX_SPECS.values()))
        )
        .select(["symbol", "date", "open", "high", "low", "close", "volume", "amount"])
        .collect()
    )


def _stock_daily_metrics(raw: pl.DataFrame, target_dates: list[date]) -> pl.DataFrame:
    if raw.is_empty() or not target_dates:
        return pl.DataFrame()
    work = raw.sort(["symbol", "date"]).with_columns([
        pl.col("close").shift(1).over("symbol").alias("_prev_close"),
        pl.col("close").rolling_mean(window_size=20, min_samples=20).over("symbol").alias("_ma20"),
        pl.col("close").rolling_mean(window_size=50, min_samples=50).over("symbol").alias("_ma50"),
        pl.col("high").rolling_max(window_size=250, min_samples=250).over("symbol").alias("_high250"),
        pl.col("low").rolling_min(window_size=250, min_samples=250).over("symbol").alias("_low250"),
    ]).with_columns([
        ((pl.col("volume") > 0) & (pl.col("amount") > 0) & (pl.col("close") > 0)).alias("_active"),
        (
            (pl.col("_prev_close").is_not_null())
            & (pl.col("_prev_close") > 0)
            & (pl.col("close") > 0)
        ).alias("_has_previous_close"),
    ]).with_columns([
        (pl.col("close") / pl.col("_prev_close") - 1.0).alias("_change_pct"),
        (pl.col("_active") & pl.col("_ma20").is_not_null()).alias("_ma20_valid"),
        (pl.col("_active") & pl.col("_ma50").is_not_null()).alias("_ma50_valid"),
        (pl.col("_active") & pl.col("_high250").is_not_null()).alias("_high_low_250_valid"),
    ])
    daily = work.group_by("date").agg([
        pl.len().alias("stock_snapshot_count"),
        pl.col("_active").sum().cast(pl.Int64).alias("active_stock_count"),
        pl.when(pl.col("_active")).then(pl.col("amount")).otherwise(0.0).sum().alias("market_amount"),
        (pl.col("_active") & pl.col("_has_previous_close")).sum().cast(pl.Int64).alias("change_valid_count"),
        (pl.col("_active") & pl.col("_has_previous_close") & (pl.col("_change_pct") > 0)).sum().cast(pl.Int64).alias("up_count"),
        (pl.col("_active") & pl.col("_has_previous_close") & (pl.col("_change_pct") < 0)).sum().cast(pl.Int64).alias("down_count"),
        (pl.col("_active") & pl.col("_has_previous_close") & (pl.col("_change_pct") == 0)).sum().cast(pl.Int64).alias("flat_count"),
        pl.col("_ma20_valid").sum().cast(pl.Int64).alias("ma20_valid_count"),
        (pl.col("_ma20_valid") & (pl.col("close") > pl.col("_ma20"))).sum().cast(pl.Int64).alias("ma20_above_count"),
        pl.col("_ma50_valid").sum().cast(pl.Int64).alias("ma50_valid_count"),
        (pl.col("_ma50_valid") & (pl.col("close") > pl.col("_ma50"))).sum().cast(pl.Int64).alias("ma50_above_count"),
        pl.col("_high_low_250_valid").sum().cast(pl.Int64).alias("new_high_low_250_valid_count"),
        (pl.col("_high_low_250_valid") & (pl.col("high") >= pl.col("_high250"))).sum().cast(pl.Int64).alias("new_high_250_count"),
        (pl.col("_high_low_250_valid") & (pl.col("low") <= pl.col("_low250"))).sum().cast(pl.Int64).alias("new_low_250_count"),
        pl.when(pl.col("_active") & pl.col("_has_previous_close") & (pl.col("_change_pct") > 0)).then(pl.col("amount")).otherwise(0.0).sum().alias("up_amount"),
        pl.when(pl.col("_active") & pl.col("_has_previous_close") & (pl.col("_change_pct") < 0)).then(pl.col("amount")).otherwise(0.0).sum().alias("down_amount"),
    ]).sort("date").with_columns([
        pl.col("market_amount").rolling_mean(window_size=5, min_samples=5).alias("market_amount_ma5"),
        pl.col("market_amount").rolling_mean(window_size=20, min_samples=20).alias("market_amount_ma20"),
    ]).with_columns([
        _ratio("ma20_above_count", "ma20_valid_count", "ma20_above_pct"),
        _ratio("ma50_above_count", "ma50_valid_count", "ma50_above_pct"),
        _ratio("change_valid_count", "active_stock_count", "change_coverage_pct"),
        _ratio("ma20_valid_count", "active_stock_count", "ma20_coverage_pct"),
        _ratio("ma50_valid_count", "active_stock_count", "ma50_coverage_pct"),
        _ratio("new_high_low_250_valid_count", "active_stock_count", "new_high_low_250_coverage_pct"),
        _ratio("down_amount", "up_amount", "_unused"),
        pl.when((pl.col("up_amount") + pl.col("down_amount")) > 0)
        .then(pl.col("down_amount") / (pl.col("up_amount") + pl.col("down_amount")))
        .otherwise(None)
        .alias("down_amount_share"),
        _ratio("market_amount", "market_amount_ma20", "market_amount_ratio_20"),
        _ratio("market_amount_ma5", "market_amount_ma20", "market_amount_ma5_ratio_20"),
    ]).drop("_unused")
    return daily.filter(pl.col("date").is_in(target_dates)).sort("date")


def _ratio(numerator: str, denominator: str, alias: str) -> pl.Expr:
    return (
        pl.when(pl.col(denominator) > 0)
        .then(pl.col(numerator) / pl.col(denominator))
        .otherwise(None)
        .alias(alias)
    )


def _market_strength_components(row: dict[str, object]) -> dict[str, float | None]:
    """用连续的市场内部数据构造研究型强度分, 不把缺失项替换为低分。"""
    index_scores: list[float] = []
    for key in _INDEX_SPECS:
        if row.get(f"{key}_available") is not True:
            return {name: None for name in ("trend", "breadth", "participation", "new_high_low", "volume", "score")}
        index_scores.append(
            (50.0 if row.get(f"{key}_above_ma60") is True else 0.0)
            + (25.0 if row.get(f"{key}_above_ma20") is True else 0.0)
            + (25.0 if row.get(f"{key}_ma20_direction") == "up" else 12.5 if row.get(f"{key}_ma20_direction") == "flat" else 0.0)
        )
    ma20 = row.get("ma20_above_pct")
    ma50 = row.get("ma50_above_pct")
    down_amount_share = row.get("down_amount_share")
    amount_ratio_20 = row.get("market_amount_ratio_20")
    amount_ma5_ratio_20 = row.get("market_amount_ma5_ratio_20")
    up_count = row.get("up_count")
    down_count = row.get("down_count")
    if not (
        isinstance(ma20, (int, float))
        and isinstance(ma50, (int, float))
        and isinstance(down_amount_share, (int, float))
        and isinstance(amount_ratio_20, (int, float))
        and isinstance(amount_ma5_ratio_20, (int, float))
        and isinstance(up_count, int)
        and isinstance(down_count, int)
        and up_count + down_count > 0
    ):
        return {name: None for name in ("trend", "breadth", "participation", "new_high_low", "volume", "score")}
    new_high = row.get("new_high_250_count")
    new_low = row.get("new_low_250_count")
    if not isinstance(new_high, int) or not isinstance(new_low, int):
        return {name: None for name in ("trend", "breadth", "participation", "new_high_low", "volume", "score")}

    trend = sum(index_scores) / len(index_scores)
    breadth = (ma20 + ma50) * 50.0
    advance_decline = 50.0 + 50.0 * (up_count - down_count) / (up_count + down_count)
    participation = (advance_decline + 100.0 * (1.0 - down_amount_share)) / 2.0
    new_high_low = 50.0 if new_high + new_low == 0 else 100.0 * new_high / (new_high + new_low)
    # Volume covers level and trend only. Directional flow is already in participation.
    volume_level = max(0.0, min(100.0, (amount_ratio_20 - 0.70) / 0.60 * 100.0))
    volume_trend = max(0.0, min(100.0, (amount_ma5_ratio_20 - 0.85) / 0.30 * 100.0))
    volume = (volume_level + volume_trend) / 2.0
    score = 0.30 * trend + 0.25 * breadth + 0.20 * participation + 0.15 * new_high_low + 0.10 * volume
    return {
        "trend": round(trend, 1),
        "breadth": round(breadth, 1),
        "participation": round(participation, 1),
        "new_high_low": round(new_high_low, 1),
        "volume": round(volume, 1),
        "score": round(score, 1),
    }


def _index_metrics(raw: pl.DataFrame, target_dates: list[date]) -> dict[tuple[date, str], dict[str, object]]:
    if raw.is_empty() or not target_dates:
        return {}
    work = raw.sort(["symbol", "date"]).with_columns(
        pl.col("close").shift(1).over("symbol").alias("_prev_close")
    ).with_columns(
        pl.max_horizontal(
            pl.col("high") - pl.col("low"),
            (pl.col("high") - pl.col("_prev_close")).abs(),
            (pl.col("low") - pl.col("_prev_close")).abs(),
        ).alias("_true_range")
    ).with_columns([
        pl.col("close").rolling_mean(window_size=20, min_samples=20).over("symbol").alias("_ma20"),
        pl.col("close").rolling_mean(window_size=60, min_samples=60).over("symbol").alias("_ma60"),
        pl.col("high").rolling_max(window_size=60, min_samples=60).over("symbol").alias("_high60"),
        pl.col("low").rolling_min(window_size=60, min_samples=60).over("symbol").alias("_low60"),
        pl.col("_true_range").rolling_mean(window_size=14, min_samples=14).over("symbol").alias("_atr14"),
    ]).with_columns(
        pl.col("_ma20").shift(1).over("symbol").alias("_prior_ma20")
    ).filter(pl.col("date").is_in(target_dates))

    by_symbol = {symbol: key for key, symbol in _INDEX_SPECS.items()}
    records: dict[tuple[date, str], dict[str, object]] = {}
    for row in work.to_dicts():
        key = by_symbol.get(str(row["symbol"]))
        if key is None:
            continue
        close = row.get("close")
        ma20 = row.get("_ma20")
        ma60 = row.get("_ma60")
        prior_ma20 = row.get("_prior_ma20")
        atr14 = row.get("_atr14")
        high60 = row.get("_high60")
        low60 = row.get("_low60")
        position60 = None
        if close is not None and high60 is not None and low60 is not None and high60 > low60:
            position60 = (close - low60) / (high60 - low60)
        available = all(value is not None for value in (close, ma20, ma60, prior_ma20))
        direction = "unavailable"
        if prior_ma20 is not None and ma20 is not None:
            direction = "up" if ma20 > prior_ma20 else "down" if ma20 < prior_ma20 else "flat"
        records[(row["date"], key)] = {
            f"{key}_symbol": row["symbol"],
            f"{key}_close": close,
            f"{key}_ma20": ma20,
            f"{key}_ma60": ma60,
            f"{key}_above_ma20": None if close is None or ma20 is None else close > ma20,
            f"{key}_above_ma60": None if close is None or ma60 is None else close > ma60,
            f"{key}_ma20_direction": direction,
            f"{key}_ma20_change": None if prior_ma20 is None or ma20 is None else ma20 - prior_ma20,
            f"{key}_atr14": atr14,
            f"{key}_atr14_close_ratio": None if atr14 is None or not close else atr14 / close,
            f"{key}_position_60": position60,
            f"{key}_available": available,
        }
    return records


def _index_defaults(key: str) -> dict[str, object]:
    return {
        f"{key}_symbol": _INDEX_SPECS[key],
        f"{key}_close": None,
        f"{key}_ma20": None,
        f"{key}_ma60": None,
        f"{key}_above_ma20": None,
        f"{key}_above_ma60": None,
        f"{key}_ma20_direction": "unavailable",
        f"{key}_ma20_change": None,
        f"{key}_atr14": None,
        f"{key}_atr14_close_ratio": None,
        f"{key}_position_60": None,
        f"{key}_available": False,
    }


def _annotate_risk_rows(rows: list[dict[str, object]], previous: pl.DataFrame) -> list[dict[str, object]]:
    """给行附加可追溯的风险、顶部预警与修复候选标签。"""
    recent: list[dict[str, object]] = []
    if not previous.is_empty():
        recent = previous.sort("date").tail(5).to_dicts()
    out: list[dict[str, object]] = []
    for row in sorted(rows, key=lambda item: item["date"]):
        warnings: list[str] = []
        if not row["csi_all_available"]:
            warnings.append("中证全指缺少 MA20/MA60 或前一日 MA20, 指数趋势不可用")
        if not row["csi300_available"]:
            warnings.append("沪深300缺少 MA20/MA60 或前一日 MA20, 指数趋势不可用")
        if not row["ma20_valid_count"]:
            warnings.append("当日没有满足 MA20 窗口的有效股票, 市场宽度不可用")
        if not row["ma50_valid_count"]:
            warnings.append("当日没有满足 MA50 窗口的有效股票, 市场宽度不可用")
        if not row["new_high_low_250_valid_count"]:
            warnings.append("当日没有满足 250 交易日窗口的有效股票, 新高/新低不可用")
        if not row["change_valid_count"]:
            warnings.append("当日没有可比较前收的有效股票, 涨跌家数与成交结构不可用")
        elif row["up_count"] + row["down_count"] == 0:
            warnings.append("当日没有上涨或下跌股票, 市场参与强度不可用")
        if row.get("market_amount_ratio_20") is None or row.get("market_amount_ma5_ratio_20") is None:
            warnings.append("全市场成交额缺少 MA5/MA20 窗口, 量能健康度不可用")

        reasons: list[str] = []
        categories: list[str] = []
        both_indices_below_ma60 = True
        for key, name in (("csi_all", "中证全指"), ("csi300", "沪深300")):
            if row[f"{key}_available"]:
                index_has_risk = False
                if row[f"{key}_above_ma60"] is False:
                    reasons.append(f"{name}收盘低于 MA60")
                    index_has_risk = True
                elif row[f"{key}_above_ma20"] is False:
                    reasons.append(f"{name}收盘低于 MA20")
                    index_has_risk = True
                if row[f"{key}_ma20_direction"] == "down":
                    reasons.append(f"{name} MA20 下行")
                    index_has_risk = True
                if row[f"{key}_above_ma60"] is not False:
                    both_indices_below_ma60 = False
                if index_has_risk and "指数趋势" not in categories:
                    categories.append("指数趋势")
            else:
                both_indices_below_ma60 = False

        recent_with_current = [*recent, row]
        last_three: list[dict[str, object]] = []
        breadth_falling = False
        if len(recent_with_current) >= 3:
            last_three = recent_with_current[-3:]
            ma50_values = [item.get("ma50_above_pct") for item in last_three]
            csi_all_above_ma60 = row.get("csi_all_above_ma60") is True
            breadth_falling = (
                csi_all_above_ma60
                and all(isinstance(value, (int, float)) for value in ma50_values)
                and ma50_values[0] > ma50_values[1] > ma50_values[2]
            )
            if breadth_falling:
                reasons.append("中证全指仍在 MA60 上方, 但站上 MA50 的股票占比连续 3 日下降")
                categories.append("市场广度")

        if row["change_valid_count"]:
            selling_pressure = False
            if row["down_count"] > row["up_count"]:
                reasons.append("下跌家数多于上涨家数")
                selling_pressure = True
            if row["down_amount_share"] is not None and row["down_amount_share"] > 0.5:
                reasons.append("下跌股票成交额在涨跌股票成交额中占优")
                selling_pressure = True
            if selling_pressure:
                categories.append("卖压")
        if row["new_high_low_250_valid_count"] and row["new_low_250_count"] > row["new_high_250_count"]:
            reasons.append("250 交易日新低家数多于新高家数")
            categories.append("新低扩散")

        strength = _market_strength_components(row) if not warnings else {
            name: None for name in ("trend", "breadth", "participation", "new_high_low", "volume", "score")
        }
        row["market_strength_trend_score"] = strength["trend"]
        row["market_strength_breadth_score"] = strength["breadth"]
        row["market_strength_participation_score"] = strength["participation"]
        row["market_strength_new_high_low_score"] = strength["new_high_low"]
        row["market_strength_volume_score"] = strength["volume"]
        row["market_strength_score"] = strength["score"]

        row["data_warnings"] = warnings
        row["risk_reasons"] = reasons
        row["risk_signal_categories"] = categories
        row["risk_signal_category_count"] = len(categories)
        row["risk_state"] = "insufficient_data" if warnings else "attention" if reasons else "neutral"
        row["availability"] = "partial" if warnings else "available"
        both_short_term_breakdown = (
            row["csi_all_above_ma20"] is False
            and row["csi_all_ma20_direction"] == "down"
            and row["csi300_above_ma20"] is False
            and row["csi300_ma20_direction"] == "down"
        )
        strength_score = row["market_strength_score"]
        active_capitulation = (
            both_short_term_breakdown
            and isinstance(strength_score, (int, float))
            and strength_score < 35.0
            and ("卖压" in categories or "新低扩散" in categories)
        )
        if warnings:
            row["risk_level"] = "unavailable"
        elif active_capitulation or (
            len(categories) >= 3
            and isinstance(strength_score, (int, float))
            and strength_score < 45.0
        ):
            row["risk_level"] = "high"
        elif len(categories) >= 2 or (
            both_indices_below_ma60
            and isinstance(strength_score, (int, float))
            and strength_score < 50.0
        ):
            row["risk_level"] = "elevated"
        elif categories or both_indices_below_ma60:
            row["risk_level"] = "watch"
        else:
            row["risk_level"] = "low"

        # 只在指数仍站于 MA60 上方时提示“顶部风险”, 不把已经转弱后的风险再称为顶部。
        top_categories: list[str] = []
        if row["csi_all_above_ma60"] is True:
            if breadth_falling:
                top_categories.append("广度连续走弱")
            if row["new_high_low_250_valid_count"] and row["new_low_250_count"] > row["new_high_250_count"]:
                top_categories.append("新低扩散")
            recent_selling = recent_with_current[-3:]
            selling_days = sum(
                item.get("down_count", 0) > item.get("up_count", 0)
                and isinstance(item.get("down_amount_share"), (int, float))
                and item["down_amount_share"] > 0.5
                for item in recent_selling
            )
            if len(recent_selling) >= 3 and selling_days >= 2:
                top_categories.append("卖压连续占优")
        if warnings:
            top_level = "unavailable"
        elif len(top_categories) >= 3:
            top_level = "high"
        elif len(top_categories) >= 2:
            top_level = "elevated"
        elif top_categories:
            top_level = "watch"
        else:
            top_level = "low"

        recovery_categories: list[str] = []
        breadth_rising = False
        if len(last_three) >= 3:
            ma50_values = [item.get("ma50_above_pct") for item in last_three]
            breadth_rising = (
                all(isinstance(value, (int, float)) for value in ma50_values)
                and ma50_values[0] < ma50_values[1] < ma50_values[2]
            )
        if breadth_rising:
            recovery_categories.append("广度连续修复")
        if (
            row["up_count"] > row["down_count"]
            and row["down_amount_share"] is not None
            and row["down_amount_share"] < 0.5
        ):
            recovery_categories.append("买盘重新占优")
        if row["csi_all_above_ma20"] is True and row["csi_all_ma20_direction"] == "up":
            recovery_categories.append("中证全指短期趋势修复")

        csi_all_weakening = (
            row["csi_all_above_ma20"] is False
            and row["csi_all_ma20_direction"] == "down"
        )
        csi300_weakening = (
            row["csi300_above_ma20"] is False
            and row["csi300_ma20_direction"] == "down"
        )
        weakening_confirmed = both_indices_below_ma60 or (csi_all_weakening and csi300_weakening)
        recovery_candidate = (
            not warnings
            and not (row["csi_all_above_ma60"] is True and row["csi300_above_ma60"] is True)
            and len(recovery_categories) >= 2
        )

        # MA60 下方不必然代表继续下杀。只有处于近 60 日低位且多项内部数据同步改善,
        # 才标记为低位震荡; 它仍不是趋势反转确认。
        consolidation_categories: list[str] = []
        recent_six = recent_with_current[-6:]
        prior_five = recent_six[0] if len(recent_six) >= 6 else None
        csi_all_position = row.get("csi_all_position_60")
        csi300_position = row.get("csi300_position_60")
        in_lower_range = (
            isinstance(csi_all_position, (int, float))
            and isinstance(csi300_position, (int, float))
            and csi_all_position <= 0.35
            and csi300_position <= 0.45
        )
        if row["csi_all_above_ma20"] is True or row["csi_all_ma20_direction"] != "down":
            consolidation_categories.append("指数短期止跌")
        if prior_five is not None:
            prior_strength = prior_five.get("market_strength_score")
            current_strength = row.get("market_strength_score")
            if (
                isinstance(prior_strength, (int, float))
                and isinstance(current_strength, (int, float))
                and current_strength - prior_strength >= 5.0
            ):
                consolidation_categories.append("市场强度 5 日回升")
            if row["new_low_250_count"] < prior_five.get("new_low_250_count", row["new_low_250_count"]):
                consolidation_categories.append("新低家数回落")
            prior_atr = prior_five.get("csi_all_atr14_close_ratio")
            current_atr = row.get("csi_all_atr14_close_ratio")
            if (
                isinstance(prior_atr, (int, float))
                and isinstance(current_atr, (int, float))
                and current_atr < prior_atr
            ):
                consolidation_categories.append("波动率收敛")
        if breadth_rising:
            consolidation_categories.append("市场广度修复")
        if (
            row["up_count"] > row["down_count"]
            and row["down_amount_share"] is not None
            and row["down_amount_share"] < 0.5
        ):
            consolidation_categories.append("卖压缓解")
        low_level_consolidation = (
            not warnings
            and both_indices_below_ma60
            and in_lower_range
            and len(consolidation_categories) >= 3
        )
        if low_level_consolidation and row["risk_level"] == "high":
            row["risk_level"] = "elevated"
        if warnings:
            market_phase = "insufficient_data"
        elif low_level_consolidation:
            market_phase = "low_level_consolidation"
        elif weakening_confirmed:
            market_phase = "weakening_confirmed"
        elif top_level != "low":
            market_phase = "top_warning"
        elif row["csi_all_above_ma60"] is True and row["csi300_above_ma60"] is True:
            market_phase = "uptrend_healthy"
        else:
            market_phase = "mixed"
        row["top_warning_level"] = top_level
        row["top_warning_categories"] = top_categories
        row["recovery_candidate"] = "unavailable" if warnings else "candidate" if recovery_candidate else "none"
        row["recovery_categories"] = recovery_categories
        row["low_level_consolidation_categories"] = consolidation_categories if low_level_consolidation else []
        row["market_phase"] = market_phase
        recent.append(row)
        recent = recent[-5:]
        out.append(row)
    return out


def build_market_risk_rows(data_dir: Path, start: date, end: date, *, previous: pl.DataFrame | None = None) -> pl.DataFrame:
    """构建指定交易日范围的风险快照, 不写入磁盘。"""
    started = time.perf_counter()
    trading_dates = _daily_part_dates(data_dir)
    target_dates = [value for value in trading_dates if start <= value <= end]
    if not target_dates:
        return pl.DataFrame()
    history_start = _history_start(trading_dates, target_dates[0])
    stock = _stock_daily_metrics(_raw_stock_frame(data_dir, history_start, target_dates[-1]), target_dates)
    if stock.is_empty():
        return pl.DataFrame()
    index = _index_metrics(_raw_index_frame(data_dir, history_start, target_dates[-1]), target_dates)
    computed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    records: list[dict[str, object]] = []
    for row in stock.to_dicts():
        for key in _INDEX_SPECS:
            row.update(_index_defaults(key))
            row.update(index.get((row["date"], key), {}))
        row.update({
            "methodology_version": METHODOLOGY_VERSION,
            "price_basis": PRICE_BASIS,
            "computed_at": computed_at,
            "calculation_ms": elapsed_ms,
        })
        records.append(row)
    prior_rows = previous if previous is not None else pl.DataFrame()
    # 重算同一交易日时不能把旧快照当成“前两日”, 否则连续下降判断会重复当日。
    if not prior_rows.is_empty() and "date" in prior_rows.columns:
        prior_rows = prior_rows.filter(pl.col("date") < target_dates[0])
    return (
        pl.DataFrame(_annotate_risk_rows(records, prior_rows))
        .with_columns([
            pl.col("data_warnings").cast(pl.List(pl.Utf8)),
            pl.col("risk_reasons").cast(pl.List(pl.Utf8)),
            pl.col("risk_signal_categories").cast(pl.List(pl.Utf8)),
            pl.col("top_warning_categories").cast(pl.List(pl.Utf8)),
            pl.col("recovery_categories").cast(pl.List(pl.Utf8)),
            pl.col("low_level_consolidation_categories").cast(pl.List(pl.Utf8)),
        ])
        .sort("date")
    )


def compute_market_risk_incremental(repo, data_dir: Path, *, today: date | None = None) -> pl.DataFrame:
    """日终增量计算; 首次仅回填最近 60 个交易日以保证看板有趋势可读。"""
    today = today or date.today()
    trading_dates = [value for value in _daily_part_dates(data_dir) if value <= today]
    if not trading_dates:
        return pl.DataFrame()
    existing = load_market_risk_history(data_dir)
    latest = trading_dates[-1]
    needs_level_backfill = (
        not existing.is_empty()
        and (
            "risk_level" not in existing.columns
            or existing.get_column("risk_level").null_count() > 0
            or "market_phase" not in existing.columns
            or existing.get_column("market_phase").null_count() > 0
            or "market_strength_score" not in existing.columns
            or "low_level_consolidation_categories" not in existing.columns
            or "methodology_version" not in existing.columns
            or existing.filter(pl.col("methodology_version") != METHODOLOGY_VERSION).height > 0
        )
    )
    if existing.is_empty():
        start = trading_dates[max(0, len(trading_dates) - INITIAL_HISTORY_DAYS)]
    elif needs_level_backfill:
        start = max(existing.get_column("date").min(), trading_dates[0])
    else:
        start = latest
    rows = build_market_risk_rows(data_dir, start, latest, previous=existing)
    if not rows.is_empty():
        upsert_market_risk_history(data_dir, rows)
    return rows
