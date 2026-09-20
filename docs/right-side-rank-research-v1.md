# Right-Side Rank Research V1

## 冻结输入与双维定义

本研究只读取已完成的随机 12 日 `ALL_WYCKOFF + VP` snapshot；没有重放 Wyckoff、修改 Sector/RS/VP/Acceptance/Extension，或使用未来收益拟合参数。

| item | value |
| --- | --- |
| random seed | 20260913 |
| signal dates | 2025-12-15、2025-12-18、2026-01-30、2026-02-26、2026-03-10、2026-03-26、2026-04-13、2026-05-12、2026-05-21、2026-06-17、2026-07-20、2026-08-10 |
| months | 2025-12、2026-01、2026-02、2026-03、2026-04、2026-05、2026-06、2026-07、2026-08 |
| observations / unique symbols | 11328 / 4030 |
| VP20 FULL / VP60 FULL | 11307/11328 (99.81%) / 11283/11328 (99.60%) |
| rank-research runtime | 3.11s |
| raw / tradable-next-open proxy | 11328 / 11299 |

`OpportunityScore = 0.40 × sector_score + 0.60 × rs_score`，直接复用冻结 strength 的原始构成；不使用 `research_context_score` 或任何 phase/state/extension 调整。Sector Phase、RS State、已有 sector breadth 字段若存在均仅保留为解释字段。

`RiskScoreRaw = VP20ExtensionRisk + VP60ExtensionRisk`，其中 NORMAL/ELEVATED/EXTENDED/EXTREME 固定映射为 0/1/2/3，`RiskScore = Raw/6×100`。风险桶按两个 profile 的**最严重**冻结状态固定为 LOW/MEDIUM/HIGH/EXTREME；任一 profile 不是 FULL 时标记 UNKNOWN。这是展示和消融映射，不是收益优化权重。

V0 以 Opportunity 排序；V1 是不加点、不删样本的 Acceptance context-first 词典序消融（BOTH_D、ANY_D、ANY_B_OR_C、ANY_A、NONE；同一 context 内再按 Opportunity）；V2 与 V0 具有相同 Opportunity 排名而单独显示 Risk；V3 与 V1 具有相同 Opportunity 排名而单独显示 Risk。另给出 `V3 risk tie-break`（Opportunity 主排序、Risk 次排序）诊断。没有 Acceptance 加分、Risk 扣分、VP 过滤或正式 Final Rank。

收益口径保持 D 收盘后信号、D+1 Open 进入、T+N Close 退出。`tradable-next-open proxy` 仅验证正开盘价和 T+20 标签；它不是涨跌停/停牌/流动性的完整成交模型。

## 母样本与 V0 基线

| group | horizon | n | unique symbols | unique dates | tradable proxy | mean return | median return | mean excess | median excess | positive excess | PF | mean MAE | mean MFE | sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ALL_WYCKOFF | T+1 | 11324 | 4029 | 12 | 11299 | 0.79% | 0.38% | 0.42% | -0.04% | 49.37% | 1.42 | -2.13% | 3.15% |  |
| ALL_WYCKOFF | T+3 | 11316 | 4029 | 12 | 11291 | 0.42% | -0.15% | -0.02% | -0.81% | 41.94% | 0.99 | -3.93% | 5.83% |  |
| ALL_WYCKOFF | T+5 | 11298 | 4024 | 12 | 11274 | 1.17% | 0.20% | 0.51% | -0.79% | 43.90% | 1.19 | -5.10% | 7.37% |  |
| ALL_WYCKOFF | T+10 | 11280 | 4017 | 12 | 11256 | 0.98% | 0.23% | 0.77% | -0.84% | 45.99% | 1.20 | -7.57% | 10.80% |  |
| ALL_WYCKOFF | T+20 | 11238 | 3999 | 12 | 11238 | 2.26% | -0.46% | 1.15% | -2.79% | 40.92% | 1.20 | -10.72% | 17.04% |  |
| V0 Top10 | T+1 | 120 | 107 | 12 | 119 | 0.80% | 0.00% | 0.51% | -0.29% | 49.17% | 1.26 | -3.99% | 5.12% |  |
| V0 Top10 | T+3 | 120 | 107 | 12 | 119 | -0.67% | -2.98% | -1.06% | -3.45% | 38.33% | 0.79 | -7.62% | 9.51% |  |
| V0 Top10 | T+5 | 120 | 107 | 12 | 119 | 1.42% | -1.32% | 0.86% | -2.57% | 46.67% | 1.15 | -9.59% | 12.32% |  |
| V0 Top10 | T+10 | 119 | 107 | 12 | 118 | 2.92% | -1.46% | 2.86% | -0.71% | 46.22% | 1.44 | -12.05% | 18.51% |  |
| V0 Top10 | T+20 | 117 | 106 | 12 | 117 | 10.14% | -3.68% | 9.44% | -5.12% | 41.88% | 2.22 | -15.57% | 31.61% |  |
| V0 Top20 | T+1 | 240 | 211 | 12 | 239 | 0.91% | 0.00% | 0.62% | -0.44% | 47.50% | 1.35 | -3.73% | 5.07% |  |
| V0 Top20 | T+3 | 240 | 211 | 12 | 239 | -0.41% | -2.06% | -0.80% | -2.45% | 38.75% | 0.83 | -7.07% | 9.32% |  |
| V0 Top20 | T+5 | 240 | 211 | 12 | 239 | 1.68% | -1.28% | 1.12% | -1.75% | 44.58% | 1.22 | -8.97% | 12.24% |  |
| V0 Top20 | T+10 | 239 | 211 | 12 | 238 | 3.38% | -1.25% | 3.33% | -0.30% | 48.12% | 1.55 | -11.29% | 18.70% |  |
| V0 Top20 | T+20 | 237 | 210 | 12 | 237 | 8.46% | -2.95% | 7.74% | -3.66% | 44.30% | 2.01 | -14.82% | 30.76% |  |
| V0 Top50 | T+1 | 599 | 484 | 12 | 597 | 1.13% | 0.33% | 0.84% | 0.15% | 51.25% | 1.55 | -3.29% | 4.83% |  |
| V0 Top50 | T+3 | 598 | 484 | 12 | 596 | 0.07% | -1.20% | -0.31% | -1.80% | 41.30% | 0.92 | -6.14% | 8.73% |  |
| V0 Top50 | T+5 | 598 | 484 | 12 | 596 | 1.76% | -0.12% | 1.20% | -0.72% | 46.82% | 1.29 | -7.69% | 11.11% |  |
| V0 Top50 | T+10 | 596 | 483 | 12 | 594 | 2.56% | -0.12% | 2.51% | -0.17% | 49.33% | 1.49 | -10.05% | 16.58% |  |
| V0 Top50 | T+20 | 593 | 481 | 12 | 593 | 7.27% | -2.03% | 6.54% | -2.44% | 45.19% | 1.96 | -13.43% | 27.19% |  |

V0 相对母样本的日期等权比较：

