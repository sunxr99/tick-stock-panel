# CZSC 多周期关系与共振

## 范围与边界

本能力位于单周期 CZSC 计算之后，只比较独立的 `日线`、`60分钟`、`30分钟`、`15分钟` 快照：

```text
四个独立 CZSC Result → timeframe state → resonance result → 前端摘要 / 日线 marker
```

它不创建混合周期 CZSC，不重算 RawBar、分型、笔、中枢或 B/S，也不调用 `CzscTrader`。B/S 仅是单周期结构证据；共振不是 BUY/SELL 指令，更没有 0–100 综合评分。

当前实现只提供**当前状态**。未以历史完整数据事后扫描生成 `List<ResonanceEvent>`，所以不会将后来才确认的关系回画为历史信号。

## 代码入口与数据流

- 后端关系层：`backend/app/custom/chanlun.py::_timeframe_state`、`_analyze_resonance`。
- API：`GET /api/chan/analyze` 在组装 `timeframes` 后调用 `_analyze_resonance(symbol, states)`，返回顶层 `resonance`。
- 前端：`frontend/src/custom/chanlun/extension.tsx::ChanlunFooter` 渲染摘要；`buildOption` 仅在日线主图画当前 `resonance.event` 的星形 marker。

每周期状态直接读取已存在的 CZSC `cxt_bi_base_V230228`：`向上/向下` 映射为 `BULLISH/BEARISH`，`中继/转折` 映射为 `UP_CONTINUATION`、`UP_TURNING`、`DOWN_CONTINUATION`、`DOWN_TURNING`。这是原生信号的展示映射，不是项目另行判定趋势。状态还透传最新笔、分型、中枢、笔状态、SMA20、MACD、量能和原始 signal detail，供人工钻取；后四项不参与共振关系或交易判断。

## 周期职责

| 周期 | 关系层用途 |
| --- | --- |
| 日线 | 主结构与大级别 bias |
| 60分钟 | 日线内部回调 / 反弹背景 |
| 30分钟 | 调整是否出现过渡、止跌或转弱迹象 |
| 15分钟 | 最小已确认结构条件 |

周线/月线目前没有进入等权判断；如后续已有独立结果，只能作为 higher-timeframe bias 补充，不能改成投票。

## 当前支持的关系模式

判断是严格的方向组合，目的在于保持第一版可解释、可测试，而非声称完整交易策略。

| `resonance_type` | 状态组合（日 / 60 / 30 / 15） | 输出含义 | warning |
| --- | --- | --- | --- |
| `PULLBACK_REVERSAL_BULLISH` | 多 / 空 / 多 / 多 | 日线偏多中的回调转强 | `M60_PULLBACK_ACTIVE` |
| `TREND_CONTINUATION_BULLISH` | 多 / 多 / 多 / 多 | 四周期同向上 | `NOT_AN_ENTRY_INSTRUCTION` |
| `COUNTERTREND_BOUNCE` | 空 / 空 / 多 / 多 | 逆日线的低周期反弹 | `COUNTER_TREND` |
| `PULLBACK_REVERSAL_BEARISH` | 空 / 多 / 空 / 空 | 日线偏空中的反弹转弱 | `M60_REBOUND_ACTIVE` |
| `TIMEFRAME_CONFLICT` | 其他组合 | 未形成已定义层级链 | `TIMEFRAME_CONFLICT` |

任一必需周期不存在或为 `UNKNOWN` 时，返回 `TIMEFRAME_CONFLICT + INSUFFICIENT_DATA`，且不生成 marker/event。四个状态的最后可用交易日不一致时，同样拒绝拼接旧状态，返回 `TIMEFRAME_CONFLICT + STALE_TIMEFRAME_DATA`。

## 结果契约

`resonance` 包含：

- `symbol`、`analysis_time`、`resonance_type`、`direction`、`summary`；
- `timeframe_states`：四周期原生状态和最近结构；
- `evidence[]`：`code`、`timeframe`、`direction`、`structure_state`、`confirmation_time`，以及原始状态 / 最新笔；
- `warnings[]`：机器可读风险代码；
- `resonance_time`：所有必要 evidence 的最大 `confirmation_time`；
- `current_only: true`；仅当前状态有可靠共振时才带 `event`。

`event_time` 仍归单周期结构端点；`resonance_time` 是最后一个必要周期状态真实可获知的时刻。它绝不回写为某根更早的笔、分型或日K时间。优先路径使用 TickFlow 原生 15/30/60 分钟收盘K；同一结束时刻先处理 60→30→15 分钟。原生周期任一缺失时才降级到 F1 聚合，并继续只在目标周期桶闭合后产生状态。

## 前端规则与钻取

- 周期 tab 始终只画所选周期自己的 K线、笔、中枢和 B/S，不交叉叠加结构。
- 摘要区域呈现当前四周期状态、结构化 evidence 与 warnings；点击周期卡切换到该周期图表，作为向下钻取入口。
- 日线图只在存在当前已确认关系时绘制一枚星形 marker，时间取 `resonance_time` 所在交易日；hover 显示类型、确认时间、证据与风险；点击 marker 会回到日线并滚动至摘要 / 钻取面板。
- 不显示历史共振 marker，以防完整样本回算造成 look-ahead。日线 marker 表示“当前状态在最后条件确认时刻”，不是历史回测信号序列。
- 原始 B/S 始终默认绘制，与共振层互不删除或替代；逆高周期结构仅以灰色、低透明度标注为“逆势反弹 / 潜在转折”。

## 已知限制与后续扩展

1. `cxt_bi_base` 给出的是当前最后笔 / 未完成笔语境，不等同完整趋势分类；关系层不应据此自动下单。
2. 60 分钟、30 分钟、15 分钟与日线的样本长度可能不同；缺一周期、任一 `UNKNOWN` 或最后交易日不一致时均 fail closed。
3. 没有增量缓存，也没有历史逐 bar 共振事件；未来若增加历史 marker，必须以每个时点冻结的四周期 snapshot 逐步重放，并以最大 confirmation time 写入事件。
4. 新增模式应只扩展 `_analyze_resonance` 的明确状态关系、补对应单元测试及本表；不得回到单周期层自行重算 CZSC 结构。
5. `czsc_daily_buy_point` 只筛日线新确认的单周期 B1/B2/B3，不消费或产生 resonance；不能将它的入选结果表述为多周期共振。
6. Wyckoff 结果页的 CZSC B 点开关同样不消费或产生 resonance；它只是对 Wyckoff L3 候选的单周期日线辅助过滤。
