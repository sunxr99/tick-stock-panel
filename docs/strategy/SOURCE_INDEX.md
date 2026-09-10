# 策略参考源码索引

本目录只记录源码研究结论，不代表已接入或已验证交易有效性。

| 体系 | 核心源码 | 核心入口 |
|---|---|---|
| CZSC | `reference/czsc-master/czsc-master/crates/czsc-core/src` | `analyze/mod.rs`, `objects/{bar,fx,bi,zs}.rs` |
| CZSC 多周期/交易 | `crates/czsc-utils/src/bar_generator.rs`, `crates/czsc-trader/src/{czsc_signals,trader}.rs` | BarGenerator、CzscSignals、CzscTrader |
| CZSC 信号 | `crates/czsc-signals/src/cxt.rs` | 一二三类买卖点等结构信号 |
| ICT/SMC | `reference/smart-money-concepts-master/smart-money-concepts-master/smartmoneyconcepts/smc.py` | `smc` 的 8 个 classmethod |
| Wyckoff | `reference/WyckoffTradingAgent/WyckoffTradingAgent-main/core/wyckoff_structure.py` | 交易区间、Spring/SOS/LPS/EVR |
| Wyckoff 外壳 | 同仓库 `agents/`, `cli/`, `workflows/`, `core/prompts.py` | Agent、LLM、工作流；不应当作策略算法迁移 |
