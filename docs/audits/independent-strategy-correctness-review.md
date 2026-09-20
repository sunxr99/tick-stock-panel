# 独立策略正确性评审（CZSC / 旧 Wyckoff Funnel / Wyckoff V2 及其市场环境链路）

> **实施状态更新（2026-09-10）**：本评审中“Sector Strength 缺失”的结论是实现前的
> 历史事实。Sector Strength V1.1 和 RelativeStrengthEngine V1 现已作为只读研究输出实现，
> 并作为 Wyckoff 候选的可解释研究上下文展示；它们不改变候选顺序、策略评分或交易信号，亦未获得
> 任何收益/样本外有效性证据。
> 当前口径见 [Sector Strength 与 Relative Strength V1](../theory/sector-rs/sector-strength-relative-strength-v1.md)。

> 只读审计，未修改任何代码、策略、参数、文档或测试。结论按“理论正确性 / 实现正确性 / 时序与回测正确性 / 统计与研究正确性 / 组合链路正确性”五类分别给出，每类结论均附源码/测试/数据/回测证据；无法证明处明确写“无法确认”。

## 1. 总结结论

| 模块 | 定级 | 一句话依据 |
| --- | --- | --- |
| CZSC（缠论分析扩展） | 只能继续研究（且当前不是候选池成员） | 只读个股详情分析，未接入选股/监控/评分/回测；结构信号实现基本忠实、点时间确认正确，但零统计证据，且原生分钟路径的“日线高周期上下文”存在文档与实现不一致 |
| 旧 Wyckoff Funnel（L1–L4） | 不应进入核心链路（有确定性实现缺陷） | 已接入正式选股，但 L4 是 observation-only（最终= L3 幸存者）、score=1.0 占位；L2 的 RS 过滤器因列名 `pct_chg` vs `change_pct` 不匹配而静默失效（主升/潜伏两通道实质死亡）；L3 生产只走 Tushare 当前行业回退、无概念/主线；无任何回测与统计验证 |
| Wyckoff V2 | 只能继续研究（研究引擎，未接入选股） | `affects_formal_selection=false` 隔离正确；点时间回放、冻结区间、事件链、T+1 开盘入场、基准/Regime 分层做得最规范；但回测未计成本/滑点/涨跌停/停牌、使用当前前复权价，其自身结果（胜率<50%、超额≈0 或负、LPS 样本极小）不支持任何已证实优势 |
| Market Regime / Phase | 仅研究（可作回测 T-1 gate，未接实时） | 全市场环境计算自洽；`regime_alignment.py` 的 T-1 对齐 fail-closed 正确；但只用于回测 gate，不参与实时选股，无样本外归因 |
| Market Mainline（涨停梯队主线） | 只能继续研究（独立因子，勿称“板块强度”） | 逻辑自洽，但有“当前成员快照回看历史”的归属漂移风险，且不产生可持续板块 strength 输出 |
| Sector Rotation / Theme（RPS 轮动 + AI 解释） | 不应进入核心链路（展示/解释层） | 名称是 RPS 实为“每日涨幅名次矩阵”；Theme 只是启发式标签；与 Overview 单日均值聚合职责重复；无稳定 DTO/历史版本 |
| Sector Strength（统一板块强度） | 缺失，需新建 | 当前无统一 SectorStrengthResult；无 stock-vs-sector RS、无板块内 percentile/rank（详见 `docs/audits/current-sector-strength-audit.md`） |

核心结论：**代码层面没有一件“已经证明有样本外价值”的策略**。CZSC 与 Wyckoff V2 是忠实度不错的研究/展示/诊断工具；旧 Wyckoff Funnel 是唯一已接入选股链路的东西，但它既缺回测证据，又存在静默失效的实现缺陷，且其“最终候选 = L3 幸存者 + L4 只观察”的口径使“Wyckoff 结构信号”实际并未参与选股过滤。

---

## 2. 策略评分表

> 评分是“正确性”而非“收益”。5 = 有充分证据支持该维度；0 = 无证据或已证伪。每项评分后附证据与限制。

### CZSC

