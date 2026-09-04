import glob

import pandas as pd
import polars as pl

from app.custom.chanlun import _load_czsc

czsc, _ = _load_czsc()
base = "../data/kline_daily"
parts = sorted(glob.glob(base + "/date=*"))
rows = []
for p in parts:
    d = pl.read_parquet(p, columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"])
    h = d.filter(pl.col("symbol").str.contains("601288"))
    if not h.is_empty():
        rows.append(h.row(0, named=True))
print("601288 农业银行 K线总数:", len(rows))
pdf = pl.DataFrame(rows).sort("date").to_pandas().rename(columns={"volume": "vol"})
pdf["dt"] = pd.to_datetime(pdf["date"])
sub = pdf.tail(400).reset_index(drop=True)
bars = czsc.format_standard_kline(sub[["dt", "symbol", "open", "close", "high", "low", "vol", "amount"]], freq=czsc.Freq.D)
c = czsc.CZSC(bars)
print("=== 笔 (共", len(c.bi_list), "笔) ===")
for i, bi in enumerate(c.bi_list):
    print(i, str(bi.sdt)[:10] + "~" + str(bi.edt)[:10], str(bi.direction),
          round(bi.fx_a.fx, 2), "->", round(bi.fx_b.fx, 2))
print()
print("=== 中枢 (共", len(c.zs_list), "个) ===")
for i, zs in enumerate(c.zs_list):
    print(i, str(zs.sdt)[:10] + "~" + str(zs.edt)[:10], "zg=", round(zs.zg, 2), "zd=", round(zs.zd, 2))
