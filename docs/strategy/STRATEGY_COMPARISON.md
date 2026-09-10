# CZSC、Wyckoff、ICT 横向比较与统一 Analyzer 设计

| 维度 | CZSC | Wyckoff reference | ICT/SMC reference |
|---|---|---|---|
| 核心 | 分型-笔-中枢-结构信号 | 区间及少量量价触发 | Swing、突破、失衡、订单块、流动性 |
| Volume | 部分信号可用 | Spring/SOS/LPS/EVR 核心使用 | OB、重采样使用；多数结构不用 |
| 日K | 结构筛选 | 区间/SOS风险 | 上级关键位/慢结构 |
| 60/15min | 原生多周期优势 | 需自行多周期 | FVG/OB/session 更合适 |
| 趋势/结构 | 笔、中枢、signals | 简化 Markup/Accum 标签 | BOS/CHoCH |
| 风险 | 未完成笔、确认延迟 | 区间失守/高量无结果 | Sweep、mitigation、未填FVG |
| 确定性 | 高（参数敏感） | 仅四类 trigger 高 | 高（但大量回看） |
| 主要偏差 | 分型/笔确认回画 | 需收盘确认，Range窗口选择 | Swing/FVG/OB/liquidity 都含未来扫描 |

## 不把重复价格信息当共振

CZSC 趋势转折、ICT BOS/CHoCH、Wyckoff SOS 都可能只是“突破前高/区间上沿”；同一价格突破只能贡献一个 `breakout` 证据。CZSC 一买、Wyckoff Spring、ICT sell-side liquidity sweep 常处于下破后收回阶段：应归入一个 `failed_breakdown/reversal` 证据簇，而非三次加分。较独立的信息是：CZSC 的笔/中枢级别，Wyckoff 的量价/区间质量，ICT 的FVG/OB/流动性区域。

## 仅设计的统一契约

`AnalysisResult`：`direction`、`structure`、`signals`、`zones`、`risk`、`confidence`、`metadata`；`ChartResult`：`lines`、`zones`、`markers`、`labels`。每个 signal 至少有 `symbol,timeframe,type,direction,event_time,confirmation_time,price,strength,status,source,details`；每个 zone 有 `type,low,high,start_time,end_time,status,source,details`。`details` 保留 FX/BI/ZS、Phase/Range、FVG/OB/Liquidity 的专属语义。

未来实现的 CZSCAnalyzer、WyckoffAnalyzer、ICTAnalyzer 应只消费已标准化的 MarketData，逐bar生成结果；不得让图表、回测或评分重算全样本后覆盖历史 confirmation_time。