| comparison | metric | horizon | matched dates | left wins | right wins | ties | left win rate | mean difference | median difference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0 Top10 - ALL_WYCKOFF | mean_excess | T+1 | 12 | 7 | 5 | 0 | 58.33% | 0.09% | 0.74% |
| V0 Top10 - ALL_WYCKOFF | median_excess | T+1 | 12 | 6 | 6 | 0 | 50.00% | -0.16% | 0.08% |
| V0 Top10 - ALL_WYCKOFF | positive_rate | T+1 | 12 | 6 | 6 | 0 | 50.00% | -0.25% | 1.58% |
| V0 Top10 - ALL_WYCKOFF | mae | T+1 | 12 | 0 | 12 | 0 | 0.00% | -1.84% | -1.71% |
| V0 Top10 - ALL_WYCKOFF | mfe | T+1 | 12 | 10 | 2 | 0 | 83.33% | 1.97% | 2.04% |
| V0 Top10 - ALL_WYCKOFF | mean_excess | T+3 | 12 | 4 | 8 | 0 | 33.33% | -0.99% | -0.80% |
| V0 Top10 - ALL_WYCKOFF | median_excess | T+3 | 12 | 4 | 8 | 0 | 33.33% | -1.72% | -1.08% |
| V0 Top10 - ALL_WYCKOFF | positive_rate | T+3 | 12 | 6 | 6 | 0 | 50.00% | -3.34% | -4.70% |
| V0 Top10 - ALL_WYCKOFF | mae | T+3 | 12 | 1 | 11 | 0 | 8.33% | -3.61% | -2.43% |
| V0 Top10 - ALL_WYCKOFF | mfe | T+3 | 12 | 11 | 1 | 0 | 91.67% | 3.66% | 3.21% |
| V0 Top10 - ALL_WYCKOFF | mean_excess | T+5 | 12 | 6 | 6 | 0 | 50.00% | 0.39% | 0.32% |
| V0 Top10 - ALL_WYCKOFF | median_excess | T+5 | 12 | 5 | 7 | 0 | 41.67% | -0.35% | -2.06% |
| V0 Top10 - ALL_WYCKOFF | positive_rate | T+5 | 12 | 6 | 6 | 0 | 50.00% | 2.82% | -1.42% |
| V0 Top10 - ALL_WYCKOFF | mae | T+5 | 12 | 2 | 10 | 0 | 16.67% | -4.37% | -3.31% |
| V0 Top10 - ALL_WYCKOFF | mfe | T+5 | 12 | 11 | 1 | 0 | 91.67% | 4.95% | 4.37% |
| V0 Top10 - ALL_WYCKOFF | mean_excess | T+10 | 12 | 7 | 5 | 0 | 58.33% | 2.21% | 4.32% |
| V0 Top10 - ALL_WYCKOFF | median_excess | T+10 | 12 | 7 | 5 | 0 | 58.33% | 1.10% | 4.91% |
| V0 Top10 - ALL_WYCKOFF | positive_rate | T+10 | 12 | 7 | 5 | 0 | 58.33% | 0.91% | 9.26% |
| V0 Top10 - ALL_WYCKOFF | mae | T+10 | 12 | 3 | 9 | 0 | 25.00% | -4.29% | -3.44% |
| V0 Top10 - ALL_WYCKOFF | mfe | T+10 | 12 | 11 | 1 | 0 | 91.67% | 7.80% | 6.43% |
| V0 Top10 - ALL_WYCKOFF | mean_excess | T+20 | 12 | 7 | 5 | 0 | 58.33% | 8.70% | 3.26% |
| V0 Top10 - ALL_WYCKOFF | median_excess | T+20 | 12 | 5 | 7 | 0 | 41.67% | 6.04% | -1.45% |
| V0 Top10 - ALL_WYCKOFF | positive_rate | T+20 | 12 | 5 | 7 | 0 | 41.67% | 1.68% | -5.85% |
| V0 Top10 - ALL_WYCKOFF | mae | T+20 | 12 | 3 | 9 | 0 | 25.00% | -4.49% | -4.06% |
| V0 Top10 - ALL_WYCKOFF | mfe | T+20 | 12 | 9 | 3 | 0 | 75.00% | 15.30% | 11.35% |
| V0 Top20 - ALL_WYCKOFF | mean_excess | T+1 | 12 | 7 | 5 | 0 | 58.33% | 0.20% | 0.89% |
| V0 Top20 - ALL_WYCKOFF | median_excess | T+1 | 12 | 6 | 6 | 0 | 50.00% | 0.03% | 0.12% |
| V0 Top20 - ALL_WYCKOFF | positive_rate | T+1 | 12 | 6 | 6 | 0 | 50.00% | -1.91% | -0.11% |
| V0 Top20 - ALL_WYCKOFF | mae | T+1 | 12 | 0 | 12 | 0 | 0.00% | -1.58% | -1.43% |
| V0 Top20 - ALL_WYCKOFF | mfe | T+1 | 12 | 10 | 2 | 0 | 83.33% | 1.92% | 1.68% |
| V0 Top20 - ALL_WYCKOFF | mean_excess | T+3 | 12 | 5 | 7 | 0 | 41.67% | -0.73% | -0.84% |
| V0 Top20 - ALL_WYCKOFF | median_excess | T+3 | 12 | 5 | 7 | 0 | 41.67% | -1.53% | -0.39% |
| V0 Top20 - ALL_WYCKOFF | positive_rate | T+3 | 12 | 6 | 6 | 0 | 50.00% | -2.92% | -0.01% |
| V0 Top20 - ALL_WYCKOFF | mae | T+3 | 12 | 1 | 11 | 0 | 8.33% | -3.06% | -2.38% |
| V0 Top20 - ALL_WYCKOFF | mfe | T+3 | 12 | 10 | 2 | 0 | 83.33% | 3.47% | 3.51% |
| V0 Top20 - ALL_WYCKOFF | mean_excess | T+5 | 12 | 7 | 5 | 0 | 58.33% | 0.66% | 1.22% |
| V0 Top20 - ALL_WYCKOFF | median_excess | T+5 | 12 | 6 | 6 | 0 | 50.00% | -0.21% | 0.34% |
| V0 Top20 - ALL_WYCKOFF | positive_rate | T+5 | 12 | 7 | 5 | 0 | 58.33% | 0.74% | 3.58% |
| V0 Top20 - ALL_WYCKOFF | mae | T+5 | 12 | 2 | 10 | 0 | 16.67% | -3.75% | -2.63% |
| V0 Top20 - ALL_WYCKOFF | mfe | T+5 | 12 | 10 | 2 | 0 | 83.33% | 4.87% | 5.01% |
| V0 Top20 - ALL_WYCKOFF | mean_excess | T+10 | 12 | 7 | 5 | 0 | 58.33% | 2.66% | 3.89% |
| V0 Top20 - ALL_WYCKOFF | median_excess | T+10 | 12 | 8 | 4 | 0 | 66.67% | 1.41% | 2.68% |
| V0 Top20 - ALL_WYCKOFF | positive_rate | T+10 | 12 | 8 | 4 | 0 | 66.67% | 2.80% | 13.11% |
| V0 Top20 - ALL_WYCKOFF | mae | T+10 | 12 | 3 | 9 | 0 | 25.00% | -3.52% | -2.50% |
| V0 Top20 - ALL_WYCKOFF | mfe | T+10 | 12 | 11 | 1 | 0 | 91.67% | 7.97% | 7.36% |
| V0 Top20 - ALL_WYCKOFF | mean_excess | T+20 | 12 | 6 | 6 | 0 | 50.00% | 6.89% | 3.94% |
| V0 Top20 - ALL_WYCKOFF | median_excess | T+20 | 12 | 6 | 6 | 0 | 50.00% | 5.08% | 1.30% |
| V0 Top20 - ALL_WYCKOFF | positive_rate | T+20 | 12 | 6 | 6 | 0 | 50.00% | 4.01% | -0.33% |
| V0 Top20 - ALL_WYCKOFF | mae | T+20 | 12 | 3 | 9 | 0 | 25.00% | -3.74% | -3.35% |
| V0 Top20 - ALL_WYCKOFF | mfe | T+20 | 12 | 9 | 3 | 0 | 75.00% | 14.21% | 13.93% |
| V0 Top50 - ALL_WYCKOFF | mean_excess | T+1 | 12 | 8 | 4 | 0 | 66.67% | 0.42% | 0.63% |
| V0 Top50 - ALL_WYCKOFF | median_excess | T+1 | 12 | 7 | 5 | 0 | 58.33% | 0.23% | 0.29% |
| V0 Top50 - ALL_WYCKOFF | positive_rate | T+1 | 12 | 7 | 5 | 0 | 58.33% | 1.82% | 1.20% |
| V0 Top50 - ALL_WYCKOFF | mae | T+1 | 12 | 0 | 12 | 0 | 0.00% | -1.14% | -1.14% |
| V0 Top50 - ALL_WYCKOFF | mfe | T+1 | 12 | 12 | 0 | 0 | 100.00% | 1.68% | 1.60% |
| V0 Top50 - ALL_WYCKOFF | mean_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | -0.24% | -0.08% |
| V0 Top50 - ALL_WYCKOFF | median_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | -0.85% | -0.33% |
| V0 Top50 - ALL_WYCKOFF | positive_rate | T+3 | 12 | 6 | 6 | 0 | 50.00% | -0.37% | -1.05% |
| V0 Top50 - ALL_WYCKOFF | mae | T+3 | 12 | 2 | 10 | 0 | 16.67% | -2.13% | -1.75% |
| V0 Top50 - ALL_WYCKOFF | mfe | T+3 | 12 | 11 | 1 | 0 | 91.67% | 2.89% | 2.42% |
| V0 Top50 - ALL_WYCKOFF | mean_excess | T+5 | 12 | 7 | 5 | 0 | 58.33% | 0.75% | 1.01% |
| V0 Top50 - ALL_WYCKOFF | median_excess | T+5 | 12 | 7 | 5 | 0 | 58.33% | 0.27% | 0.95% |
| V0 Top50 - ALL_WYCKOFF | positive_rate | T+5 | 12 | 7 | 5 | 0 | 58.33% | 3.03% | 3.18% |
| V0 Top50 - ALL_WYCKOFF | mae | T+5 | 12 | 2 | 10 | 0 | 16.67% | -2.46% | -2.00% |
| V0 Top50 - ALL_WYCKOFF | mfe | T+5 | 12 | 11 | 1 | 0 | 91.67% | 3.74% | 4.02% |
| V0 Top50 - ALL_WYCKOFF | mean_excess | T+10 | 12 | 7 | 5 | 0 | 58.33% | 1.84% | 3.58% |
| V0 Top50 - ALL_WYCKOFF | median_excess | T+10 | 12 | 7 | 5 | 0 | 58.33% | 0.14% | 1.54% |
| V0 Top50 - ALL_WYCKOFF | positive_rate | T+10 | 12 | 8 | 4 | 0 | 66.67% | 3.96% | 9.29% |
| V0 Top50 - ALL_WYCKOFF | mae | T+10 | 12 | 4 | 8 | 0 | 33.33% | -2.29% | -1.85% |
| V0 Top50 - ALL_WYCKOFF | mfe | T+10 | 12 | 11 | 1 | 0 | 91.67% | 5.83% | 6.89% |
| V0 Top50 - ALL_WYCKOFF | mean_excess | T+20 | 12 | 6 | 6 | 0 | 50.00% | 5.64% | 1.50% |
| V0 Top50 - ALL_WYCKOFF | median_excess | T+20 | 12 | 6 | 6 | 0 | 50.00% | 3.81% | 1.11% |
| V0 Top50 - ALL_WYCKOFF | positive_rate | T+20 | 12 | 8 | 4 | 0 | 66.67% | 4.85% | 2.43% |
| V0 Top50 - ALL_WYCKOFF | mae | T+20 | 12 | 3 | 9 | 0 | 25.00% | -2.35% | -2.82% |
| V0 Top50 - ALL_WYCKOFF | mfe | T+20 | 12 | 11 | 1 | 0 | 91.67% | 10.49% | 8.08% |

V0 Top10 vs ALL T+10 mean excess: 左组更优 5/9 months；月份差值 2025-12=10.43%, 2026-01=-5.80%, 2026-02=-3.95%, 2026-03=-15.10%, 2026-04=13.67%, 2026-05=13.77%, 2026-06=4.14%, 2026-07=-4.29%, 2026-08=4.50%。
V0 Top10 vs ALL T+10 MAE: 左组更优 2/9 months；月份差值 2025-12=-5.69%, 2026-01=-4.74%, 2026-02=-3.44%, 2026-03=-12.13%, 2026-04=1.47%, 2026-05=0.96%, 2026-06=-0.19%, 2026-07=-4.16%, 2026-08=-6.68%。
V0 Top20 vs ALL T+10 mean excess: 左组更优 5/9 months；月份差值 2025-12=13.39%, 2026-01=-3.62%, 2026-02=-1.49%, 2026-03=-13.18%, 2026-04=10.67%, 2026-05=12.28%, 2026-06=5.92%, 2026-07=-6.33%, 2026-08=1.85%。
V0 Top20 vs ALL T+10 MAE: 左组更优 3/9 months；月份差值 2025-12=-4.63%, 2026-01=-3.66%, 2026-02=-2.63%, 2026-03=-10.44%, 2026-04=1.05%, 2026-05=0.37%, 2026-06=1.55%, 2026-07=-5.02%, 2026-08=-4.18%。
V0 Top50 vs ALL T+10 mean excess: 左组更优 5/9 months；月份差值 2025-12=6.63%, 2026-01=-4.41%, 2026-02=-1.81%, 2026-03=-8.70%, 2026-04=8.13%, 2026-05=10.27%, 2026-06=4.41%, 2026-07=-3.40%, 2026-08=2.76%。
V0 Top50 vs ALL T+10 MAE: 左组更优 3/9 months；月份差值 2025-12=-3.31%, 2026-01=-3.27%, 2026-02=-3.54%, 2026-03=-7.15%, 2026-04=0.34%, 2026-05=1.33%, 2026-06=2.23%, 2026-07=-2.95%, 2026-08=-1.99%。

## V0–V3 TopN 消融

每张表首先给 pooled stock-date 结果；随后给日期等权差异。MAE 的正差值表示左组 MAE 更接近零、风险路径更健康。

### Top10