| 维度 | 分 | 证据与限制 |
| --- | --- | --- |
| 理论自洽性 | 4/5 | 一/二/三买卖点是 CZSC 结构信号，不是 BUY/SELL 指令，文档（`CZSC_SIGNAL_CATALOG.md`）与实现（`chanlun.py`）一致；共振层明示“不产生交易指令、不做投票、无 0–100 评分”（`CZSC_RESONANCE.md`）。扣 1 分：共振本质依赖 `cxt_bi_base` 的“最后笔/未完成笔”语境而非完整趋势分类，文档已自述其局限，严格说不是“趋势一致”的完整证明 |
| 实现可信度 | 4/5 | 日线逐快照 `CZSC(bars[:index+1])` 求信号（`chanlun.py:316`）、流式确认时刻 `_track_structure_confirmations`（`:220-231`）、数据 fail-closed（`:66-97`）均忠实。扣 1 分：原生分钟路径 `_analyze_native_minute_multi` 的 `signal_state` 只写入 15/30/60 三周期、无“日线”，导致 `_higher_context` 对 15 分钟恒判“上下文不明确”（见 §3），与 `CZSC_SIGNAL_CATALOG.md` 声称的“15 分钟检查 30/60/日线”不符 |
| 时序可信度 | 4/5 | `event_time`（结构端点）与 `confirmation_time`（首次可观察时刻）分离，marker 画在确认时刻；共振 `resonance_time` = 各 evidence 最大确认时刻，缺任一周期或最后交易日不一致即 fail-closed（`CZSC_RESONANCE.md`、`chanlun.py:357-388`）。扣 1 分：日线读取终点为 `date.today()`（`chanlun.py:102`），盘中可能含未收盘当日 K，生产盘中必须只传已闭合 bar（文档已提示，但无代码强制） |
| 统计证据强度 | 0/5 | 全仓库无 CZSC 回测/样本外证据；`chanlun.py` 与 `api/kline.py` 只做展示。0 分是因为“无证据”，不是“证伪” |
| A 股适配性 | 2/5 | 分钟桶用 `BarGenerator(market='A股')` 对齐 A 股收盘桶（`chanlun.py:397-399`）；涨跌停/T+1/停牌/复权口径未参与（因为是展示工具，暂不构成 look-ahead），但若未来接入选股需全部补齐。原生分钟 K 与日 K 复权口径是否一致仅有文档声明，未以测试证明 |
| 是否可进入正式候选链路 | 否（当前）/ 仅研究 | 未接入选股、监控、评分、回测（`CZSC_INTEGRATION_V2.md:3`；grep 确认 `czsc` 仅出现在 `chanlun.py`、`api/kline.py`、`kline_sync.py`、`repository.py`） |

### 旧 Wyckoff Funnel（L1–L4）

| 维度 | 分 | 证据与限制 |
| --- | --- | --- |
| 理论自洽性 | 3/5 | 规则有内部自洽（L1 过滤→L2 通道→L3 共振→L4 观察），但“L4 是否过滤”存在实质矛盾：`funnel.py:141` 明写 `returned_because = "current implementation returns all L3 survivors; L4 is observation only"`，因此“L1–L4 漏斗”实际是 L1–L3。多个伪精确阈值（如 `spring_tr_max_range_pct*1.5` 与 `max(...,24.0)`、`45%` 上限）是上游迁移默认值，无实证 |
| 实现可信度 | 1/5 | **确定性缺陷**：`layer2_strength.py:148` 要求 `"pct_chg" in df.columns`，而 TSP enriched 历史提供的是 `change_pct`（`pipeline.py:126,341,505-506`），生产数据永远缺失 `pct_chg` → `_rs_flags` 恒 `return (False, False)`，主升/潜伏通道的 RS 分支静默失效，`rs_structural_bypass`（`:161-163`）与 `max_drawdown_pct` 因此不可达。测试用合成 `pct_chg` 列（`test_wyckoff_layer2_strength.py:25`）且多用 `enable_rs_filter=False` 掩盖。另有：生产不传 `concept_map/hot_concepts`（`engine.py:1102-1109`），L3 恒走行业回退；`adapter.to_wyckoff_ohlcv` 定义+测试但 `_run_wyckoff_funnel` 未使用（`engine.py:1093` 直接 `drop("symbol").to_pandas()`）；`limit_move.py::classify_limit_move` 定义+测试但漏斗未调用（L1 仅 `is_st_risk_warning` 排除 ST），一字板/涨跌停未进入 L4 触发判定 |
| 时序可信度 | 2/5 | 作为“当日快照”筛选器，layer2/3 均取最新一根 K（`.tail()/.iloc[-1]`），无未来函数。扣分：Tushare 行业映射是**当前**快照（`tushare_metadata.py` 读 `stock_basic`），无逐日历史版本；RPS universe 是“当前在场股票”，用于历史回放会有幸存者/成分漂移。但这些只在未来历史回放时暴露，当前无回测，无法验证 |
| 统计证据强度 | 0/5 | 旧漏斗没有任何回测（grep 确认 `backend/app/backtest/` 无 wyckoff 引用）。score=1.0 是占位（`WYCKOFF.md:77-79`、`engine.py:1155`），无排序/胜率/容量证据 |
| A 股适配性 | 2/5 | L1 有主板/创业板/科创板/北交所区分（`cn_boards.py`）与 ST 排除；但涨跌停、T+1、停牌、一字板未进入信号判定；`total_market_cap` 用当前快照（`engine.py:1101` 除以 1e8 转亿），历史口径无版本 |
| 是否可进入正式候选链路 | 否 | 已接入但缺陷使 L2 部分通道失效、L4 不生效、无回测；在修复前不应作为可信候选源 |

