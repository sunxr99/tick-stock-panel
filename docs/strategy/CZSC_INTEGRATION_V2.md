# CZSC V2 集成入口

后端入口是 `backend/app/custom/chanlun.py::setup` 注册的 `GET /api/chan/analyze`；前端入口是 `frontend/src/custom/chanlun/extension.tsx`。个股详情保持只读；另有日线 B 点选股策略。两者均未接入监控、自动交易或 `CzscTrader`。

## 日线 B 点选股

内置策略 `czsc_daily_buy_point`（`backend/app/strategy/builtin/czsc_daily_buy_point.py`）使用本地 enriched 日K的最后 250 个交易日，全市场逐标的构造 CZSC。它只返回最后一根**已收盘日K**相对前一根首次可见的 B1/B2/B3：当前与前一日分别调用同一组 `_SIGNAL_SPECS`，再以 `signal_name + raw_value + bi anchor` 做边沿比较。历史上已经确认、但仍停留在最后结构中的 B 点不会重复入选。

选股不读取或下载 1/15/30/60 分钟K，不使用多周期共振，也不把 B 点解释为交易指令。结果行保留 `czsc_buy_types`、`czsc_buy_signals` 与 `czsc_confirmation_time`，列表标签显示 `CZSC · B1/B2/B3`，供用户进入个股详情核对结构与质量摘要。同一 `signal_name + raw_value + bi anchor` 在历史中已确认后，即使 CZSC 原始状态短暂消失又重现，也不能再次作为“新 B 点”入选。

Wyckoff 漏斗结果页也可开启“筛 CZSC 新B点”。后端只在 Wyckoff 已经通过 L3 的候选中计算同一日线 B 点，再由页面本地过滤；它不改变漏斗正式入选集、评分或诊断，也不会重新扫描全市场。

## 调用链与周期

- 日线：`KlineRepository.get_daily_asset` → `_fetch_daily_frame` → `_validate_and_standardize` → `_to_bars(..., Freq.D)` → `_serialize_daily`。查询窗口按北京时间确定，盘中排除当日日K，标准化后精确保留请求的最后 `days` 个交易日。
- 原生分钟（优先）：个股详情的“同步分钟数据” → `POST /api/kline/sync_czsc_minutes` → `sync_and_persist_czsc_native_minutes` → TickFlow `period=15m/30m/60m` → `data/kline_czsc_minute/freq=<period>/date=<date>/part.parquet`。分析时 `KlineRepository.get_czsc_minute_range` → `_fetch_native_minute_frames` → `_analyze_native_minute_multi`；三个周期各自创建 `CZSC`，不经 F1 聚合。只有三个周期均覆盖本次日线窗口的每个交易日，且过滤盘中未闭合桶后仍完整，才采用此路径。
- F1 降级：原生三周期任一缺失或覆盖不完整时，才使用 `KlineRepository.get_minute_range` → `_fetch_minute_frame` → `_to_bars(..., Freq.F1)` → `BarGenerator(F1, [F15, F30, F60, D], market='A股')` → `CzscSignals(bg, _signal_config())` → `_analyze_minute_multi`。分钟 B/S 的日线上下文另由主分析的长日K逐日推进，不使用短分钟窗口临时聚合出的日线。

界面可切换 `15分钟`、`30分钟`、`60分钟`、`日线`。原生同步范围以当前日线分析窗口的实际首末交易日为准（默认 250 根日K），而不是全库最早分钟数据；“开始分析”始终只读本地数据，不会发起同步。分钟来源会在界面显示为 `TickFlow原生15/30/60分钟` 或 `1分钟` 降级。日线主图始终来自长历史 `daily_enriched`。

## 实现约定