| group | horizon | n | unique symbols | unique dates | tradable proxy | mean return | median return | mean excess | median excess | positive excess | PF | mean MAE | mean MFE | sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ALL_WYCKOFF | T+1 | 11324 | 4029 | 12 | 11299 | 0.79% | 0.38% | 0.42% | -0.04% | 49.37% | 1.42 | -2.13% | 3.15% |  |
| ALL_WYCKOFF | T+3 | 11316 | 4029 | 12 | 11291 | 0.42% | -0.15% | -0.02% | -0.81% | 41.94% | 0.99 | -3.93% | 5.83% |  |
| ALL_WYCKOFF | T+5 | 11298 | 4024 | 12 | 11274 | 1.17% | 0.20% | 0.51% | -0.79% | 43.90% | 1.19 | -5.10% | 7.37% |  |
| ALL_WYCKOFF | T+10 | 11280 | 4017 | 12 | 11256 | 0.98% | 0.23% | 0.77% | -0.84% | 45.99% | 1.20 | -7.57% | 10.80% |  |
| ALL_WYCKOFF | T+20 | 11238 | 3999 | 12 | 11238 | 2.26% | -0.46% | 1.15% | -2.79% | 40.92% | 1.20 | -10.72% | 17.04% |  |
| V0 Top10 | T+1 | 120 | 107 | 12 | 119 | 0.80% | 0.00% | 0.51% | -0.29% | 49.17% | 1.26 | -3.99% | 5.12% |  |
| V0 Top10 | T+3 | 120 | 107 | 12 | 119 | -0.67% | -2.98% | -1.06% | -3.45% | 38.33% | 0.79 | -7.62% | 9.51% |  |
| V0 Top10 | T+5 | 120 | 107 | 12 | 119 | 1.42% | -1.32% | 0.86% | -2.57% | 46.67% | 1.15 | -9.59% | 12.32% |  |
| V0 Top10 | T+10 | 119 | 107 | 12 | 118 | 2.92% | -1.46% | 2.86% | -0.71% | 46.22% | 1.44 | -12.05% | 18.51% |  |
| V0 Top10 | T+20 | 117 | 106 | 12 | 117 | 10.14% | -3.68% | 9.44% | -5.12% | 41.88% | 2.22 | -15.57% | 31.61% |  |
| V1 Acceptance context Top10 | T+1 | 119 | 117 | 12 | 119 | 1.35% | 1.03% | 1.05% | 0.85% | 57.98% | 1.97 | -2.76% | 4.29% |  |
| V1 Acceptance context Top10 | T+3 | 119 | 117 | 12 | 119 | 0.48% | -1.45% | 0.09% | -1.37% | 42.86% | 1.02 | -5.80% | 8.91% |  |
| V1 Acceptance context Top10 | T+5 | 119 | 117 | 12 | 119 | 2.09% | -0.03% | 1.52% | -0.67% | 48.74% | 1.36 | -7.56% | 11.26% |  |
| V1 Acceptance context Top10 | T+10 | 119 | 117 | 12 | 119 | 2.92% | -0.69% | 2.87% | -0.46% | 47.90% | 1.59 | -10.02% | 17.00% |  |
| V1 Acceptance context Top10 | T+20 | 119 | 117 | 12 | 119 | 7.51% | 1.09% | 6.76% | -0.10% | 48.74% | 2.06 | -13.00% | 26.65% |  |
| V2 Risk overlay Top10 | T+1 | 120 | 107 | 12 | 119 | 0.80% | 0.00% | 0.51% | -0.29% | 49.17% | 1.26 | -3.99% | 5.12% |  |
| V2 Risk overlay Top10 | T+3 | 120 | 107 | 12 | 119 | -0.67% | -2.98% | -1.06% | -3.45% | 38.33% | 0.79 | -7.62% | 9.51% |  |
| V2 Risk overlay Top10 | T+5 | 120 | 107 | 12 | 119 | 1.42% | -1.32% | 0.86% | -2.57% | 46.67% | 1.15 | -9.59% | 12.32% |  |
| V2 Risk overlay Top10 | T+10 | 119 | 107 | 12 | 118 | 2.92% | -1.46% | 2.86% | -0.71% | 46.22% | 1.44 | -12.05% | 18.51% |  |
| V2 Risk overlay Top10 | T+20 | 117 | 106 | 12 | 117 | 10.14% | -3.68% | 9.44% | -5.12% | 41.88% | 2.22 | -15.57% | 31.61% |  |
| V3 Acceptance + Risk Top10 | T+1 | 119 | 117 | 12 | 119 | 1.35% | 1.03% | 1.05% | 0.85% | 57.98% | 1.97 | -2.76% | 4.29% |  |
| V3 Acceptance + Risk Top10 | T+3 | 119 | 117 | 12 | 119 | 0.48% | -1.45% | 0.09% | -1.37% | 42.86% | 1.02 | -5.80% | 8.91% |  |
| V3 Acceptance + Risk Top10 | T+5 | 119 | 117 | 12 | 119 | 2.09% | -0.03% | 1.52% | -0.67% | 48.74% | 1.36 | -7.56% | 11.26% |  |
| V3 Acceptance + Risk Top10 | T+10 | 119 | 117 | 12 | 119 | 2.92% | -0.69% | 2.87% | -0.46% | 47.90% | 1.59 | -10.02% | 17.00% |  |
| V3 Acceptance + Risk Top10 | T+20 | 119 | 117 | 12 | 119 | 7.51% | 1.09% | 6.76% | -0.10% | 48.74% | 2.06 | -13.00% | 26.65% |  |
| V3 risk tie-break Top10 | T+1 | 120 | 107 | 12 | 119 | 0.80% | 0.00% | 0.51% | -0.29% | 49.17% | 1.26 | -3.99% | 5.12% |  |
| V3 risk tie-break Top10 | T+3 | 120 | 107 | 12 | 119 | -0.67% | -2.98% | -1.06% | -3.45% | 38.33% | 0.79 | -7.62% | 9.51% |  |
| V3 risk tie-break Top10 | T+5 | 120 | 107 | 12 | 119 | 1.42% | -1.32% | 0.86% | -2.57% | 46.67% | 1.15 | -9.59% | 12.32% |  |
| V3 risk tie-break Top10 | T+10 | 119 | 107 | 12 | 118 | 2.92% | -1.46% | 2.86% | -0.71% | 46.22% | 1.44 | -12.05% | 18.51% |  |
| V3 risk tie-break Top10 | T+20 | 117 | 106 | 12 | 117 | 10.14% | -3.68% | 9.44% | -5.12% | 41.88% | 2.22 | -15.57% | 31.61% |  |

日期等权比较（左组 - V0）：

| comparison | metric | horizon | matched dates | left wins | right wins | ties | left win rate | mean difference | median difference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V1 Acceptance context - V0 | mean_excess | T+1 | 12 | 6 | 6 | 0 | 50.00% | 0.51% | -0.23% |
| V1 Acceptance context - V0 | median_excess | T+1 | 12 | 7 | 5 | 0 | 58.33% | 0.78% | 0.29% |
| V1 Acceptance context - V0 | positive_rate | T+1 | 12 | 8 | 3 | 1 | 66.67% | 8.70% | 10.00% |
| V1 Acceptance context - V0 | mae | T+1 | 12 | 11 | 1 | 0 | 91.67% | 1.22% | 1.00% |
| V1 Acceptance context - V0 | mfe | T+1 | 12 | 5 | 7 | 0 | 41.67% | -0.84% | -0.32% |
| V1 Acceptance context - V0 | mean_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | 1.13% | 0.28% |
| V1 Acceptance context - V0 | median_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | 1.39% | 0.78% |
| V1 Acceptance context - V0 | positive_rate | T+3 | 12 | 7 | 4 | 1 | 58.33% | 4.44% | 6.67% |
| V1 Acceptance context - V0 | mae | T+3 | 12 | 8 | 4 | 0 | 66.67% | 1.80% | 1.43% |
| V1 Acceptance context - V0 | mfe | T+3 | 12 | 6 | 6 | 0 | 50.00% | -0.62% | -0.06% |
| V1 Acceptance context - V0 | mean_excess | T+5 | 12 | 8 | 4 | 0 | 66.67% | 0.61% | 1.46% |
| V1 Acceptance context - V0 | median_excess | T+5 | 12 | 8 | 4 | 0 | 66.67% | 0.67% | 0.81% |
| V1 Acceptance context - V0 | positive_rate | T+5 | 12 | 6 | 5 | 1 | 50.00% | 1.94% | 5.00% |
| V1 Acceptance context - V0 | mae | T+5 | 12 | 8 | 4 | 0 | 66.67% | 1.98% | 1.63% |
| V1 Acceptance context - V0 | mfe | T+5 | 12 | 6 | 6 | 0 | 50.00% | -1.10% | -0.11% |
| V1 Acceptance context - V0 | mean_excess | T+10 | 12 | 7 | 5 | 0 | 58.33% | -0.08% | 0.93% |
| V1 Acceptance context - V0 | median_excess | T+10 | 12 | 7 | 5 | 0 | 58.33% | 0.95% | 3.77% |
| V1 Acceptance context - V0 | positive_rate | T+10 | 12 | 6 | 4 | 2 | 50.00% | 1.30% | 5.00% |
| V1 Acceptance context - V0 | mae | T+10 | 12 | 7 | 5 | 0 | 58.33% | 1.99% | 1.22% |
| V1 Acceptance context - V0 | mfe | T+10 | 12 | 5 | 7 | 0 | 41.67% | -1.63% | -0.68% |
| V1 Acceptance context - V0 | mean_excess | T+20 | 12 | 7 | 5 | 0 | 58.33% | -2.81% | 2.67% |
| V1 Acceptance context - V0 | median_excess | T+20 | 12 | 8 | 4 | 0 | 66.67% | -1.19% | 2.44% |
| V1 Acceptance context - V0 | positive_rate | T+20 | 12 | 7 | 2 | 3 | 58.33% | 6.85% | 9.44% |
| V1 Acceptance context - V0 | mae | T+20 | 12 | 7 | 5 | 0 | 58.33% | 2.55% | 0.55% |
| V1 Acceptance context - V0 | mfe | T+20 | 12 | 6 | 6 | 0 | 50.00% | -5.44% | 0.09% |
| V2 Risk overlay - V0 | mean_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 Acceptance + Risk - V0 | mean_excess | T+1 | 12 | 6 | 6 | 0 | 50.00% | 0.51% | -0.23% |
| V3 Acceptance + Risk - V0 | median_excess | T+1 | 12 | 7 | 5 | 0 | 58.33% | 0.78% | 0.29% |
| V3 Acceptance + Risk - V0 | positive_rate | T+1 | 12 | 8 | 3 | 1 | 66.67% | 8.70% | 10.00% |
| V3 Acceptance + Risk - V0 | mae | T+1 | 12 | 11 | 1 | 0 | 91.67% | 1.22% | 1.00% |
| V3 Acceptance + Risk - V0 | mfe | T+1 | 12 | 5 | 7 | 0 | 41.67% | -0.84% | -0.32% |
| V3 Acceptance + Risk - V0 | mean_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | 1.13% | 0.28% |
| V3 Acceptance + Risk - V0 | median_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | 1.39% | 0.78% |
| V3 Acceptance + Risk - V0 | positive_rate | T+3 | 12 | 7 | 4 | 1 | 58.33% | 4.44% | 6.67% |
| V3 Acceptance + Risk - V0 | mae | T+3 | 12 | 8 | 4 | 0 | 66.67% | 1.80% | 1.43% |
| V3 Acceptance + Risk - V0 | mfe | T+3 | 12 | 6 | 6 | 0 | 50.00% | -0.62% | -0.06% |
| V3 Acceptance + Risk - V0 | mean_excess | T+5 | 12 | 8 | 4 | 0 | 66.67% | 0.61% | 1.46% |
| V3 Acceptance + Risk - V0 | median_excess | T+5 | 12 | 8 | 4 | 0 | 66.67% | 0.67% | 0.81% |
| V3 Acceptance + Risk - V0 | positive_rate | T+5 | 12 | 6 | 5 | 1 | 50.00% | 1.94% | 5.00% |
| V3 Acceptance + Risk - V0 | mae | T+5 | 12 | 8 | 4 | 0 | 66.67% | 1.98% | 1.63% |
| V3 Acceptance + Risk - V0 | mfe | T+5 | 12 | 6 | 6 | 0 | 50.00% | -1.10% | -0.11% |
| V3 Acceptance + Risk - V0 | mean_excess | T+10 | 12 | 7 | 5 | 0 | 58.33% | -0.08% | 0.93% |
| V3 Acceptance + Risk - V0 | median_excess | T+10 | 12 | 7 | 5 | 0 | 58.33% | 0.95% | 3.77% |
| V3 Acceptance + Risk - V0 | positive_rate | T+10 | 12 | 6 | 4 | 2 | 50.00% | 1.30% | 5.00% |
| V3 Acceptance + Risk - V0 | mae | T+10 | 12 | 7 | 5 | 0 | 58.33% | 1.99% | 1.22% |
| V3 Acceptance + Risk - V0 | mfe | T+10 | 12 | 5 | 7 | 0 | 41.67% | -1.63% | -0.68% |
| V3 Acceptance + Risk - V0 | mean_excess | T+20 | 12 | 7 | 5 | 0 | 58.33% | -2.81% | 2.67% |
| V3 Acceptance + Risk - V0 | median_excess | T+20 | 12 | 8 | 4 | 0 | 66.67% | -1.19% | 2.44% |
| V3 Acceptance + Risk - V0 | positive_rate | T+20 | 12 | 7 | 2 | 3 | 58.33% | 6.85% | 9.44% |
| V3 Acceptance + Risk - V0 | mae | T+20 | 12 | 7 | 5 | 0 | 58.33% | 2.55% | 0.55% |
| V3 Acceptance + Risk - V0 | mfe | T+20 | 12 | 6 | 6 | 0 | 50.00% | -5.44% | 0.09% |
| V3 risk tie-break - V0 | mean_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |

