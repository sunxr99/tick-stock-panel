# Reference 仓库学习报告（Docs First → Source Verified → Code Expanded）

本报告只记录本工作区内三个上游仓库可验证的事实。状态含义：**VERIFIED** 为文档声明与确定性源码相符；**PARTIALLY_VERIFIED** 为有实现但边界较窄；**LLM_DEPENDENT** 为最终判断交给模型或工作流；**DOC_ONLY** 为本轮未定位到确定性实现；**CODE_ONLY** 为源码存在、作者主文档未突出。

## 阅读方法与范围

先枚举 Markdown，再优先读取策略/API/架构文档，最后用 Serena 定位 symbol、调用者和必要源码。现有主项目 UA 图谱的提交早于当前工作区，且没有 `reference/` 节点；因此没有把它当第三方源码证据，也没有为此全量重建主项目图谱。CZSC 的 Rust 文件未被当前 Serena Python language server 解析；对其使用 Serena 的定向文本定位，并读取该定位到的最小 Rust 片段验证。

## CZSC

### 文档地图与作者词汇

Markdown 共 275 份，但 257 份位于 `.claude/`，主要是信号函数参考，不是公开产品文档。本轮将 18 份非隐藏 Markdown 建为作者文档地图，其中高价值 5 份。

| 文档 | 主要内容 | 策略相关 | 优先级 | 后续/本轮验证 |
|---|---|---|---|---|
| `README.md` | Rust+Python 架构、RawBar、CZSC、Signals、Trader、多周期示例 | 是 | HIGH | 核心 crate 与运行路径 |
| `docs/public_api.md` | 顶层公开 API、实现位置和依赖 | 是 | HIGH | API 路径与 facade/核心边界 |
| `docs/examples.md` | 核心、信号、策略、绘图推荐用法 | 是 | HIGH | 示例与实际 API 一致性 |
| `crates/czsc-trader/README.md` | 交易器 crate 的使用定位 | 是 | HIGH | `CzscSignals`/`CzscTrader` 职责 |
| `crates/czsc-signals/README.md` | 信号 crate 的使用定位 | 是 | HIGH | 信号注册与执行 |
| `crates/czsc-core/README.md`、`crates/czsc-utils/README.md` 等 | 单 crate 基础使用 | 是 | MEDIUM | 核心对象与 BarGenerator |
| `scripts/auto-czsc-quant/README.md` | 自动量化研究脚本 | 间接 | MEDIUM | 与本次结构分析无直接耦合 |
| `CHANGELOG.md`、`docs/release_checklist.md`、CLI plan、测试基线 | 发布/兼容/开发 | 间接 | LOW | 不作为算法事实 |
| `.claude/skills/signal-functions/references/signals/*.md` | 大量单信号说明 | 是 | MEDIUM（按当前使用信号升 HIGH） | 仅在选定 signal 后逐篇核验 |

**Document Vocabulary：** `RawBar`、`NewBar`、`FX`、`BI`、`ZS`、`CZSC`、`BarGenerator`、`CzscSignals`、`CzscTrader`、`Signal`、`Event`、`Position`、`signals_all/any/not`、`generate_czsc_signals`、`format_standard_kline`、`Freq`。

### 作者文档声称的核心能力与核验

| 作者声明 | 状态 | 源码证据与结论 |
|---|---|---|
| 1.0 把分型、笔、中枢等迁至 Rust/PyO3 | VERIFIED | `crates/czsc-core/src/analyze/mod.rs` 的 `CZSC`，`objects/{bar,fx,bi,zs}.rs`，PyO3 绑定路径均存在。 |
| `CZSC → Signals → Trader` 为主要体系 | VERIFIED | `CzscSignals` 维护 `BarGenerator`、各频率 `CZSC` 和 signal map；`CzscTrader.update` 先更新 signals，再把 map 交给 `Position`/`Event`。 |
| `BarGenerator` 从低周期合成高周期 | VERIFIED | `bar_generator.rs::update_bar` 验证 base freq 后更新每个目标频率；不能从日线反推分钟线。 |
| `generate_czsc_signals` 批量信号生成 | VERIFIED | `czsc-python/src/trader/generate.rs` 用 `BarGenerator` 预热，逐根更新 `CzscSignals` 后输出字典。 |
| `format_standard_kline` 是标准 DataFrame→RawBar 转换 | PARTIALLY_VERIFIED | 实现要求 `symbol/dt/open/close/high/low/vol/amount` 与正确 Polars dtype；按输入行序创建 `id`，不排序、未做 NaN/重复/复权治理。 |
| `docs/public_api.md` 中 CZSC 位于 `crates/czsc-core/src/czsc.rs` | DOC_ONLY（路径失配） | 真实定义在 `crates/czsc-core/src/analyze/mod.rs`；这是文档实现路径过时，不影响公开 API 结论。 |

