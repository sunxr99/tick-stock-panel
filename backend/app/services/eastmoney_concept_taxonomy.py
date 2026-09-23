"""Auditable display taxonomy for 东方财富 flat concept boards.

This only classifies the vendor's board *names* for the hotspot dashboard. It
does not alter the raw board facts, constituent history, Sector Strength, or
any backtest input. Rules are intentionally explicit so a board can be moved
after review without silently changing the underlying data.
"""
from __future__ import annotations

from dataclasses import dataclass

TAXONOMY_VERSION = "eastmoney-concept-display-v1"


@dataclass(frozen=True)
class ConceptClassification:
    category: str
    reason: str


_SENTIMENT_PREFIXES = ("昨日",)
_SENTIMENT_NAMES = {
    "历史新高", "历史新低", "近期新高", "百日新高", "最近多板", "超跌股", "反转股",
    "趋势股", "题材股", "东方财富热股", "密集调研", "举牌", "并购重组概念",
}
_SENTIMENT_MARKERS = ("连板", "首板", "涨停", "跌停", "炸板", "触板", "预增", "预减", "扭亏", "首亏")

_STYLE_NAMES = {
    "AB股", "AH股", "B股", "GDR", "HS300_", "MSCI中国", "富时罗素", "标准普尔",
    "上证180_", "上证380", "上证50_", "中证500", "创业成份", "创业板综", "深成500",
    "深证100R", "央视50_", "宁组合", "茅指数", "低价股", "百元股", "破净股",
    "破发股", "破增发价股", "低市净率", "高市净率", "长期破净", "微利股", "微盘精选",
    "微盘股", "小盘股", "中盘股", "大盘股", "小盘价值", "小盘成长", "中盘价值",
    "中盘成长", "大盘价值", "大盘成长", "价值股", "周期股", "权重股", "红利股",
    "红利破净股", "高成长股", "行业龙头", "超级品牌", "先进制造风格", "消费风格",
    "科技风格", "医药医疗风格", "金融地产风格", "QFII重仓", "基金重仓", "机构重仓",
    "社保重仓", "证金持股", "沪股通", "深股通", "融资融券", "转债标的", "北交所概念",
    "科创板做市商", "科创板做市股", "次新股",
}
_STYLE_MARKERS = ("重仓", "持股", "指数", "成份", "成分")


def classify_concept(name: str) -> ConceptClassification:
    """Return the dashboard category and a human-readable deterministic reason."""
    normalized = name.strip()
    if normalized.startswith(_SENTIMENT_PREFIXES) or normalized in _SENTIMENT_NAMES:
        return ConceptClassification("sentiment", "短线事件或价格状态板块")
    marker = next((item for item in _SENTIMENT_MARKERS if item in normalized), None)
    if marker:
        return ConceptClassification("sentiment", f"名称包含“{marker}”短线事件标记")
    if normalized in _STYLE_NAMES:
        return ConceptClassification("style", "估值、样本、持仓或风格筛选板块")
    marker = next((item for item in _STYLE_MARKERS if item in normalized), None)
    if marker:
        return ConceptClassification("style", f"名称包含“{marker}”风格/样本标记")
    return ConceptClassification("theme", "未命中情绪或风格规则, 归为产业/技术/政策主题")
