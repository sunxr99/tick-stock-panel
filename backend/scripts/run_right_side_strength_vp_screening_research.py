"""Frozen S100/S150/S200 Opportunity broad-pool VP routing research."""

# ruff: noqa: RUF001
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

POOLS = (100, 150, 200)
H = (1, 3, 5, 10, 20)
BUCKETS = ("LOW", "MEDIUM", "HIGH", "EXTREME", "UNKNOWN")


def rd(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def wr(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2), encoding="utf-8")


def fmt(x, p=False):
    return (
        "—"
        if x is None or pd.isna(x) or not np.isfinite(float(x))
        else f"{float(x) * 100:.2f}%"
        if p
        else f"{float(x):.2f}"
    )


def tab(h, r):
    return "\n".join(
        [
            "| " + " | ".join(h) + " |",
            "| " + " | ".join(["---"] * len(h)) + " |",
            *["| " + " | ".join(map(str, x)) + " |" for x in r],
        ]
    )


def pf(x):
    losses = -x[x < 0].sum()
    return x[x > 0].sum() / losses if losses > 0 else None


def met(f, n):
    d = f.dropna(subset=[f"return_{n}d", f"excess_return_{n}d", f"mae_{n}d", f"mfe_{n}d"])
    e = d[f"excess_return_{n}d"]
    return dict(
        n=len(d),
        sym=d.symbol.nunique(),
        dates=d.signal_date.nunique(),
        mr=d[f"return_{n}d"].mean(),
        mdr=d[f"return_{n}d"].median(),
        me=e.mean(),
        med=e.median(),
        pos=(e > 0).mean(),
        pf=pf(e),
        mae=d[f"mae_{n}d"].mean(),
        mfe=d[f"mfe_{n}d"].mean(),
        status="INSUFFICIENT" if len(d) < 20 or d.signal_date.nunique() <= 2 else "",
    )


def mt(groups, hs=H):
    r = []
    for label, f in groups:
        for n in hs:
            x = met(f, n)
            r.append(
                [
                    label,
                    f"T+{n}",
                    x["n"],
                    x["sym"],
                    x["dates"],
                    fmt(x["mr"], 1),
                    fmt(x["mdr"], 1),
                    fmt(x["me"], 1),
                    fmt(x["med"], 1),
                    fmt(x["pos"], 1),
                    fmt(x["pf"]),
                    fmt(x["mae"], 1),
                    fmt(x["mfe"], 1),
                    x["status"],
                ]
            )
    return tab(
        [
            "group",
            "horizon",
            "n",
            "symbols",
            "dates",
            "mean return",
            "median return",
            "mean excess",
            "median excess",
            "positive",
            "PF",
            "MAE",
            "MFE",
            "sample",
        ],
        r,
    )


def ds(f, n, k):
    d = f.dropna(subset=[f"excess_return_{n}d", f"mae_{n}d", f"mfe_{n}d"])
    if k == "mean excess":
        return d.groupby("signal_date")[f"excess_return_{n}d"].mean()
    if k == "median excess":
        return d.groupby("signal_date")[f"excess_return_{n}d"].median()
    if k == "positive":
        return d.assign(q=d[f"excess_return_{n}d"].gt(0)).groupby("signal_date").q.mean()
    return d.groupby("signal_date")[f"{k}_{n}d"].mean()


def cmp(a, b, n, k, label):
    z = pd.concat([ds(a, n, k).rename("a"), ds(b, n, k).rename("b")], axis=1, join="inner").dropna()
    x = z.a - z.b
    return [
        label,
        k,
        f"T+{n}",
        len(x),
        int((x > 0).sum()),
        int((x < 0).sum()),
        int((x == 0).sum()),
        fmt((x > 0).mean() if len(x) else None, 1),
        fmt(x.mean() if len(x) else None, 1),
        fmt(x.median() if len(x) else None, 1),
    ]


def month(a, b, k):
    z = pd.concat(
        [ds(a, 10, k).rename("a"), ds(b, 10, k).rename("b")], axis=1, join="inner"
    ).dropna()
    if z.empty:
        return "no matched months"
    z["m"] = pd.to_datetime(z.index).strftime("%Y-%m")
    q = z.groupby("m").apply(lambda x: (x.a - x.b).mean(), include_groups=False)
    return f"{k}: filtered better {int((q > 0).sum())}/{len(q)} months; " + "、".join(
        f"{m}={fmt(v, 1)}" for m, v in q.items()
    )


