"""缠论(czsc)分析扩展 — 提供缠论结构图与结构化分析接口。

二开扩展点: 放在 backend/app/custom/ 下由 loader.py 自动发现并注册路由,
不修改任何核心源码 (见 docs/secondary-development.md)。

接口:
- GET /api/chan/plot     : 返回 czsc 自包含 HTML (阶段 1, iframe 兼容保留)
- GET /api/chan/analyze  : 返回结构化 JSON (K线 + 笔 + 中枢 + 买卖点), 供前端 ECharts 原生渲染

数据口径 (遵循 CONTRIBUTING §3):
- 画图使用本地 enriched 日K 的前复权价 open/high/low/close。
- czsc 输入契约: pandas DataFrame 八列 dt/symbol/open/close/high/low/vol/amount,
  dt 为北京时间墙钟 (日线即交易日 00:00)。
- 买卖点来自 czsc 内置信号函数 (v1 字段即类型: 一买/一卖/二买/二卖/三买/三卖)。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from app.extensions import (
    BACKEND_EXTENSION_API_VERSION,
    BackendExtensionRegistrar,
)

logger = logging.getLogger(__name__)

EXTENSION_ID = "local.chanlun"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION

# 仓库日K的存储列 (14 列基础 parquet 中可直接列下推的 OHLCV 子集)。
_CZSC_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]

# 买卖点信号函数: v1 字段即类型 (一买/一卖/二买/二卖/三买/三卖), "其他" 表示非信号。
_BUY_SELL_SIGNALS = (
    "cxt_first_buy_V221126",
    "cxt_first_sell_V221126",
    "cxt_second_bs_V240524",
    "cxt_third_bs_V230319",
)
_BUY_SELL_TYPES = frozenset({"一买", "一卖", "二买", "二卖", "三买", "三卖"})

# 滚动识别买卖点的最小 K 线数 (过少时分型/笔尚未成立)。
_MIN_SIGNAL_BARS = 10


def _load_czsc():
    """惰性导入 czsc: 依赖未安装时扩展仍能注册, 仅在调用时报明确错误 (隔离原则)。"""
    try:
        import czsc
        from czsc.utils.plotting.lightweight import plot_czsc

        return czsc, plot_czsc
    except Exception as exc:
        raise HTTPException(
            status_code=501,
            detail=f"czsc 未安装或加载失败, 请先在后端安装依赖 (`uv add 'czsc>=1.0,<2.0'`): {exc}",
        ) from exc


def _fetch_bars(repo, symbol: str, days: int) -> tuple[pd.DataFrame, str]:
    """从本地仓库取近 N 交易日的前复权日K, 转成 czsc 标准八列 DataFrame。"""
    asset_type = repo.resolve_asset_type(symbol)
    end = date.today()
    # 自然日 → 交易日放大: days*2 覆盖周末/节假日, 再 +30 留余量。
    start = end - timedelta(days=days * 2 + 30)
    df = repo.get_daily_asset(asset_type, symbol, start, end, columns=_CZSC_COLUMNS)
    if df.is_empty():
        return pd.DataFrame(), asset_type

    pdf = df.sort("date").to_pandas().rename(columns={"volume": "vol"})
    out = pd.DataFrame({"dt": pd.to_datetime(pdf["date"]), "symbol": symbol})
    for col in ("open", "close", "high", "low", "vol", "amount"):
        if col in pdf.columns:
            out[col] = pd.to_numeric(pdf[col], errors="coerce").fillna(0.0)
        else:
            out[col] = 0.0
    return out, asset_type


def _dt_str(value) -> str:
    """把 czsc 的时间 (pandas Timestamp / datetime) 转成 'YYYY-MM-DD' 字符串。"""
    return str(value)[:10]


def _find_buy_sell_points(czsc, bars: list) -> list[dict]:
    """滚动构造 CZSC, 在历史 K 线上识别买卖点。

    czsc 的买卖点信号是「当前时点」的状态判断 (不含历史序列), 因此对每个时点
    滚动构造 CZSC(bars[:i+1]) 并调用信号函数。信号是持续状态 (一旦成立会连续
    多日返回同一类型), 故用「边沿检测」: 仅在该类型从无到有的那一天记录, 避免
    同一买卖点重复标注。单股详情按需调用, K 线数量有限 (≤ 2000), 成本可控,
    不进入全市场扫描路径。
    """
    from czsc._native.signals import call_signal

    points: list[dict] = []
    active: set[str] = set()
    for i in range(_MIN_SIGNAL_BARS, len(bars)):
        c = czsc.CZSC(bars[: i + 1])
        current: set[str] = set()
        for name in _BUY_SELL_SIGNALS:
            for sig in call_signal(name, c):
                if sig.v1 in _BUY_SELL_TYPES:
                    current.add(sig.v1)
        for ptype in current - active:
            points.append(
                {
                    "dt": _dt_str(bars[i].dt),
                    "type": ptype,
                    "price": round(float(bars[i].close), 2),
                }
            )
        active = current
    points.sort(key=lambda p: p["dt"])
    return points


def _serialize(czsc, bars: list) -> dict:
    """把 CZSC 分析结果转成前端可直接渲染的结构化数据。"""
    c = czsc.CZSC(bars)
    klines = [
        {
            "dt": _dt_str(bar.dt),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "vol": float(bar.vol),
        }
        for bar in bars
    ]
    bis = [
        {
            "sdt": _dt_str(bi.sdt),
            "edt": _dt_str(bi.edt),
            "direction": str(bi.direction),  # 向上 / 向下
            "start_price": float(bi.fx_a.fx),
            "end_price": float(bi.fx_b.fx),
            "high": float(bi.high),
            "low": float(bi.low),
            "power": float(bi.power),
        }
        for bi in c.bi_list
    ]
    zss = [
        {
            "sdt": _dt_str(zs.sdt),
            "edt": _dt_str(zs.edt),
            "zg": float(zs.zg),
            "zd": float(zs.zd),
            "gg": float(zs.gg),
            "dd": float(zs.dd),
        }
        for zs in c.zs_list
    ]
    return {
        "bars": klines,
        "bi": bis,
        "zs": zss,
        "buy_sell": _find_buy_sell_points(czsc, bars),
    }


def setup(registrar: BackendExtensionRegistrar) -> None:
    router = APIRouter(prefix="/api/chan", tags=["chanlun"])

    @router.get("/plot")
    def chan_plot(
        request: Request,
        symbol: str = Query(..., description="标的代码, 如 000001.SZ"),
        days: int = Query(250, ge=30, le=2000, description="K线数量(交易日)"),
        theme: str = Query("dark", pattern="^(light|dark)$"),
    ) -> dict:
        czsc, plot_czsc = _load_czsc()
        repo = request.app.state.repo

        std, asset_type = _fetch_bars(repo, symbol, days)
        if std.empty or len(std) < 10:
            raise HTTPException(
                status_code=404,
                detail="本地无该标的日K数据, 请先在「数据」页同步日K后再试",
            )

        try:
            bars = czsc.format_standard_kline(std, freq=czsc.Freq.D)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"转换K线失败: {exc}") from exc

        if len(bars) < 3:
            raise HTTPException(status_code=422, detail="K线数量不足, 无法识别分型/笔")

        c = czsc.CZSC(bars)
        try:
            html = plot_czsc(c, output="html", theme=theme, tail_bars=days)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"缠论画图失败: {exc}") from exc

        return {
            "symbol": symbol,
            "asset_type": asset_type,
            "bars": len(bars),
            "bi_count": len(c.bi_list),
            "zs_count": len(c.zs_list),
            "html": html,
        }

    @router.get("/analyze")
    def chan_analyze(
        request: Request,
        symbol: str = Query(..., description="标的代码, 如 000001.SZ"),
        days: int = Query(250, ge=30, le=2000, description="K线数量(交易日)"),
    ) -> dict:
        czsc, _ = _load_czsc()
        repo = request.app.state.repo

        std, asset_type = _fetch_bars(repo, symbol, days)
        if std.empty or len(std) < 10:
            raise HTTPException(
                status_code=404,
                detail="本地无该标的日K数据, 请先在「数据」页同步日K后再试",
            )

        try:
            bars = czsc.format_standard_kline(std, freq=czsc.Freq.D)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"转换K线失败: {exc}") from exc

        if len(bars) < 3:
            raise HTTPException(status_code=422, detail="K线数量不足, 无法识别分型/笔")

        data = _serialize(czsc, bars)
        return {
            "symbol": symbol,
            "asset_type": asset_type,
            "bars_count": len(bars),
            "bi_count": len(data["bi"]),
            "zs_count": len(data["zs"]),
            "buy_sell_count": len(data["buy_sell"]),
            **data,
        }

    registrar.include_router(router)
