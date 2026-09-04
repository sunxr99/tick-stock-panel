# 阶段 2 完成：czsc 缠论 ECharts 原生叠加 + 买卖点标注

> 目标：把阶段 1 的「iframe 嵌入 czsc HTML」升级为「后端结构化 JSON + 前端 ECharts 原生渲染」，
> 并在图上标注缠论一二三类买卖点。
> 分级：L2（后端路由 + 前端插槽），不改任何核心源码（沿用阶段 1 已完成的插槽类型修复）。

---

## 1. 交付了什么

个股详情对话框底部的「缠论结构」面板现在用 **ECharts 原生图**渲染，一张图内叠加：

- **K 线**（candlestick，涨红跌绿）
- **笔**（橙色线段，连接分型点）
- **中枢**（半透明蓝色矩形，zg/zd 区间）
- **买卖点**（红 B1/B2/B3 = 一二三买，绿 S1/S2/S3 = 一二三卖）
- 支持 dataZoom 缩放、十字光标、tooltip、跟随浅色/深色主题

阶段 1 的 `/api/chan/plot`（iframe）保留，向后兼容；新增 `/api/chan/analyze` 走原生渲染。

---

## 2. 修改思路

### 2.1 后端：结构化接口 `/api/chan/analyze`

新增接口返回前端可直接渲染的 JSON（不再依赖 czsc 的 HTML 画图）：

```json
{
  "bars": [{ "dt": "2025-05-30", "open": 10, "high": 11, "low": 9, "close": 10.8, "vol": 1000 }],
  "bi":   [{ "sdt": "...", "edt": "...", "direction": "向上", "start_price": 106.27, "end_price": 114.74, "power": 8.47 }],
  "zs":   [{ "sdt": "...", "edt": "...", "zg": 129.69, "zd": 122.01, "gg": 140.92, "dd": 106.27 }],
  "buy_sell": [{ "dt": "...", "type": "一买", "price": 105.55 }]
}
```

字段来源（czsc 1.0.1 Rust 对象，实测确认）：

| JSON 字段 | czsc 来源 |
| :--- | :--- |
| `bi.direction` | `str(bi.direction)` → "向上"/"向下" |
| `bi.start_price` / `end_price` | `bi.fx_a.fx` / `bi.fx_b.fx`（笔两端分型价） |
| `zs.zg/zd/gg/dd` | `zs.zg`（上沿）/`zd`（下沿）/`gg`（最高）/`dd`（最低） |
| K 线 | `RawBar.open/high/low/close/vol` |

### 2.2 买卖点：用 czsc 内置信号函数（不是自己写背驰算法）

关键发现：**czsc 已内置缠论买卖点信号函数**，无需自己实现背驰判断。信号对象
`Signal` 的 `v1` 字段即买卖点类型：

| 信号函数 | `v1` 取值 | 含义 |
| :--- | :--- | :--- |
| `cxt_first_buy_V221126` | "一买" | 第一类买点（底背驰） |
| `cxt_first_sell_V221126` | "一卖" | 第一类卖点（顶背驰） |
| `cxt_second_bs_V240524` | "二买" / "二卖" | 第二类买卖点 |
| `cxt_third_bs_V230319` | "三买" / "三卖" | 第三类买卖点 |

> 备选：`cxt_third_buy_V230228`（k3="三买辅助"）只给方向不区分买卖，故改用
> `cxt_third_bs_V230319`（`v1` 明确区分三买/三卖）。

### 2.3 买卖点历史序列：滚动 + 边沿检测

czsc 的买卖点信号是**当前时点状态判断**（不含历史序列），且一旦成立会**连续多日
返回同一类型**。因此：

1. **滚动**：对每个历史时点构造 `CZSC(bars[:i+1])` 并调用 `call_signal`。
2. **边沿检测**：仅在类型从「无」到「有」的那一天记录，避免同一买卖点重复标注。

实测：边沿检测前 126 个重复点 → 25 个有效买卖点（一买 8 / 三卖 5 / 一卖 3 / 三买 2 / 二买 3 / 二卖 4）。
单股 250 根 K 线全量滚动约 0.26s，仅单股详情按需调用，不进入全市场扫描路径。