### Wyckoff V2

| 维度 | 分 | 证据与限制 |
| --- | --- | --- |
| 理论自洽性 | 4/5 | 事件/状态/Entry 三者分离（`models.py`），Spring 三分类 + Test + 保守确认、SOS 需次日跟随后确认、LPS 仅以 `SOS_CONFIRMED` 为 parent，逻辑自洽且可解释。扣 1 分：大量阈值是“研究默认值”而非理论常量（`v2/config.py:1-8` 自述），Spring/SOS/LPS 定义是项目自定义 ATR/CLV/量能版本，不等同传统 Wyckoff 教条 |
| 实现可信度 | 5/5 | 与旧模块隔离（`v2/__init__.py` 不导入 `wyckoff_structure`）；区间严格用事件日前 K 建立（`range_engine.py:62-125`）、冻结 support/Creek/ATR/容差（`TradingRangeSnapshot`）；事件链用 `parent_event_id`/`range_id` 去重（`engine.py:77-102,341-360`）；`analyze_wyckoff_v2` 无 legacy 依赖。测试覆盖状态机关键负例（`test_wyckoff_v2.py`） |
| 时序可信度 | 5/5 | 逐 bar 回放，事件在闭合 K 后判定，新事件在更新后评估避免自确认（`engine.py:555-556`）；回测 `_outcome` 以“下一交易日开盘”入场、`T+N` 以信号日计（`backtest.py:48-78`），MFE/MAE 不含入场前数据；`research_service._benchmark` 的 all_a 用 `shift(-1)` 次日开盘、`shift(-days)` 收盘，无未来日期构造信号（`research_service.py:153-162`）；`_market_regime` 用当日及以前 000300 收盘（`:180-207`）；Range 预热 220 自然日仅用于建区、只统计请求窗口内 Entry（`:119`） |
| 统计证据强度 | 2/5 | 有全市场回放（三年 5543 只、26k 事件）与分层报告，这是全仓最强证据，但：未计手续费/滑点/涨跌停/停牌不可成交；使用**当前重建前复权价**（`WYCKOFF.md:159-160` 自述存在点时间复权前视）；结果本身不支持优势（激进/标准 Spring 平均超额≈0 或负、胜率<50%；保守 Spring T+20 超额+0.81% 但正收益率 48.9%；LPS 样本 315 且 T+20 超额 -0.20%）。故只能给“有描述性证据、无交易有效性证据” |
| A 股适配性 | 2/5 | 已显式建模并报告 `invalidation_hit`（触及失效价）与正收益分离，方向正确；但回测未做涨跌停不可成交/停牌剔除/T+1 的卖点约束，实际 A 股成本结构未验证 |
| 是否可进入正式候选链路 | 否（保持冻结）/ 仅研究 | 文档与代码均 `affects_formal_selection=false`；`engine.py:1144-1151` 只写入 evidence/diagnostics，最终 score 与候选集不变 |

