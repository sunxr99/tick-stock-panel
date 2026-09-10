# CZSC V1 审计

## KEEP

- `get_daily_asset` 的前复权 OHLC、`volume→vol`、`Freq.D`、`format_standard_kline`、`CZSC(bars)` 正确。
- 笔来自原生 `finished_bis`，中枢来自原生 `zs_list`；项目未自行重算。
- 买卖点来自四个 CZSC `cxt_*` signal，历史以每个当时 bars 快照计算，未直接读取未来序列。

## FIX

- 不再把缺失字段/NaN 填 0；重复 dt、非法 OHLC 现 fail-closed。
- 笔、中枢、信号新增 `event_time/confirmation_time/status`；信号 marker 画在确认时刻，避免把结构端点伪装为当时可交易点。
- 前端切换标的时清空旧图并用请求版本防止旧响应覆盖新标的。
- 日线窗口按北京时间截为请求的实际交易日数量；分析层排除盘中未闭合日K与分钟桶。原生分钟路径还要求 15/30/60 分钟均覆盖该日线窗口的每个交易日，否则降级为 F1。
- F1 分钟 B/S 的日线高周期上下文改由主日线历史按时间推进，不再使用短分钟窗口聚合出的另一份日线状态。
- 日线选股新增 `czsc_daily_buy_point`：仅保留最后一根已收盘日K首次确认的 B1/B2/B3，以前一日 snapshot 的原始 signal 与笔锚点去重；不会把旧结构的重复 B 点当作当天信号。
- Wyckoff 漏斗结果可按同一 CZSC 新 B 点二次过滤：仅 enrich 已通过 L3 的候选，不将该辅助条件写回漏斗正式选择。
- 修复日线图与选股的 B/S 事件识别：同一结构锚点的原始状态重现不新增 marker 或筛选结果，避免将同一 B 点反复显示为新的交易事件。

## REFACTOR

- 引入最小 `MultiTimeframeCZSCResult` 与数据适配辅助函数，为 V2 服务；未重写日线 V1 或引入交易器。

## VERIFY

- 收盘边界以北京时间处理；盘中同步可落盘，但分析结果不会采用未闭合的当日日K、当前 1 分钟K或 15/30/60 分钟桶。
- 交易日缺失只能由交易日历/供应商质量报告判定，当前接口不补造停牌 K。