**Code Expanded Vocabulary：** `bars_ubi`（未完成、去包含 K 线）、`get_finished_bis`、`min_bi_len`、`max_bi_num`、`prime_signals`、`signal_map`、`compiled_kline_groups`、`warmup_bar`。`CZSC.update_bar` 对相同 dt 把末根视为时间延伸，重算最后的未完成结构；因此调用方需显式区分已闭合 bar 与更新中的 bar。

### 本轮可下的结论与待深挖

作者把 CZSC 设计为“结构/信号”与“事件/仓位”分层体系，单个 signal 本身不是订单。核心中，分型需要三根去包含 K 线；笔至少使用 `min_bi_len`（默认 6）；`CzscTrader` 才把组合后的 `Event` 与 `Position` 状态机接在一起。下一阶段最值得深挖的是当前项目实际调用的 `cxt_first_buy_V221126`、`cxt_first_sell_V221126`、`cxt_second_bs_V240524`、`cxt_third_bs_V230319` 及其文档/源码，避免将结构状态误呈现为直接交易指令。

## smart-money-concepts

### 文档地图与作者词汇

该仓库只有 3 份 Markdown；仅 `README.md` 是策略/API 文档，也是本轮唯一 HIGH 文档。

| 文档 | 主要内容 | 策略相关 | 优先级 | 后续/本轮验证 |
|---|---|---|---|---|
| `README.md` | DataFrame 输入约定与八个公开指标 | 是 | HIGH | 每个公开函数、字段、未来数据语义 |
| `CONTRIBUTING.md` | 贡献约定 | 否 | LOW | 无 |
| `CODE_OF_CONDUCT.md` | 社区行为规范 | 否 | LOW | 无 |

**Document Vocabulary：** `FVG`、`Swing Highs and Lows`、`BOS`、`CHoCH`、`OB`、`Liquidity`、`PreviousHigh/Low`、`Sessions`、`Retracements`、`BrokenIndex`、`MitigatedIndex`、`join_consecutive`、`close_break`、`close_mitigation`、`range_percent`。

### 作者文档声称的核心能力与核验

README 声称的八个 API 与 `smartmoneyconcepts/smc.py::smc` 的八个 classmethod 一一对应，故 API 覆盖为 **VERIFIED**。但作者文档没有明确给出时间语义；源码验证后其能力边界如下。

| 文档声明 | 状态 | 实现事实 |
|---|---|---|
| Swing 是左右 `swing_length` 极值 | VERIFIED | 使用 `shift(-swing_length)`/rolling；极值日需未来窗口确认，首尾还会被补作相反 swing。 |
| FVG 以三根 K 构成，可记录 mitigation | VERIFIED | `t` 的判定直接读取 `t+1`；MitigatedIndex 再扫描未来，因此只能离线复盘或需延迟确认。 |
| BOS/CHoCH 返回 `BrokenIndex` | VERIFIED | 先依赖 Swing，再以四个交替点建立结构；标记写回较早 swing，真正确认是随后突破 K。 |
| OB 使用 volume 并输出强度 | VERIFIED | 上/下破 swing 后，回写区间内极值 K 为 OB；`Percentage` 是两段量的 min/max 比，非置信度/收益预测。 |
| Liquidity 是相近高/低点并可 sweep | VERIFIED | 使用**全样本**价格总范围 × `range_percent` 聚类，且 scan 后续 bar 填 Swept，在线计算需自行截断。 |
| Previous High/Low、Sessions、Retracements | VERIFIED | 其余三函数均存在；retracement 继承 swing 的回看风险。 |

**Code Expanded Vocabulary：** `HighLow`、`Level`、`Top/Bottom`、`OBVolume`、`Percentage`、`End`、`Swept`、`Active`。最大的文档缺口是 event/confirmation 语义：该库没有此字段，也没有流式状态/下单层；集成方必须自行补充。

### 本轮可下的结论与待深挖

作者把它设计为 pandas 指标集合，而不是 ICT 执行系统。足以开始设计只读 Adapter 的**数据契约**，但不足以直接接入生产/回测：必须先定义逐 bar 计算、event_time、confirmation_time 与 invalidation 的包装语义。最值得深挖的文件是唯一实现文件 `smartmoneyconcepts/smc.py` 的 `ob`、`liquidity`，以及测试目录中对返回索引的期望；不需要扩展到仓库未声明的 ICT 名词。

## WyckoffTradingAgent

### 文档地图与作者词汇

Markdown 共 42 份（37 份非隐藏），其中 25 份在 `docs/`。本轮识别 6 份高价值文档，且把证据/运营/LLM 文档与策略算法分开。