### Market Regime / Phase

| 维度 | 分 | 证据与限制 |
| --- | --- | --- |
| 理论自洽性 | 4/5 | 四子分（profit/speculation/resilience/trend）加权 0–100 环境分 + 独立离散 phase，公式明确（`docs/audits/current-sector-strength-audit.md:174-182`）。扣 1 分：子分权重 0.35/0.25/0.20/0.20 与各 S 函数上下界是启发式，无校准 |
| 实现可信度 | 4/5 | `regime_builder` 从 enriched 聚合，字段口径清晰。扣 1 分：未读源码逐行核对其与文档公式是否逐字一致（本次只核对了 T-1 对齐层） |
| 时序可信度 | 5/5 | `backtest/regime_alignment.py` 用前一交易日环境做 T-1 gate、内部缺口 fail-closed（`:89-123`）、`build_regime_filter_mask` 逐日对齐（`:126-166`）；`clamp_formal_start_for_regime` 处理首日无前驱的顺延。是组合链路中时序最严谨的环节 |
| 统计证据强度 | 2/5 | 仅证明“回测中可按 T-1 gate 拦截 entry”，未证明 gate 本身改善样本外收益；无 Regime 分组的收益归因报告 |
| A 股适配性 | 4/5 | 用上证指数 + 全市场涨停/连板/涨跌家数，符合 A 股情绪；扣 1 分：未纳入两融/北向等 |
| 是否可进入正式候选链路 | 否（当前）/ 仅研究 | 仅作回测 gate，不影响实时 screener（`audit` 文档明确） |

### Market Mainline（涨停梯队主线）

| 维度 | 分 | 证据与限制 |
| --- | --- | --- |
| 理论自洽性 | 3/5 | 连板数>=1/>=2、max_boards、rungs_filled、leader 四因子 0.35/0.25/0.25/0.15 加权，先剔除 limit_up_count<3，逻辑自洽；扣分：与 Sector Strength 语义混用风险（它测的是“涨停生态”，不是板块收益强度） |
| 实现可信度 | 3/5 | `market_mainline.compute_mainline_range` 从 enriched 窄扫，ST/名称黑名单/成员上下限在聚合前处理。扣分：成员关系是当前扩展数据快照，历史主线存在归属漂移（文档已声明） |
| 时序可信度 | 2/5 | 当日截面 rank 归一；跨窗口有 top1_days/avg_score 持续性，但无逐日 rank 变化/衰减的稳定历史输出；成员快照回看历史是确定性漂移风险 |
| 统计证据强度 | 1/5 | 未与收益/超额收益做关联验证；只是“主线统计” |
| A 股适配性 | 3/5 | 涨停梯队本身是 A 股特有，合理；扣分：未与涨跌停不可成交/炸板口径联动 |
| 是否可进入正式候选链路 | 否（当前）/ 仅研究 | 独立因子，勿当板块强度，勿当硬过滤 |

### Sector Rotation / Theme

| 维度 | 分 | 证据与限制 |
| --- | --- | --- |
| 理论自洽性 | 2/5 | `rps_rotation` 名为 RPS 实为“每日板块涨幅名次矩阵”；`concept_rotation_analyzer` 的“主线/新晋/退潮/机构式/游资式”是启发式标签（rank<=10、提升>=20 名等），阈值无实证 |
| 实现可信度 | 3/5 | 成员映射加载与按日 `mean(change_pct)` 聚合可复用；但与 Overview 的单日均值聚合职责重复，且无稳定 DTO（返回 `date -> [[member, avg_pct]]` 矩阵） |
| 时序可信度 | 2/5 | 只输出最近 7–30 日名次，无相对大盘、无持续性字段；成员快照漂移同上 |
| 统计证据强度 | 1/5 | 供 AI 文案使用，无收益归因 |
| A 股适配性 | 2/5 | 未按市值/成交额加权，无板块 Breadth |
| 是否可进入正式候选链路 | 否 | 展示/解释层，不应作候选池硬过滤 |

---

## 3. CZSC 评价

