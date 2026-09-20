# 候选池链路审阅复核（2026-09-13）

## 范围

本记录复核外部审阅对以下链路的结论：

```text
Wyckoff 候选 -> Sector / RS 研究上下文 -> 候选展示 -> Volume Profile 只读上下文
```

本轮只审阅与记录；不修改 Wyckoff、Sector/RS、VP、阈值、权重或正式策略排序。

## 已确认的结论

### 实现与时序

- Wyckoff 结构与事件代码产出诊断/观察信息，不把事件本身编码为买卖指令。
- Sector Strength、RS 与 VP 均有 as-of 截断、缺日 fail-closed 与前缀一致性测试；高值排名方向一致为高分/低 rank。
- 历史成员的裸代码与带市场后缀双 key 分母问题已由 `canonical_symbol()` 规范化与去重修复。
- VP Extension 曾因 Position 写入顺序错误全部落为 `VP_NORMAL`；该问题已修复，并已使用同一正式纯函数回填五日研究文件。详见 `volume-profile-extension-fix-random5.md`。
- VP 的 `VP_NORMAL/ELEVATED/EXTENDED/EXTREME` 枚举值已有 `VP_` 前缀，和 Sector/RS 的无前缀 Extension 状态在数据契约上不同；未来前端展示仍应保留“VP 延展”与“Sector/RS 延展”的中文来源标识，避免语义误读。

### 职责边界

- Wyckoff 决定候选集合；`rank_wyckoff_candidates()` 不删除候选，只计算解释性 Sector/RS 研究上下文。
- VP 当前不进入 `final_rank_score` 或正式候选排序，只输出 Position、Acceptance、Migration、Extension 等上下文。
- Sector/RS 动态 Phase/State 消费冻结静态分数，不改写 Sector Strength V1.1 或 Relative Strength V1 的定义。

## 外部审阅中已过时的两项描述

### `final_rank_score` 已不再写入通用 Strategy score

外部审阅提到 `final_rank_score` 写入 `StrategyResult.scores` 并决定 Wyckoff 默认顺序。当前实现不是这样：

```text
final_rank_score -> research_context_score
rank             -> research_context_rank
priority_level   -> research_context_level
StrategyResult.scores = {}
ranking_mode = research_context_only
candidate_order 保持 Wyckoff 原候选顺序
```

证据：`backend/app/strategy/engine.py` 的 `_run_wyckoff_funnel()`。因此“不要让未验证的 Sector/RS 分主导 Wyckoff 默认顺序”这项建议已经落实为当前行为；研究字段仍会展示，不能被误解为正式交易评分。

### RangeVP 预载现在已 as-of 过滤

外部审阅提到 `run_volume_profile_context_validation.py` 的 RangeVP preload 只取 `range_start` 而没有筛掉未来确认的范围。当前实现已在两处收口：

- 研究脚本仅在 `range_start` 与 `range_confirmed_at` 均存在、且 `range_confirmed_at <= as_of` 时传入预载；
- `VolumeProfileService.prepare_batch_context()` 再次以相同条件过滤，并且实际 RangeVP 构建还在服务层 fail-closed。

因此该历史描述目前只会对应旧版本，不再是现行问题。

## 证据层：应维持研究级别

外部审阅的核心研究治理判断成立：目前没有足够、稳定、独立且数据口径完全无偏的前向证据，支持把 Sector/RS 的高静态分、Phase/State 调整或 VP Context 升级为正式候选排序规则。

现有报告显示的更准确表述是：

- Sector/RS 的前向表现存在跨年份、跨月份不稳定或反转现象；
- 行业历史成员已使用申万历史区间，但概念成员仍有当前同花顺快照的历史漂移风险；
- VP Extension 修复后有“高延展 MAE 扩大”的描述性风险路径，尚无严格单调的收益证据；
- 五日 VP 样本仅用于方法和状态诊断，不能推导权重、阈值或 VPScore。

这意味着“尚无证据支持正式排序”，而不是数学上证明因子永远无效。历史成员、可交易性、重复候选与市场 regime 仍是影响研究外推的竞争解释。

## 当前决策

1. 保持 `research_context_score/rank/level` 为只读研究字段，不写入通用 `StrategyResult.scores`，不改变 `candidate_order`。
2. 保持 VP 为独立 Position/Risk Context；不创建 VPScore，不接入 `final_rank_score`。
3. 不基于现有短样本调 Sector/RS/VP 的权重、阈值或方向。
4. 后续优先补充独立、分钟 FULL、可交易性明确的样本，并以 Wyckoff 结构事件的首次确认日降低连续重复候选对统计的影响。
5. 若未来在 UI 同时展示两类 Extension，明确标为“Sector/RS 延展”和“VP 上行延展”，不要只显示无来源的 `EXTENDED`。

## 相关证据

- `docs/research/sector-rs/sector-rs-independent-validation.md`
- `docs/audits/sector-rs-data-and-implementation-audit.md`
- `docs/research/wyckoff/wyckoff-sector-rs-jan-feb-comparison.md`
- `docs/research/volume-profile/volume-profile-v1-vp-first-random5-analysis.md`
- `docs/research/volume-profile/volume-profile-extension-fix-random5.md`
