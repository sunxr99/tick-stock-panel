# CZSC 当前信号目录

所有信号是结构状态，**不是** BUY/SELL 指令；前端称“结构信号”。标记在 `confirmation_time`，并保留结构 `event_time`。

| signal | 上游 | 参数/依赖 | 原始语义 | 回画/回测 |
|---|---|---|---|---|
| `cxt_first_buy_V221126` | `cxt.rs` | `di=1`，5–21笔 | `check_first_buy` 命中一买 | 最后笔确认后才可用 |
| `cxt_first_sell_V221126` | `cxt.rs` | `di=1`，5–21笔 | `check_first_sell` 命中一卖 | 同上 |
| `cxt_second_bs_V240524` | `cxt.rs` | `di=1,w=9,t=2` | 最后一笔端分型重叠计数的二买/二卖 | 需已完成笔且 `bars_ubi<=7` |
| `cxt_third_bs_V230319` | `cxt.rs` | `di=1,SMA(34)` | 五笔中枢离开后的三买/三卖**辅助** | 不是独立交易决策 |
| `cxt_bi_status_V230101` | `cxt.rs` | `D1` | 最后一笔表里关系 / 分型状态 | 当前质量摘要；不画买卖 marker |
| `tas_ma_base_V221101` | `tas.rs` | `D1,SMA(20)` | SMA20 分类与方向 | 当前质量摘要；不画买卖 marker |
| `tas_macd_base_V221028` | `tas.rs` | `D1,MACD(12,26,9)` | MACD 多空与方向 | 当前质量摘要；不画买卖 marker |
| `bar_vol_grow_V221112` | `bar.rs` | `D1,K5` | 相对近 5 根K是否放量 | 当前质量摘要；不画买卖 marker |

日线使用逐根历史快照计算。优先原生分钟路径按真实时间逐根更新各自的 `CZSC` 并调用同一组 signal；同一时刻按 60→30→15 分钟处理，低周期上下文只读取已闭合的高周期结构。原生数据不完整时，分钟降级为 `CzscSignals.s`，且只在高周期桶结束采样。未来回测以 `confirmation_time` 为信号可见时点；`event_time` 只用于结构定位。

## 日线 B 点选股

`czsc_daily_buy_point` 只使用本表前四个 B/S 信号中的 `一买/二买/三买` 值。对每个标的它先比较最后一根已收盘日K与前一根的 CZSC 快照；只有边沿出现后才向前核验同一 signal 名、原始 value 与笔锚点是否已确认。历史状态重现不会再次入选。该策略不筛选一卖/二卖/三卖，不扫描分钟周期，也不以质量摘要或共振追加筛选条件。

Wyckoff 结果的 CZSC 开关复用完全相同的 B 点定义；它只对 L3 候选附加 `czsc_buy_types` 等证据，不能把开关结果理解为 Wyckoff 或 CZSC 的新 signal 定义。

## 当前 DTO 与展示

CZSC 原生 `Signal` 的固定字段是 `k1/k2/k3/v1/v2/v3/score`，并提供 `key`、`value` 与完整字符串。`buy_sell[].signal` 保留 B/S 的 `signal_name`、`signal_key`、`raw_signal`、`raw_value`、上述 values、运行参数，以及能从原始 `v2` 直接读出的 `structure_count`（如 `5笔`）和 `subcondition`（如 `均线顶分`）。每个 `timeframe.state.quality[]` 额外透传笔状态、SMA20、MACD 与量能的当前原始值，作为人工核对结构质量的辅助证据；它们不生成 marker、评分或交易指令。

每个 marker 同时带有 `structure_anchor`：这是 signal 函数实际读取的 `c.bi_list` 最新笔的 `sdt/edt/direction`，不是项目自创 ID。去重键为 `signal_name + raw_value + anchor(sdt, edt)`：同一原始信号对同一笔锚点只标首次确认；中间消失后以相同锚点重新出现不构成新事件。相同 B1 但 5/9/13 笔窗口或锚点不同会保留为不同事件。CZSC 的 B/S 函数没有独立的 candidate/invalidated 状态；它们在已闭合目标周期K的 `confirmation_time` 首次可见，基础结构取自 `bi_list`，因此前端使用 `confirmed` 仅表示“该快照可见”，不等同交易建议。

`cxt_bi_base_V230228` 额外作为**上下文**而非买卖点读取。它原生输出 `向上/向下 + 中继/转折`，来源是最后一笔与未完成笔 `bars_ubi`；不是本项目自行计算的趋势。15 分钟检查当时 30/60/日线状态，30 分钟检查 60/日线，60 分钟检查日线；只有全部声明的高周期状态可用时才给出 `顺高周期结构 / 逆高周期结构 / 高周期冲突`，否则为 `上下文不明确`。所有 CZSC 原始 signal 始终绘制，逆高周期仅作灰色、低透明度的“逆势反弹 / 潜在转折”标识，不做过滤、评分或交易决策。