### 理论
市场假设：价格按“分型→笔→中枢→结构信号”递归，一二三类买卖点指示结构转折/延续；多周期共振用于判定层级关系。这与其上游 czsc 定义一致（`SOURCE_MAP.md` 映射 `RawBar/CZSC/ZS/BarGenerator/CzscSignals`）。项目正确地把 B/S 定位为“结构证据，非交易指令”，并明确共振不是 BUY/SELL、无综合评分（`CZSC_RESONANCE.md:11-13`）。

### 实现
- 忠实点：笔取 `finished_bis`、中枢取 `zs_list`、信号取四个 `cxt_*`，未自行重算（`CZSC_V1_AUDIT.md:5-7`）；`_validate_and_standardize` 拒绝而非用 0 掩盖坏数据（`chanlun.py:66-97`）；`_signal_detail` 透传上游 `Signal` 原始字段，未臆造结构字段。
- 确认时刻：日线用逐根快照 `CZSC(bars[:index+1])`（`:316`），`_track_structure_confirmations` 流式记录首个出现时刻（`:220-231`）。
- **文档/实现不一致（低危，仅展示）**：原生分钟路径 `_analyze_native_minute_multi` 中 `signal_state` 只含 15/30/60 三周期（`:454,479-482`），无“日线”。而 `_higher_context`（`:262-284`）对 15 分钟要求检查 `("30分钟","60分钟","日线")`，缺“日线”后 `v1="其他"` → 恒判“上下文不明确”。这与 `CZSC_SIGNAL_CATALOG.md`“15 分钟检查当时 30/60/日线状态”不一致。F1 降级路径因 `signals.kas` 含 `Freq.D`（`:396`）而能读到日线，两者行为不同。影响：`higher_timeframe_context` 字段在原生路径对日线成分失效，不改变 signal 本身。
- 共振：`_analyze_resonance` 对缺周期/`UNKNOWN`/最后交易日不一致均 fail-closed（`:359-367`），输出结构化 evidence/warnings。

### 时序与数据口径
- `confirmation_time` 与 `event_time` 分离，marker 在确认时刻；共振 `resonance_time` = 最大确认时刻，不回写为更早笔/分型时间。
- 日 K 为前复权；分钟原生 15/30/60 独立目录，缺失即整体降级 F1；三周期不完整不混用口径（`CZSC_DATA_CONTRACT.md`）。
- 缺口：盘中 `date.today()` 可能含未收盘当日 K（文档自述），无交易日历补停牌 K；原生分钟与日 K 的复权一致性“仅文档声明、未以测试证明”。

### 回测证据与风险
无任何回测。CZSC 是只读展示工具，因此“已确认”仅表示“该快照可见”，不具交易含义。若未来接入，必须先补：点时间复权、停牌/新股数据不足、涨跌停不可成交、T+1、以及各买卖点作为信号的样本外收益。

---

## 4. Wyckoff 评价

### 旧 Funnel（L1–L4）
- 生产入口：`strategy/builtin/wyckoff_funnel.py`（`EXECUTION_BACKEND="wyckoff_funnel"`）→ `StrategyEngine._run_wyckoff_funnel`（`engine.py:1078-1180`）→ `run_funnel`（`funnel.py`）。这是唯一接入正式选股的 Wyckoff 路径。
- 实际口径：L1 过滤 → L2 八通道 → L3 行业/概念共振 → L4 观察。最终返回 **L3 幸存者**，`score=float(symbol in layer3_symbols)`（`engine.py:1155`），即 1.0/0.0 占位；L4 触发只写 `wyckoff_trigger`/`wyckoff_legacy_signals` 展示，不改候选（`funnel.py:133-142,167`）。
- L2：`layer2_strength.py` 八通道（主升/潜伏/吸筹/地量/暗中护盘/趋势延续/加速突破/点火破局）。**实现缺陷（已确认）**：`_rs_flags` 检查 `"pct_chg"`（`:148`），生产 enriched 提供 `change_pct`，故恒返回 `(False, False)`，主升、潜伏通道的 RS 分支死亡，且 `rs_structural_bypass`（`:161-163`）不可达。测试用 `pct_chg` 合成列掩盖（`test_wyckoff_layer2_strength.py:25`）。此外 `_ensure_pct_chg`（`wyckoff_structure.py:64-69`）有 fallback，但 L2 的 `_rs_flags` 无等价 fallback，说明是迁移时未适配 TSP 列名。
- L3：`layer3_resonance.py` 概念优先/行业兜底。生产 `_run_wyckoff_funnel` 只传 `sector_map`（Tushare `stock_basic.industry` 当前快照），不传 `concept_map/hot_concepts`（`engine.py:1098-1109`），故 `use_concept_map=True` 配置在 `concept_map=None` 时失效（`layer3_resonance.py:62`），恒走行业回退；且存在 `<3 幸存者` 或“缺分组元数据”时 fail-open 回退到全量 L2（`:103-114`、`:64-71`）。因此“板块共振”在生产是“候选集内的行业分位过滤 + 两个 fail-open 回退”。
- 无回测：`backend/app/backtest/` 无 wyckoff 引用。旧漏斗既无历史验证，也无成本/容量/回撤指标。

