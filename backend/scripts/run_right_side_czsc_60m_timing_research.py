"""Frozen as-of 60m CZSC B2/B3 timing research on existing V0 snapshots."""

# ruff: noqa: RUF001
from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.custom import chanlun
from app.tickflow.repository import DataStore, KlineRepository

HORIZONS = (1, 3, 5, 10, 20)
TOP_NS = (10, 20, 50)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _points_for_as_of(czsc, frame: pd.DataFrame, as_of: date) -> dict[str, object]:
    """Replay official F1->60m logic, then retain only D-day confirmations.

    ``_analyze_minute_multi`` emits a point only when a closed target bucket is
    processed; no event_time is used for eligibility.
    """
    # This is the 60m-only projection of the formal F1 failover: use the same
    # A-share BarGenerator, the same official signal specs and native CZSC
    # ``call_signal``.  It deliberately does not calculate 15/30/D context,
    # which this phase is forbidden to consume.  Processing only closed F60
    # bars avoids the unrelated multi-timeframe chart work per candidate.
    from czsc._native.signals import call_signal

    raw = chanlun._to_bars(czsc, frame, czsc.Freq.F1)
    # The project BarGenerator requires the ordered A-share ladder even when
    # the study consumes only F60 output.
    generator = czsc.BarGenerator(czsc.Freq.F1, [czsc.Freq.F15, czsc.Freq.F30, czsc.Freq.F60, czsc.Freq.D], market="A股")
    analyzer = None
    seen_times: set[str] = set()
    seen_events: set[tuple] = set()
    points: list[dict] = []
    for bar in raw:
        generator.update(bar)
        bars = generator.bars["60分钟"]
        if not bars:
            continue
        current = bars[-1]
        now = chanlun._dt_str(current.dt)
        if chanlun._dt_str(bar.dt) != now:
            continue
        if now in seen_times:
            continue
        seen_times.add(now)
        analyzer = czsc.CZSC([current]) if analyzer is None else analyzer.update(current) or analyzer
        if len(bars) < chanlun._MIN_SIGNAL_BARS:
            continue
        for name, _, params in chanlun._SIGNAL_SPECS:
            for signal in call_signal(name, analyzer, params):
                if signal.v1 not in {"一买", "二买", "三买"}:
                    continue
                point = chanlun._make_signal_point(analyzer, name=name, key=signal.key, params=params, value=signal.value, confirmation_time=now, price=float(current.close))
                key = chanlun._signal_occurrence_key(point)
                if key not in seen_events:
                    seen_events.add(key)
                    points.append(point)
    day = as_of.isoformat()
    buys = [point for point in points if str(point.get("confirmation_time", "")).startswith(day)]
    by_type = {kind: [point for point in buys if point["type"] == kind] for kind in ("一买", "二买", "三买")}
    b2 = by_type["二买"]
    b3 = by_type["三买"]
    selected = b2 + b3
    latest = max(selected, key=lambda point: str(point["confirmation_time"])) if selected else None
    return {
        "czsc_60_b1": bool(by_type["一买"]), "czsc_60_b2": bool(b2), "czsc_60_b3": bool(b3),
        "czsc_60_setup_type": "B2_OR_B3" if b2 and b3 else "B2" if b2 else "B3" if b3 else "NO_SIGNAL",
        "czsc_60_event_time": latest.get("event_time") if latest else None,
        "czsc_60_confirmation_time": latest.get("confirmation_time") if latest else None,
        "czsc_60_bars_since_confirmation": 0 if latest else None,
        "czsc_60_timing_eligible": bool(selected), "czsc_60_timing_state": "NEW_SIGNAL" if selected else "NO_SIGNAL",
        "czsc_60_source": "minute_bar_generator_60m_only",
    }


def _fmt(value: object, pct: bool = False) -> str:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return "—"
    return f"{float(value) * 100:.2f}%" if pct else f"{float(value):.2f}"


def _table(headers: list[str], rows: list[list[object]]) -> str:
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |", *["| " + " | ".join(map(str, row)) + " |" for row in rows]])


def _pf(values: pd.Series) -> float | None:
    losses = -values[values < 0].sum()
    return float(values[values > 0].sum() / losses) if losses > 0 else None