V1 Acceptance context vs V0 T+10 mean excess: 左组更优 4/9 months；月份差值 2025-12=-4.68%, 2026-01=0.10%, 2026-02=6.98%, 2026-03=9.39%, 2026-04=-2.12%, 2026-05=-7.26%, 2026-06=5.96%, 2026-07=-0.36%, 2026-08=-6.37%。
V1 Acceptance context vs V0 T+10 MAE: 左组更优 6/9 months；月份差值 2025-12=2.38%, 2026-01=-1.93%, 2026-02=2.18%, 2026-03=7.36%, 2026-04=0.25%, 2026-05=-2.61%, 2026-06=6.51%, 2026-07=-1.39%, 2026-08=3.96%。
V2 Risk overlay vs V0 T+10 mean excess: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。
V2 Risk overlay vs V0 T+10 MAE: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。
V3 Acceptance + Risk vs V0 T+10 mean excess: 左组更优 4/9 months；月份差值 2025-12=-4.68%, 2026-01=0.10%, 2026-02=6.98%, 2026-03=9.39%, 2026-04=-2.12%, 2026-05=-7.26%, 2026-06=5.96%, 2026-07=-0.36%, 2026-08=-6.37%。
V3 Acceptance + Risk vs V0 T+10 MAE: 左组更优 6/9 months；月份差值 2025-12=2.38%, 2026-01=-1.93%, 2026-02=2.18%, 2026-03=7.36%, 2026-04=0.25%, 2026-05=-2.61%, 2026-06=6.51%, 2026-07=-1.39%, 2026-08=3.96%。
V3 risk tie-break vs V0 T+10 mean excess: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。
V3 risk tie-break vs V0 T+10 MAE: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。

### Top20

| group | horizon | n | unique symbols | unique dates | tradable proxy | mean return | median return | mean excess | median excess | positive excess | PF | mean MAE | mean MFE | sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ALL_WYCKOFF | T+1 | 11324 | 4029 | 12 | 11299 | 0.79% | 0.38% | 0.42% | -0.04% | 49.37% | 1.42 | -2.13% | 3.15% |  |
| ALL_WYCKOFF | T+3 | 11316 | 4029 | 12 | 11291 | 0.42% | -0.15% | -0.02% | -0.81% | 41.94% | 0.99 | -3.93% | 5.83% |  |
| ALL_WYCKOFF | T+5 | 11298 | 4024 | 12 | 11274 | 1.17% | 0.20% | 0.51% | -0.79% | 43.90% | 1.19 | -5.10% | 7.37% |  |
| ALL_WYCKOFF | T+10 | 11280 | 4017 | 12 | 11256 | 0.98% | 0.23% | 0.77% | -0.84% | 45.99% | 1.20 | -7.57% | 10.80% |  |
| ALL_WYCKOFF | T+20 | 11238 | 3999 | 12 | 11238 | 2.26% | -0.46% | 1.15% | -2.79% | 40.92% | 1.20 | -10.72% | 17.04% |  |
| V0 Top20 | T+1 | 240 | 211 | 12 | 239 | 0.91% | 0.00% | 0.62% | -0.44% | 47.50% | 1.35 | -3.73% | 5.07% |  |
| V0 Top20 | T+3 | 240 | 211 | 12 | 239 | -0.41% | -2.06% | -0.80% | -2.45% | 38.75% | 0.83 | -7.07% | 9.32% |  |
| V0 Top20 | T+5 | 240 | 211 | 12 | 239 | 1.68% | -1.28% | 1.12% | -1.75% | 44.58% | 1.22 | -8.97% | 12.24% |  |
| V0 Top20 | T+10 | 239 | 211 | 12 | 238 | 3.38% | -1.25% | 3.33% | -0.30% | 48.12% | 1.55 | -11.29% | 18.70% |  |
| V0 Top20 | T+20 | 237 | 210 | 12 | 237 | 8.46% | -2.95% | 7.74% | -3.66% | 44.30% | 2.01 | -14.82% | 30.76% |  |
| V1 Acceptance context Top20 | T+1 | 239 | 226 | 12 | 239 | 1.15% | 0.63% | 0.86% | 0.53% | 55.65% | 1.74 | -2.72% | 4.16% |  |
| V1 Acceptance context Top20 | T+3 | 238 | 225 | 12 | 238 | 1.00% | -0.40% | 0.61% | -1.06% | 43.70% | 1.19 | -5.41% | 8.54% |  |
| V1 Acceptance context Top20 | T+5 | 238 | 225 | 12 | 238 | 2.38% | 0.46% | 1.82% | -0.26% | 49.58% | 1.49 | -6.94% | 10.79% |  |
| V1 Acceptance context Top20 | T+10 | 238 | 225 | 12 | 238 | 2.80% | 0.16% | 2.76% | -0.38% | 48.74% | 1.56 | -9.41% | 16.29% |  |
| V1 Acceptance context Top20 | T+20 | 238 | 225 | 12 | 238 | 5.94% | -0.11% | 5.22% | -2.21% | 44.96% | 1.78 | -12.76% | 25.10% |  |
| V2 Risk overlay Top20 | T+1 | 240 | 211 | 12 | 239 | 0.91% | 0.00% | 0.62% | -0.44% | 47.50% | 1.35 | -3.73% | 5.07% |  |
| V2 Risk overlay Top20 | T+3 | 240 | 211 | 12 | 239 | -0.41% | -2.06% | -0.80% | -2.45% | 38.75% | 0.83 | -7.07% | 9.32% |  |
| V2 Risk overlay Top20 | T+5 | 240 | 211 | 12 | 239 | 1.68% | -1.28% | 1.12% | -1.75% | 44.58% | 1.22 | -8.97% | 12.24% |  |
| V2 Risk overlay Top20 | T+10 | 239 | 211 | 12 | 238 | 3.38% | -1.25% | 3.33% | -0.30% | 48.12% | 1.55 | -11.29% | 18.70% |  |
| V2 Risk overlay Top20 | T+20 | 237 | 210 | 12 | 237 | 8.46% | -2.95% | 7.74% | -3.66% | 44.30% | 2.01 | -14.82% | 30.76% |  |
| V3 Acceptance + Risk Top20 | T+1 | 239 | 226 | 12 | 239 | 1.15% | 0.63% | 0.86% | 0.53% | 55.65% | 1.74 | -2.72% | 4.16% |  |
| V3 Acceptance + Risk Top20 | T+3 | 238 | 225 | 12 | 238 | 1.00% | -0.40% | 0.61% | -1.06% | 43.70% | 1.19 | -5.41% | 8.54% |  |
| V3 Acceptance + Risk Top20 | T+5 | 238 | 225 | 12 | 238 | 2.38% | 0.46% | 1.82% | -0.26% | 49.58% | 1.49 | -6.94% | 10.79% |  |
| V3 Acceptance + Risk Top20 | T+10 | 238 | 225 | 12 | 238 | 2.80% | 0.16% | 2.76% | -0.38% | 48.74% | 1.56 | -9.41% | 16.29% |  |
| V3 Acceptance + Risk Top20 | T+20 | 238 | 225 | 12 | 238 | 5.94% | -0.11% | 5.22% | -2.21% | 44.96% | 1.78 | -12.76% | 25.10% |  |
| V3 risk tie-break Top20 | T+1 | 240 | 211 | 12 | 239 | 0.91% | 0.00% | 0.62% | -0.44% | 47.50% | 1.35 | -3.73% | 5.07% |  |
| V3 risk tie-break Top20 | T+3 | 240 | 211 | 12 | 239 | -0.41% | -2.06% | -0.80% | -2.45% | 38.75% | 0.83 | -7.07% | 9.32% |  |
| V3 risk tie-break Top20 | T+5 | 240 | 211 | 12 | 239 | 1.68% | -1.28% | 1.12% | -1.75% | 44.58% | 1.22 | -8.97% | 12.24% |  |
| V3 risk tie-break Top20 | T+10 | 239 | 211 | 12 | 238 | 3.38% | -1.25% | 3.33% | -0.30% | 48.12% | 1.55 | -11.29% | 18.70% |  |
| V3 risk tie-break Top20 | T+20 | 237 | 210 | 12 | 237 | 8.46% | -2.95% | 7.74% | -3.66% | 44.30% | 2.01 | -14.82% | 30.76% |  |

