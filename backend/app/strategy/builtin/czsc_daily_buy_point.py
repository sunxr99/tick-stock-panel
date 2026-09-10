"""CZSC daily B-point screener backed by the same signal definitions as the chart."""

from app.custom.chanlun import filter_daily_czsc_buy_points

META = {
    "id": "czsc_daily_buy_point",
    "name": "CZSC 日线新买点",
    "description": "筛选最后一根已收盘日K首次确认的一买、二买或三买, 历史遗留买点不重复入选。",
    "tags": ["CZSC", "缠论", "B1/B2/B3", "日线"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "scoring": {"momentum_20d": 0.4, "vol_ratio_5d": 0.3, "change_pct": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

LOOKBACK_DAYS = 250
EXECUTION_BACKEND = "python_history_legacy"


def filter_history(history, params):
    return filter_daily_czsc_buy_points(history, params)
