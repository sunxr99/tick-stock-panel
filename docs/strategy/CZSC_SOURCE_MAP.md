# CZSC 当前源码地图

版本锁定：后端 `czsc 1.0.1`（`backend/uv.lock`）。只在需要确认未覆盖 API 时再进入 `reference/czsc-master/czsc-master`。

| 上游路径 | symbol | 职责 | 当前项目对应 |
|---|---|---|---|
| `crates/czsc-core/src/objects/bar.rs` | `RawBar`, `Freq` | OHLCV 与频率 | `chanlun._to_bars` |
| `crates/czsc-core/src/analyze/mod.rs` | `CZSC.update_bar`, `finished_bis` | 去包含、笔、未完成结构 | `_track_structure_confirmations`、`_serialize_czsc` |
| `crates/czsc-core/src/objects/zs.rs` | `ZS` | 原生中枢 | `_serialize_czsc` 读取 `zs_list` |
| `crates/czsc-utils/src/bar_generator.rs` | `BarGenerator.update_bar` | F1 向高周期聚合 | `_analyze_minute_multi` |
| `crates/czsc-trader/src/czsc_signals.rs` | `CzscSignals.update_signals` | BG→各周期 CZSC→signals map | `_analyze_minute_multi` |
| `crates/czsc-signals/src/cxt.rs` | B/S、笔状态与上下文 `cxt_*` | 结构信号 | `_SIGNAL_SPECS`、`_CONTEXT_SIGNAL_SPEC`、`_QUALITY_SIGNAL_SPECS` |
| `crates/czsc-signals/src/tas.rs` / `bar.rs` | SMA、MACD、量能 | 当前质量摘要 | `_QUALITY_SIGNAL_SPECS` |
| `crates/czsc-utils/src/freq_data.rs` | `freq_end_time` | A 股分钟收盘桶边界 | `BarGenerator(..., market='A股')` |

## 当前项目的原生分钟数据接入

- `backend/app/api/kline.py::_czsc_daily_analysis_window`：用当前日线分析窗口（默认 250 根日K）的实际首末交易日确定单股分钟同步范围。
- `backend/app/api/kline.py::sync_czsc_minutes`：启动可轮询后台任务；不执行 CZSC 分析，返回后由用户点击“开始分析”读取本地数据。
- `backend/app/services/kline_sync.py::sync_and_persist_czsc_native_minutes`：逐一调用通用 `sync_minute_batch(..., freq='15m'|'30m'|'60m')`；TickFlow 端对应 `tf.klines.batch(period=freq)`。
- `backend/app/tickflow/repository.py::get_czsc_minute_range`：读取隔离的 `data/kline_czsc_minute/freq=<period>/date=<date>/part.parquet`。它绝不读取或写入通用 `kline_minute` 的 1 分钟数据。
- `backend/app/custom/chanlun.py::_fetch_daily_frame` / `_drop_unclosed_bars`：按北京时间截取请求的最后 N 个交易日，并在分析视图中排除仍在形成的当日日K与 15/30/60 分钟桶。
- `backend/app/custom/chanlun.py::_fetch_native_minute_frames`：三种供应商原生周期除非均覆盖本次日线窗口的全部交易日，否则拒绝混用并降级到 F1。
- `backend/app/custom/chanlun.py::_analyze_native_minute_multi`：优先分别分析三种供应商原生周期；同一结束时刻按 `60 → 30 → 15` 分钟处理，因此低周期 signal 上下文仅使用已闭合高周期K。若三周期不完整，`_analyze_minute_multi` 保留为 F1 `BarGenerator` 降级路径，并将分钟 B/S 的日线上下文替换为主日线历史中当时已收盘的快照。
- `backend/app/custom/chanlun.py::find_latest_daily_buy_points` / `filter_daily_czsc_buy_points`：全市场日线筛选复用同一 B/S signal 与笔锚点；仅比较最后两根已收盘日K的可见 signal，返回新确认 B1/B2/B3。
- `backend/app/custom/chanlun.py::_find_daily_buy_sell_points`：个股日线图按 signal 与笔锚点全历史去重，只绘制同一结构事件的首次确认 marker。
- `backend/app/strategy/builtin/czsc_daily_buy_point.py`：策略注册入口，声明 250 根日线历史并委托上述筛选函数；不读取分钟数据。
- `backend/app/strategy/engine.py::_run_wyckoff_funnel`：在 Wyckoff L3 结果生成后，仅对这些候选调用 `filter_daily_czsc_buy_points` 并附加 B 点字段；`frontend/src/pages/Screener.tsx` 的开关据此二次过滤。

调用：TSP repository → `_validate_and_standardize` → `format_standard_kline` → 日线 `CZSC` 或分钟 `BarGenerator`/`CzscSignals` → DTO → ECharts。`CzscTrader` 未使用：项目不做自动交易。

上游调用关系：`BarGenerator.update` 维护 `bars[freq]`；`CzscSignals.update_signals` 更新 BG 后为每个 `kas[freq]` 创建/更新 `CZSC`，并写入 `s` signal map；`CZSC.update_bar` 处理包含、分型和笔，`finished_bis` 仅为完成笔；`ZS` 从分析对象的 `zs_list` 读取。TSP 的 `_track_structure_confirmations` 以逐根 `CZSC.update` 的首次出现时间记录确认时刻；`_find_daily_buy_sell_points` 以当时 bars 快照调用 native `call_signal`。

信号对象定义在 `crates/czsc-core/src/objects/signal.rs::Signal`：`k1/k2/k3` 为名称，`v1/v2/v3/score` 为值，`key/value/to_string` 是 Python 可见 API。当前项目的 `_signal_detail` 透传这些字段；`_bi_anchor` 则读取调用 signal 时 `CZSC.bi_list` 的最新笔，供区分滚动结构。高周期原生状态来自 `crates/czsc-signals/src/cxt.rs::cxt_bi_base_V230228`，其 `v1/v2` 为 `向上/向下` 与 `中继/转折`。