### L2 / L3（与 Funnel 的关系）
二者是 `run_funnel` 内部层，非独立导出产物。L2 的“个股 vs 大盘 RS + 全市场 RPS”是冻结门槛，未产出通用 DTO；L3 是“L2 候选集内”的强度分位，非全市场板块 Rank（`audit` 文档 §7 已确认）。

### Wyckoff V2（冻结规则 vs 实际生产调用）
- **冻结规则**：`v2/config.py` 的研究默认阈值（Spring 穿透 ≤1.5 ATR、CLV≥0.60、量比 1.30/0.80；SOS 突破 0.3 ATR、振幅 1.2 ATR、CLV 0.70、量 80 分位；LPS 双口径缩量 0.65/0.90 等）均为“研究起点”，本次评审未建议调整。
- **实际生产调用差异**：生产只对 `layer3_symbols` 调 `analyze_wyckoff_v2`（`engine.py:1122-1124`）且默认 `full_replay=False`，只回放 `range_lookback + horizon` 尾部窗口（`engine.py:122-127`）以取“最新事件”；`affects_formal_selection=false`，V2 输出只进 `evidence["wyckoff_snapshot"]["v2"]` 与每行 `wyckoff_v2_*` 展示字段，不改 score/候选。回测则由独立 `research_service.py` 以 `full_replay=True` 全量回放。
- **V2 证据**：三年全市场报告（`WYCKOFF.md:217-234`）显示激进/标准 Spring 平均超额≈0 或负、胜率<50%，保守 Spring T+20 超额 +0.81% 但正收益率 48.9%，LPS 样本 315 且 T+20 超额 -0.20%。报告自身结论是“均保持研究诊断，不接入 L1–L3/L4”，并指出未计成本/滑点/涨跌停/停牌、使用当前前复权价存在点时间复权前视。这是诚实且正确的处理。

### 旧 Funnel 与 V2 的隔离
`v2/__init__.py` 不导入 `wyckoff_structure`；`engine.py` 中旧漏斗结果先算，V2 只作为其上附加诊断，异常被捕获（`:1132-1137`）且不 fail-open 不 fail-closed 旧结果。隔离成立，无意外影响正式选股。

---

## 5. 当前策略组合评价

### 重复因子 / 重复职责
1. **三份“板块单日均值”**：`market_overview_builder._dimension_rank`（Dashboard）、`rps_rotation.build_rps_rotation`、`api/overview.py` 已废弃的私有聚合副本，三者按成员映射算 `mean(change_pct)`，口径/成员加载重复（`audit` 文档 §2/§3/B）。
2. **两份涨跌停实现**：`app/price_limits.py`（回测/指标用）与 `app/wyckoff/limit_move.py`（迁入但漏斗未接）。后者 `classify_limit_move` 只被测试引用，未进入 L4 触发判定，是一字板/炸板语义的“死代码”。
3. **Mainline 与 L3 的“板块选择”语义重叠**：前者是涨停梯队、后者是候选集内强度分位，样本与决策语义不同，但都被叫“主线/共振”，易混用（`audit` §7 明确不应合并）。