| 文档 | 主要内容 | 策略相关 | 优先级 | 后续/本轮验证 |
|---|---|---|---|---|
| `README.md` | 产品能力、L1–L5 漏斗、Agent/数据源 | 是 | HIGH | 哪些层由确定性算法、哪些由 LLM/OMS 完成 |
| `README_STRATEGY.md` | 漏斗、AI、OMS、跨日确认与执行纪律 | 是 | HIGH | L4 trigger 和正式候选关系 |
| `GLOSSARY.md` | 作者术语、L4 检测目标、方法说明 | 是 | HIGH | 术语是否有算法实现 |
| `docs/ARCHITECTURE.md` | 系统/数据/工作流架构 | 间接 | HIGH | 策略、Agent、基础设施边界 |
| `docs/A_SHARE_FUNNEL_FLOW.md` | 日漏斗调用流程 | 是 | HIGH | 文档所列文件与真实 caller |
| `docs/OPERATOR_PLAYBOOK.md` | 操作和次日开盘纪律 | 是 | HIGH | 信号确认/OMS 是否算法本体 |
| `docs/ITERATION_STRATEGY.md`、`docs/evidence/*.md` | 研究治理和实证 | 是 | MEDIUM | 只作研究状态证据，不等同算法规范 |
| `docs/README_EN.md` | 英文总览 | 间接 | MEDIUM | 与中文 README 对照 |
| `docs/SIGNAL_FEEDBACK_LOOP.md`、Step3 文档 | 信号反馈/缓存 | 间接 | MEDIUM | 工作流、非 Wyckoff 核心 |
| `llmdoc/`、部署、桌面、成本、会员文档 | LLM/运营/交付 | 否 | LOW | 默认不读入策略结论 |

**Document Vocabulary：** `Mainline Funnel`、`L1–L5`、`Eight-Channel Strength`、`Spring`、`LPS`、`SOS`、`EVR`、`Compression`、`Trend Pullback`、`VALIDATED/confirmed`、`OMS`、`Trading Range`、`AI Three-Camp Report`、`Accumulation`、`Dry Volume`、`Support`。

### 文档声明与源码核验

| 文档声明 | 状态 | 源码证据与结论 |
|---|---|---|
| L4 包含 Spring/LPS/SOS/EVR 等触发 | PARTIALLY_VERIFIED | `core/wyckoff_structure.py` 有动态 TR 的 Spring/SOS/LPS/EVR；但 `build_structure_shadow` 明确 `observation_only` 且 `affects_formal_selection=False`，不能说它们已进入正式选股。 |
| Trading Range 与结构触发 | VERIFIED | `identify_trading_range` 与 `detect_structure_triggers` 存在；后者按 symbol 排序数据、以 `exclude_last=1` 建 range，再测试最后一根 bar。 |
| Phase/Accumulation 诊断 | PARTIALLY_VERIFIED | `_infer_stage` 仅返回 `Markup/Accum_A/Accum_B/Accum_C` 的简化标签；没有完整 A–E 状态机或 Distribution 对偶。 |
| AI 负责研报/复核 | LLM_DEPENDENT | README_STRATEGY 把 Step3 标为 AI 研报，README 也将 L5 描述为 LLM+OMS verdict；这不是确定性 Wyckoff 算法。 |
| confirmed 后且 OMS 区间内才可行动 | VERIFIED（工作流规则） | 作者文档清楚要求跨日确认与 OMS；它是系统执行门槛，不等于 Spring/SOS 单函数输出。 |
| Spring Test、Shakeout、UT/UTAD、SOW、LPSY、完整 A–E | DOC_ONLY/Domain Gap | 本轮核心结构模块未找到这些确定性算法；不能以理论术语补写为仓库能力。 |

**Code Expanded Vocabulary：** `TradingRange`、`StructureTriggerResult`、`_StructureSeries`、`_LastBar`、`quality_score`、`support_tests`、`resistance_tests`、`stage_map`、`structure_shadow`。动态 range 默认观察 90 根、至少 40 根，支撑/压力各至少 2 次（3.5% 容差），且排除最后 K；Spring/SOS/LPS/EVR 的精确阈值见更新后的 `WYCKOFF.md`。

### 本轮可下的结论与待深挖

若移除 Agent/LLM/Prompt/Workflow，仍可保留动态 Trading Range、四个结构触发和相关 OHLCV 特征；但它们当前是影子观察，且不足以构成完整 Wyckoff 策略。下阶段优先深挖 `core/wyckoff_engine.py` 的八通道与 `core/wyckoff_events.py`，并追踪它们到 `workflows/funnel_layers.py` 的正式候选路径；这能回答“历史 legacy L4”与新动态结构模块的区别，而不需要阅读 Agent/UI。

## 是否已足够开始接入

**不够开始生产接入，也不应现在接入。** 已足够做后续方案设计和小范围验证，但尚缺三项证据：

1. 当前项目选择的 CZSC 四个具体 signal 的逐条语义、触发/确认时点与版本绑定；
2. Wyckoff 正式 L4 的 `wyckoff_engine.py` 与 funnel caller 的证据链，确认而非假定 shadow 模块的生产地位；
3. SMC 逐 bar 包装的真实期望：原库全序列回写，需要在未来实现前确定 event/confirmation/status 的不泄漏契约。

本阶段未修改业务代码、前端、策略、回测或评分系统。