F1 降级路径的 `CzscSignals` 用 `BarGenerator` 只构造一次，随后每个 F1 `RawBar` 调用一次 `CzscSignals.update_signals(raw)`；不得为每根K重新初始化。由于 native `CzscSignals` 接管传入 BG，`_analyze_minute_multi` 另建 `chart_bg` 并对同一 raw bar 调用 `update`，专用于保留完整聚合K线；它在每个分钟时点只叠加此前收盘的长日K `cxt_bi_base` 状态。原生路径的 `_analyze_native_minute_multi` 则按时间排序处理三组已闭合 K，并在同一结束时刻先处理 60→30→15 分钟，令低周期 signal 上下文不使用尚未闭合的高周期 K。`_signal_config()` 除四个 B/S 与 `cxt_bi_base` 外，还计算笔状态、SMA20、MACD(12,26,9) 和 K5 量能；后四项只进入每周期当前质量摘要，不产生额外 B/S marker。

`MultiTimeframeCZSCResult` 包含 `timeframes`、`summary`、`base_frequency`。每个 timeframe DTO 包含独立的 `bars`、`bi`、`zs`、`buy_sell`、`source` 与原生 `cxt_bi_base_V230228` 派生的只读 `state`；`state.quality[]` 透传笔状态、SMA20、MACD 与量能的当前原始状态。摘要仅统计数量，绝不做跨周期 BUY/SELL 投票或评分。前端以 `timeframes[timeframe]` 重绘，切换标的时清空状态并通过请求版本丢弃旧响应。

`event_time` 表示结构端点，`confirmation_time` 是流式运行首次观察到该完成结构/信号的 F1 或日K时刻；图上 marker 以确认时刻绘制。分析层会移除北京时间当日尚未闭合的日K、当前 1 分钟K与 15/30/60 分钟桶；未闭合高周期桶不采样 signal，输出 K 线也截到最后一根基础K，避免把未来桶放入图表。

买卖 marker 不是简化的 `type`：后端在 `buy_sell[].signal` 保留 CZSC 原生 `Signal` 的名称、key、完整 raw string/value、`v1/v2/v3/score` 与运行参数，并在 `structure_anchor` 保留 signal 输入 `bi_list` 最新笔。前端 Marker 仍显示 B1/B2/B3/S1/S2/S3，但 hover 显示这些原始字段、锚点和确认时刻。同一 `signal_name + raw_value + 笔锚点` 只记录首次确认；后续原始状态短暂消失又重现时不新增 marker，避免把同一结构事件反复显示为新的 B/S。

高周期上下文使用新增但只读的原生 `cxt_bi_base_V230228`，不是投票或自建趋势算法。对 15 分钟 signal 检查 30/60/日线的 `向上/向下 + 中继/转折` 原始状态；30 分钟检查 60/日线，60 分钟检查日线。F1 降级时日线状态来自与日线主图一致的长日K历史，并只使用该分钟日期之前已经收盘的日线快照。只有全部声明的高周期状态可用时才标为顺、逆或冲突，缺任一周期则标为上下文不明确。所有原始结构信号默认绘制；逆高周期 signal 仅以低透明度和灰色标识为“逆势反弹 / 潜在转折”，绝不从图上隐藏或从 API 删除。日线图仍仅显示日线自己的 signal，不映射低周期 marker。

## 运行与限制

顶层 API 同时返回 `resonance`：它由 `_analyze_resonance` 比较日/60/30/15 分钟的独立 `state`，只输出当前关系与结构化 evidence/warnings，未产生历史回画。详细规则、确认时刻和前端 marker 见 `CZSC_RESONANCE.md`。

当前无跨请求缓存或增量状态：一次个股请求重新计算，避免污染实时/全市场路径。分钟数据缺失时安全降级为日线；核心指数的通用分钟K已独立落入 `kline_index_minute`，但尚未提供 CZSC 原生 15/30/60 分钟分区，故指数 CZSC 当前仍走日线。数据质量、北京时间墙钟、午休和复权约束见 `CZSC_DATA_CONTRACT.md`。交易日缺失仍需交易日历或供应商质量任务检查；当前原生完整性校验保证交易日覆盖，不用伪造停牌日或缺失桶。新增 CZSC 能力时同步更新本文件、SOURCE_MAP、SIGNAL_CATALOG、DATA_CONTRACT、RESONANCE，并先以 Serena 精确定位上游 symbol。