### 错误职责 / 展示指标误用风险
- Dashboard 的 `mainline_score` 雷达是当日情绪可视化分量，取前 N 板块最大值，不能作选股因子（`audit` §D）。
- `concept_rotation_analyzer` 的“主线/新晋/退潮”是 AI 解释标签，不应作候选池硬过滤。
- 旧漏斗把 `score=1.0` 当“属于最终集合”的占位，前端默认排序不是 Wyckoff 强弱排名（`WYCKOFF.md:77-79`）；若任何 UI 把该 score 当排序，即属误用。

### 展示指标被误用成硬过滤（已发生）
- 旧漏斗 L2 的 RS 过滤器本应是“个股 vs 大盘 RS”硬门槛，但列名不匹配使其**静默失效**（`layer2_strength.py:148`），属“本意硬过滤、实为永不通过”。这是比“展示误用”更隐蔽的问题。

### 缺失环节（相对目标链路）
目标：`Sector Strength → 板块内 Stock RS → Candidate Pool → Wyckoff/ICT`。
- **缺 Sector Strength**：无统一 `SectorStrengthResult`（收益/相对收益/Breadth/成交额放大/持续性/rank 变化）。
- **缺 Stock-vs-Sector RS**：只有 stock-vs-market（且 buggy）与 stock-vs-universe RPS；无 `RelativeStrengthEngine`、无板块内 percentile/rank。
- **缺 Candidate Pool 编排边界**：各层（Regime gate / SectorStrength / StockRS / Wyckoff）无统一编排与逐层拒绝原因。
- **已有但需降级**：CZSC、Wyckoff V2、AI Rotation 标签、Dashboard 雷达、L3 候选集 sector rank、日内分钟动量，均应保持“研究/展示/诊断”，不进核心决策。

---

## 6. 统计证据缺口（必须补齐的验证，而非调参）

1. **样本外验证**：当前唯一“有数字”的是 Wyckoff V2 三年全市场回放，且未成本化；旧漏斗与 CZSC 无任何回测。需按时间滚动（walk-forward）验证，禁止用单区间最佳结果回写默认参数。
2. **成本/滑点/涨跌停/停牌不可成交**：V2 回测 `execution.costs_and_slippage_included=False`，无涨跌停/停牌剔除；必须计入佣金+印花税+滑点，剔除一字板/停牌不可成交，T+1 卖出约束。
3. **点时间复权与幸存者偏差**：V2 用当前重建前复权价（`WYCKOFF.md:159-160` 自述）；需按交易日可得复权因子重建 point-in-time 价格序列，并用退市股历史排除幸存者偏差。
4. **基准对照与超额收益**：需逐信号日横截面等权/市值加权基准 + 简单基线（如全市场均值、买入持有 000300）对比；报告超额收益分布而非只看均值。
5. **市场环境分组**：按 Regime（BULL/SIDEWAYS/BEAR）分层报告收益，确认策略是否只在强势行情有效。
6. **收益分布与尾部**：均值/中位数/P25/P75/标准差已有（V2），但需加入最大回撤、连续亏损、按持有期的收益分布，避免只看胜率。
7. **事件重叠与重复计数**：V2 已有 5/10 日重复事件率（4.33%）与 unique range 统计，方向正确；需进一步做去重后的组合级收益，而非事件级均值。
8. **行业/概念成员历史漂移**：L3/主线均用当前成员快照；需先版本化逐日行业/概念成员再回放，否则“历史 L3”是前视。
9. **容量/流动性**：候选的成交额门槛（L1 `min_avg_amount_wan=4000万`）需与目标资金规模对比，验证冲击成本与容量上限。
10. **候选池每层增益**：逐层（Regime gate / Sector / StockRS / Wyckoff）做消融，量化每层相对上一层的增量，避免重复因子叠加。

---

## 7. 最小验证实验设计（只设计，不实现）

### 7.1 时间滚动样本外
- 用不重叠年份（如 2021/2022/2023/2024/2025 各为独立 out-of-sample），前一年数据只用于 Range 预热与参数不变。报告每个 fold 的收益/超额/回撤，取全部 fold 的中位数而非最佳 fold。