日期等权比较（左组 - V0）：

| comparison | metric | horizon | matched dates | left wins | right wins | ties | left win rate | mean difference | median difference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V1 Acceptance context - V0 | mean_excess | T+1 | 12 | 8 | 4 | 0 | 66.67% | 0.23% | 0.47% |
| V1 Acceptance context - V0 | median_excess | T+1 | 12 | 6 | 6 | 0 | 50.00% | 0.39% | -0.03% |
| V1 Acceptance context - V0 | positive_rate | T+1 | 12 | 8 | 3 | 1 | 66.67% | 8.09% | 12.50% |
| V1 Acceptance context - V0 | mae | T+1 | 12 | 12 | 0 | 0 | 100.00% | 1.00% | 0.86% |
| V1 Acceptance context - V0 | mfe | T+1 | 12 | 4 | 8 | 0 | 33.33% | -0.92% | -0.76% |
| V1 Acceptance context - V0 | mean_excess | T+3 | 12 | 8 | 4 | 0 | 66.67% | 1.39% | 0.92% |
| V1 Acceptance context - V0 | median_excess | T+3 | 12 | 7 | 5 | 0 | 58.33% | 1.55% | 0.64% |
| V1 Acceptance context - V0 | positive_rate | T+3 | 12 | 6 | 5 | 1 | 50.00% | 4.87% | 0.92% |
| V1 Acceptance context - V0 | mae | T+3 | 12 | 9 | 3 | 0 | 75.00% | 1.64% | 1.44% |
| V1 Acceptance context - V0 | mfe | T+3 | 12 | 5 | 7 | 0 | 41.67% | -0.80% | -0.52% |
| V1 Acceptance context - V0 | mean_excess | T+5 | 12 | 7 | 5 | 0 | 58.33% | 0.64% | 0.92% |
| V1 Acceptance context - V0 | median_excess | T+5 | 12 | 8 | 4 | 0 | 66.67% | 1.76% | 1.93% |
| V1 Acceptance context - V0 | positive_rate | T+5 | 12 | 6 | 4 | 2 | 50.00% | 4.82% | 2.50% |
| V1 Acceptance context - V0 | mae | T+5 | 12 | 9 | 3 | 0 | 75.00% | 1.99% | 1.28% |
| V1 Acceptance context - V0 | mfe | T+5 | 12 | 4 | 8 | 0 | 33.33% | -1.47% | -1.18% |
| V1 Acceptance context - V0 | mean_excess | T+10 | 12 | 5 | 7 | 0 | 41.67% | -0.65% | -1.45% |
| V1 Acceptance context - V0 | median_excess | T+10 | 12 | 4 | 8 | 0 | 33.33% | -0.22% | -2.05% |
| V1 Acceptance context - V0 | positive_rate | T+10 | 12 | 4 | 5 | 3 | 33.33% | 0.39% | 0.00% |
| V1 Acceptance context - V0 | mae | T+10 | 12 | 8 | 4 | 0 | 66.67% | 1.84% | 1.70% |
| V1 Acceptance context - V0 | mfe | T+10 | 12 | 5 | 7 | 0 | 41.67% | -2.50% | -0.90% |
| V1 Acceptance context - V0 | mean_excess | T+20 | 12 | 5 | 7 | 0 | 41.67% | -2.62% | -2.50% |
| V1 Acceptance context - V0 | median_excess | T+20 | 12 | 5 | 7 | 0 | 41.67% | -3.22% | -4.35% |
| V1 Acceptance context - V0 | positive_rate | T+20 | 12 | 7 | 4 | 1 | 58.33% | 0.53% | 3.42% |
| V1 Acceptance context - V0 | mae | T+20 | 12 | 9 | 3 | 0 | 75.00% | 2.03% | 1.25% |
| V1 Acceptance context - V0 | mfe | T+20 | 12 | 3 | 9 | 0 | 25.00% | -5.97% | -3.02% |
| V2 Risk overlay - V0 | mean_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 Acceptance + Risk - V0 | mean_excess | T+1 | 12 | 8 | 4 | 0 | 66.67% | 0.23% | 0.47% |
| V3 Acceptance + Risk - V0 | median_excess | T+1 | 12 | 6 | 6 | 0 | 50.00% | 0.39% | -0.03% |
| V3 Acceptance + Risk - V0 | positive_rate | T+1 | 12 | 8 | 3 | 1 | 66.67% | 8.09% | 12.50% |
| V3 Acceptance + Risk - V0 | mae | T+1 | 12 | 12 | 0 | 0 | 100.00% | 1.00% | 0.86% |
| V3 Acceptance + Risk - V0 | mfe | T+1 | 12 | 4 | 8 | 0 | 33.33% | -0.92% | -0.76% |
| V3 Acceptance + Risk - V0 | mean_excess | T+3 | 12 | 8 | 4 | 0 | 66.67% | 1.39% | 0.92% |
| V3 Acceptance + Risk - V0 | median_excess | T+3 | 12 | 7 | 5 | 0 | 58.33% | 1.55% | 0.64% |
| V3 Acceptance + Risk - V0 | positive_rate | T+3 | 12 | 6 | 5 | 1 | 50.00% | 4.87% | 0.92% |
| V3 Acceptance + Risk - V0 | mae | T+3 | 12 | 9 | 3 | 0 | 75.00% | 1.64% | 1.44% |
| V3 Acceptance + Risk - V0 | mfe | T+3 | 12 | 5 | 7 | 0 | 41.67% | -0.80% | -0.52% |
| V3 Acceptance + Risk - V0 | mean_excess | T+5 | 12 | 7 | 5 | 0 | 58.33% | 0.64% | 0.92% |
| V3 Acceptance + Risk - V0 | median_excess | T+5 | 12 | 8 | 4 | 0 | 66.67% | 1.76% | 1.93% |
| V3 Acceptance + Risk - V0 | positive_rate | T+5 | 12 | 6 | 4 | 2 | 50.00% | 4.82% | 2.50% |
| V3 Acceptance + Risk - V0 | mae | T+5 | 12 | 9 | 3 | 0 | 75.00% | 1.99% | 1.28% |
| V3 Acceptance + Risk - V0 | mfe | T+5 | 12 | 4 | 8 | 0 | 33.33% | -1.47% | -1.18% |
| V3 Acceptance + Risk - V0 | mean_excess | T+10 | 12 | 5 | 7 | 0 | 41.67% | -0.65% | -1.45% |
| V3 Acceptance + Risk - V0 | median_excess | T+10 | 12 | 4 | 8 | 0 | 33.33% | -0.22% | -2.05% |
| V3 Acceptance + Risk - V0 | positive_rate | T+10 | 12 | 4 | 5 | 3 | 33.33% | 0.39% | 0.00% |
| V3 Acceptance + Risk - V0 | mae | T+10 | 12 | 8 | 4 | 0 | 66.67% | 1.84% | 1.70% |
| V3 Acceptance + Risk - V0 | mfe | T+10 | 12 | 5 | 7 | 0 | 41.67% | -2.50% | -0.90% |
| V3 Acceptance + Risk - V0 | mean_excess | T+20 | 12 | 5 | 7 | 0 | 41.67% | -2.62% | -2.50% |
| V3 Acceptance + Risk - V0 | median_excess | T+20 | 12 | 5 | 7 | 0 | 41.67% | -3.22% | -4.35% |
| V3 Acceptance + Risk - V0 | positive_rate | T+20 | 12 | 7 | 4 | 1 | 58.33% | 0.53% | 3.42% |
| V3 Acceptance + Risk - V0 | mae | T+20 | 12 | 9 | 3 | 0 | 75.00% | 2.03% | 1.25% |
| V3 Acceptance + Risk - V0 | mfe | T+20 | 12 | 3 | 9 | 0 | 25.00% | -5.97% | -3.02% |
| V3 risk tie-break - V0 | mean_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |

V1 Acceptance context vs V0 T+10 mean excess: 左组更优 4/9 months；月份差值 2025-12=-9.21%, 2026-01=4.68%, 2026-02=3.49%, 2026-03=9.18%, 2026-04=-0.14%, 2026-05=-6.14%, 2026-06=-3.04%, 2026-07=2.35%, 2026-08=-2.76%。
V1 Acceptance context vs V0 T+10 MAE: 左组更优 7/9 months；月份差值 2025-12=2.29%, 2026-01=-0.10%, 2026-02=2.34%, 2026-03=5.61%, 2026-04=0.63%, 2026-05=-1.29%, 2026-06=1.79%, 2026-07=1.61%, 2026-08=2.55%。
V2 Risk overlay vs V0 T+10 mean excess: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。
V2 Risk overlay vs V0 T+10 MAE: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。
V3 Acceptance + Risk vs V0 T+10 mean excess: 左组更优 4/9 months；月份差值 2025-12=-9.21%, 2026-01=4.68%, 2026-02=3.49%, 2026-03=9.18%, 2026-04=-0.14%, 2026-05=-6.14%, 2026-06=-3.04%, 2026-07=2.35%, 2026-08=-2.76%。
V3 Acceptance + Risk vs V0 T+10 MAE: 左组更优 7/9 months；月份差值 2025-12=2.29%, 2026-01=-0.10%, 2026-02=2.34%, 2026-03=5.61%, 2026-04=0.63%, 2026-05=-1.29%, 2026-06=1.79%, 2026-07=1.61%, 2026-08=2.55%。
V3 risk tie-break vs V0 T+10 mean excess: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。
V3 risk tie-break vs V0 T+10 MAE: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。

### Top50