def _metrics(frame: pd.DataFrame, horizon: int) -> dict:
    cols = [f"return_{horizon}d", f"excess_return_{horizon}d", f"mae_{horizon}d", f"mfe_{horizon}d"]
    data = frame.dropna(subset=cols)
    excess = data[f"excess_return_{horizon}d"]
    return {"n": len(data), "symbols": data.symbol.nunique(), "dates": data.signal_date.nunique(), "mean_return": data[f"return_{horizon}d"].mean(), "median_return": data[f"return_{horizon}d"].median(), "mean_excess": excess.mean(), "median_excess": excess.median(), "positive": (excess > 0).mean(), "pf": _pf(excess), "mae": data[f"mae_{horizon}d"].mean(), "mfe": data[f"mfe_{horizon}d"].mean(), "status": "INSUFFICIENT" if len(data) < 20 or data.signal_date.nunique() <= 2 else ""}


def _metric_table(groups: list[tuple[str, pd.DataFrame]]) -> str:
    rows = []
    for label, frame in groups:
        for horizon in HORIZONS:
            item = _metrics(frame, horizon)
            rows.append([label, f"T+{horizon}", item["n"], item["symbols"], item["dates"], _fmt(item["mean_return"], True), _fmt(item["median_return"], True), _fmt(item["mean_excess"], True), _fmt(item["median_excess"], True), _fmt(item["positive"], True), _fmt(item["pf"]), _fmt(item["mae"], True), _fmt(item["mfe"], True), item["status"]])
    return _table(["group", "horizon", "n", "symbols", "dates", "mean return", "median return", "mean excess", "median excess", "positive excess", "PF", "MAE", "MFE", "sample"], rows)


def _date_values(frame: pd.DataFrame, horizon: int, metric: str) -> pd.Series:
    data = frame.dropna(subset=[f"excess_return_{horizon}d", f"mae_{horizon}d", f"mfe_{horizon}d"])
    if metric == "median_excess":
        return data.groupby("signal_date")[f"excess_return_{horizon}d"].median()
    if metric == "positive":
        return data.assign(_x=data[f"excess_return_{horizon}d"].gt(0)).groupby("signal_date")._x.mean()
    if metric == "mean_excess":
        return data.groupby("signal_date")[f"excess_return_{horizon}d"].mean()
    return data.groupby("signal_date")[f"{metric}_{horizon}d"].mean()


def _comparison(left: pd.DataFrame, right: pd.DataFrame, horizon: int, metric: str, label: str) -> dict:
    joined = pd.concat([_date_values(left, horizon, metric).rename("l"), _date_values(right, horizon, metric).rename("r")], axis=1, join="inner").dropna()
    diff = joined.l - joined.r
    return {"label": label, "metric": metric, "horizon": horizon, "dates": len(diff), "wins": int((diff > 0).sum()), "losses": int((diff < 0).sum()), "ties": int((diff == 0).sum()), "win_rate": (diff > 0).mean() if len(diff) else None, "mean": diff.mean() if len(diff) else None, "median": diff.median() if len(diff) else None}


def _comparison_table(items: list[dict]) -> str:
    return _table(["comparison", "metric", "horizon", "matched dates", "signal wins", "other wins", "ties", "win rate", "mean Δ", "median Δ"], [[x["label"], x["metric"], f"T+{x['horizon']}", x["dates"], x["wins"], x["losses"], x["ties"], _fmt(x["win_rate"], True), _fmt(x["mean"], True), _fmt(x["median"], True)] for x in items])


def _month_text(left: pd.DataFrame, right: pd.DataFrame, metric: str) -> str:
    a, b = _date_values(left, 10, metric), _date_values(right, 10, metric)
    merged = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    if merged.empty:
        return "无重叠月份。"
    merged["month"] = pd.to_datetime(merged.index).strftime("%Y-%m")
    delta = merged.groupby("month").apply(lambda x: (x.a - x.b).mean(), include_groups=False)
    return f"T+10 {metric}: signal 更优 {int((delta > 0).sum())}/{len(delta)} months；" + "、".join(f"{m}={_fmt(v, True)}" for m, v in delta.items())