### 7.2 Regime 分组
- 复用 `regime_alignment.py` 的 T-1 对齐（或用 V2 `_market_regime` 的当日闭合 60 日 000300 收益分类），把信号按 BULL/SIDEWAYS/BEAR 分组报告，验证策略在各环境下的一致性；禁止用 Regime 标签做参数选择。

### 7.3 行业/概念成员历史漂移处理
- 为每个信号日冻结当日可得行业/概念成员（版本化快照）。缺失历史成员时，该日的 L3/主线标记为“成员不可得”，单独统计，不得用当前 Tushare 映射倒灌历史（`WYCKOFF.md:236-243` 已明令）。

### 7.4 基准、成本、滑点、涨跌停不可成交
- 基准：逐信号日全 A 等权 `D+1 open → T+N close`（已由 `research_service._benchmark` 实现，可复用）+ 000300.SH。
- 成本：固定佣金（双边）+ 印花税（卖出）+ 滑点（如 5bp 或按 ATR 比例）；一字涨停开盘不可买入、一字跌停不可卖出、停牌跳过，单列被剔除信号占比。

### 7.5 与简单基线比较
- 基线 1：全市场随机等权买入持有；基线 2：000300 买入持有；基线 3：单纯 RPS top-N（如 top 10%）。比较 V2 Entry 与基线的超额/回撤/信息比率。

### 7.6 消融实验
- Wyckoff V2：分别关闭 Spring / Test 确认 / SOS 确认 / LPS parent 约束，观察每步对收益与失效率的边际贡献；保留“原始事件 + 状态链”的对照，确认哪个确认条件真正降低风险。

### 7.7 候选池每层增益评估
- 构建 `Sector Strength → 板块内 Stock RS → Candidate Pool → Wyckoff/ICT` 后，逐层报告：候选数、命中率（后续 N 日跑赢基准比例）、每层增量超额、每层剔除后的剩余风险。每层都保留拒绝原因，量化“这一层到底贡献了什么”。

---

## 8. 最终判定（五类结论严格区分）

1. **代码实现正确（不报错/忠实）**
   - CZSC 结构计算：**基本正确**（逐快照点时间、确认时刻、数据 fail-closed），但原生分钟路径“日线高周期上下文”存在文档/实现不一致（低危，仅展示）。
   - Wyckoff V2：**正确且最严谨**（隔离、冻结区间、事件链、T+1 开盘入场、无未来函数）。
   - 旧 Wyckoff Funnel：**不正确**（L2 RS 过滤器列名 `pct_chg` 不匹配导致主升/潜伏通道静默失效；L3 概念/主线未接；`adapter`/`limit_move` 迁入后未接线）。

2. **理论逻辑合理（假设自洽）**
   - CZSC 结构/共振定位：合理；Wyckoff V2 事件-确认-Entry 分层：合理；Regime T-1 gate：合理；旧漏斗 L1–L3 分层：方向合理但“L4 只观察、最终=L3”与“漏斗”名义有偏差。

3. **有历史统计证据（样本外价值）**
   - CZSC：无。旧 Funnel：无。Mainline/Rotation/Theme：无（只有展示，无收益归因）。Wyckoff V2：有描述性回放，但未成本化 + 点时间复权前视 + 结果不显示优势，**不能据此认定有样本外价值**。**统一结论：当前没有任何一个模块具备“已验证有效”的历史统计证据。**

4. **可以进入模拟盘**
   - 仅当：Wyckoff V2 完成成本/滑点/涨跌停/停牌 + 点时间复权 + 滚动样本外 + 基准对比后，若保守型 Entry 仍显稳定优势，才可作为**模拟盘观察对象**。当前状态：**均不可直接进模拟盘**。

5. **可以进入实盘**
   - 当前：**全部不可**。没有任何模块满足“代码正确 + 理论合理 + 有样本外统计证据 + 成本化后仍有超额”的完整链条。

禁止把上述五句合并为一句“策略有效”：本评审的明确结论是——**实现层只有 Wyckoff V2 与 CZSC 结构计算是可信的，旧 Wyckoff Funnel 存在确定性缺陷；证据层没有任何模块被证明有效；组合链路缺失统一的 Sector Strength 与 Stock RS，且不应把展示/诊断指标接入核心决策。**
