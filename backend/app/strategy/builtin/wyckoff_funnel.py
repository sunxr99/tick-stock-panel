"""Built-in all-market Wyckoff funnel strategy."""

from app.wyckoff.config import FunnelConfig

META = {
    "id": "wyckoff_funnel",
    "name": "威科夫全市场漏斗",
    "description": "L1–L4 全市场威科夫筛选；手动运行，结果含结构与漏斗证据。",
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "tags": ["威科夫", "全市场", "结构"],
    "limit": 0,
}

EXECUTION_BACKEND = "wyckoff_funnel"
WYCKOFF_CONFIG = FunnelConfig()