def _status(signal: pd.DataFrame, base: pd.DataFrame) -> tuple[str, str, str, str]:
    median = _comparison(signal, base, 10, "median_excess", "")
    mae = _comparison(signal, base, 10, "mae", "")
    mfe = _comparison(signal, base, 10, "mfe", "")
    if _metrics(signal, 10)["status"]:
        return "INSUFFICIENT", "INSUFFICIENT", "INSUFFICIENT", "INSUFFICIENT"
    med_ok = (median["win_rate"] or 0) >= 2 / 3 and (median["mean"] or 0) > 0
    risk_ok = (mae["win_rate"] or 0) >= 2 / 3 and (mae["mean"] or 0) > 0
    mfe_ok = (mfe["mean"] or 0) >= -0.25 * abs(_metrics(base, 10)["mfe"] or 0)
    overall = "TIMING_IMPROVED" if (med_ok or risk_ok) and mfe_ok else "MIXED" if any((med_ok, risk_ok, mfe_ok)) else "NO_INCREMENTAL_VALUE"
    return overall, "IMPROVED" if med_ok else "MIXED", "IMPROVED" if risk_ok else "MIXED", "ACCEPTABLE" if mfe_ok else "SACRIFICED"


def _render(frame: pd.DataFrame, source_state: dict) -> str:
    frame.signal_date = pd.to_datetime(frame.signal_date)
    dates = "、".join(sorted(frame.signal_date.dt.strftime("%Y-%m-%d").unique()))
    lines = ["# Right-Side CZSC 60m Timing Research V1", "", "## 冻结边界与实际实现", "", f"样本沿用冻结 random-12：{dates}。Wyckoff 候选、OpportunityScore（0.40 Sector + 0.60 RS）、VP Position/Acceptance/Extension 与未来标签均只读。", "", "正式 CZSC 实现的 B2=`cxt_second_bs_V240524`（di=1,w=9,t=2），B3=`cxt_third_bs_V230319`（di=1,SMA34）。本地原生 60m 仅覆盖 9 个标的，故按正式 failover 调用同一 `CzscSignals + BarGenerator(F1→60m)` 逐根重放。只有 60m 闭合桶当日首次可见的 `confirmation_time` 才标 `NEW_SIGNAL`；`event_time` 只保存结构锚点，不参与资格。无现成有效期，故本 V1 不扩展为 recent-window，`bars_since_confirmation=0` 或空。", "", "## Coverage", ""]
    coverage_rows = []
    for n in TOP_NS:
        base = frame[frame.v0_rank.le(n)]
        for label, column in (("B2", "czsc_60_b2"), ("B3", "czsc_60_b3"), ("B2_OR_B3", "czsc_60_timing_eligible")):
            selected = base[base[column]]
            coverage_rows.append([f"Top{n}", label, len(base), len(selected), f"{len(selected)/len(base):.2%}", selected.symbol.nunique(), selected.signal_date.nunique(), "LOW_COVERAGE" if len(selected)/len(base) < .10 else ""])
    lines.extend([_table(["V0 scope", "setup", "stock-dates", "setup n", "coverage", "symbols", "dates", "warning"], coverage_rows), "", "覆盖率 <10% 必须按小样本处理，即使结果漂亮也不能形成正式结论。", ""])
    summary_rows = []
    for n in TOP_NS:
        base = frame[frame.v0_rank.le(n)]
        groups = [(f"C0 Top{n}", base)]
        for label, col in (("C1 B2", "czsc_60_b2"), ("C2 B3", "czsc_60_b3"), ("C3 B2_OR_B3", "czsc_60_timing_eligible")):
            signal = base[base[col]]
            no_signal = base[~base[col]]
            groups.extend([(f"{label} Top{n}", signal), (f"{label} NO_SIGNAL Top{n}", no_signal)])
            comparisons = [_comparison(signal, no_signal, h, metric, f"{label} - NO_SIGNAL") for h in (3, 5, 10, 20) for metric in ("median_excess", "positive", "mae", "mfe")]
            lines.extend([f"## Top{n} · {label}", "", _metric_table([(f"C0 Top{n}", base), (f"{label}", signal), ("NO_SIGNAL", no_signal)]), "", "同一 Opportunity TopN：Timing signal - NO_SIGNAL 的日期等权比较（MAE 正差为风险改善）：", "", _comparison_table(comparisons), "", f"月份一致性（相对 NO_SIGNAL）：{_month_text(signal, no_signal, 'median_excess')}；{_month_text(signal, no_signal, 'mae')}", ""])
            overall, med, risk, mfe = _status(signal, no_signal)
            summary_rows.append([f"C{1 if label == 'C1 B2' else 2 if label == 'C2 B3' else 3} Top{n}", overall, med, risk, mfe, f"{len(signal)/len(base):.2%}"])
    lines.extend(["## 状态与下一阶段判断", "", _table(["version", "overall", "Median Effect", "Entry Risk Effect", "MFE Preservation", "coverage"], summary_rows), "", "结论规则：只有 median excess 或 MAE 至少一项在 T+10 跨日期稳定改善，且 MFE 未严重牺牲、覆盖率足够，才可进入 30m Trigger。", "", "本报告的最终判断由上表决定：若 C1/C2/C3 没有 `TIMING_IMPROVED`，则 **不进入 60m Setup + 30m Trigger**；应先分析 60m setup 的覆盖与结构质量。CZSC 在本阶段仍仅是 Timing Eligible/Not Eligible，不是 Opportunity 加分、候选池、VP 过滤或正式 Final Rank。", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen 60m CZSC timing study")
    parser.add_argument("--input-dir", type=Path, default=Path("../data/research/right_side_rank_research_v1_20260913"))
    parser.add_argument("--output-dir", type=Path, default=Path("../data/research/right_side_czsc_60m_timing_v1_20260913"))
    parser.add_argument("--report", type=Path, default=Path("../docs/right-side-czsc-60m-timing-v1.md"))
    parser.add_argument("--rebuild", action="store_true", help="rebuild only derived CZSC research checkpoints")
    args = parser.parse_args()
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    source_state = _read(source / "progress.json")
    if source_state.get("status") != "complete":
        raise ValueError("Rank Research V1 checkpoints are incomplete")
    out_snapshots, state_path = output / "snapshots", output / "progress.json"
    out_snapshots.mkdir(parents=True, exist_ok=True)
    state = _read(state_path) or {"status": "running", "date_runs": {}, "source": str(source)}
    repo = KlineRepository(DataStore(Path("../data").resolve()))
    czsc, _ = chanlun._load_czsc()
    started = time.perf_counter()
    for path in sorted((source / "snapshots").glob("signal_date=*.parquet")):
        target = out_snapshots / path.name
        key = path.stem.removeprefix("signal_date=")
        if target.exists() and not args.rebuild:
            continue
        began = time.perf_counter()
        frame = pd.read_parquet(path)
        as_of = pd.Timestamp(frame.signal_date.iloc[0]).date()
        symbols = frame.loc[frame.v0_rank.le(50), "symbol"].astype(str).tolist()
        available = repo.list_minute_dates(as_of - timedelta(days=140), as_of)
        dates = available[-60:]
        minute = repo.get_minute_by_dates(symbols, dates)
        annotations = []
        for _, row in frame.iterrows():
            if row["symbol"] not in symbols:
                annotations.append({"czsc_60_b1": False, "czsc_60_b2": False, "czsc_60_b3": False, "czsc_60_setup_type": "NOT_IN_TOP50", "czsc_60_event_time": None, "czsc_60_confirmation_time": None, "czsc_60_bars_since_confirmation": None, "czsc_60_timing_eligible": False, "czsc_60_timing_state": "NOT_EVALUATED", "czsc_60_source": None})
                continue
            piece = minute.filter(minute["symbol"] == row["symbol"])
            try:
                standard = chanlun._validate_and_standardize(piece, str(row["symbol"]), timestamp_col="datetime")
                annotations.append(_points_for_as_of(czsc, standard, as_of))
            except Exception as exc:
                annotations.append({"czsc_60_b1": False, "czsc_60_b2": False, "czsc_60_b3": False, "czsc_60_setup_type": "UNAVAILABLE", "czsc_60_event_time": None, "czsc_60_confirmation_time": None, "czsc_60_bars_since_confirmation": None, "czsc_60_timing_eligible": False, "czsc_60_timing_state": "NO_SIGNAL", "czsc_60_source": f"unavailable:{type(exc).__name__}"})
        result = pd.concat([frame.reset_index(drop=True), pd.DataFrame(annotations)], axis=1)
        result.to_parquet(target, index=False)
        state["date_runs"][key] = {"status": "complete", "rows": len(result), "top50": len(symbols), "minute_dates": len(dates), "elapsed_seconds": time.perf_counter() - began}
        _write(state_path, state)
        print(f"completed {key}: {len(symbols)} Top50 candidates")
    combined = pd.concat([pd.read_parquet(path) for path in sorted(out_snapshots.glob("signal_date=*.parquet"))], ignore_index=True)
    state.update({"status": "complete", "elapsed_seconds": time.perf_counter() - started})
    _write(state_path, state)
    args.report.resolve().write_text(_render(combined, source_state), encoding="utf-8")
    print(f"wrote {args.report.resolve()}")


if __name__ == "__main__":
    main()