| group | horizon | n | unique symbols | unique dates | tradable proxy | mean return | median return | mean excess | median excess | positive excess | PF | mean MAE | mean MFE | sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ALL_WYCKOFF | T+1 | 11324 | 4029 | 12 | 11299 | 0.79% | 0.38% | 0.42% | -0.04% | 49.37% | 1.42 | -2.13% | 3.15% |  |
| ALL_WYCKOFF | T+3 | 11316 | 4029 | 12 | 11291 | 0.42% | -0.15% | -0.02% | -0.81% | 41.94% | 0.99 | -3.93% | 5.83% |  |
| ALL_WYCKOFF | T+5 | 11298 | 4024 | 12 | 11274 | 1.17% | 0.20% | 0.51% | -0.79% | 43.90% | 1.19 | -5.10% | 7.37% |  |
| ALL_WYCKOFF | T+10 | 11280 | 4017 | 12 | 11256 | 0.98% | 0.23% | 0.77% | -0.84% | 45.99% | 1.20 | -7.57% | 10.80% |  |
| ALL_WYCKOFF | T+20 | 11238 | 3999 | 12 | 11238 | 2.26% | -0.46% | 1.15% | -2.79% | 40.92% | 1.20 | -10.72% | 17.04% |  |
| V0 Top50 | T+1 | 599 | 484 | 12 | 597 | 1.13% | 0.33% | 0.84% | 0.15% | 51.25% | 1.55 | -3.29% | 4.83% |  |
| V0 Top50 | T+3 | 598 | 484 | 12 | 596 | 0.07% | -1.20% | -0.31% | -1.80% | 41.30% | 0.92 | -6.14% | 8.73% |  |
| V0 Top50 | T+5 | 598 | 484 | 12 | 596 | 1.76% | -0.12% | 1.20% | -0.72% | 46.82% | 1.29 | -7.69% | 11.11% |  |
| V0 Top50 | T+10 | 596 | 483 | 12 | 594 | 2.56% | -0.12% | 2.51% | -0.17% | 49.33% | 1.49 | -10.05% | 16.58% |  |
| V0 Top50 | T+20 | 593 | 481 | 12 | 593 | 7.27% | -2.03% | 6.54% | -2.44% | 45.19% | 1.96 | -13.43% | 27.19% |  |
| V1 Acceptance context Top50 | T+1 | 599 | 530 | 12 | 598 | 1.13% | 0.45% | 0.84% | 0.29% | 52.59% | 1.71 | -2.70% | 4.11% |  |
| V1 Acceptance context Top50 | T+3 | 598 | 529 | 12 | 597 | 0.48% | -0.83% | 0.09% | -1.26% | 41.30% | 1.03 | -5.22% | 7.84% |  |
| V1 Acceptance context Top50 | T+5 | 596 | 527 | 12 | 595 | 1.56% | -0.12% | 1.00% | -1.14% | 45.30% | 1.28 | -6.75% | 9.75% |  |
| V1 Acceptance context Top50 | T+10 | 596 | 527 | 12 | 595 | 2.33% | -0.06% | 2.29% | -0.08% | 49.50% | 1.49 | -9.28% | 14.65% |  |
| V1 Acceptance context Top50 | T+20 | 595 | 526 | 12 | 595 | 5.84% | 0.33% | 5.11% | -1.17% | 47.39% | 1.81 | -12.52% | 23.89% |  |
| V2 Risk overlay Top50 | T+1 | 599 | 484 | 12 | 597 | 1.13% | 0.33% | 0.84% | 0.15% | 51.25% | 1.55 | -3.29% | 4.83% |  |
| V2 Risk overlay Top50 | T+3 | 598 | 484 | 12 | 596 | 0.07% | -1.20% | -0.31% | -1.80% | 41.30% | 0.92 | -6.14% | 8.73% |  |
| V2 Risk overlay Top50 | T+5 | 598 | 484 | 12 | 596 | 1.76% | -0.12% | 1.20% | -0.72% | 46.82% | 1.29 | -7.69% | 11.11% |  |
| V2 Risk overlay Top50 | T+10 | 596 | 483 | 12 | 594 | 2.56% | -0.12% | 2.51% | -0.17% | 49.33% | 1.49 | -10.05% | 16.58% |  |
| V2 Risk overlay Top50 | T+20 | 593 | 481 | 12 | 593 | 7.27% | -2.03% | 6.54% | -2.44% | 45.19% | 1.96 | -13.43% | 27.19% |  |
| V3 Acceptance + Risk Top50 | T+1 | 599 | 530 | 12 | 598 | 1.13% | 0.45% | 0.84% | 0.29% | 52.59% | 1.71 | -2.70% | 4.11% |  |
| V3 Acceptance + Risk Top50 | T+3 | 598 | 529 | 12 | 597 | 0.48% | -0.83% | 0.09% | -1.26% | 41.30% | 1.03 | -5.22% | 7.84% |  |
| V3 Acceptance + Risk Top50 | T+5 | 596 | 527 | 12 | 595 | 1.56% | -0.12% | 1.00% | -1.14% | 45.30% | 1.28 | -6.75% | 9.75% |  |
| V3 Acceptance + Risk Top50 | T+10 | 596 | 527 | 12 | 595 | 2.33% | -0.06% | 2.29% | -0.08% | 49.50% | 1.49 | -9.28% | 14.65% |  |
| V3 Acceptance + Risk Top50 | T+20 | 595 | 526 | 12 | 595 | 5.84% | 0.33% | 5.11% | -1.17% | 47.39% | 1.81 | -12.52% | 23.89% |  |
| V3 risk tie-break Top50 | T+1 | 599 | 484 | 12 | 597 | 1.13% | 0.33% | 0.84% | 0.15% | 51.25% | 1.55 | -3.29% | 4.83% |  |
| V3 risk tie-break Top50 | T+3 | 598 | 484 | 12 | 596 | 0.07% | -1.20% | -0.31% | -1.80% | 41.30% | 0.92 | -6.14% | 8.73% |  |
| V3 risk tie-break Top50 | T+5 | 598 | 484 | 12 | 596 | 1.76% | -0.12% | 1.20% | -0.72% | 46.82% | 1.29 | -7.69% | 11.11% |  |
| V3 risk tie-break Top50 | T+10 | 596 | 483 | 12 | 594 | 2.56% | -0.12% | 2.51% | -0.17% | 49.33% | 1.49 | -10.05% | 16.58% |  |
| V3 risk tie-break Top50 | T+20 | 593 | 481 | 12 | 593 | 7.27% | -2.03% | 6.54% | -2.44% | 45.19% | 1.96 | -13.43% | 27.19% |  |

日期等权比较（左组 - V0）：

| comparison | metric | horizon | matched dates | left wins | right wins | ties | left win rate | mean difference | median difference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V1 Acceptance context - V0 | mean_excess | T+1 | 12 | 5 | 7 | 0 | 41.67% | -0.00% | -0.03% |
| V1 Acceptance context - V0 | median_excess | T+1 | 12 | 4 | 8 | 0 | 33.33% | -0.14% | -0.27% |
| V1 Acceptance context - V0 | positive_rate | T+1 | 12 | 6 | 6 | 0 | 50.00% | 1.33% | 0.98% |
| V1 Acceptance context - V0 | mae | T+1 | 12 | 11 | 1 | 0 | 91.67% | 0.59% | 0.64% |
| V1 Acceptance context - V0 | mfe | T+1 | 12 | 3 | 9 | 0 | 25.00% | -0.72% | -0.56% |
| V1 Acceptance context - V0 | mean_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | 0.40% | 0.03% |
| V1 Acceptance context - V0 | median_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | 0.52% | -0.09% |
| V1 Acceptance context - V0 | positive_rate | T+3 | 12 | 6 | 6 | 0 | 50.00% | -0.02% | 0.51% |
| V1 Acceptance context - V0 | mae | T+3 | 12 | 9 | 3 | 0 | 75.00% | 0.92% | 0.53% |
| V1 Acceptance context - V0 | mfe | T+3 | 12 | 3 | 9 | 0 | 25.00% | -0.90% | -1.07% |
| V1 Acceptance context - V0 | mean_excess | T+5 | 12 | 4 | 8 | 0 | 33.33% | -0.24% | -1.02% |
| V1 Acceptance context - V0 | median_excess | T+5 | 12 | 5 | 7 | 0 | 41.67% | 0.17% | -0.28% |
| V1 Acceptance context - V0 | positive_rate | T+5 | 12 | 6 | 5 | 1 | 50.00% | -1.64% | 1.00% |
| V1 Acceptance context - V0 | mae | T+5 | 12 | 8 | 4 | 0 | 66.67% | 0.92% | 0.71% |
| V1 Acceptance context - V0 | mfe | T+5 | 12 | 3 | 9 | 0 | 25.00% | -1.37% | -1.85% |
| V1 Acceptance context - V0 | mean_excess | T+10 | 12 | 4 | 8 | 0 | 33.33% | -0.26% | -1.35% |
| V1 Acceptance context - V0 | median_excess | T+10 | 12 | 4 | 8 | 0 | 33.33% | 0.76% | -0.49% |
| V1 Acceptance context - V0 | positive_rate | T+10 | 12 | 5 | 7 | 0 | 41.67% | 0.06% | -2.76% |
| V1 Acceptance context - V0 | mae | T+10 | 12 | 6 | 6 | 0 | 50.00% | 0.75% | -0.04% |
| V1 Acceptance context - V0 | mfe | T+10 | 12 | 3 | 9 | 0 | 25.00% | -1.97% | -2.17% |
| V1 Acceptance context - V0 | mean_excess | T+20 | 12 | 4 | 8 | 0 | 33.33% | -1.42% | -0.96% |
| V1 Acceptance context - V0 | median_excess | T+20 | 12 | 5 | 7 | 0 | 41.67% | -0.66% | -0.75% |
| V1 Acceptance context - V0 | positive_rate | T+20 | 12 | 5 | 6 | 1 | 41.67% | 2.21% | -1.00% |
| V1 Acceptance context - V0 | mae | T+20 | 12 | 7 | 5 | 0 | 58.33% | 0.90% | 1.12% |
| V1 Acceptance context - V0 | mfe | T+20 | 12 | 2 | 10 | 0 | 16.67% | -3.41% | -2.83% |
| V2 Risk overlay - V0 | mean_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mean_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | median_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | positive_rate | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mae | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V2 Risk overlay - V0 | mfe | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 Acceptance + Risk - V0 | mean_excess | T+1 | 12 | 5 | 7 | 0 | 41.67% | -0.00% | -0.03% |
| V3 Acceptance + Risk - V0 | median_excess | T+1 | 12 | 4 | 8 | 0 | 33.33% | -0.14% | -0.27% |
| V3 Acceptance + Risk - V0 | positive_rate | T+1 | 12 | 6 | 6 | 0 | 50.00% | 1.33% | 0.98% |
| V3 Acceptance + Risk - V0 | mae | T+1 | 12 | 11 | 1 | 0 | 91.67% | 0.59% | 0.64% |
| V3 Acceptance + Risk - V0 | mfe | T+1 | 12 | 3 | 9 | 0 | 25.00% | -0.72% | -0.56% |
| V3 Acceptance + Risk - V0 | mean_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | 0.40% | 0.03% |
| V3 Acceptance + Risk - V0 | median_excess | T+3 | 12 | 6 | 6 | 0 | 50.00% | 0.52% | -0.09% |
| V3 Acceptance + Risk - V0 | positive_rate | T+3 | 12 | 6 | 6 | 0 | 50.00% | -0.02% | 0.51% |
| V3 Acceptance + Risk - V0 | mae | T+3 | 12 | 9 | 3 | 0 | 75.00% | 0.92% | 0.53% |
| V3 Acceptance + Risk - V0 | mfe | T+3 | 12 | 3 | 9 | 0 | 25.00% | -0.90% | -1.07% |
| V3 Acceptance + Risk - V0 | mean_excess | T+5 | 12 | 4 | 8 | 0 | 33.33% | -0.24% | -1.02% |
| V3 Acceptance + Risk - V0 | median_excess | T+5 | 12 | 5 | 7 | 0 | 41.67% | 0.17% | -0.28% |
| V3 Acceptance + Risk - V0 | positive_rate | T+5 | 12 | 6 | 5 | 1 | 50.00% | -1.64% | 1.00% |
| V3 Acceptance + Risk - V0 | mae | T+5 | 12 | 8 | 4 | 0 | 66.67% | 0.92% | 0.71% |
| V3 Acceptance + Risk - V0 | mfe | T+5 | 12 | 3 | 9 | 0 | 25.00% | -1.37% | -1.85% |
| V3 Acceptance + Risk - V0 | mean_excess | T+10 | 12 | 4 | 8 | 0 | 33.33% | -0.26% | -1.35% |
| V3 Acceptance + Risk - V0 | median_excess | T+10 | 12 | 4 | 8 | 0 | 33.33% | 0.76% | -0.49% |
| V3 Acceptance + Risk - V0 | positive_rate | T+10 | 12 | 5 | 7 | 0 | 41.67% | 0.06% | -2.76% |
| V3 Acceptance + Risk - V0 | mae | T+10 | 12 | 6 | 6 | 0 | 50.00% | 0.75% | -0.04% |
| V3 Acceptance + Risk - V0 | mfe | T+10 | 12 | 3 | 9 | 0 | 25.00% | -1.97% | -2.17% |
| V3 Acceptance + Risk - V0 | mean_excess | T+20 | 12 | 4 | 8 | 0 | 33.33% | -1.42% | -0.96% |
| V3 Acceptance + Risk - V0 | median_excess | T+20 | 12 | 5 | 7 | 0 | 41.67% | -0.66% | -0.75% |
| V3 Acceptance + Risk - V0 | positive_rate | T+20 | 12 | 5 | 6 | 1 | 41.67% | 2.21% | -1.00% |
| V3 Acceptance + Risk - V0 | mae | T+20 | 12 | 7 | 5 | 0 | 58.33% | 0.90% | 1.12% |
| V3 Acceptance + Risk - V0 | mfe | T+20 | 12 | 2 | 10 | 0 | 16.67% | -3.41% | -2.83% |
| V3 risk tie-break - V0 | mean_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+1 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+3 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+5 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+10 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mean_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | median_excess | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | positive_rate | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mae | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |
| V3 risk tie-break - V0 | mfe | T+20 | 12 | 0 | 0 | 12 | 0.00% | 0.00% | 0.00% |

