# CZSC 源码研究

## 架构与数据流

CZSC 1.0 核心在 Rust：`crates/czsc-core/src/analyze/mod.rs`（CZSC）、`objects/{bar,fx,bi,zs}.rs`（RawBar、分型、笔、中枢）；`czsc-utils/src/bar_generator.rs` 聚合周期；`czsc-trader/src/{czsc_signals,trader}.rs` 管理多周期信号/交易事件；`czsc-signals/src/cxt.rs` 提供结构信号。

RawBar 的核心为 symbol、id、datetime、Freq、open/close/high/low、vol、amount。格式化器保持输入行序，CZSC 不做复权：项目必须先选择一致的前复权或原始价、确保时间升序、去重和已闭合K。当前 Tick Stock Panel 正确使用 `format_standard_kline(..., Freq.D)`、`CZSC`、笔/中枢和四个 cxt signals；它没有使用 BarGenerator、CzscSignals、CzscTrader 或多周期。

## 结构、确认与重绘

原始K先经包含关系压缩为 NewBar，再以三根内部K的中间极值形成 FX；因此分型的 event_time 是中间K，但 confirmation_time 是右侧K完成后。BI 连接相反分型，最低笔长度当前默认6；`bi_list` 是已确认笔，`bars_ubi` 是未完成笔，后者会随新K变化。历史将笔端点画在 FX 日期而非确认日会产生视觉回画；实时/回测必须记录两种时间。

ZS 由笔序列构造并可延伸；当前对象提供 `zs_list`，但没有把“标准线段”作为项目当前接入的独立输出。背驰并非一个统一的 CZSC 核心字段：通常由具体 signal 以笔结构、价格力度，或 MACD/均线等辅助条件表达，必须按 signal 源码逐项解释。

## 买卖点与多周期

当前项目的 B1/S1/B2/S2/B3/S3 来自 `cxt_first_buy_V221126`、`cxt_first_sell_V221126`、`cxt_second_bs_V240524`、`cxt_third_bs_V230319`；它们是当前 CZSC 状态信号，非订单。第一类在最近 5–21 笔上识别结构；第二类以最近9笔端分型重叠计数；第三类以5笔中枢离开并使用 SMA(34) 辅助。项目滚动 `bars[:i+1]` 再调用信号，避免了买卖点序列的直接未来读取；但最终结构图仍未展示确认日，且将状态压缩为 BUY/SELL 标签是不恰当的。

BarGenerator 原生支持低周期向上聚合，CzscSignals/CzscTrader 汇总多周期状态。15min可向30/60min/日线聚合；日线不能反推分钟K。未来接入应以最细、完整、北京时区分钟K为基础，逐bar更新各周期；不要从日K伪造分钟信号。

## 当前项目建议

保留隔离扩展和日线数据映射；优先补 `event_time`/`confirmation_time`、已收盘标志、signal id/v2/参数和状态。日K适合中级结构/选股筛选，60/15分钟更适合择时；所有 CZSC 结构均需与成交、风控分离。

## Docs First 补充：作者 API 与源码的边界

作者的 `README.md` 将 CZSC 描述为 Rust 核心、Python 门面和“信号—事件—交易”体系：`CZSC` 负责结构，`CzscSignals` 做多周期状态，`CzscTrader` 再把信号交给 `Position`/`Event`。这与源码相符：`CzscSignals.update_signals` 驱动 `BarGenerator`、更新各周期 `CZSC`、重置并写入 `signal_map`；`CzscTrader.update` 在此之后才更新持仓。故 `cxt_*` 返回的单个信号不应被解释为订单。

`format_standard_kline` 的真实约束比作者示例严格：Polars DataFrame 必须有 `symbol/dt/open/close/high/low/vol/amount`，并以**输入行顺序**创建递增 id；函数不排序、不去重、不验证 NaN，也不处理复权。相反，`BarGenerator.update_bar` 会拒绝频率不匹配或 NaN、忽略同 dt 的重复基础 bar。当前日线接入应继续在 Adapter 边界保证时间升序、唯一、同一复权口径和已收盘。

文档实现路径有一处可追溯的失配：`docs/public_api.md` 写 `crates/czsc-core/src/czsc.rs`，当前实际 `CZSC` 定义位于 `crates/czsc-core/src/analyze/mod.rs`。这不改变 API 结论，但将来升级上游时不要按该过时路径定位。