### 2.4 前端：ECharts 原生渲染

在 `stock-preview.footer` 插槽内自建 ECharts 图（不侵入核心 `EChartsCandlestick`）：

- **K 线**：`candlestick` series
- **笔**：`markLine`（`xAxis` 用日期字符串定位）
- **中枢**：`markArea`（zd→zg 矩形）
- **买卖点**：`markPoint`（`symbol: 'arrow'`，买点朝上红、卖点朝下绿）
- 复用项目语义色 `bull=#C74040` / `bear=#2D9B65`，主题走 `useChartTheme()`
- markPoint/markArea/markLine 的 data 用 `any[]`（与核心 `EChartsCandlestick` 同一处理方式，规避 ECharts 元组类型的严格校验）

---

## 3. 修改文件清单

| 文件 | 类型 | 说明 |
| :--- | :--- | :--- |
| `backend/app/custom/chanlun.py` | 修改 | 新增 `/api/chan/analyze`、`_serialize`、`_find_buy_sell_points` |
| `backend/tests/test_chanlun_extension.py` | 修改 | 新增结构化序列化 + 买卖点边沿检测测试 |
| `frontend/src/custom/chanlun/extension.tsx` | 修改 | 由 iframe 改为 ECharts 原生渲染（K线+笔+中枢+买卖点） |

> 未改动任何核心源码；阶段 1 的插槽类型修复（`types.ts`/`registry.ts`）沿用。

---

## 4. 验证结果（实际执行）

| 验证 | 命令 | 结果 |
| :--- | :--- | :--- |
| 结构化输出 | `_serialize` 跑 mock 日K | 29 笔 / 4 中枢 / 25 买卖点 / 0.26s |
| 买卖点类型分布 | 边沿检测后 | 一买8/一卖3/二买3/二卖4/三买2/三卖5 |
| 路由注册 | `chanlun.setup(registrar)` | `/api/chan/plot` + `/api/chan/analyze` |
| 后端 lint | `ruff check` | All checks passed |
| 单元测试 | `pytest tests/test_chanlun_extension.py` | 5 passed |
| 前端构建 | `pnpm build` | 通过（extension chunk 1.6KB → 4.7KB） |
| diff 检查 | `git diff --check` | 无输出（通过） |

---

## 5. 验收方法

1. 重启 dev：`.\dev.ps1`。
2. 打开个股详情 → 日 K 视图 → 底部「缠论结构」面板 → 点「开始分析」。
3. 应看到 K 线图上叠加：橙色笔、蓝色中枢、红色 B1/B2/B3 与绿色 S1/S2/S3 买卖点。
4. 可缩放（底部 dataZoom）查看历史买卖点；切换主题时图表配色跟随。
5. 接口自测：`http://localhost:3018/api/chan/analyze?symbol=000001.SZ&days=250`，
   返回含 `bars/bi/zs/buy_sell` 的 JSON。

---

## 6. 遗留风险与后续

- **买卖点漂移**：缠论结构随新 K 线变化，历史买卖点会动态变化（czsc 通病）；本阶段按当前快照标注，不持久化。
- **笔的颜色**：ECharts 单个 markLine 无法按笔区分红绿，当前统一橙色；如需向上/向下分色需额外 series（阶段 3 可选）。
- **买卖点精度**：买卖点价格暂用当日收盘价，非精确的笔端点/分型价；如需精确到点位可改为取对应笔的 `high/low`。
- **性能**：滚动 CZSC 是 O(n²)，250 根 0.26s 可接受；`days` 上限 2000 时约 4-5s，仍仅单股按需调用。
- **Free/Pro 兼容**：日线缠论 + 买卖点全走本地 enriched，Free 可用；分钟级缠论（BarGenerator 合成）需 Pro+ 分钟数据，属后续扩展。
- **阶段 3 预告**：① 买卖点价格精确到笔端点；② 笔按方向分色；③（可选）分钟级多级别联立。