def render(f, state):
    f.signal_date = pd.to_datetime(f.signal_date)
    dates = "、".join(sorted(f.signal_date.dt.strftime("%Y-%m-%d").unique()))
    lines = [
        "# Strength Broad Pool + VP Screening Research V1",
        "",
        "## Frozen input",
        "",
        f"Random-12 signal dates: {dates}。仅读取已落盘 ALL_WYCKOFF / Opportunity / VP snapshot；不重跑或修改 Wyckoff、Sector/RS、VP、Extension 或收益标签。",
        "",
        "`OpportunityScore = 0.40 × SectorScore + 0.60 × RSScore` 保持冻结。S100/S150/S200 是固定实验组，不是参数寻优。VP 不改 Opportunity，P1/P2/P3 均不补位。",
        "",
        "## Broad Pool P0",
        "",
        mt([("ALL_WYCKOFF", f), *[(f"S{p} P0", f[f.v0_rank.le(p)]) for p in POOLS]]),
        "",
    ]
    for p in POOLS:
        base = f[f.v0_rank.le(p)]
        groups = [(f"S{p} P0", base)] + [
            (f"S{p} {b}", base[base.risk_bucket.eq(b)]) for b in BUCKETS
        ]
        cov = []
        for lab, x in [
            ("P1 no EXTREME", base[base.risk_bucket.isin(["LOW", "MEDIUM", "HIGH"])]),
            ("P2 LOW+MEDIUM", base[base.risk_bucket.isin(["LOW", "MEDIUM"])]),
            ("P3 HIGH+EXTREME", base[base.risk_bucket.isin(["HIGH", "EXTREME"])]),
        ]:
            cov.append(
                [
                    f"S{p}",
                    lab,
                    len(x),
                    f"{len(x) / len(base):.2%}",
                    x.symbol.nunique(),
                    x.signal_date.nunique(),
                ]
            )
        lines += [
            f"## S{p}: Risk Buckets and Coverage",
            "",
            mt(groups, (5, 10, 20)),
            "",
            tab(["pool", "version", "n", "coverage", "symbols", "dates"], cov),
            "",
        ]
        versions = [
            ("P1 no EXTREME", base[base.risk_bucket.isin(["LOW", "MEDIUM", "HIGH"])]),
            ("P2 LOW+MEDIUM", base[base.risk_bucket.isin(["LOW", "MEDIUM"])]),
            ("P3 HIGH+EXTREME", base[base.risk_bucket.isin(["HIGH", "EXTREME"])]),
        ]
        for lab, x in versions:
            rows = [
                cmp(x, base, n, k, f"S{p} {lab} - P0")
                for n in (5, 10, 20)
                for k in ("mean excess", "median excess", "positive", "mae", "mfe")
            ]
            lines += [
                f"### S{p} {lab} vs P0",
                "",
                tab(
                    [
                        "comparison",
                        "metric",
                        "horizon",
                        "dates",
                        "filtered wins",
                        "P0 wins",
                        "ties",
                        "win rate",
                        "mean Δ",
                        "median Δ",
                    ],
                    rows,
                ),
                "",
                f"Month consistency: {month(x, base, 'median excess')}; {month(x, base, 'mae')}",
                "",
            ]
        pos = []
        for b in BUCKETS:
            x = base[base.risk_bucket.eq(b)]
            pos.append(
                [
                    b,
                    len(x),
                    f"{len(x) / len(base):.2%}",
                    f"{(x.vp20_position.eq('ABOVE_VAH') | x.vp60_position.eq('ABOVE_VAH')).mean():.2%}"
                    if len(x)
                    else "—",
                    f"{(x.vp20_acceptance.eq('ABOVE_VAH_ACCEPTED') | x.vp60_acceptance.eq('ABOVE_VAH_ACCEPTED')).mean():.2%}"
                    if len(x)
                    else "—",
                ]
            )
        lines += [
            f"### S{p} Position / Acceptance context (not filters)",
            "",
            tab(["risk bucket", "n", "share", "any ABOVE_VAH", "any formal acceptance D"], pos),
            "",
        ]
    lines += [
        "## Conclusions",
        "",
        "Read the pooled tables with the date/month tables: a hard filter is allowed only if P1/P2 improve median/MAE across dates without material MFE loss. Otherwise High/Extreme remain a high-momentum/high-path-risk route, not “bad” candidates.",
        "",
        "Recommendation rule: `HARD_FILTER` requires stable date-level MAE/median improvement and acceptable MFE loss; `SOFT_ROUTING` applies when High/Extreme retain right-tail MFE/alpha while path risk is higher; `CONTEXT_ONLY` applies if buckets show no separation. No final TopN or formal optimal pool is created here.",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input-dir",
        type=Path,
        default=Path("../data/research/right_side_rank_research_v1_20260913"),
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../data/research/right_side_strength_vp_screening_v1_20260913"),
    )
    ap.add_argument(
        "--report", type=Path, default=Path("../docs/right-side-strength-vp-screening-v1.md")
    )
    a = ap.parse_args()
    src = a.input_dir.resolve()
    out = a.output_dir.resolve()
    st = rd(src / "progress.json")
    if st.get("status") != "complete":
        raise ValueError("Rank V1 input incomplete")
    od = out / "snapshots"
    od.mkdir(parents=True, exist_ok=True)
    pr = out / "progress.json"
    state = rd(pr) or {"status": "running", "source": str(src), "date_runs": {}}
    t = time.perf_counter()
    for p in sorted((src / "snapshots").glob("signal_date=*.parquet")):
        q = od / p.name
        key = p.stem.removeprefix("signal_date=")
        if not q.exists():
            x = pd.read_parquet(p).copy()
            x["opportunity_rank"] = x.v0_rank
            x["in_top100"] = x.v0_rank.le(100)
            x["in_top150"] = x.v0_rank.le(150)
            x["in_top200"] = x.v0_rank.le(200)
            x.to_parquet(q, index=False)
            state["date_runs"][key] = {"status": "complete", "rows": len(x)}
            wr(pr, state)
    f = pd.concat([pd.read_parquet(p) for p in sorted(od.glob("*.parquet"))], ignore_index=True)
    state.update(status="complete", elapsed_seconds=time.perf_counter() - t)
    wr(pr, state)
    a.report.resolve().write_text(render(f, st), encoding="utf-8")
    print(a.report.resolve())


if __name__ == "__main__":
    main()