V1 Acceptance context vs V0 T+10 mean excess: 左组更优 3/9 months；月份差值 2025-12=-2.88%, 2026-01=3.32%, 2026-02=1.30%, 2026-03=6.35%, 2026-04=-1.94%, 2026-05=-4.54%, 2026-06=-0.76%, 2026-07=-0.06%, 2026-08=-2.83%。
V1 Acceptance context vs V0 T+10 MAE: 左组更优 5/9 months；月份差值 2025-12=0.71%, 2026-01=0.25%, 2026-02=3.00%, 2026-03=3.89%, 2026-04=-0.32%, 2026-05=-2.04%, 2026-06=-0.80%, 2026-07=-0.34%, 2026-08=2.09%。
V2 Risk overlay vs V0 T+10 mean excess: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。
V2 Risk overlay vs V0 T+10 MAE: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。
V3 Acceptance + Risk vs V0 T+10 mean excess: 左组更优 3/9 months；月份差值 2025-12=-2.88%, 2026-01=3.32%, 2026-02=1.30%, 2026-03=6.35%, 2026-04=-1.94%, 2026-05=-4.54%, 2026-06=-0.76%, 2026-07=-0.06%, 2026-08=-2.83%。
V3 Acceptance + Risk vs V0 T+10 MAE: 左组更优 5/9 months；月份差值 2025-12=0.71%, 2026-01=0.25%, 2026-02=3.00%, 2026-03=3.89%, 2026-04=-0.32%, 2026-05=-2.04%, 2026-06=-0.80%, 2026-07=-0.34%, 2026-08=2.09%。
V3 risk tie-break vs V0 T+10 mean excess: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。
V3 risk tie-break vs V0 T+10 MAE: 左组更优 0/9 months；月份差值 2025-12=0.00%, 2026-01=0.00%, 2026-02=0.00%, 2026-03=0.00%, 2026-04=0.00%, 2026-05=0.00%, 2026-06=0.00%, 2026-07=0.00%, 2026-08=0.00%。

## 版本状态（相对 V0 同一 TopN）

状态规则预先固定：T+10 mean excess 与日期胜率 ≥2/3 才标 Alpha `IMPROVED`；T+10 MAE（更接近零）与日期胜率 ≥2/3 才标 Risk `IMPROVED`。选择集合完全相同则标 `NO_INCREMENTAL_VALUE`。

| version | overall | Alpha Effect | Risk Effect | tail / selection note |
| --- | --- | --- | --- | --- |
| V1 Acceptance context Top10 | MIXED | MIXED | MIXED | RIGHT_TAIL_DRIVEN |
| V2 Risk overlay Top10 | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | identical selection |
| V3 Acceptance + Risk Top10 | MIXED | MIXED | MIXED | RIGHT_TAIL_DRIVEN |
| V3 risk tie-break Top10 | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | identical selection |
| V1 Acceptance context Top20 | MIXED | NO_INCREMENTAL_VALUE | IMPROVED | RIGHT_TAIL_DRIVEN |
| V2 Risk overlay Top20 | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | identical selection |
| V3 Acceptance + Risk Top20 | MIXED | NO_INCREMENTAL_VALUE | IMPROVED | RIGHT_TAIL_DRIVEN |
| V3 risk tie-break Top20 | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | identical selection |
| V1 Acceptance context Top50 | MIXED | NO_INCREMENTAL_VALUE | MIXED | RIGHT_TAIL_DRIVEN |
| V2 Risk overlay Top50 | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | identical selection |
| V3 Acceptance + Risk Top50 | MIXED | NO_INCREMENTAL_VALUE | MIXED | RIGHT_TAIL_DRIVEN |
| V3 risk tie-break Top50 | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | NO_INCREMENTAL_VALUE | identical selection |

## V2：Opportunity Top50 内的独立 Risk Overlay

此节不以 Risk 重排或过滤候选；先固定 V0 Opportunity Top50，再观察风险桶。

| group | horizon | n | unique symbols | unique dates | tradable proxy | mean return | median return | mean excess | median excess | positive excess | PF | mean MAE | mean MFE | sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Risk LOW | T+1 | 77 | 73 | 12 | 77 | 0.26% | -0.76% | -0.07% | -0.82% | 46.75% | 0.96 | -3.57% | 4.49% |  |
| Risk LOW | T+3 | 77 | 73 | 12 | 77 | -0.84% | -1.35% | -1.63% | -2.10% | 35.06% | 0.61 | -6.16% | 7.25% |  |
| Risk LOW | T+5 | 77 | 73 | 12 | 77 | 0.73% | -0.57% | -0.51% | -1.78% | 41.56% | 0.89 | -7.61% | 9.89% |  |
| Risk LOW | T+10 | 76 | 72 | 12 | 76 | 3.71% | -0.64% | 2.26% | -0.41% | 48.68% | 1.42 | -9.53% | 16.51% |  |
| Risk LOW | T+20 | 76 | 72 | 12 | 76 | 13.24% | 3.47% | 9.50% | 0.79% | 51.32% | 2.75 | -11.02% | 33.02% |  |
| Risk MEDIUM | T+1 | 125 | 119 | 12 | 125 | -0.21% | -0.59% | -0.47% | -1.22% | 35.20% | 0.74 | -3.56% | 3.82% |  |
| Risk MEDIUM | T+3 | 125 | 119 | 12 | 125 | -0.36% | -1.41% | -1.01% | -1.97% | 37.60% | 0.73 | -6.23% | 7.28% |  |
| Risk MEDIUM | T+5 | 125 | 119 | 12 | 125 | -0.09% | -1.21% | -1.02% | -2.30% | 37.60% | 0.77 | -7.65% | 9.10% |  |
| Risk MEDIUM | T+10 | 125 | 119 | 12 | 125 | 0.28% | -1.68% | -0.25% | -1.43% | 44.80% | 0.95 | -10.17% | 13.38% |  |
| Risk MEDIUM | T+20 | 125 | 119 | 12 | 125 | 6.89% | -2.13% | 4.04% | -5.24% | 36.00% | 1.55 | -12.11% | 23.79% |  |
| Risk HIGH | T+1 | 160 | 151 | 12 | 159 | 1.13% | 0.56% | 0.86% | 0.46% | 55.00% | 1.59 | -3.15% | 4.92% |  |
| Risk HIGH | T+3 | 160 | 151 | 12 | 159 | -0.81% | -2.02% | -1.16% | -2.26% | 37.50% | 0.73 | -6.30% | 8.10% |  |
| Risk HIGH | T+5 | 160 | 151 | 12 | 159 | 0.76% | -0.51% | 0.26% | -1.01% | 45.00% | 1.06 | -8.08% | 10.27% |  |
| Risk HIGH | T+10 | 160 | 151 | 12 | 159 | 0.94% | -0.98% | 1.18% | -0.87% | 46.25% | 1.21 | -10.63% | 15.61% |  |
| Risk HIGH | T+20 | 159 | 150 | 12 | 159 | 5.46% | -3.88% | 5.14% | -3.83% | 41.51% | 1.65 | -14.42% | 25.48% |  |
| Risk EXTREME | T+1 | 231 | 207 | 12 | 231 | 2.24% | 1.03% | 1.95% | 1.15% | 59.31% | 2.51 | -3.11% | 5.43% |  |
| Risk EXTREME | T+3 | 230 | 207 | 12 | 230 | 1.36% | -0.45% | 1.22% | -0.70% | 48.26% | 1.36 | -5.91% | 10.48% |  |
| Risk EXTREME | T+5 | 230 | 207 | 12 | 230 | 3.96% | 1.95% | 3.79% | 1.90% | 55.65% | 2.10 | -7.36% | 13.24% |  |
| Risk EXTREME | T+10 | 229 | 207 | 12 | 229 | 4.58% | 2.08% | 5.06% | 2.81% | 54.15% | 2.15 | -9.65% | 19.07% |  |
| Risk EXTREME | T+20 | 229 | 207 | 12 | 229 | 7.03% | -2.15% | 8.13% | 1.01% | 51.09% | 2.30 | -14.14% | 28.57% |  |
| Risk UNKNOWN | T+1 | 6 | 5 | 4 | 5 | -2.41% | 0.00% | -2.84% | -0.41% | 33.33% | 0.13 | -4.29% | 4.74% | INSUFFICIENT |
| Risk UNKNOWN | T+3 | 6 | 5 | 4 | 5 | -4.92% | -7.42% | -5.12% | -7.34% | 33.33% | 0.28 | -8.41% | 8.24% | INSUFFICIENT |
| Risk UNKNOWN | T+5 | 6 | 5 | 4 | 5 | -4.38% | -2.64% | -4.81% | -3.42% | 16.67% | 0.20 | -11.50% | 9.16% | INSUFFICIENT |
| Risk UNKNOWN | T+10 | 6 | 5 | 4 | 5 | 1.90% | -1.27% | 1.52% | -0.24% | 50.00% | 1.22 | -13.57% | 14.57% | INSUFFICIENT |
| Risk UNKNOWN | T+20 | 4 | 4 | 2 | 4 | -9.56% | -8.46% | -7.32% | -8.33% | 25.00% | 0.05 | -19.66% | 10.92% | INSUFFICIENT |

