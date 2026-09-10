# CZSC 数据契约

`RawBar` 需要 `symbol, dt, freq, open, close, high, low, vol, amount`；上游格式化函数不负责排序、去重、复权或空值治理。

当前映射：enriched 日K `date/open/high/low/close/volume/amount` → `dt/open/high/low/close/vol/amount`；价格为前复权价。分钟K来自 `KlineRepository.get_minute_range` 的 `datetime` 与同名 OHLCVA。日线查询使用北京时间日期，盘中移除当日日K后精确保留请求的最后 N 个交易日。`_validate_and_standardize` 强制升序、唯一 dt、正 OHLC、非负量额、high/low 包络关系；坏数据返回 422，不填 0。

分钟 `datetime` 是北京时间墙钟 naive 值。股票通用分钟K存于 `kline_minute`；核心四只指数（上证指数、深证成指、创业板指、科创综指）同步到独立的 `kline_index_minute`，不会与股票分区混写。全量/盘后分钟同步会同步这四只指数；单标的同步也接受指数代码。CZSC 原生分钟数据存于另一独立目录 `kline_czsc_minute/freq=15m|30m|60m/date=...`，不得写进通用分钟存储。同步时 TickFlow 请求的 `period` 与目录频率一一对应；分析前每个周期都必须覆盖同一日线窗口的全部交易日，否则整体降级为 F1 聚合。分析层按北京时间过滤仍在形成的当日日K、当前 1 分钟K及 15/30/60 分钟收盘桶，落盘中可能存在的盘中数据不得绕过这一过滤。停牌/缺分钟分区不会伪造 K；分钟周期不可用时只提供日线。日K/分钟K不得混用复权口径。

`symbol` 必须是请求标的代码；`freq` 不从供应商字段透传，而由 `_to_bars` 显式指定为 `Freq.D` 或 `Freq.F1`。输入先按 `dt` 稳定升序，再拒绝重复时间、NaN、负量额、非正价格和不包络的 high/low；仅对小于 `1e-8` 的 Float64 尾差归一化 high/low 至 open/close 包络，真实越界仍拒绝。CZSC 的 `format_standard_kline` 本身不代替这些检查。`amount` 当前仅作为 `RawBar` 契约保留，缠论结构的核心路径不以它替代价格结构。复权由数据提供方决定：当前日K为前复权，分钟与日K不能被静默混合比较。

日线 B 点选股复用同一标准化、前复权与已收盘K契约。它的输入是 enriched 日K历史面板，而非 `kline_czsc_minute`；单个标的数据异常只记录 warning 并跳过该标的，绝不以缺值合成 B 点。

结果行的 `czsc_event_identity_version=2` 表示已使用“同一 signal、raw value 与笔锚点仅首次确认”的事件口径。前端发现旧缓存没有该版本时会重跑该策略，避免历史状态重现被继续显示为新 B 点。

Wyckoff 的 CZSC B 点开关只将上述日线字段附加到其 L3 结果行；CZSC 不可用或候选数据异常时，该标的 B 点字段为空，开关按空结果 fail closed。