日期等权比较：

| comparison | metric | horizon | matched dates | left wins | right wins | ties | left win rate | mean difference | median difference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LOW - HIGH | mean_excess | T+5 | 12 | 6 | 6 | 0 | 50.00% | 1.98% | -0.23% |
| LOW - HIGH | median_excess | T+5 | 12 | 6 | 6 | 0 | 50.00% | 2.79% | 0.42% |
| LOW - HIGH | positive_rate | T+5 | 12 | 7 | 4 | 1 | 58.33% | 7.75% | 4.00% |
| LOW - HIGH | mae | T+5 | 12 | 6 | 6 | 0 | 50.00% | 0.92% | -0.15% |
| LOW - HIGH | mfe | T+5 | 12 | 4 | 8 | 0 | 33.33% | 2.36% | -0.21% |
| LOW - HIGH | mean_excess | T+10 | 12 | 6 | 6 | 0 | 50.00% | -0.30% | -0.11% |
| LOW - HIGH | median_excess | T+10 | 12 | 6 | 6 | 0 | 50.00% | 1.44% | 0.32% |
| LOW - HIGH | positive_rate | T+10 | 12 | 6 | 6 | 0 | 50.00% | 5.22% | 0.18% |
| LOW - HIGH | mae | T+10 | 12 | 7 | 5 | 0 | 58.33% | 0.78% | 0.30% |
| LOW - HIGH | mfe | T+10 | 12 | 7 | 5 | 0 | 58.33% | 2.48% | 0.42% |
| LOW - HIGH | mean_excess | T+20 | 12 | 6 | 6 | 0 | 50.00% | -3.08% | -0.01% |
| LOW - HIGH | median_excess | T+20 | 12 | 6 | 6 | 0 | 50.00% | -1.70% | -0.10% |
| LOW - HIGH | positive_rate | T+20 | 12 | 4 | 8 | 0 | 33.33% | -4.30% | -5.66% |
| LOW - HIGH | mae | T+20 | 12 | 6 | 6 | 0 | 50.00% | -0.33% | 0.18% |
| LOW - HIGH | mfe | T+20 | 12 | 6 | 6 | 0 | 50.00% | 1.98% | -0.26% |
| LOW - EXTREME | mean_excess | T+5 | 12 | 4 | 8 | 0 | 33.33% | -0.12% | -0.87% |
| LOW - EXTREME | median_excess | T+5 | 12 | 5 | 7 | 0 | 41.67% | 1.03% | -0.56% |
| LOW - EXTREME | positive_rate | T+5 | 12 | 6 | 5 | 1 | 50.00% | 3.60% | 0.38% |
| LOW - EXTREME | mae | T+5 | 12 | 5 | 7 | 0 | 41.67% | 0.87% | -0.28% |
| LOW - EXTREME | mfe | T+5 | 12 | 4 | 8 | 0 | 33.33% | -0.07% | -1.81% |
| LOW - EXTREME | mean_excess | T+10 | 12 | 3 | 9 | 0 | 25.00% | -2.09% | -4.50% |
| LOW - EXTREME | median_excess | T+10 | 12 | 6 | 6 | 0 | 50.00% | 0.24% | -0.81% |
| LOW - EXTREME | positive_rate | T+10 | 12 | 5 | 7 | 0 | 41.67% | 1.56% | -10.57% |
| LOW - EXTREME | mae | T+10 | 12 | 9 | 3 | 0 | 75.00% | 0.54% | 0.32% |
| LOW - EXTREME | mfe | T+10 | 12 | 4 | 8 | 0 | 33.33% | 0.25% | -1.79% |
| LOW - EXTREME | mean_excess | T+20 | 12 | 6 | 6 | 0 | 50.00% | -2.11% | -3.14% |
| LOW - EXTREME | median_excess | T+20 | 12 | 7 | 5 | 0 | 58.33% | -0.22% | 0.82% |
| LOW - EXTREME | positive_rate | T+20 | 12 | 3 | 9 | 0 | 25.00% | -6.61% | -7.95% |
| LOW - EXTREME | mae | T+20 | 12 | 6 | 6 | 0 | 50.00% | -0.08% | 0.03% |
| LOW - EXTREME | mfe | T+20 | 12 | 6 | 6 | 0 | 50.00% | 0.56% | -0.55% |
| exclude EXTREME (no refill) - full Top50 | mean_excess | T+5 | 12 | 3 | 9 | 0 | 25.00% | -0.81% | -0.89% |
| exclude EXTREME (no refill) - full Top50 | median_excess | T+5 | 12 | 3 | 8 | 1 | 25.00% | -0.64% | -0.76% |
| exclude EXTREME (no refill) - full Top50 | positive_rate | T+5 | 12 | 2 | 10 | 0 | 16.67% | -3.13% | -4.00% |
| exclude EXTREME (no refill) - full Top50 | mae | T+5 | 12 | 7 | 5 | 0 | 58.33% | -0.12% | 0.06% |
| exclude EXTREME (no refill) - full Top50 | mfe | T+5 | 12 | 3 | 9 | 0 | 25.00% | -0.63% | -0.45% |
| exclude EXTREME (no refill) - full Top50 | mean_excess | T+10 | 12 | 5 | 7 | 0 | 41.67% | -1.13% | -0.88% |
| exclude EXTREME (no refill) - full Top50 | median_excess | T+10 | 12 | 5 | 6 | 1 | 41.67% | -1.01% | -0.36% |
| exclude EXTREME (no refill) - full Top50 | positive_rate | T+10 | 12 | 3 | 8 | 1 | 25.00% | -2.24% | -2.09% |
| exclude EXTREME (no refill) - full Top50 | mae | T+10 | 12 | 4 | 8 | 0 | 33.33% | -0.30% | -0.18% |
| exclude EXTREME (no refill) - full Top50 | mfe | T+10 | 12 | 3 | 9 | 0 | 25.00% | -0.83% | -0.71% |
| exclude EXTREME (no refill) - full Top50 | mean_excess | T+20 | 12 | 5 | 7 | 0 | 41.67% | -0.26% | -0.66% |
| exclude EXTREME (no refill) - full Top50 | median_excess | T+20 | 12 | 4 | 7 | 1 | 33.33% | 0.22% | -0.98% |
| exclude EXTREME (no refill) - full Top50 | positive_rate | T+20 | 12 | 3 | 9 | 0 | 25.00% | -2.74% | -2.39% |
| exclude EXTREME (no refill) - full Top50 | mae | T+20 | 12 | 4 | 8 | 0 | 33.33% | -0.24% | -0.27% |
| exclude EXTREME (no refill) - full Top50 | mfe | T+20 | 12 | 4 | 8 | 0 | 33.33% | -0.48% | -0.94% |

LOW vs EXTREME T+20 MAE: 左组更优 5/9 months；月份差值 2025-12=0.94%, 2026-01=-4.57%, 2026-02=-6.44%, 2026-03=4.22%, 2026-04=1.53%, 2026-05=-1.81%, 2026-06=-3.34%, 2026-07=0.27%, 2026-08=4.87%。

`exclude EXTREME` 是直接移除 Top50 内 EXTREME、**不补位**的诊断，避免把筛选结构变化伪装成 Risk 的预测收益。若 mean excess 高而 median excess 为负、且 MFE 不低于 |MAE|，表内按 `RIGHT_TAIL_DRIVEN` 解释，不宣称更优。

| group | T+5 marker | T+10 marker | T+20 marker |
| --- | --- | --- | --- |
| Risk LOW | — | RIGHT_TAIL_DRIVEN | — |
| Risk MEDIUM | — | — | RIGHT_TAIL_DRIVEN |
| Risk HIGH | RIGHT_TAIL_DRIVEN | RIGHT_TAIL_DRIVEN | RIGHT_TAIL_DRIVEN |
| Risk EXTREME | — | — | — |
| Risk UNKNOWN | — | RIGHT_TAIL_DRIVEN | — |

## 研究结论与下一阶段

1. **V0 TopN 区分能力：MIXED。** V0 的 pooled T+10/T+20 mean excess 高于母样本，但 Top10/20/50 的中位 excess 仍多为负，且 MAE 比母样本更深；它表现为高机会/高弹性样本，而不是已经验证的低风险 Alpha 排名。
2. **Acceptance 增量：MIXED，不进入 Score 或 Filter。** V1 Top20 的 T+10 MAE 由 V0 的 -11.29% 改善至 -9.41%，但 mean excess 由 3.33% 降至 2.76%，Top10/50 亦不是一致改善，并有 `RIGHT_TAIL_DRIVEN` 标记。因此仍仅保留 Acceptance context，不改正式 D，也不给 B/D 配分。
3. **VP Extension 独立 Risk Layer：保留，但在 Opportunity Top50 内是 MIXED。** EXTREME 的 T+10 mean excess/MFE 为 5.06%/19.07%，高于 LOW 的 2.26%/16.51%；LOW 的 T+10 MAE 仅以 9/12 dates 更健康，T+20 MAE 则 6/12 打平。这支持“高弹性 + 高风险”解释，不能把 Risk 当成方向预测。
4. **Risk 是否减少 MAE：当前 Top50 证据不足以支持直接排除。** 直接排除 EXTREME（不补位）在 T+5/T+10/T+20 的平均 excess、MFE 和日期胜率均较完整 Top50 弱，T+10/T+20 MAE 也没有稳定改善；不能创建 EXTREME filter 或惩罚。
5. **Risk 是否参与 Opportunity Rank：NO_INCREMENTAL_VALUE。** Opportunity 主排序、Risk 次排序没有改变本样本的 Top10/20/50 选择集合；V2 也按设计不改 Opportunity。Risk 应继续作为独立展示/风险维度，而非反向扣分。
6. **Position 与双维结构：** Position 继续只作为 Context（冻结 H1 `NOT_SUPPORTED`）。OpportunityScore 与 RiskScore 应继续独立，允许同时出现高机会/高风险；Sector Phase、RS State、breadth context 也只作解释。
7. **下一阶段候选：** 不进入正式 `final_rank_score`。若开展后续组合层研究，仅可把 `V0 Opportunity + 独立 VP Risk disclosure` 作为描述性候选，并需在完整成交/仓位框架中验证；V1/V3 Acceptance context-first 与 Risk tie-break 没有足够跨日期、跨月的稳定增量。本报告不加入 CZSC，也不进行 Portfolio Backtest。
